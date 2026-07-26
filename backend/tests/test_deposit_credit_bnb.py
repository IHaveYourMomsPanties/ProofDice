"""Iteration 7 — deposit-credit + watcher cursor-hold + initial-lookback tests.

Covers the fixes shipped for user 'thirdeyeion' whose BNB deposit
0x387f3badc706c0c9d76bb34ad0615072fd99c0f84eeab1c91175a6cfabb3c6f7
went missing until it was manually credited via watcher._credit_deposit.
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
import jwt as pyjwt
import pytest
import requests

sys.path.insert(0, "/app/backend")

from dotenv import load_dotenv  # noqa: E402
load_dotenv("/app/backend/.env")

import watcher  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402


TX_HASH = "0x387f3badc706c0c9d76bb34ad0615072fd99c0f84eeab1c91175a6cfabb3c6f7"
UNIQUE_ID = f"{TX_HASH}:external"
BNB_AMOUNT = 0.00878122735637456
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-me-in-prod-betterdice")

def _base_url():
    for line in open("/app/frontend/.env"):
        if line.startswith("REACT_APP_BACKEND_URL"):
            return line.split("=", 1)[1].strip().strip('"').rstrip("/")
    return os.environ["REACT_APP_BACKEND_URL"].rstrip("/")


BASE_URL = _base_url()
API = f"{BASE_URL}/api"


@pytest.fixture
def db():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return client[os.environ["DB_NAME"]]


def _mint_token(user_id: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=1)
    return pyjwt.encode({"sub": user_id, "exp": exp}, JWT_SECRET, algorithm="HS256")


# ---------------------------------------------------------------------------
# 1. Persisted deposit for thirdeyeion
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_thirdeyeion_balance_and_deposit_row_persisted(db):
    u = await db.users.find_one({"username": "thirdeyeion"})
    assert u is not None, "thirdeyeion user missing"
    assert u.get("balances", {}).get("BNB") == BNB_AMOUNT, (
        f"BNB balance mismatch: {u.get('balances', {}).get('BNB')}"
    )

    d = await db.deposits.find_one({"tx_hash": TX_HASH})
    assert d is not None, "deposit row for BNB tx missing"
    assert d["unique_id"].endswith(":external")
    assert d["chain"] == "BNB Chain"
    assert d["chain_id"] == "bnb"
    assert d["asset"] == "BNB"
    assert d["amount"] == BNB_AMOUNT


# ---------------------------------------------------------------------------
# 2. Idempotency: re-invoking _credit_deposit does NOT double-credit
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_credit_deposit_idempotent_on_real_tx(db):
    user = await db.users.find_one({"username": "thirdeyeion"})
    before = user["balances"]["BNB"]

    transfer = {
        "uniqueId": UNIQUE_ID,
        "hash": TX_HASH,
        "category": "external",
        "value": BNB_AMOUNT,
        "from": "0x006bf88d9dc4f16a614d697c4469d2c4d23023e9",
        "to": "0x59be4233124c531342d76b59360b3402c9261e3b",
        "blockNum": hex(112220246),
        "metadata": {"blockTimestamp": "2026-07-25T20:00:00.000Z"},
    }

    r = await watcher._credit_deposit(db, user, transfer, "BNB", BNB_AMOUNT, "BNB Chain", "bnb")
    assert r is False, "expected idempotent False on re-credit"

    after = (await db.users.find_one({"username": "thirdeyeion"}))["balances"]["BNB"]
    assert after == before, f"balance was mutated on replay: {before} -> {after}"


# ---------------------------------------------------------------------------
# 3. Cursor-hold behavior when a user is rate-limited
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scan_chain_cursor_holds_when_any_user_is_429(db, monkeypatch):
    # Seed three fresh test users
    tag = uuid.uuid4().hex[:6]
    ids = []
    for i in range(3):
        uid = f"TEST_hold_{tag}_{i}"
        await db.users.insert_one({
            "id": uid,
            "username": f"TEST_h_{tag}_{i}",
            "email": f"{uid}@bd.io",
            "password_hash": "x",
            "balances": {c: 0.0 for c in ["BTC","ETH","USDC","USDT","BNB","POL","SOL","GRAM","SEPETH"]},
            "wallet_index": 990000 + i,
            "created_at": "2026-01-01T00:00:00+00:00",
            "server_seed":"x","server_seed_hashed":"x","client_seed":"x","nonce":0,
        })
        ids.append(uid)

    chain_id = f"testchain_{tag}"
    chain = {"id": chain_id, "label": "TestChain", "rpc": "x", "native_asset": "TST", "erc20": {}}
    cursor_key = f"{chain_id}_last_block"

    # Manually seed a fresh cursor so _get_last_block returns it directly
    await db.system.update_one({"_id": cursor_key}, {"$set": {"value": 1000}}, upsert=True)

    # RPC that reports head=2000 always, and yields 429 for one user
    class FakeRPC:
        def __init__(self, fail_addr_lc: str | None):
            self.fail_addr_lc = fail_addr_lc
            self.calls = []
        async def block_number(self):
            return 2000
        async def asset_transfers(self, to_address, from_block, to_block):
            self.calls.append((to_address, from_block, to_block))
            if self.fail_addr_lc and to_address.lower() == self.fail_addr_lc:
                req = httpx.Request("POST", "https://x")
                resp = httpx.Response(429, request=req)
                raise httpx.HTTPStatusError("429", request=req, response=resp)
            return []

    # Derive address for user index of ids[1] — that's the one we'll 429
    from wallet import _derive_by_kind
    target_addr = _derive_by_kind("evm", 990001).lower()

    # Only scan the 3 seeded users, not all real DB users. Patch the users
    # cursor by patching db.users.find via monkeypatch on the watcher module's
    # scan function — simpler: patch _scan_chain_once's user list source by
    # patching db.users.find. Since motor's find returns a cursor with to_list,
    # we'll just filter via a wrapper.
    try:
        # --- Case A: one user 429s -> cursor must NOT advance ---
        rpc_a = FakeRPC(fail_addr_lc=target_addr)
        stats_a = await watcher._scan_chain_once(db, chain, rpc_a)
        assert stats_a["rate_limited"] == 1, stats_a
        assert stats_a["credited"] == 0
        cur = await db.system.find_one({"_id": cursor_key})
        assert cur["value"] == 1000, f"cursor advanced on rate-limit: {cur['value']}"

        # --- Case B: no 429s -> cursor DOES advance ---
        rpc_b = FakeRPC(fail_addr_lc=None)
        stats_b = await watcher._scan_chain_once(db, chain, rpc_b)
        assert stats_b["rate_limited"] == 0
        cur = await db.system.find_one({"_id": cursor_key})
        # to_block = head - CONFIRMATIONS = 2000 - 12 = 1988
        assert cur["value"] == 2000 - watcher.CONFIRMATIONS, f"cursor did not advance: {cur['value']}"
    finally:
        await db.users.delete_many({"id": {"$in": ids}})
        await db.system.delete_one({"_id": cursor_key})


# ---------------------------------------------------------------------------
# 4. _chain_initial_lookback + _get_last_block behaviour
# ---------------------------------------------------------------------------
def test_chain_initial_lookback_default_and_override(monkeypatch):
    # Ensure no override for BNB
    monkeypatch.delenv("WATCHER_INITIAL_LOOKBACK_BNB", raising=False)
    monkeypatch.delenv("WATCHER_INITIAL_LOOKBACK_ETH", raising=False)
    # Also reset the module-level default in case env changed it
    import importlib
    importlib.reload(watcher)
    assert watcher._chain_initial_lookback("bnb") == 7200
    assert watcher._chain_initial_lookback("eth") == 7200

    monkeypatch.setenv("WATCHER_INITIAL_LOOKBACK_BNB", "999")
    assert watcher._chain_initial_lookback("bnb") == 999
    # Unrelated chains untouched
    assert watcher._chain_initial_lookback("eth") == 7200


@pytest.mark.asyncio
async def test_get_last_block_uses_lookback_for_fresh_cursor(db, monkeypatch):
    monkeypatch.delenv("WATCHER_INITIAL_LOOKBACK_TEST9", raising=False)
    import importlib
    importlib.reload(watcher)

    chain_id = f"test9_{uuid.uuid4().hex[:6]}"
    key = f"{chain_id}_last_block"
    # Ensure no pre-existing cursor
    await db.system.delete_one({"_id": key})

    class FakeRPC:
        async def block_number(self):
            return 10_000_000

    try:
        got = await watcher._get_last_block(db, chain_id, FakeRPC())
        # 10_000_000 - 7200 = 9_992_800
        assert got == 9_992_800, got
        doc = await db.system.find_one({"_id": key})
        assert doc["value"] == 9_992_800
    finally:
        await db.system.delete_one({"_id": key})


# ---------------------------------------------------------------------------
# 5. /api/wallet/deposits for thirdeyeion returns exactly the BNB row
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_wallet_deposits_endpoint_for_thirdeyeion(db):
    u = await db.users.find_one({"username": "thirdeyeion"})
    token = _mint_token(u["id"])
    r = requests.get(f"{API}/wallet/deposits", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    rows = r.json()
    matching = [x for x in rows if x.get("tx_hash") == TX_HASH]
    assert len(matching) == 1, f"expected 1 BNB row, got rows={rows}"
    row = matching[0]
    assert row["asset"] == "BNB"
    assert row["chain"] == "BNB Chain"
    assert row["chain_id"] == "bnb"
    assert row["amount"] == BNB_AMOUNT


# ---------------------------------------------------------------------------
# 6. /api/auth/me for thirdeyeion returns BNB balance
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_auth_me_returns_bnb_balance_for_thirdeyeion(db):
    u = await db.users.find_one({"username": "thirdeyeion"})
    token = _mint_token(u["id"])
    r = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["username"] == "thirdeyeion"
    assert me["balances"]["BNB"] == BNB_AMOUNT


# ---------------------------------------------------------------------------
# 7. Dice roll works when BNB balance is positive (uses fresh alt user)
# ---------------------------------------------------------------------------
def test_dice_roll_bnb_with_positive_balance_for_alt_user():
    import pymongo
    sync = pymongo.MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    tag = uuid.uuid4().hex[:8]
    body = {"username": f"TEST_{tag}", "email": f"t_{tag}@bd.io", "password": "TestPass123!"}
    r = requests.post(f"{API}/auth/register", json=body)
    assert r.status_code == 200
    reg = r.json()
    uid = reg["user"]["id"]
    token = reg["token"]

    try:
        # Manually rewrite balance
        sync.users.update_one({"id": uid}, {"$set": {"balances.BNB": 1.0}})

        payload = {"coin": "BNB", "amount": 0.001, "target": 50, "direction": "under"}
        r2 = requests.post(f"{API}/dice/roll", json=payload,
                           headers={"Authorization": f"Bearer {token}"})
        assert r2.status_code == 200, r2.text
        result = r2.json()
        # Balance after should reflect result
        assert "balance_after" in result or "balance" in result or "roll" in result, result
        # Verify DB balance was updated correctly
        u = sync.users.find_one({"id": uid})
        new_bal = u["balances"]["BNB"]
        # Either won (1.0 + payout - stake) or lost (1.0 - 0.001)
        # Cheapest sanity: change must be either -0.001 or positive delta
        delta = new_bal - 1.0
        assert delta == pytest.approx(-0.001) or delta > 0, f"unexpected delta {delta}"
    finally:
        sync.users.delete_one({"id": uid})
        sync.bets.delete_many({"user_id": uid})
