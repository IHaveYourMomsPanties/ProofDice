"""BetterDice.io Phase 2 Step 1b (multi-chain: ETH + BNB + Polygon) regression tests."""
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

EXPECTED_COINS = ["BTC", "ETH", "USDC", "USDT", "BNB", "POL", "SOL", "GRAM", "SEPETH"]

# aggregate `wired` per asset (any network wired -> asset wired)
EXPECTED_WIRED = {
    "BTC": False, "ETH": True, "USDC": True, "USDT": True,
    "BNB": True, "POL": True, "SOL": False, "GRAM": False, "SEPETH": True,
}

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
def test_config_coins_and_assets():
    r = requests.get(f"{API}/config")
    assert r.status_code == 200
    j = r.json()
    assert j["coins"] == EXPECTED_COINS
    assets = j["assets"]
    assert set(assets.keys()) == set(EXPECTED_COINS)
    for c in EXPECTED_COINS:
        a = assets[c]
        assert a["code"] == c
        assert a["wired"] is EXPECTED_WIRED[c], f"{c} wired={a['wired']} expected {EXPECTED_WIRED[c]}"
        assert "name" in a and "decimals" in a and "color" in a and "min_bet" in a
    assert j["faucet_amounts"] == {}


def test_config_networks_list():
    j = requests.get(f"{API}/config").json()
    nets = j["networks"]
    assert isinstance(nets, list)
    assert len(nets) == 12, f"expected 12 network entries, got {len(nets)}"

    # Build (asset, chain_id) -> wired map
    pairs = {(n["asset"], n["chain_id"]): n["wired"] for n in nets}

    # Wired subset (9): ETH-eth, USDC-eth, USDC-polygon, USDT-eth, USDT-bnb,
    # USDT-polygon, BNB-bnb, POL-polygon, SEPETH-sepolia
    wired_expected = {
        ("ETH", "eth"), ("USDC", "eth"), ("USDC", "polygon"),
        ("USDT", "eth"), ("USDT", "bnb"), ("USDT", "polygon"),
        ("BNB", "bnb"), ("POL", "polygon"), ("SEPETH", "sepolia"),
    }
    for key in wired_expected:
        assert pairs.get(key) is True, f"{key} should be wired=True"

    # Unwired
    for key in [("BTC", "btc"), ("SOL", "sol"), ("GRAM", "ton")]:
        assert pairs.get(key) is False, f"{key} should be wired=False"

    # USDT has 3 networks; USDC has 2
    usdt_nets = [n for n in nets if n["asset"] == "USDT"]
    usdc_nets = [n for n in nets if n["asset"] == "USDC"]
    assert len(usdt_nets) == 3
    assert len(usdc_nets) == 2
    for n in usdt_nets + usdc_nets:
        assert n["contract"] and n["contract"].startswith("0x")


# ---------------- auth ----------------
def test_register_returns_zero_balances(user_a):
    u = user_a["user"]
    assert u["balances"] == {c: 0.0 for c in EXPECTED_COINS}
    assert u["nonce"] == 0
    assert len(u["server_seed_hashed"]) == 64
    assert user_a["token"]


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


# ---------------- wallet addresses (new per-asset+per-network shape) ----------------
def test_wallet_addresses_requires_auth():
    r = requests.get(f"{API}/wallet/addresses")
    assert r.status_code == 401


def test_wallet_addresses_shape_and_formats(user_a):
    r = requests.get(f"{API}/wallet/addresses", headers=auth_headers(user_a))
    assert r.status_code == 200, r.text
    j = r.json()
    assert "wallet_index" in j and isinstance(j["wallet_index"], int)
    assets = {row["asset"]: row for row in j["assets"]}
    assert set(assets.keys()) == set(EXPECTED_COINS)

    # Per-asset network counts
    assert len(assets["BTC"]["networks"]) == 1
    assert len(assets["ETH"]["networks"]) == 1
    assert len(assets["USDC"]["networks"]) == 2
    assert len(assets["USDT"]["networks"]) == 3
    assert len(assets["BNB"]["networks"]) == 1
    assert len(assets["POL"]["networks"]) == 1
    assert len(assets["SOL"]["networks"]) == 1
    assert len(assets["GRAM"]["networks"]) == 1
    assert len(assets["SEPETH"]["networks"]) == 1

    # Verify network entry fields
    for row in j["assets"]:
        for n in row["networks"]:
            for k in ("chain", "chain_id", "addr_kind", "contract", "wired", "min_deposit", "address"):
                assert k in n, f"missing {k} in {row['asset']} network entry"

    # BTC first (and only) network -> bech32
    btc_addr = assets["BTC"]["networks"][0]["address"]
    assert BECH32_RE.match(btc_addr), f"BTC not bech32: {btc_addr}"

    # SOL base58
    sol_addr = assets["SOL"]["networks"][0]["address"]
    assert B58_RE.match(sol_addr), f"SOL not b58: {sol_addr}"

    # GRAM TON friendly
    gram_addr = assets["GRAM"]["networks"][0]["address"]
    assert gram_addr.startswith(("UQ", "EQ")), f"GRAM not TON friendly: {gram_addr}"

    # All EVM addresses (ETH, BNB, POL, all USDC nets, all USDT nets) IDENTICAL for same user
    evm_addresses = set()
    for code in ("ETH", "USDC", "USDT", "BNB", "POL", "SEPETH"):
        for n in assets[code]["networks"]:
            if n["addr_kind"] == "evm":
                assert EVM_RE.match(n["address"]), f"{code}/{n['chain']} not EVM: {n['address']}"
                evm_addresses.add(n["address"].lower())
    assert len(evm_addresses) == 1, f"EVM addresses differ across chains: {evm_addresses}"


def test_wallet_addresses_deterministic(user_a):
    r1 = requests.get(f"{API}/wallet/addresses", headers=auth_headers(user_a)).json()
    r2 = requests.get(f"{API}/wallet/addresses", headers=auth_headers(user_a)).json()
    assert r1 == r2


def test_two_users_have_different_addresses(user_a, user_b):
    a_assets = {row["asset"]: row for row in requests.get(f"{API}/wallet/addresses", headers=auth_headers(user_a)).json()["assets"]}
    b_assets = {row["asset"]: row for row in requests.get(f"{API}/wallet/addresses", headers=auth_headers(user_b)).json()["assets"]}
    assert a_assets["BTC"]["networks"][0]["address"] != b_assets["BTC"]["networks"][0]["address"]
    assert a_assets["ETH"]["networks"][0]["address"] != b_assets["ETH"]["networks"][0]["address"]
    assert a_assets["SOL"]["networks"][0]["address"] != b_assets["SOL"]["networks"][0]["address"]


# ---------------- faucet disabled ----------------
def test_faucet_returns_400(user_a):
    r = requests.post(f"{API}/faucet/claim", headers=auth_headers(user_a))
    assert r.status_code == 400


# ---------------- dice ----------------
def test_dice_roll_insufficient_balance(user_a):
    r = requests.post(f"{API}/dice/roll", headers=auth_headers(user_a),
                      json={"coin": "BTC", "amount": 0.0001, "target": 50, "direction": "under"})
    assert r.status_code == 400
    assert "insufficient" in r.text.lower()


def test_dice_roll_invalid_coin(user_a):
    r = requests.post(f"{API}/dice/roll", headers=auth_headers(user_a),
                      json={"coin": "XRP", "amount": 1.0, "target": 50, "direction": "under"})
    assert r.status_code == 400


def test_dice_roll_and_provably_fair_determinism(user_b):
    # Manually credit balance via mongo (no full deposit path in test)
    import pymongo
    env = {}
    for line in open("/app/backend/.env"):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k] = v.strip().strip('"').strip("'")
    m = pymongo.MongoClient(env["MONGO_URL"])
    db = m[env["DB_NAME"]]
    db.users.update_one({"id": user_b["user"]["id"]}, {"$set": {"balances.BTC": 1.0}})

    r = requests.post(f"{API}/seeds/rotate", headers=auth_headers(user_b), json={"client_seed": "testseed"})
    assert r.status_code == 200
    r2 = requests.post(f"{API}/dice/roll", headers=auth_headers(user_b),
                       json={"coin": "BTC", "amount": 0.001, "target": 50, "direction": "under"})
    assert r2.status_code == 200, r2.text
    roll1 = r2.json()["roll"]
    r3 = requests.post(f"{API}/seeds/rotate", headers=auth_headers(user_b), json={"client_seed": "testseed"})
    prev = r3.json()["previous_server_seed"]
    digest = hmac.new(prev.encode(), b"testseed:0", hashlib.sha256).hexdigest()
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



# ---------------- SEPETH test-coin faucet ----------------
def _mongo():
    import pymongo
    env = {}
    for line in open("/app/backend/.env"):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k] = v.strip().strip('"').strip("'")
    m = pymongo.MongoClient(env["MONGO_URL"])
    return m[env["DB_NAME"]]


def test_test_faucet_requires_auth():
    r = requests.post(f"{API}/faucet/test-claim")
    assert r.status_code == 401


def test_test_faucet_credits_and_cooldown_and_roll():
    # fresh user so we know cooldown state
    u = _register()
    h = auth_headers(u)

    # 1st claim -> ok, +0.01 SEPETH
    r1 = requests.post(f"{API}/faucet/test-claim", headers=h)
    assert r1.status_code == 200, r1.text
    j1 = r1.json()
    assert j1["ok"] is True
    assert j1["coin"] == "SEPETH"
    assert j1["credited"] == 0.01
    assert j1["cooldown_s"] == 60
    assert abs(j1["balance"] - 0.01) < 1e-9

    # 2nd claim immediately -> 429
    r2 = requests.post(f"{API}/faucet/test-claim", headers=h)
    assert r2.status_code == 429, r2.text
    assert "cooldown" in r2.text.lower() or "try again" in r2.text.lower()

    # Rewind last_test_faucet to simulate >60s elapsed
    db = _mongo()
    from datetime import datetime, timezone, timedelta
    past = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    db.users.update_one({"id": u["user"]["id"]}, {"$set": {"last_test_faucet": past}})

    # 3rd claim succeeds -> balance now 0.02
    r3 = requests.post(f"{API}/faucet/test-claim", headers=h)
    assert r3.status_code == 200, r3.text
    j3 = r3.json()
    assert abs(j3["balance"] - 0.02) < 1e-9

    # SEPETH is spendable via /dice/roll
    r4 = requests.post(
        f"{API}/dice/roll",
        headers=h,
        json={"coin": "SEPETH", "amount": 0.001, "target": 50, "direction": "under"},
    )
    assert r4.status_code == 200, r4.text
    j4 = r4.json()
    assert j4["coin"] == "SEPETH"
    assert "roll" in j4
    assert 0 <= j4["roll"] <= 99.99
    assert "balance_after" in j4
    # provably-fair fields
    for k in ("server_seed_hashed", "client_seed", "nonce"):
        assert k in j4, f"missing PF field {k}"


def test_config_includes_sepeth_asset():
    j = requests.get(f"{API}/config").json()
    assert "SEPETH" in j["coins"]
    assert "SEPETH" in j["assets"]
    a = j["assets"]["SEPETH"]
    assert a["code"] == "SEPETH"
    assert a["wired"] is True


def test_wallet_addresses_sepeth_matches_eth(user_a):
    r = requests.get(f"{API}/wallet/addresses", headers=auth_headers(user_a)).json()
    assets = {row["asset"]: row for row in r["assets"]}
    sep = assets["SEPETH"]["networks"]
    assert len(sep) == 1
    net = sep[0]
    assert net["chain"] == "Ethereum Sepolia"
    assert net["chain_id"] == "sepolia"
    assert net["wired"] is True
    assert net["addr_kind"] == "evm"
    # SEPETH address equals ETH address (same EVM derivation)
    eth_addr = assets["ETH"]["networks"][0]["address"].lower()
    assert net["address"].lower() == eth_addr


def test_watcher_started_sepolia_chain():
    # Read supervisor backend log for evidence sepolia RPC is being called
    log_paths = [
        "/var/log/supervisor/backend.err.log",
        "/var/log/supervisor/backend.out.log",
    ]
    text = ""
    for p in log_paths:
        if os.path.exists(p):
            try:
                with open(p, "r", errors="ignore") as f:
                    text += f.read()[-200_000:]
            except Exception:
                pass
    assert "eth-sepolia.g.alchemy.com" in text, \
        "Sepolia watcher never called Alchemy RPC — chain not started?"
