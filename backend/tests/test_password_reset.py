"""Password-reset flow regression tests (BetterDice.io)."""
import hashlib
import os
import re
import uuid
from datetime import datetime, timedelta, timezone

import pymongo
import pytest
import requests


def _load_url():
    for line in open("/app/frontend/.env"):
        if line.startswith("REACT_APP_BACKEND_URL"):
            return line.split("=", 1)[1].strip().strip('"')
    return os.environ["REACT_APP_BACKEND_URL"]


BASE_URL = _load_url().rstrip("/")
API = f"{BASE_URL}/api"

GENERIC_MSG_RE = re.compile(r"if an account", re.I)


def _env():
    env = {}
    for line in open("/app/backend/.env"):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k] = v.strip().strip('"').strip("'")
    return env


def _mongo():
    e = _env()
    return pymongo.MongoClient(e["MONGO_URL"])[e["DB_NAME"]]


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _register():
    tag = uuid.uuid4().hex[:8]
    body = {
        "username": f"TEST_pw_{tag}",
        "email": f"test_pw_{tag}@bd.io",
        "password": "OldPass123!",
    }
    r = requests.post(f"{API}/auth/register", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    data["password"] = body["password"]
    data["email"] = body["email"]
    return data


# ---------------- forgot-password ----------------
def test_forgot_password_existing_user_inserts_row():
    u = _register()
    db = _mongo()
    # ensure no last_reset_request stale
    db.users.update_one({"id": u["user"]["id"]}, {"$unset": {"last_reset_request": ""}})

    before = db.password_resets.count_documents({"user_id": u["user"]["id"]})
    r = requests.post(f"{API}/auth/forgot-password", json={"email": u["email"]})
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert GENERIC_MSG_RE.search(j["message"])

    rows = list(db.password_resets.find({"user_id": u["user"]["id"]}))
    assert len(rows) == before + 1
    row = rows[-1]
    assert "token_hash" in row and len(row["token_hash"]) == 64
    # raw token should NOT be stored
    assert not any(k in row for k in ("token", "raw_token"))
    assert row["email"] == u["email"].lower()
    assert row["used_at"] is None
    created = datetime.fromisoformat(row["created_at"])
    expires = datetime.fromisoformat(row["expires_at"])
    delta = (expires - created).total_seconds()
    assert 29 * 60 <= delta <= 31 * 60

    user_row = db.users.find_one({"id": u["user"]["id"]})
    assert user_row.get("last_reset_request")


def test_forgot_password_nonexistent_email_generic_and_no_row():
    db = _mongo()
    fake = f"nobody_{uuid.uuid4().hex[:8]}@bd.io"
    before = db.password_resets.count_documents({"email": fake.lower()})
    r = requests.post(f"{API}/auth/forgot-password", json={"email": fake})
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert GENERIC_MSG_RE.search(j["message"])
    after = db.password_resets.count_documents({"email": fake.lower()})
    assert after == before


def test_forgot_password_rate_limit_60s():
    u = _register()
    db = _mongo()
    # First request creates a row
    r1 = requests.post(f"{API}/auth/forgot-password", json={"email": u["email"]})
    assert r1.status_code == 200
    n1 = db.password_resets.count_documents({"user_id": u["user"]["id"]})
    assert n1 >= 1

    # Immediate second call — still generic 200, but NO new row
    r2 = requests.post(f"{API}/auth/forgot-password", json={"email": u["email"]})
    assert r2.status_code == 200
    n2 = db.password_resets.count_documents({"user_id": u["user"]["id"]})
    assert n2 == n1, "cooldown must not create a new row"

    # Rewind last_reset_request > 60s and request again — must create a new row
    past = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    db.users.update_one({"id": u["user"]["id"]}, {"$set": {"last_reset_request": past}})
    r3 = requests.post(f"{API}/auth/forgot-password", json={"email": u["email"]})
    assert r3.status_code == 200
    n3 = db.password_resets.count_documents({"user_id": u["user"]["id"]})
    assert n3 == n2 + 1


# ---------------- reset-password ----------------
def _insert_reset_row(db, user_id: str, email: str, raw_token: str, expires_in_min=30, used=False):
    now = datetime.now(timezone.utc)
    doc = {
        "token_hash": _sha256(raw_token),
        "user_id": user_id,
        "email": email.lower(),
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=expires_in_min)).isoformat(),
        "used_at": now.isoformat() if used else None,
    }
    db.password_resets.insert_one(doc)
    return doc


def test_reset_password_happy_path_and_login():
    u = _register()
    db = _mongo()
    raw = f"rawtoken_{uuid.uuid4().hex}"
    _insert_reset_row(db, u["user"]["id"], u["email"], raw)

    new_pw = "newpass456"
    r = requests.post(f"{API}/auth/reset-password", json={"token": raw, "new_password": new_pw})
    assert r.status_code == 200, r.text
    j = r.json()
    assert "token" in j and "user" in j
    assert j["user"]["email"] == u["email"]

    # (a) used_at set
    row = db.password_resets.find_one({"token_hash": _sha256(raw)})
    assert row["used_at"] is not None

    # (b) password_hash changed
    user_row = db.users.find_one({"id": u["user"]["id"]})
    old_hash_row = u  # we don't have old hash easily; verify old pw fails, new succeeds

    # (c) old password fails
    r_old = requests.post(f"{API}/auth/login", json={"email": u["email"], "password": u["password"]})
    assert r_old.status_code == 401

    # (d) new password works
    r_new = requests.post(f"{API}/auth/login", json={"email": u["email"], "password": new_pw})
    assert r_new.status_code == 200


def test_reset_password_unknown_token():
    r = requests.post(f"{API}/auth/reset-password", json={"token": "unknown_" + uuid.uuid4().hex, "new_password": "abcdef1"})
    assert r.status_code == 400
    assert "invalid" in r.text.lower() or "expired" in r.text.lower()


def test_reset_password_expired_token():
    u = _register()
    db = _mongo()
    raw = f"exp_{uuid.uuid4().hex}"
    _insert_reset_row(db, u["user"]["id"], u["email"], raw, expires_in_min=-5)
    r = requests.post(f"{API}/auth/reset-password", json={"token": raw, "new_password": "abcdef1"})
    assert r.status_code == 400


def test_reset_password_already_used_token():
    u = _register()
    db = _mongo()
    raw = f"used_{uuid.uuid4().hex}"
    _insert_reset_row(db, u["user"]["id"], u["email"], raw, used=True)
    r = requests.post(f"{API}/auth/reset-password", json={"token": raw, "new_password": "abcdef1"})
    assert r.status_code == 400


def test_reset_password_short_password_rejected():
    r = requests.post(f"{API}/auth/reset-password", json={"token": "abcdefgh", "new_password": "abc"})
    # Pydantic min_length=6 -> 422 (or 400 if custom)
    assert r.status_code in (400, 422)


def test_reset_password_mass_invalidates_other_tokens():
    u = _register()
    db = _mongo()
    raw_a = f"aa_{uuid.uuid4().hex}"
    raw_b = f"bb_{uuid.uuid4().hex}"
    _insert_reset_row(db, u["user"]["id"], u["email"], raw_a)
    _insert_reset_row(db, u["user"]["id"], u["email"], raw_b)
    # Consume raw_a
    r = requests.post(f"{API}/auth/reset-password", json={"token": raw_a, "new_password": "brandnew1"})
    assert r.status_code == 200
    # raw_b should now be used_at set even though never consumed
    row_b = db.password_resets.find_one({"token_hash": _sha256(raw_b)})
    assert row_b["used_at"] is not None
    # And attempting to use it should now fail
    r2 = requests.post(f"{API}/auth/reset-password", json={"token": raw_b, "new_password": "another1"})
    assert r2.status_code == 400
