"""BetterDice.io Phase 1 (real-crypto custodial) backend regression tests."""
import hashlib
import hmac
import os
import re
import uuid

import pytest
import requests


def _load_frontend_url():
    p = "/app/frontend/.env"
    if os.path.exists(p):
        for line in open(p):
            if line.startswith("REACT_APP_BACKEND_URL"):
                return line.split("=", 1)[1].strip().strip('"')
    return os.environ["REACT_APP_BACKEND_URL"]


BASE_URL = _load_frontend_url().rstrip("/")
API = f"{BASE_URL}/api"

EXPECTED_COINS = ["BTC", "ETH", "USDC", "USDT", "BNB", "SOL", "GRAM"]

BECH32_RE = re.compile(r"^bc1[a-z0-9]{20,90}$")
EVM_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
B58_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


def rand_user():
    tag = uuid.uuid4().hex[:8]
    return {
        "username": f"TEST_{tag}",
        "email": f"test_{tag}@bd.io",
        "password": "TestPass123!",
    }


def _register():
    body = rand_user()
    r = requests.post(f"{API}/auth/register", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    data["password"] = body["password"]
    data["email"] = body["email"]
    return data


@pytest.fixture(scope="module")
def user_a():
    return _register()


@pytest.fixture(scope="module")
def user_b():
    return _register()


def auth_headers(u):
    return {"Authorization": f"Bearer {u['token']}"}


# ---------------- config ----------------
def test_config_has_new_coin_list_and_specs():
    r = requests.get(f"{API}/config")
    assert r.status_code == 200
    j = r.json()
    assert j["coins"] == EXPECTED_COINS
    specs = j["coin_specs"]
    wired_expected = {"BTC": False, "ETH": True, "USDC": True, "USDT": False, "BNB": False, "SOL": False, "GRAM": False}
    for c in EXPECTED_COINS:
        s = specs[c]
        assert s["wired"] is wired_expected[c], f"{c} wired mismatch: {s['wired']}"
        assert "color" in s and "chain" in s and "decimals" in s
        assert s["min_deposit"] > 0
    # stables must have contract
    assert specs["USDC"]["contract"].startswith("0x")
    assert specs["USDT"]["contract"].startswith("0x")
    # non-stables should have contract=None
    for c in ("BTC", "ETH", "BNB", "SOL", "GRAM"):
        assert specs[c]["contract"] in (None, "")
    # faucet_amounts should be empty in phase 1
    assert j["faucet_amounts"] == {}


# ---------------- auth ----------------
def test_register_returns_zero_balances_and_wallet_index(user_a):
    u = user_a["user"]
    assert u["balances"] == {c: 0.0 for c in EXPECTED_COINS}
    assert u["nonce"] == 0
    assert len(u["server_seed_hashed"]) == 64
    assert user_a["token"]


def test_two_registrations_get_consecutive_wallet_indices():
    a = _register()
    b = _register()
    ra = requests.get(f"{API}/wallet/addresses", headers=auth_headers(a)).json()
    rb = requests.get(f"{API}/wallet/addresses", headers=auth_headers(b)).json()
    assert rb["wallet_index"] == ra["wallet_index"] + 1


def test_login_ok_and_wrong_password(user_a):
    r = requests.post(f"{API}/auth/login", json={"email": user_a["email"], "password": user_a["password"]})
    assert r.status_code == 200
    r2 = requests.post(f"{API}/auth/login", json={"email": user_a["email"], "password": "wrongpass"})
    assert r2.status_code == 401


def test_me_requires_auth(user_a):
    r = requests.get(f"{API}/auth/me")
    assert r.status_code == 401
    r3 = requests.get(f"{API}/auth/me", headers=auth_headers(user_a))
    assert r3.status_code == 200


# ---------------- wallet addresses ----------------
def test_wallet_addresses_requires_auth():
    r = requests.get(f"{API}/wallet/addresses")
    assert r.status_code == 401


def test_wallet_addresses_shape_and_formats(user_a):
    r = requests.get(f"{API}/wallet/addresses", headers=auth_headers(user_a))
    assert r.status_code == 200, r.text
    j = r.json()
    addrs = {row["coin"]: row["address"] for row in j["addresses"]}
    assert list(addrs.keys()) == EXPECTED_COINS

    # BTC: bech32
    assert BECH32_RE.match(addrs["BTC"]), f"BTC not bech32: {addrs['BTC']}"
    # EVM addrs
    for c in ("ETH", "USDC", "USDT", "BNB"):
        assert EVM_RE.match(addrs[c]), f"{c} not EVM: {addrs[c]}"
    # ETH-family share the same derivation
    assert addrs["ETH"].lower() == addrs["USDC"].lower() == addrs["USDT"].lower() == addrs["BNB"].lower()
    # SOL: base58
    assert B58_RE.match(addrs["SOL"]), f"SOL not b58: {addrs['SOL']}"
    # GRAM: TON friendly-address
    assert addrs["GRAM"].startswith(("UQ", "EQ")), f"GRAM not TON friendly: {addrs['GRAM']}"


def test_wallet_addresses_deterministic(user_a):
    r1 = requests.get(f"{API}/wallet/addresses", headers=auth_headers(user_a)).json()
    r2 = requests.get(f"{API}/wallet/addresses", headers=auth_headers(user_a)).json()
    assert r1 == r2


def test_two_users_have_different_addresses(user_a, user_b):
    a = {r["coin"]: r["address"] for r in requests.get(f"{API}/wallet/addresses", headers=auth_headers(user_a)).json()["addresses"]}
    b = {r["coin"]: r["address"] for r in requests.get(f"{API}/wallet/addresses", headers=auth_headers(user_b)).json()["addresses"]}
    assert a["BTC"] != b["BTC"]
    assert a["ETH"] != b["ETH"]
    assert a["SOL"] != b["SOL"]
    assert a["GRAM"] != b["GRAM"]


# ---------------- faucet disabled ----------------
def test_faucet_returns_400_with_deposit_message(user_a):
    r = requests.post(f"{API}/faucet/claim", headers=auth_headers(user_a))
    assert r.status_code == 400
    body = r.text.lower()
    assert "deposit" in body or "/api/wallet/addresses" in body
    assert "betterdice" in body or "token" in body


# ---------------- dice ----------------
def test_dice_roll_insufficient_balance(user_a):
    r = requests.post(
        f"{API}/dice/roll",
        headers=auth_headers(user_a),
        json={"coin": "BTC", "amount": 0.0001, "target": 50, "direction": "under"},
    )
    assert r.status_code == 400
    assert "insufficient" in r.text.lower()


def test_dice_roll_invalid_coin(user_a):
    r = requests.post(f"{API}/dice/roll", headers=auth_headers(user_a),
                      json={"coin": "XRP", "amount": 1.0, "target": 50, "direction": "under"})
    assert r.status_code == 400


def test_dice_roll_after_manual_credit_and_prov_fair_determinism(user_b):
    # Manually credit balance via mongo for the test (bypass — no deposit watcher yet)
    import pymongo
    from urllib.parse import quote_plus
    mongo_url = os.environ.get("MONGO_URL") or open("/app/backend/.env").read()
    # Read from backend/.env
    env = {}
    for line in open("/app/backend/.env"):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k] = v.strip().strip('"').strip("'")
    m = pymongo.MongoClient(env["MONGO_URL"])
    db = m[env["DB_NAME"]]
    db.users.update_one({"id": user_b["user"]["id"]}, {"$set": {"balances." + "BTC": 1.0}})
    # rotate seeds
    r = requests.post(f"{API}/seeds/rotate", headers=auth_headers(user_b), json={"client_seed": "testseed"})
    assert r.status_code == 200
    # roll
    r2 = requests.post(f"{API}/dice/roll", headers=auth_headers(user_b),
                       json={"coin": "BTC", "amount": 0.001, "target": 50, "direction": "under"})
    assert r2.status_code == 200, r2.text
    roll1 = r2.json()["roll"]
    # rotate again to reveal server seed
    r3 = requests.post(f"{API}/seeds/rotate", headers=auth_headers(user_b), json={"client_seed": "testseed"})
    prev = r3.json()["previous_server_seed"]
    msg = f"testseed:0".encode()
    digest = hmac.new(prev.encode(), msg, hashlib.sha256).hexdigest()
    expected = round((int(digest[:8], 16) % 10000) / 100.0, 2)
    assert expected == roll1


# ---------------- bets ----------------
def test_bets_endpoints(user_a):
    for path in ("/bets/all", "/bets/high-rollers"):
        r = requests.get(f"{API}{path}")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
    r2 = requests.get(f"{API}/bets/mine", headers=auth_headers(user_a))
    assert r2.status_code == 200


def test_bets_mine_requires_auth():
    r = requests.get(f"{API}/bets/mine")
    assert r.status_code == 401


# ---------------- seeds ----------------
def test_seeds_rotate(user_a):
    r = requests.post(f"{API}/seeds/rotate", headers=auth_headers(user_a), json={"client_seed": "newseed"})
    assert r.status_code == 200
    j = r.json()
    assert j["nonce"] == 0
    assert hashlib.sha256(j["previous_server_seed"].encode()).hexdigest() == j["previous_server_seed_hashed"]


# ---------------- chat ----------------
def test_chat_flow(user_a):
    msg = f"hello TEST_{uuid.uuid4().hex[:6]}"
    r = requests.post(f"{API}/chat/messages", headers=auth_headers(user_a), json={"message": msg})
    assert r.status_code == 200
    r2 = requests.get(f"{API}/chat/messages")
    assert r2.status_code == 200
    assert any(m["message"] == msg for m in r2.json())
