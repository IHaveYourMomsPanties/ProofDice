"""Base network deposit watcher for BetterDice.io.

Polls Alchemy's `alchemy_getAssetTransfers` for every user's derived Base
address, filters to supported assets (native ETH + USDC), waits for
`BASE_CONFIRMATIONS` blocks, then credits internal balances atomically.

Idempotency: every observed transfer has a stable `uniqueId` from Alchemy
(`<txHash>:log:<idx>` for ERC-20, `<txHash>:external:<idx>` for native).
We store this as `_id` in `deposits` so retries can never double-credit.

This module is intentionally simple (per-user polling in the app process)
because we expect a small user count in Phase 2. Scale-out later by
switching to `eth_getLogs` with batched topic filter for USDC and moving
the watcher into a dedicated worker process.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from pymongo.errors import DuplicateKeyError

from wallet import COINS, derive_address

logger = logging.getLogger("betterdice.watcher")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_RPC = os.environ.get("ALCHEMY_BASE_RPC")
USDC_BASE = os.environ.get(
    "USDC_BASE_ADDRESS", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
).lower()

BASE_CONFIRMATIONS = int(os.environ.get("BASE_CONFIRMATIONS", "12"))
POLL_SECONDS = int(os.environ.get("BASE_WATCHER_POLL_S", "20"))
INITIAL_LOOKBACK_BLOCKS = int(os.environ.get("BASE_INITIAL_LOOKBACK", "300"))

# Assets we recognise on Base (lower-cased contract address or None for native)
BASE_ASSETS: dict[Optional[str], str] = {
    None: "ETH",           # native
    USDC_BASE: "USDC",
}


# ---------------------------------------------------------------------------
# RPC helpers
# ---------------------------------------------------------------------------
class BaseRPC:
    def __init__(self, url: str):
        self._url = url
        self._client = httpx.AsyncClient(timeout=20.0)
        self._id = 0

    async def _call(self, method: str, params: list) -> Any:
        self._id += 1
        payload = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
        r = await self._client.post(self._url, json=payload)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise RuntimeError(f"RPC {method} error: {data['error']}")
        return data.get("result")

    async def block_number(self) -> int:
        hex_num = await self._call("eth_blockNumber", [])
        return int(hex_num, 16)

    async def asset_transfers(
        self,
        to_address: str,
        from_block: int,
        to_block: int,
    ) -> list[dict]:
        params = [
            {
                "fromBlock": hex(from_block),
                "toBlock": hex(to_block),
                "toAddress": to_address,
                "category": ["external", "erc20"],
                "withMetadata": True,
                "excludeZeroValue": True,
                "maxCount": "0x64",  # 100 per address per scan window
                "order": "asc",
            }
        ]
        result = await self._call("alchemy_getAssetTransfers", params)
        return list(result.get("transfers", []))

    async def aclose(self) -> None:
        await self._client.aclose()


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------
async def _ensure_indexes(db) -> None:
    # unique on Alchemy's unique_id -> primary idempotency guarantee
    await db.deposits.create_index("unique_id", unique=True)
    await db.deposits.create_index([("user_id", 1), ("created_at", -1)])
    await db.deposits.create_index("tx_hash")


async def _get_last_block(db, rpc: BaseRPC) -> int:
    doc = await db.system.find_one({"_id": "base_last_block"})
    if doc:
        return int(doc["value"])
    # First run — start `INITIAL_LOOKBACK_BLOCKS` behind current head
    head = await rpc.block_number()
    start = max(0, head - INITIAL_LOOKBACK_BLOCKS)
    await db.system.update_one(
        {"_id": "base_last_block"},
        {"$set": {"value": start}},
        upsert=True,
    )
    logger.info("watcher init: last_block=%d (head=%d)", start, head)
    return start


async def _set_last_block(db, block: int) -> None:
    await db.system.update_one(
        {"_id": "base_last_block"},
        {"$set": {"value": int(block)}},
        upsert=True,
    )


def _classify_transfer(t: dict) -> Optional[tuple[str, float]]:
    """Return (coin_code, amount) if the transfer is one we credit, else None."""
    category = t.get("category")
    value = t.get("value")
    if value is None:
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None

    if category == "external":
        # Native ETH on Base
        return ("ETH", amount)
    if category == "erc20":
        raw = t.get("rawContract") or {}
        contract = (raw.get("address") or "").lower()
        code = BASE_ASSETS.get(contract)
        if code:
            return (code, amount)
    return None


async def _credit_deposit(
    db,
    user: dict,
    transfer: dict,
    coin: str,
    amount: float,
) -> bool:
    """Insert deposit doc + $inc user balance. Returns True on first-time credit."""
    unique_id = transfer.get("uniqueId") or transfer["hash"]
    tx_hash = transfer.get("hash")
    block_num_hex = transfer.get("blockNum") or "0x0"
    try:
        block_num = int(block_num_hex, 16)
    except (TypeError, ValueError):
        block_num = 0
    meta = transfer.get("metadata") or {}
    now_iso = datetime.now(timezone.utc).isoformat()

    doc = {
        "_id": unique_id,
        "unique_id": unique_id,
        "user_id": user["id"],
        "username": user["username"],
        "coin": coin,
        "chain": "Base",
        "amount": amount,
        "tx_hash": tx_hash,
        "block_num": block_num,
        "from_address": (transfer.get("from") or "").lower(),
        "to_address": (transfer.get("to") or "").lower(),
        "block_timestamp": meta.get("blockTimestamp"),
        "created_at": now_iso,
    }
    try:
        await db.deposits.insert_one(doc)
    except DuplicateKeyError:
        return False

    # Atomic credit
    await db.users.update_one(
        {"id": user["id"]},
        {"$inc": {f"balances.{coin}": amount}},
    )
    logger.info(
        "credited %s %s to user=%s via %s (block %d)",
        amount, coin, user["username"], tx_hash, block_num,
    )
    return True


async def _scan_once(db, rpc: BaseRPC) -> dict:
    head = await rpc.block_number()
    to_block = head - BASE_CONFIRMATIONS
    from_block = await _get_last_block(db, rpc)
    if to_block <= from_block:
        return {"scanned_users": 0, "credited": 0, "head": head, "to_block": to_block}

    # +1 to avoid re-scanning the fully-processed last block, but unique_id
    # protects against double-credit anyway.
    from_block_inclusive = from_block + 1
    users = await db.users.find({}, {"id": 1, "username": 1, "wallet_index": 1}).to_list(length=10_000)

    credited = 0
    for u in users:
        idx = int(u.get("wallet_index", 0))
        try:
            addr = derive_address("ETH", idx).lower()  # ETH & USDC share this addr
        except Exception:
            logger.exception("derive_address failed for user %s", u.get("id"))
            continue

        try:
            transfers = await rpc.asset_transfers(addr, from_block_inclusive, to_block)
        except Exception:
            logger.exception("asset_transfers failed for %s", addr)
            continue

        for t in transfers:
            classified = _classify_transfer(t)
            if not classified:
                continue
            coin, amount = classified
            if await _credit_deposit(db, u, t, coin, amount):
                credited += 1

    await _set_last_block(db, to_block)
    return {
        "scanned_users": len(users),
        "credited": credited,
        "head": head,
        "to_block": to_block,
        "from_block": from_block_inclusive,
    }


# ---------------------------------------------------------------------------
# Public entrypoint (called from FastAPI startup)
# ---------------------------------------------------------------------------
_task: Optional[asyncio.Task] = None
_rpc: Optional[BaseRPC] = None


async def _loop(db) -> None:
    global _rpc
    _rpc = BaseRPC(BASE_RPC)
    logger.info(
        "Base watcher started: rpc=%s confirmations=%d poll=%ds",
        BASE_RPC.split("/v2/")[0] if BASE_RPC else "-",
        BASE_CONFIRMATIONS,
        POLL_SECONDS,
    )
    await _ensure_indexes(db)
    while True:
        try:
            stats = await _scan_once(db, _rpc)
            if stats["credited"] > 0 or stats["scanned_users"] > 0:
                logger.info("watcher scan: %s", stats)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("watcher scan loop error")
        try:
            await asyncio.sleep(POLL_SECONDS)
        except asyncio.CancelledError:
            raise


def start_watcher(db) -> None:
    """Kick off the background watcher task."""
    global _task
    if _task and not _task.done():
        return
    if not BASE_RPC:
        logger.warning("ALCHEMY_BASE_RPC not set — watcher NOT started")
        return
    _task = asyncio.create_task(_loop(db), name="base_watcher")


async def stop_watcher() -> None:
    global _task, _rpc
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
    _task = None
    if _rpc:
        await _rpc.aclose()
        _rpc = None
