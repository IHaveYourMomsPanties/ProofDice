"""Password reset flow for BetterDice.io.

Design (defensive against email enumeration + DB leaks + replay):
  - Request endpoint returns generic 200 whether or not the email exists.
  - Reset token = 32-byte URL-safe random string. Only the SHA-256 HASH is
    stored in db.password_resets, never the raw token.
  - Tokens expire 30 minutes after issuance and are single-use (marked
    `used_at` on first successful reset).
  - Per-email rate limit: at most one reset request per 60 seconds.
  - Delivery via Resend, non-blocking (`asyncio.to_thread`).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import resend
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

logger = logging.getLogger("betterdice.password_reset")

RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "onboarding@resend.dev")
PUBLIC_FRONTEND_URL = os.environ.get("PUBLIC_FRONTEND_URL", "").rstrip("/")

if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY

RESET_TOKEN_TTL_MIN = 30
RESET_REQUEST_COOLDOWN_S = 60


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_reset_token() -> tuple[str, str]:
    """Return (raw_token, token_hash). Send raw via email, store hash in DB."""
    tok = secrets.token_urlsafe(32)
    return tok, _hash_token(tok)


def _reset_email_html(username: str, reset_url: str, ttl_min: int) -> str:
    return f"""
<!doctype html>
<html>
<body style="margin:0;padding:0;background:#fbf5ea;font-family:Arial,Helvetica,sans-serif;color:#1a3d2c;">
  <table role="presentation" align="center" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;margin:32px auto;background:#ffffff;border-radius:20px;overflow:hidden;box-shadow:0 6px 20px rgba(7,85,50,0.12);">
    <tr>
      <td style="background:linear-gradient(135deg,#0fa968 0%,#075532 55%,#ff6b57 130%);padding:28px 32px;color:#ffffff;">
        <div style="font-family:'Courier New',monospace;font-size:12px;letter-spacing:0.3em;opacity:0.85;text-transform:uppercase;">BetterDice.io</div>
        <div style="font-size:24px;font-weight:900;margin-top:6px;">Reset your password</div>
      </td>
    </tr>
    <tr>
      <td style="padding:24px 32px 8px 32px;">
        <p style="margin:0 0 12px 0;font-size:15px;line-height:1.5;">Hi <b>{username}</b>,</p>
        <p style="margin:0 0 20px 0;font-size:15px;line-height:1.5;">We got a request to reset the password on your BetterDice account. Click the button below to pick a new one:</p>
        <p style="margin:0 0 24px 0;text-align:center;">
          <a href="{reset_url}" style="display:inline-block;background:#0fa968;color:#ffffff;font-weight:900;letter-spacing:0.16em;text-decoration:none;padding:14px 28px;border-radius:999px;font-size:14px;">RESET PASSWORD</a>
        </p>
        <p style="margin:0 0 8px 0;font-size:13px;color:#4a6b58;">This link expires in {ttl_min} minutes and can only be used once.</p>
        <p style="margin:0 0 24px 0;font-size:13px;color:#4a6b58;">If you didn't ask for this, you can safely ignore this email — nothing was changed.</p>
        <hr style="border:none;border-top:1px solid #ead9b4;margin:16px 0;" />
        <p style="margin:0;font-size:11px;color:#7a8a80;word-break:break-all;">If the button doesn't work, paste this URL into your browser:<br/>{reset_url}</p>
      </td>
    </tr>
    <tr>
      <td style="padding:12px 32px 24px 32px;font-size:11px;color:#7a8a80;">
        BetterDice.io · Play responsibly · Follow your local laws.
      </td>
    </tr>
  </table>
</body>
</html>
""".strip()


async def send_reset_email(recipient: str, username: str, raw_token: str) -> Optional[str]:
    """Send the reset link via Resend. Returns email id on success, None on failure."""
    if not RESEND_API_KEY:
        logger.warning("RESEND_API_KEY missing — cannot send reset email")
        return None
    if not PUBLIC_FRONTEND_URL:
        logger.warning("PUBLIC_FRONTEND_URL missing — cannot build reset link")
        return None

    reset_url = f"{PUBLIC_FRONTEND_URL}/reset-password?token={raw_token}"
    html = _reset_email_html(username, reset_url, RESET_TOKEN_TTL_MIN)

    params = {
        "from": SENDER_EMAIL,
        "to": [recipient],
        "subject": "Reset your BetterDice password",
        "html": html,
    }
    try:
        email = await asyncio.to_thread(resend.Emails.send, params)
        eid = (email or {}).get("id")
        logger.info("reset email sent to %s id=%s", recipient, eid)
        return eid
    except Exception as e:  # noqa: BLE001
        logger.exception("resend send failed for %s: %s", recipient, e)
        return None


async def create_reset_record(db, user: dict, token_hash: str) -> None:
    now = datetime.now(timezone.utc)
    await db.password_resets.insert_one(
        {
            "token_hash": token_hash,
            "user_id": user["id"],
            "email": user["email"].lower(),
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=RESET_TOKEN_TTL_MIN)).isoformat(),
            "used_at": None,
        }
    )
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"last_reset_request": now.isoformat()}},
    )


async def consume_reset_token(db, raw_token: str) -> Optional[dict]:
    """Return the user doc if the token is valid + unused + unexpired; else None.

    Marks the token as `used_at=now` atomically so it can't be replayed.
    """
    token_hash = _hash_token(raw_token)
    now = datetime.now(timezone.utc)
    row = await db.password_resets.find_one_and_update(
        {"token_hash": token_hash, "used_at": None},
        {"$set": {"used_at": now.isoformat()}},
    )
    if not row:
        return None
    # expiry check
    try:
        exp = datetime.fromisoformat(row["expires_at"])
    except (KeyError, ValueError):
        return None
    if exp < now:
        return None
    return await db.users.find_one({"id": row["user_id"]})


async def can_request_reset(db, user: dict) -> tuple[bool, int]:
    """Rate-limit password-reset requests per user."""
    last = user.get("last_reset_request")
    if not last:
        return True, 0
    try:
        last_dt = datetime.fromisoformat(last)
    except (TypeError, ValueError):
        return True, 0
    elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
    if elapsed >= RESET_REQUEST_COOLDOWN_S:
        return True, 0
    return False, int(RESET_REQUEST_COOLDOWN_S - elapsed)
