"""Phase 2 Step 1 — Base ETH + USDC watcher tests."""
import asyncio
import os
import re
import sys
import uuid

import pytest
import requests

sys.path.insert(0, "/app/backend")

from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

import watcher  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402


def _load_frontend_url():
    for line in open("/app/frontend/.env"):
        if line.startswith("REACT_APP_BACKEND_URL"):
            return line.split("=", 1)[1].strip().strip('"')
    return os.environ["REACT_APP_BACKEND_URL"]


BASE_URL = _load_frontend_url().rstrip("/")
API = f"{BASE_URL}/api"
USDC_BASE = os.environ["USDC_BASE_ADDRESS"].lower()


@pytest.fixture(scope="module")
def db():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return client[os.environ["DB_NAME"]]


# ---------------- /api/config: wired flags ----------------
def test_config_wired_eth_usdc_only():
    r = requests.get(f"{API}/config")
    assert r.status_code == 200
    specs = r.json()["coin_specs"]
    assert specs["ETH"]["wired"] is True
    assert specs["USDC"]["wired"] is True
    for c in ("BTC", "USDT", "BNB", "SOL", "GRAM"):
        assert specs[c]["wired"] is False, f"{c} should not be wired"


# ---------------- watcher startup logs ----------------
def test_watcher_log_lines_present():
    with open("/var/log/supervisor/backend.err.log") as f:
        content = f.read()
    assert "Base watcher started" in content
    assert "watcher scan:" in content


# ---------------- /api/wallet/deposits ----------------
def _register():
    tag = uuid.uuid4().hex[:8]
    body = {"username": f"TEST_{tag}", "email": f"test_{tag}@bd.io", "password": "TestPass123!"}
    r = requests.post(f"{API}/auth/register", json=body)
    assert r.status_code == 200
    return r.json()


def test_wallet_deposits_requires_auth():
    r = requests.get(f"{API}/wallet/deposits")
    assert r.status_code == 401


def test_wallet_deposits_empty_for_new_user():
    u = _register()
    r = requests.get(f"{API}/wallet/deposits", headers={"Authorization": f"Bearer {u['token']}"})
    assert r.status_code == 200
    assert r.json() == []


# ---------------- _classify_transfer ----------------
def test_classify_external_eth():
    t = {"category": "external", "value": 0.5}
    assert watcher._classify_transfer(t) == ("ETH", 0.5)


def test_classify_erc20_usdc():
    t = {"category": "erc20", "value": 12.34, "rawContract": {"address": USDC_BASE}}
    assert watcher._classify_transfer(t) == ("USDC", 12.34)


def test_classify_erc20_usdc_case_insensitive():
    t = {"category": "erc20", "value": 5.0, "rawContract": {"address": USDC_BASE.upper()}}
    assert watcher._classify_transfer(t) == ("USDC", 5.0)


def test_classify_erc20_unknown_contract_returns_none():
    t = {"category": "erc20", "value": 1.0, "rawContract": {"address": "0x1111111111111111111111111111111111111111"}}
    assert watcher._classify_transfer(t) is None


def test_classify_zero_value_returns_none():
    assert watcher._classify_transfer({"category": "external", "value": 0}) is None


def test_classify_missing_value_returns_none():
    assert watcher._classify_transfer({"category": "external"}) is None


# ---------------- _credit_deposit end-to-end + idempotency ----------------
@pytest.mark.asyncio
async def test_credit_deposit_idempotent_eth_and_usdc(db):
    # Ensure indexes exist (watcher creates them on startup, but be safe)
    await watcher._ensure_indexes(db)

    user_id = f"TEST_watcher_{uuid.uuid4().hex[:8]}"
    fake_user = {
        "id": user_id,
        "username": f"TEST_w_{user_id[-6:]}",
        "email": f"{user_id}@bd.io",
        "password_hash": "x",
        "balances": {"ETH": 0.0, "USDC": 0.0},
        "wallet_index": 999999,
        "created_at": "2026-01-01T00:00:00+00:00",
        "server_seed": "x", "server_seed_hashed": "x", "client_seed": "x", "nonce": 0,
    }
    await db.users.insert_one(fake_user)

    try:
        eth_unique = f"0xdead{uuid.uuid4().hex}:external:0"
        usdc_unique = f"0xcafe{uuid.uuid4().hex}:log:0"

        eth_transfer = {
            "uniqueId": eth_unique,
            "hash": eth_unique.split(":")[0],
            "category": "external",
            "value": 0.25,
            "from": "0xabc",
            "to": "0xdef",
            "blockNum": "0x1",
            "metadata": {"blockTimestamp": "2026-01-01T00:00:00Z"},
        }
        usdc_transfer = {
            "uniqueId": usdc_unique,
            "hash": usdc_unique.split(":")[0],
            "category": "erc20",
            "value": 42.5,
            "rawContract": {"address": USDC_BASE},
            "from": "0xabc",
            "to": "0xdef",
            "blockNum": "0x2",
            "metadata": {"blockTimestamp": "2026-01-01T00:00:00Z"},
        }

        # First credit ETH
        r1 = await watcher._credit_deposit(db, fake_user, eth_transfer, "ETH", 0.25)
        assert r1 is True
        # First credit USDC
        r2 = await watcher._credit_deposit(db, fake_user, usdc_transfer, "USDC", 42.5)
        assert r2 is True

        u = await db.users.find_one({"id": user_id})
        assert u["balances"]["ETH"] == 0.25
        assert u["balances"]["USDC"] == 42.5

        # Deposit docs exist
        assert await db.deposits.find_one({"_id": eth_unique}) is not None
        assert await db.deposits.find_one({"_id": usdc_unique}) is not None

        # Second attempt with same uniqueIds -> idempotent
        r3 = await watcher._credit_deposit(db, fake_user, eth_transfer, "ETH", 0.25)
        r4 = await watcher._credit_deposit(db, fake_user, usdc_transfer, "USDC", 42.5)
        assert r3 is False
        assert r4 is False

        u = await db.users.find_one({"id": user_id})
        assert u["balances"]["ETH"] == 0.25, "ETH balance double-credited"
        assert u["balances"]["USDC"] == 42.5, "USDC balance double-credited"

        # Verify unique index exists on deposits
        idx = await db.deposits.index_information()
        has_unique = any(v.get("unique") for k, v in idx.items() if "unique_id" in k)
        assert has_unique, f"unique index on deposits.unique_id not found: {idx}"
    finally:
        await db.users.delete_one({"id": user_id})
        await db.deposits.delete_many({"user_id": user_id})
