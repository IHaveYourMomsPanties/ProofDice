"""Multi-chain EVM deposit watcher for BetterDice.io.

Chains watched (Phase 2 Step 1b):
  - Ethereum L1     (native ETH + USDC ERC-20 + USDT ERC-20)
  - BNB Chain (BSC) (native BNB + USDT ERC-20)
  - Polygon PoS     (native POL + USDC ERC-20 + USDT ERC-20)

Design:
  - One background asyncio task per chain (independent poll cursor).
  - Uses Alchemy's `alchemy_getAssetTransfers` for both native and ERC-20
    transfers in a single call per (user, chain, poll).
  - Idempotency: Alchemy's `uniqueId` is `_id` in db.deposits (unique).
  - Credits go to the user's single balance for that ASSET code, regardless
    of which chain the deposit arrived on.

Scale note: currently O(N users) RPC calls per chain per poll. Fine for MVP;
switch to batched `eth_getLogs` + `alchemy_getAssetTransfers` w/ toAddresses[]
before user count > ~1k.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from pymongo.errors import DuplicateKeyError

from wallet import NETWORKS, derive_network_address

logger = logging.getLogger("betterdice.watcher")


# ---------------------------------------------------------------------------
# Chain registry — each has an RPC + native-asset code + list of ERC-20 contracts
# ---------------------------------------------------------------------------
def _mk_chain(chain_id: str, rpc_env: str, native_asset: str, label: str) -> Optional[dict]:
    rpc = os.environ.get(rpc_env)
    if not rpc:
        logger.warning("%s RPC (%s) not set — watcher disabled for %s", label, rpc_env, label)
        return None

    # Every ERC-20 network entry that lives on this chain becomes a
    # (contract_lower -> asset_code) map so the watcher can classify.
    erc20 = {}
    for n in NETWORKS:
        if n.chain_id == chain_id and n.addr_kind == "evm" and n.contract:
            erc20[n.contract.lower()] = n.asset

    return {
        "id": chain_id,
        "label": label,
        "rpc": rpc,
        "native_asset": native_asset,
        "erc20": erc20,   # {contract_addr_lc: asset_code}
    }


def _build_chains() -> list[dict]:
    chains = [
        _mk_chain("eth",     "ALCHEMY_ETH_RPC",     "ETH",    "Ethereum"),
        _mk_chain("bnb",     "ALCHEMY_BNB_RPC",     "BNB",    "BNB Chain"),
        _mk_chain("polygon", "ALCHEMY_POLYGON_RPC", "POL",    "Polygon"),
        _mk_chain("sepolia", "ALCHEMY_SEPOLIA_RPC", "SEPETH", "Ethereum Sepolia"),
    ]
    return [c for c in chains if c]


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CONFIRMATIONS = int(os.environ.get("EVM_CONFIRMATIONS", "12"))
POLL_SECONDS = int(os.environ.get("WATCHER_POLL_S", "20"))
INITIAL_LOOKBACK_BLOCKS = int(os.environ.get("WATCHER_INITIAL_LOOKBACK", "300"))


# ---------------------------------------------------------------------------
# Alchemy RPC helpers (one client per chain)
# ---------------------------------------------------------------------------
class AlchemyRPC:
    def __init__(self, url: str) -> None:
        self._url = url
        self._client = httpx.AsyncClient(timeout=25.0)
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
        return int(await self._call("eth_blockNumber", []), 16)

    async def asset_transfers(self, to_address: str, from_block: int, to_block: int) -> list[dict]:
        params = [{
            "fromBlock": hex(from_block),
            "toBlock": hex(to_block),
            "toAddress": to_address,
            "category": ["external", "erc20"],
            "withMetadata": True,
            "excludeZeroValue": True,
            "maxCount": "0x64",
            "order": "asc",
        }]
        return list((await self._call("alchemy_getAssetTransfers", params)).get("transfers", []))

    async def aclose(self) -> None:
        await self._client.aclose()


# ---------------------------------------------------------------------------
# Scanner primitives
# ---------------------------------------------------------------------------
async def _ensure_indexes(db) -> None:
    await db.deposits.create_index("unique_id", unique=True)
    await db.deposits.create_index([("user_id", 1), ("created_at", -1)])
    await db.deposits.create_index("tx_hash")


def _classify_transfer(t: dict, chain: dict) -> Optional[tuple[str, float]]:
    """Return (asset_code, amount) if the transfer matches something we credit."""
    val = t.get("value")
    if val is None:
        return None
    try:
        amount = float(val)
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None

    cat = t.get("category")
    if cat == "external":
        return (chain["native_asset"], amount)
    if cat == "erc20":
        raw = t.get("rawContract") or {}
        contract = (raw.get("address") or "").lower()
        asset = chain["erc20"].get(contract)
        if asset:
            return (asset, amount)
    return None


async def _get_last_block(db, chain_id: str, rpc: AlchemyRPC) -> int:
    key = f"{chain_id}_last_block"
    doc = await db.system.find_one({"_id": key})
    if doc:
        return int(doc["value"])
    head = await rpc.block_number()
    start = max(0, head - INITIAL_LOOKBACK_BLOCKS)
    await db.system.update_one({"_id": key}, {"$set": {"value": start}}, upsert=True)
    logger.info("watcher init [%s]: last_block=%d (head=%d)", chain_id, start, head)
    return start


async def _set_last_block(db, chain_id: str, block: int) -> None:
    await db.system.update_one(
        {"_id": f"{chain_id}_last_block"},
        {"$set": {"value": int(block)}},
        upsert=True,
    )


async def _credit_deposit(
    db,
    user: dict,
    transfer: dict,
    asset: str,
    amount: float,
    chain_label: str,
    chain_id: str,
) -> bool:
    unique_id = transfer.get("uniqueId") or transfer.get("hash")
    if not unique_id:
        return False
    tx_hash = transfer.get("hash")
    try:
        block_num = int((transfer.get("blockNum") or "0x0"), 16)
    except (TypeError, ValueError):
        block_num = 0
    meta = transfer.get("metadata") or {}

    doc = {
        "_id": unique_id,
        "unique_id": unique_id,
        "user_id": user["id"],
        "username": user["username"],
        "asset": asset,
        "coin": asset,       # legacy alias (older API consumers)
        "chain": chain_label,
        "chain_id": chain_id,
        "amount": amount,
        "tx_hash": tx_hash,
        "block_num": block_num,
        "from_address": (transfer.get("from") or "").lower(),
        "to_address": (transfer.get("to") or "").lower(),
        "block_timestamp": meta.get("blockTimestamp"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await db.deposits.insert_one(doc)
    except DuplicateKeyError:
        return False

    await db.users.update_one(
        {"id": user["id"]},
        {"$inc": {f"balances.{asset}": amount}},
    )
    logger.info(
        "credited %s %s to user=%s via %s on %s (block %d)",
        amount, asset, user["username"], tx_hash, chain_label, block_num,
    )
    return True


async def _scan_chain_once(db, chain: dict, rpc: AlchemyRPC) -> dict:
    head = await rpc.block_number()
    to_block = head - CONFIRMATIONS
    from_block = await _get_last_block(db, chain["id"], rpc)
    if to_block <= from_block:
        return {"chain": chain["id"], "scanned": 0, "credited": 0}

    users = await db.users.find({}, {"id": 1, "username": 1, "wallet_index": 1}).to_list(length=10_000)
    from_inc = from_block + 1
    credited = 0

    for u in users:
        idx = int(u.get("wallet_index", 0))
        # All wired chains here are EVM — derive by kind
        from wallet import _derive_by_kind  # local import to avoid circular at module load
        addr = _derive_by_kind("evm", idx).lower()
        try:
            transfers = await rpc.asset_transfers(addr, from_inc, to_block)
        except Exception:
            logger.exception("asset_transfers failed [%s] %s", chain["id"], addr)
            continue
        for t in transfers:
            cls = _classify_transfer(t, chain)
            if not cls:
                continue
            asset, amount = cls
            if await _credit_deposit(db, u, t, asset, amount, chain["label"], chain["id"]):
                credited += 1

    await _set_last_block(db, chain["id"], to_block)
    return {"chain": chain["id"], "scanned": len(users), "credited": credited, "head": head, "to_block": to_block}


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------
_tasks: list[asyncio.Task] = []
_rpcs: list[AlchemyRPC] = []


async def _chain_loop(db, chain: dict) -> None:
    rpc = AlchemyRPC(chain["rpc"])
    _rpcs.append(rpc)
    logger.info("watcher started [%s] confirmations=%d poll=%ds", chain["id"], CONFIRMATIONS, POLL_SECONDS)
    consecutive_403 = 0
    while True:
        try:
            stats = await _scan_chain_once(db, chain, rpc)
            if stats.get("credited", 0) > 0:
                logger.info("watcher [%s] scan: %s", chain["id"], stats)
            consecutive_403 = 0
        except asyncio.CancelledError:
            raise
        except httpx.HTTPStatusError as e:
            if e.response is not None and e.response.status_code == 403:
                consecutive_403 += 1
                if consecutive_403 == 1:
                    logger.warning(
                        "watcher [%s]: network not enabled on your Alchemy app "
                        "(HTTP 403). Enable at https://dashboard.alchemy.com/apps and "
                        "restart. Suppressing further errors for this chain.",
                        chain["id"],
                    )
                if consecutive_403 >= 3:
                    logger.warning("watcher [%s]: disabled after 3 consecutive 403s", chain["id"])
                    return
            else:
                logger.exception("watcher [%s] http error", chain["id"])
        except Exception:
            logger.exception("watcher [%s] loop error", chain["id"])
        try:
            await asyncio.sleep(POLL_SECONDS)
        except asyncio.CancelledError:
            raise


def start_watcher(db) -> None:
    """Kick off one background task per configured EVM chain."""
    global _tasks
    if _tasks and any(not t.done() for t in _tasks):
        return
    chains = _build_chains()
    if not chains:
        logger.warning("no chains configured — watcher NOT started")
        return
    asyncio.get_event_loop()  # ensure loop exists
    # Prime the indexes once
    asyncio.create_task(_ensure_indexes(db))
    _tasks = [asyncio.create_task(_chain_loop(db, c), name=f"watcher_{c['id']}") for c in chains]


async def stop_watcher() -> None:
    global _tasks, _rpcs
    for t in _tasks:
        if not t.done():
            t.cancel()
    for t in _tasks:
        try:
            await t
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
    _tasks = []
    for r in _rpcs:
        try:
            await r.aclose()
        except Exception:  # noqa: BLE001
            pass
    _rpcs = []
