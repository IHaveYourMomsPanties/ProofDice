"""Phase 2 Step 1b — Multi-chain (ETH + BNB + Polygon) watcher tests."""
import os
import sys
import uuid

import pytest
import requests

sys.path.insert(0, "/app/backend")

from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

import watcher  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

USDC_ETH = os.environ["USDC_ETH_ADDRESS"].lower()
USDC_POLYGON = os.environ["USDC_POLYGON_ADDRESS"].lower()
USDT_ETH = os.environ["USDT_ETH_ADDRESS"].lower()
USDT_BNB = os.environ["USDT_BNB_ADDRESS"].lower()
USDT_POLYGON = os.environ["USDT_POLYGON_ADDRESS"].lower()


def _load_frontend_url():
    for line in open("/app/frontend/.env"):
        if line.startswith("REACT_APP_BACKEND_URL"):
            return line.split("=", 1)[1].strip().strip('"')
    return os.environ["REACT_APP_BACKEND_URL"]


BASE_URL = _load_frontend_url().rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def db():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return client[os.environ["DB_NAME"]]


# Build the same chain dicts the watcher uses at runtime, but bypass env-based
# skip so we can classify against all three even without RPC access.
def _mkchain(chain_id, native):
    erc20 = {}
    from wallet import NETWORKS
    for n in NETWORKS:
        if n.chain_id == chain_id and n.addr_kind == "evm" and n.contract:
            erc20[n.contract.lower()] = n.asset
    return {"id": chain_id, "label": chain_id, "rpc": "x", "native_asset": native, "erc20": erc20}


ETH_CHAIN = _mkchain("eth", "ETH")
BNB_CHAIN = _mkchain("bnb", "BNB")
POLYGON_CHAIN = _mkchain("polygon", "POL")


# ---------------- Watcher startup log lines ----------------
def test_watcher_startup_logs_eth_success_and_bnb_polygon_403():
    with open("/var/log/supervisor/backend.err.log") as f:
        content = f.read()
    # ETH is live
    assert "watcher init [eth]" in content or "watcher started [eth]" in content
    # BNB & Polygon warned about 403 and then disabled after 3 consecutive 403s
    assert "watcher [bnb]" in content
    assert "watcher [polygon]" in content
    assert "network not enabled" in content or "disabled after 3 consecutive 403s" in content


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


# ---------------- _classify_transfer with chain param ----------------
def test_classify_external_eth_native():
    assert watcher._classify_transfer({"category": "external", "value": 0.5}, ETH_CHAIN) == ("ETH", 0.5)


def test_classify_external_bnb_native():
    assert watcher._classify_transfer({"category": "external", "value": 1.25}, BNB_CHAIN) == ("BNB", 1.25)


def test_classify_external_polygon_native():
    assert watcher._classify_transfer({"category": "external", "value": 3.0}, POLYGON_CHAIN) == ("POL", 3.0)


def test_classify_erc20_usdc_eth():
    t = {"category": "erc20", "value": 12.34, "rawContract": {"address": USDC_ETH}}
    assert watcher._classify_transfer(t, ETH_CHAIN) == ("USDC", 12.34)


def test_classify_erc20_usdt_eth():
    t = {"category": "erc20", "value": 42.5, "rawContract": {"address": USDT_ETH}}
    assert watcher._classify_transfer(t, ETH_CHAIN) == ("USDT", 42.5)


def test_classify_erc20_usdt_bnb():
    t = {"category": "erc20", "value": 7.0, "rawContract": {"address": USDT_BNB}}
    assert watcher._classify_transfer(t, BNB_CHAIN) == ("USDT", 7.0)


def test_classify_erc20_usdc_polygon():
    t = {"category": "erc20", "value": 9.0, "rawContract": {"address": USDC_POLYGON}}
    assert watcher._classify_transfer(t, POLYGON_CHAIN) == ("USDC", 9.0)


def test_classify_erc20_usdt_polygon():
    t = {"category": "erc20", "value": 11.0, "rawContract": {"address": USDT_POLYGON}}
    assert watcher._classify_transfer(t, POLYGON_CHAIN) == ("USDT", 11.0)


def test_classify_wrong_contract_for_chain_returns_none():
    # USDT_BNB address on the ETH chain -> unknown -> None
    t = {"category": "erc20", "value": 1.0, "rawContract": {"address": USDT_BNB}}
    assert watcher._classify_transfer(t, ETH_CHAIN) is None


def test_classify_unknown_contract():
    t = {"category": "erc20", "value": 1.0, "rawContract": {"address": "0x1111111111111111111111111111111111111111"}}
    assert watcher._classify_transfer(t, ETH_CHAIN) is None


def test_classify_zero_and_missing_value():
    assert watcher._classify_transfer({"category": "external", "value": 0}, ETH_CHAIN) is None
    assert watcher._classify_transfer({"category": "external"}, ETH_CHAIN) is None


def test_classify_case_insensitive_contract():
    t = {"category": "erc20", "value": 5.0, "rawContract": {"address": USDC_ETH.upper()}}
    assert watcher._classify_transfer(t, ETH_CHAIN) == ("USDC", 5.0)


# ---------------- _credit_deposit end-to-end + idempotency + chain-agnostic ----------------
@pytest.mark.asyncio
async def test_credit_deposit_usdt_multi_chain_and_idempotency(db):
    await watcher._ensure_indexes(db)

    user_id = f"TEST_watcher_{uuid.uuid4().hex[:8]}"
    fake_user = {
        "id": user_id,
        "username": f"TEST_w_{user_id[-6:]}",
        "email": f"{user_id}@bd.io",
        "password_hash": "x",
        "balances": {c: 0.0 for c in ["BTC", "ETH", "USDC", "USDT", "BNB", "POL", "SOL", "GRAM"]},
        "wallet_index": 999998,
        "created_at": "2026-01-01T00:00:00+00:00",
        "server_seed": "x", "server_seed_hashed": "x", "client_seed": "x", "nonce": 0,
    }
    await db.users.insert_one(fake_user)

    try:
        eth_unique = f"0xusdteth:{uuid.uuid4().hex}:log:0"
        polygon_unique = f"0xusdtpoly:{uuid.uuid4().hex}:log:0"

        eth_transfer = {
            "uniqueId": eth_unique,
            "hash": "0xhash_eth",
            "category": "erc20",
            "value": 100.0,
            "rawContract": {"address": USDT_ETH},
            "from": "0xabc", "to": "0xdef",
            "blockNum": "0x1",
            "metadata": {"blockTimestamp": "2026-01-01T00:00:00Z"},
        }
        polygon_transfer = {
            "uniqueId": polygon_unique,
            "hash": "0xhash_pol",
            "category": "erc20",
            "value": 50.0,
            "rawContract": {"address": USDT_POLYGON},
            "from": "0xabc", "to": "0xdef",
            "blockNum": "0x2",
            "metadata": {"blockTimestamp": "2026-01-01T00:00:00Z"},
        }

        # Credit USDT on Ethereum
        r1 = await watcher._credit_deposit(db, fake_user, eth_transfer, "USDT", 100.0, "Ethereum", "eth")
        assert r1 is True
        # Credit USDT on Polygon -> same balance (single-balance model)
        r2 = await watcher._credit_deposit(db, fake_user, polygon_transfer, "USDT", 50.0, "Polygon", "polygon")
        assert r2 is True

        u = await db.users.find_one({"id": user_id})
        assert u["balances"]["USDT"] == 150.0, f"chain-agnostic sum wrong: {u['balances']['USDT']}"

        # Check deposit docs carry asset + chain + chain_id
        d1 = await db.deposits.find_one({"_id": eth_unique})
        d2 = await db.deposits.find_one({"_id": polygon_unique})
        assert d1 is not None and d1["asset"] == "USDT" and d1["chain"] == "Ethereum" and d1["chain_id"] == "eth"
        assert d2 is not None and d2["asset"] == "USDT" and d2["chain"] == "Polygon" and d2["chain_id"] == "polygon"

        # Idempotent replay
        r3 = await watcher._credit_deposit(db, fake_user, eth_transfer, "USDT", 100.0, "Ethereum", "eth")
        r4 = await watcher._credit_deposit(db, fake_user, polygon_transfer, "USDT", 50.0, "Polygon", "polygon")
        assert r3 is False
        assert r4 is False

        u = await db.users.find_one({"id": user_id})
        assert u["balances"]["USDT"] == 150.0, "double-credited on replay"

        idx = await db.deposits.index_information()
        assert any(v.get("unique") for k, v in idx.items() if "unique_id" in k)
    finally:
        await db.users.delete_one({"id": user_id})
        await db.deposits.delete_many({"user_id": user_id})


# ---------------- /api/wallet/deposits returns asset+chain fields ----------------
def test_wallet_deposits_returns_asset_and_chain():
    import pymongo
    sync = pymongo.MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    body = {"username": f"TEST_{uuid.uuid4().hex[:8]}", "email": f"t_{uuid.uuid4().hex[:8]}@bd.io", "password": "TestPass123!"}
    r = requests.post(f"{API}/auth/register", json=body)
    assert r.status_code == 200
    reg = r.json()
    uid = reg["user"]["id"]
    token = reg["token"]

    unique = f"0xseeded:{uuid.uuid4().hex}"
    try:
        sync.deposits.insert_one({
            "_id": unique,
            "unique_id": unique,
            "user_id": uid,
            "username": reg["user"]["username"],
            "asset": "USDT",
            "coin": "USDT",
            "chain": "Polygon",
            "chain_id": "polygon",
            "amount": 12.5,
            "tx_hash": "0xh",
            "block_num": 1,
            "from_address": "0xa", "to_address": "0xb",
            "block_timestamp": "2026-01-01T00:00:00Z",
            "created_at": "2026-01-01T00:00:00+00:00",
        })
        r2 = requests.get(f"{API}/wallet/deposits", headers={"Authorization": f"Bearer {token}"})
        assert r2.status_code == 200
        rows = r2.json()
        assert len(rows) == 1
        row = rows[0]
        assert row["asset"] == "USDT"
        assert row["chain"] == "Polygon"
        assert row["chain_id"] == "polygon"
    finally:
        sync.deposits.delete_many({"user_id": uid})
