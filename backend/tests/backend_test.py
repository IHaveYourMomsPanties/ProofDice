"""SimpleDice backend regression tests."""
import hashlib
import hmac
import os
import time
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


def rand_user():
    tag = uuid.uuid4().hex[:8]
    return {
        "username": f"TEST_{tag}",
        "email": f"test_{tag}@example.com",
        "password": "TestPass123!",
    }


@pytest.fixture(scope="module")
def user_a():
    body = rand_user()
    r = requests.post(f"{API}/auth/register", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    data["password"] = body["password"]
    data["email"] = body["email"]
    return data


@pytest.fixture(scope="module")
def user_b():
    body = rand_user()
    r = requests.post(f"{API}/auth/register", json=body)
    assert r.status_code == 200
    return r.json()


def auth_headers(u):
    return {"Authorization": f"Bearer {u['token']}"}


# ---- config ----
def test_config():
    r = requests.get(f"{API}/config")
    assert r.status_code == 200
    j = r.json()
    assert j["coins"] == ["BTC", "LTC", "DOGE", "ETH"]
    assert set(j["faucet_amounts"].keys()) == {"BTC", "LTC", "DOGE", "ETH"}


# ---- auth ----
def test_register_returns_expected_shape(user_a):
    u = user_a["user"]
    assert u["balances"] == {"BTC": 0.001, "LTC": 1.0, "DOGE": 1000.0, "ETH": 0.05}
    assert u["nonce"] == 0
    assert len(u["server_seed_hashed"]) == 64
    assert u["client_seed"]
    assert user_a["token"]


def test_login_ok_and_wrong_password(user_a):
    r = requests.post(f"{API}/auth/login", json={"email": user_a["email"], "password": user_a["password"]})
    assert r.status_code == 200
    r2 = requests.post(f"{API}/auth/login", json={"email": user_a["email"], "password": "wrongpass"})
    assert r2.status_code == 401


def test_me_requires_auth(user_a):
    r = requests.get(f"{API}/auth/me")
    assert r.status_code == 401
    r2 = requests.get(f"{API}/auth/me", headers={"Authorization": "Bearer notatoken"})
    assert r2.status_code == 401
    r3 = requests.get(f"{API}/auth/me", headers=auth_headers(user_a))
    assert r3.status_code == 200
    assert r3.json()["email"] == user_a["email"]


# ---- provably fair determinism ----
def hmac_roll(server_seed, client_seed, nonce):
    msg = f"{client_seed}:{nonce}".encode()
    digest = hmac.new(server_seed.encode(), msg, hashlib.sha256).hexdigest()
    return round((int(digest[:8], 16) % 10000) / 100.0, 2)


def test_dice_roll_under_and_over(user_a):
    # Under
    r = requests.post(
        f"{API}/dice/roll",
        headers=auth_headers(user_a),
        json={"coin": "DOGE", "amount": 1.0, "target": 50.0, "direction": "under"},
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["win_chance"] == 50.0
    assert abs(j["payout_multiplier"] - 1.98) < 0.001
    assert 0.0 <= j["roll"] <= 99.99
    # Over
    r2 = requests.post(
        f"{API}/dice/roll",
        headers=auth_headers(user_a),
        json={"coin": "DOGE", "amount": 1.0, "target": 50.0, "direction": "over"},
    )
    assert r2.status_code == 200
    j2 = r2.json()
    assert j2["win_chance"] == round(99.99 - 50.0, 2)
    assert j2["nonce"] == j["nonce"] + 1  # nonce increments


def test_dice_roll_determinism(user_b):
    # rotate to known seeds; use client_seed = 'testseed'
    r = requests.post(f"{API}/seeds/rotate", headers=auth_headers(user_b), json={"client_seed": "testseed"})
    assert r.status_code == 200
    # get me to know current hashed server seed
    me = requests.get(f"{API}/auth/me", headers=auth_headers(user_b)).json()
    assert me["nonce"] == 0
    assert me["client_seed"] == "testseed"

    # perform roll
    r2 = requests.post(
        f"{API}/dice/roll",
        headers=auth_headers(user_b),
        json={"coin": "DOGE", "amount": 1.0, "target": 50, "direction": "under"},
    )
    assert r2.status_code == 200
    roll1 = r2.json()["roll"]

    # rotate again with same seed; now new server_seed but same client_seed & nonce=0
    r3 = requests.post(f"{API}/seeds/rotate", headers=auth_headers(user_b), json={"client_seed": "testseed"})
    prev_server_seed = r3.json()["previous_server_seed"]
    # verify hash of previous seed matches previous_server_seed_hashed
    assert hashlib.sha256(prev_server_seed.encode()).hexdigest() == r3.json()["previous_server_seed_hashed"]
    # recompute roll offline using revealed prev server seed
    expected = hmac_roll(prev_server_seed, "testseed", 0)
    assert expected == roll1, f"expected {expected}, got {roll1}"


def test_dice_roll_validations(user_a):
    # invalid coin
    r = requests.post(f"{API}/dice/roll", headers=auth_headers(user_a),
                      json={"coin": "XRP", "amount": 1.0, "target": 50, "direction": "under"})
    assert r.status_code == 400
    # invalid direction
    r = requests.post(f"{API}/dice/roll", headers=auth_headers(user_a),
                      json={"coin": "DOGE", "amount": 1.0, "target": 50, "direction": "sideways"})
    assert r.status_code == 400
    # negative amount -> Pydantic 422
    r = requests.post(f"{API}/dice/roll", headers=auth_headers(user_a),
                      json={"coin": "DOGE", "amount": -1.0, "target": 50, "direction": "under"})
    assert r.status_code in (400, 422)
    # bad target
    r = requests.post(f"{API}/dice/roll", headers=auth_headers(user_a),
                      json={"coin": "DOGE", "amount": 1.0, "target": 0.0, "direction": "under"})
    assert r.status_code in (400, 422)
    # insufficient balance
    r = requests.post(f"{API}/dice/roll", headers=auth_headers(user_a),
                      json={"coin": "BTC", "amount": 999999.0, "target": 50, "direction": "under"})
    assert r.status_code == 400


# ---- faucet ----
def test_faucet_claim_and_cooldown():
    body = rand_user()
    r = requests.post(f"{API}/auth/register", json=body)
    tok = r.json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    r1 = requests.post(f"{API}/faucet/claim", headers=h)
    assert r1.status_code == 200
    assert "balances" in r1.json()
    r2 = requests.post(f"{API}/faucet/claim", headers=h)
    assert r2.status_code == 429


# ---- seeds rotate ----
def test_seeds_rotate_resets_nonce(user_a):
    r = requests.post(f"{API}/seeds/rotate", headers=auth_headers(user_a), json={"client_seed": "newseed123"})
    assert r.status_code == 200
    j = r.json()
    assert j["nonce"] == 0
    assert j["client_seed"] == "newseed123"
    assert hashlib.sha256(j["previous_server_seed"].encode()).hexdigest() == j["previous_server_seed_hashed"]


# ---- bets endpoints ----
def test_bets_endpoints(user_a, user_b):
    r = requests.get(f"{API}/bets/all")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    r2 = requests.get(f"{API}/bets/mine", headers=auth_headers(user_a))
    assert r2.status_code == 200
    ids = {b["username"] for b in r2.json()}
    assert ids <= {user_a["user"]["username"]}
    r3 = requests.get(f"{API}/bets/high-rollers")
    assert r3.status_code == 200
    for bet in r3.json():
        assert bet["won"] is True


def test_bets_mine_requires_auth():
    r = requests.get(f"{API}/bets/mine")
    assert r.status_code == 401


# ---- chat ----
def test_chat_flow(user_a):
    msg = f"hello TEST_{uuid.uuid4().hex[:6]}"
    r = requests.post(f"{API}/chat/messages", headers=auth_headers(user_a), json={"message": msg})
    assert r.status_code == 200
    r2 = requests.get(f"{API}/chat/messages")
    assert r2.status_code == 200
    msgs = r2.json()
    assert any(m["message"] == msg for m in msgs)


def test_chat_post_requires_auth():
    r = requests.post(f"{API}/chat/messages", json={"message": "hi"})
    assert r.status_code == 401
