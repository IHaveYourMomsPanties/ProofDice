"""BetterDice.io crypto dice gambling backend.

Provably-fair dice roll engine + JWT auth + demo-money balances + bet history + chat.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, List, Optional

import jwt
from bcrypt import checkpw, gensalt, hashpw
from bson import ObjectId
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, BeforeValidator, ConfigDict, EmailStr, Field
from starlette.middleware.cors import CORSMiddleware

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-me-in-prod-betterdice")
JWT_ALGO = "HS256"
JWT_TTL_HOURS = 24 * 7

SUPPORTED_COINS = ["BTC", "LTC", "DOGE", "ETH"]
FAUCET_AMOUNTS = {"BTC": 0.00010000, "LTC": 0.10000000, "DOGE": 100.00000000, "ETH": 0.00500000}
FAUCET_COOLDOWN_MIN = 5
HOUSE_EDGE_PCT = 1.0  # 1% house edge

app = FastAPI(title="BetterDice API")
api = APIRouter(prefix="/api")
bearer = HTTPBearer(auto_error=False)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("betterdice")

# ---------------------------------------------------------------------------
# Helpers - Mongo & datetime
# ---------------------------------------------------------------------------
def _coerce_object_id(v):
    if isinstance(v, ObjectId):
        return str(v)
    return v


PyObjectId = Annotated[str, BeforeValidator(_coerce_object_id)]


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class UserPublic(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    username: str
    email: EmailStr
    balances: dict
    server_seed_hashed: str
    client_seed: str
    nonce: int
    wagered: dict
    profit: dict
    bets_count: int
    created_at: str


class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=24)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class AuthOut(BaseModel):
    token: str
    user: UserPublic


class DiceRollIn(BaseModel):
    coin: str
    amount: float = Field(gt=0)
    target: float = Field(ge=0.01, le=99.98)  # 0.01 – 99.98
    direction: str  # 'over' | 'under'


class DiceRollOut(BaseModel):
    id: str
    roll: float
    won: bool
    payout_multiplier: float
    win_chance: float
    profit: float
    balance_after: float
    server_seed_hashed: str
    client_seed: str
    nonce: int
    target: float
    direction: str
    coin: str


class BetPublic(BaseModel):
    id: str
    username: str
    coin: str
    amount: float
    target: float
    direction: str
    roll: float
    payout_multiplier: float
    win_chance: float
    won: bool
    profit: float
    nonce: int
    server_seed_hashed: str
    client_seed: str
    created_at: str


class SeedsUpdateIn(BaseModel):
    client_seed: str = Field(min_length=1, max_length=64)


class SeedsRotateOut(BaseModel):
    previous_server_seed: str
    previous_server_seed_hashed: str
    new_server_seed_hashed: str
    client_seed: str
    nonce: int


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=280)


class ChatOut(BaseModel):
    id: str
    username: str
    message: str
    created_at: str


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def hash_password(pw: str) -> str:
    return hashpw(pw.encode(), gensalt()).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return checkpw(pw.encode(), hashed.encode())
    except Exception:
        return False


def create_token(user_id: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=JWT_TTL_HOURS)
    return jwt.encode({"sub": user_id, "exp": exp}, JWT_SECRET, algorithm=JWT_ALGO)


async def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
) -> dict:
    if not creds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing token")
    try:
        payload = jwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALGO])
        user_id = payload.get("sub")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    user = await db.users.find_one({"id": user_id})
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return user


def to_user_public(u: dict) -> UserPublic:
    return UserPublic(
        id=u["id"],
        username=u["username"],
        email=u["email"],
        balances=u["balances"],
        server_seed_hashed=u["server_seed_hashed"],
        client_seed=u["client_seed"],
        nonce=u["nonce"],
        wagered=u.get("wagered", {c: 0.0 for c in SUPPORTED_COINS}),
        profit=u.get("profit", {c: 0.0 for c in SUPPORTED_COINS}),
        bets_count=u.get("bets_count", 0),
        created_at=u["created_at"],
    )


# ---------------------------------------------------------------------------
# Dice engine (provably fair)
# ---------------------------------------------------------------------------
def new_server_seed() -> str:
    return secrets.token_hex(32)


def hash_seed(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def roll_dice(server_seed: str, client_seed: str, nonce: int) -> float:
    """Return roll in [0.00, 99.99] (2 decimals) using HMAC-SHA256."""
    msg = f"{client_seed}:{nonce}".encode()
    digest = hmac.new(server_seed.encode(), msg, hashlib.sha256).hexdigest()
    # take first 5 hex chars => resample if value >= 10^6 - (10^6 mod 10000)
    # simple approach: take first 8 hex chars -> mod 10000
    val = int(digest[:8], 16) % 10000
    return round(val / 100.0, 2)


def compute_payout(win_chance: float) -> float:
    """1% house edge => payout = 99 / win_chance"""
    return round((100.0 - HOUSE_EDGE_PCT) / win_chance, 6)


def compute_win_chance(target: float, direction: str) -> float:
    if direction == "under":
        return round(target, 2)
    return round(99.99 - target, 2)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def _startup() -> None:
    await db.users.create_index("email", unique=True)
    await db.users.create_index("username", unique=True)
    await db.users.create_index("id", unique=True)
    await db.bets.create_index([("created_at", -1)])
    await db.bets.create_index([("user_id", 1), ("created_at", -1)])
    await db.chat.create_index([("created_at", -1)])
    logger.info("BetterDice API startup complete")


@app.on_event("shutdown")
async def _shutdown() -> None:
    client.close()


# ---------------------------------------------------------------------------
# Routes: meta
# ---------------------------------------------------------------------------
@api.get("/")
async def root():
    return {"service": "betterdice", "ok": True}


@api.get("/config")
async def get_config():
    return {
        "coins": SUPPORTED_COINS,
        "faucet_amounts": FAUCET_AMOUNTS,
        "faucet_cooldown_min": FAUCET_COOLDOWN_MIN,
        "house_edge_pct": HOUSE_EDGE_PCT,
    }


# ---------------------------------------------------------------------------
# Routes: auth
# ---------------------------------------------------------------------------
@api.post("/auth/register", response_model=AuthOut)
async def register(body: RegisterIn):
    existing = await db.users.find_one({"$or": [{"email": body.email}, {"username": body.username}]})
    if existing:
        raise HTTPException(400, "Username or email already in use")
    server_seed = new_server_seed()
    now = utcnow_iso()
    starting_balance = {"BTC": 0.001, "LTC": 1.0, "DOGE": 1000.0, "ETH": 0.05}
    doc = {
        "id": str(uuid.uuid4()),
        "username": body.username,
        "email": body.email,
        "password_hash": hash_password(body.password),
        "balances": starting_balance,
        "wagered": {c: 0.0 for c in SUPPORTED_COINS},
        "profit": {c: 0.0 for c in SUPPORTED_COINS},
        "bets_count": 0,
        "server_seed": server_seed,
        "server_seed_hashed": hash_seed(server_seed),
        "client_seed": secrets.token_hex(8),
        "nonce": 0,
        "last_faucet": None,
        "created_at": now,
    }
    await db.users.insert_one(doc)
    return AuthOut(token=create_token(doc["id"]), user=to_user_public(doc))


@api.post("/auth/login", response_model=AuthOut)
async def login(body: LoginIn):
    u = await db.users.find_one({"email": body.email})
    if not u or not verify_password(body.password, u["password_hash"]):
        raise HTTPException(401, "Invalid email or password")
    return AuthOut(token=create_token(u["id"]), user=to_user_public(u))


@api.get("/auth/me", response_model=UserPublic)
async def me(user=Depends(get_current_user)):
    return to_user_public(user)


# ---------------------------------------------------------------------------
# Routes: faucet
# ---------------------------------------------------------------------------
@api.post("/faucet/claim")
async def faucet_claim(user=Depends(get_current_user)):
    now = datetime.now(timezone.utc)
    last = user.get("last_faucet")
    if last:
        last_dt = datetime.fromisoformat(last)
        if (now - last_dt) < timedelta(minutes=FAUCET_COOLDOWN_MIN):
            remaining = int(FAUCET_COOLDOWN_MIN * 60 - (now - last_dt).total_seconds())
            raise HTTPException(429, f"Faucet cooldown, try again in {remaining}s")
    balances = user["balances"]
    for c, a in FAUCET_AMOUNTS.items():
        balances[c] = round(balances.get(c, 0.0) + a, 8)
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"balances": balances, "last_faucet": now.isoformat()}},
    )
    return {"ok": True, "credited": FAUCET_AMOUNTS, "balances": balances}


# ---------------------------------------------------------------------------
# Routes: seeds
# ---------------------------------------------------------------------------
@api.post("/seeds/rotate", response_model=SeedsRotateOut)
async def seeds_rotate(body: SeedsUpdateIn, user=Depends(get_current_user)):
    prev_seed = user["server_seed"]
    prev_hash = user["server_seed_hashed"]
    new_seed = new_server_seed()
    new_hash = hash_seed(new_seed)
    await db.users.update_one(
        {"id": user["id"]},
        {
            "$set": {
                "server_seed": new_seed,
                "server_seed_hashed": new_hash,
                "client_seed": body.client_seed,
                "nonce": 0,
            }
        },
    )
    return SeedsRotateOut(
        previous_server_seed=prev_seed,
        previous_server_seed_hashed=prev_hash,
        new_server_seed_hashed=new_hash,
        client_seed=body.client_seed,
        nonce=0,
    )


# ---------------------------------------------------------------------------
# Routes: dice
# ---------------------------------------------------------------------------
@api.post("/dice/roll", response_model=DiceRollOut)
async def dice_roll(body: DiceRollIn, user=Depends(get_current_user)):
    if body.coin not in SUPPORTED_COINS:
        raise HTTPException(400, "Unsupported coin")
    if body.direction not in ("over", "under"):
        raise HTTPException(400, "direction must be 'over' or 'under'")
    if body.amount <= 0:
        raise HTTPException(400, "amount must be positive")
    balances = user["balances"]
    bal = balances.get(body.coin, 0.0)
    if bal < body.amount:
        raise HTTPException(400, "Insufficient balance")

    win_chance = compute_win_chance(body.target, body.direction)
    if win_chance <= 0 or win_chance >= 100:
        raise HTTPException(400, "Invalid target")
    payout_mult = compute_payout(win_chance)

    server_seed = user["server_seed"]
    client_seed = user["client_seed"]
    nonce = user["nonce"]
    roll = roll_dice(server_seed, client_seed, nonce)

    if body.direction == "under":
        won = roll < body.target
    else:
        won = roll > body.target

    if won:
        profit = round(body.amount * (payout_mult - 1.0), 8)
    else:
        profit = -round(body.amount, 8)

    new_bal = round(bal + profit, 8)
    balances[body.coin] = new_bal
    wagered = user.get("wagered", {c: 0.0 for c in SUPPORTED_COINS})
    profit_total = user.get("profit", {c: 0.0 for c in SUPPORTED_COINS})
    wagered[body.coin] = round(wagered.get(body.coin, 0.0) + body.amount, 8)
    profit_total[body.coin] = round(profit_total.get(body.coin, 0.0) + profit, 8)

    server_seed_hashed = user["server_seed_hashed"]

    await db.users.update_one(
        {"id": user["id"]},
        {
            "$set": {
                "balances": balances,
                "wagered": wagered,
                "profit": profit_total,
                "nonce": nonce + 1,
            },
            "$inc": {"bets_count": 1},
        },
    )

    bet_doc = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "username": user["username"],
        "coin": body.coin,
        "amount": body.amount,
        "target": body.target,
        "direction": body.direction,
        "roll": roll,
        "payout_multiplier": payout_mult,
        "win_chance": win_chance,
        "won": won,
        "profit": profit,
        "nonce": nonce,
        "server_seed_hashed": server_seed_hashed,
        "client_seed": client_seed,
        "created_at": utcnow_iso(),
    }
    await db.bets.insert_one(bet_doc)

    return DiceRollOut(
        id=bet_doc["id"],
        roll=roll,
        won=won,
        payout_multiplier=payout_mult,
        win_chance=win_chance,
        profit=profit,
        balance_after=new_bal,
        server_seed_hashed=server_seed_hashed,
        client_seed=client_seed,
        nonce=nonce,
        target=body.target,
        direction=body.direction,
        coin=body.coin,
    )


# ---------------------------------------------------------------------------
# Routes: bets
# ---------------------------------------------------------------------------
def bet_from_doc(d: dict) -> BetPublic:
    return BetPublic(
        id=d["id"],
        username=d["username"],
        coin=d["coin"],
        amount=d["amount"],
        target=d["target"],
        direction=d["direction"],
        roll=d["roll"],
        payout_multiplier=d["payout_multiplier"],
        win_chance=d["win_chance"],
        won=d["won"],
        profit=d["profit"],
        nonce=d["nonce"],
        server_seed_hashed=d["server_seed_hashed"],
        client_seed=d["client_seed"],
        created_at=d["created_at"],
    )


@api.get("/bets/all", response_model=List[BetPublic])
async def bets_all(limit: int = 25):
    limit = max(1, min(limit, 100))
    rows = await db.bets.find({}, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    return [bet_from_doc(r) for r in rows]


@api.get("/bets/mine", response_model=List[BetPublic])
async def bets_mine(limit: int = 25, user=Depends(get_current_user)):
    limit = max(1, min(limit, 100))
    rows = (
        await db.bets.find({"user_id": user["id"]}, {"_id": 0})
        .sort("created_at", -1)
        .limit(limit)
        .to_list(limit)
    )
    return [bet_from_doc(r) for r in rows]


@api.get("/bets/high-rollers", response_model=List[BetPublic])
async def bets_high_rollers(limit: int = 25):
    limit = max(1, min(limit, 100))
    rows = (
        await db.bets.find({"won": True}, {"_id": 0})
        .sort("profit", -1)
        .limit(limit)
        .to_list(limit)
    )
    return [bet_from_doc(r) for r in rows]


# ---------------------------------------------------------------------------
# Routes: chat
# ---------------------------------------------------------------------------
@api.get("/chat/messages", response_model=List[ChatOut])
async def chat_list(limit: int = 50):
    limit = max(1, min(limit, 200))
    rows = await db.chat.find({}, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    rows.reverse()
    return [ChatOut(id=r["id"], username=r["username"], message=r["message"], created_at=r["created_at"]) for r in rows]


@api.post("/chat/messages", response_model=ChatOut)
async def chat_post(body: ChatIn, user=Depends(get_current_user)):
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "username": user["username"],
        "message": body.message.strip(),
        "created_at": utcnow_iso(),
    }
    await db.chat.insert_one(doc)
    return ChatOut(id=doc["id"], username=doc["username"], message=doc["message"], created_at=doc["created_at"])


# ---------------------------------------------------------------------------
# Routes: leaderboard
# ---------------------------------------------------------------------------
@api.get("/leaderboard")
async def leaderboard(limit: int = 10):
    limit = max(1, min(limit, 50))
    pipeline = [
        {"$project": {"_id": 0, "username": 1, "bets_count": 1, "profit": 1, "wagered": 1}},
        {"$sort": {"bets_count": -1}},
        {"$limit": limit},
    ]
    rows = await db.users.aggregate(pipeline).to_list(limit)
    return rows


# ---------------------------------------------------------------------------
# Mount
# ---------------------------------------------------------------------------
app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
