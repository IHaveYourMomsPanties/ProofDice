"""Custodial HD wallet module for BetterDice.io.

Derives per-user, per-chain deposit addresses from a single BIP39 mnemonic loaded
from `HOT_WALLET_MNEMONIC` in the backend `.env`.

Each user is assigned a stable `wallet_index` (auto-incrementing integer) at
registration; the deposit address for a given (user, coin) is the deterministic
child address at that index under the coin's BIP44 path.

Currently supported chains
--------------------------
    - BTC   : Bitcoin native, bech32 (bc1...) — m/84'/0'/0'/0/i
    - ETH   : Ethereum on Base (chain 8453)  — m/44'/60'/0'/0/i
    - BNB   : BNB Chain (chain 56)           — m/44'/60'/0'/0/i (same as ETH)
    - USDC  : ERC-20 on Base — piggybacks on the ETH Base address
    - USDT  : ERC-20 on BNB  — piggybacks on the BNB address
    - SOL   : Solana                          — m/44'/501'/0'/0/i
    - GRAM  : TON (Toncoin)                   — m/44'/607'/0'/0/i (using TON derivation)

Withdrawal / deposit monitoring is NOT implemented here — this module only
provides deterministic address derivation. Add signer + broadcaster + watcher
services in Phase 2 (chain-by-chain).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from bip_utils import (
    Bip39SeedGenerator,
    Bip44,
    Bip44Changes,
    Bip44Coins,
    Bip84,
    Bip84Coins,
)
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# ---------------------------------------------------------------------------
# Coin registry
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CoinSpec:
    code: str            # display symbol
    name: str            # long name
    chain: str           # network label
    decimals: int
    color: str
    wired: bool          # whether deposit monitoring + withdrawal are actually implemented
    min_deposit: float
    contract: Optional[str] = None  # ERC-20 contract address (for stables)


COINS: dict[str, CoinSpec] = {
    "BTC": CoinSpec(
        code="BTC", name="Bitcoin", chain="Bitcoin", decimals=8,
        color="#f7931a", wired=False, min_deposit=0.00005,
    ),
    "ETH": CoinSpec(
        code="ETH", name="Ethereum (Base)", chain="Base", decimals=18,
        color="#627eea", wired=False, min_deposit=0.001,
    ),
    "USDC": CoinSpec(
        code="USDC", name="USD Coin (Base)", chain="Base", decimals=6,
        color="#2775ca", wired=False, min_deposit=1.0,
        contract=os.environ.get("USDC_BASE_ADDRESS", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"),
    ),
    "USDT": CoinSpec(
        code="USDT", name="Tether (BNB Chain)", chain="BNB", decimals=18,
        color="#26a17b", wired=False, min_deposit=1.0,
        contract=os.environ.get("USDT_BNB_ADDRESS", "0x55d398326f99059fF775485246999027B3197955"),
    ),
    "BNB": CoinSpec(
        code="BNB", name="BNB", chain="BNB Chain", decimals=18,
        color="#f3ba2f", wired=False, min_deposit=0.005,
    ),
    "SOL": CoinSpec(
        code="SOL", name="Solana", chain="Solana", decimals=9,
        color="#14f195", wired=False, min_deposit=0.02,
    ),
    "GRAM": CoinSpec(
        code="GRAM", name="Gram (TON)", chain="TON", decimals=9,
        color="#0098ea", wired=False, min_deposit=1.0,
    ),
}

SUPPORTED_COINS: list[str] = list(COINS.keys())


# ---------------------------------------------------------------------------
# Seed handling
# ---------------------------------------------------------------------------
_MNEMONIC = os.environ.get("HOT_WALLET_MNEMONIC")
if not _MNEMONIC:
    raise RuntimeError(
        "HOT_WALLET_MNEMONIC missing from backend/.env — cannot derive addresses"
    )

_SEED = Bip39SeedGenerator(_MNEMONIC).Generate()


# ---------------------------------------------------------------------------
# Derivation (cached per (coin, index) so repeat calls are free)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=4096)
def derive_address(coin: str, index: int) -> str:
    """Return the deterministic deposit address for (coin, wallet_index)."""
    coin = coin.upper()
    if coin not in COINS:
        raise ValueError(f"Unsupported coin: {coin}")

    # ETH-family (ETH on Base, BNB, USDC on Base, USDT on BNB) — share ETH path
    if coin in ("ETH", "USDC"):
        acc = (
            Bip44.FromSeed(_SEED, Bip44Coins.ETHEREUM)
            .Purpose().Coin().Account(0)
            .Change(Bip44Changes.CHAIN_EXT)
            .AddressIndex(index)
        )
        return acc.PublicKey().ToAddress()

    if coin in ("BNB", "USDT"):
        # BNB Chain uses standard Ethereum keys (secp256k1) — same derivation
        acc = (
            Bip44.FromSeed(_SEED, Bip44Coins.ETHEREUM)
            .Purpose().Coin().Account(0)
            .Change(Bip44Changes.CHAIN_EXT)
            .AddressIndex(index)
        )
        return acc.PublicKey().ToAddress()

    if coin == "BTC":
        # BIP84 native segwit
        acc = (
            Bip84.FromSeed(_SEED, Bip84Coins.BITCOIN)
            .Purpose().Coin().Account(0)
            .Change(Bip44Changes.CHAIN_EXT)
            .AddressIndex(index)
        )
        return acc.PublicKey().ToAddress()

    if coin == "SOL":
        acc = (
            Bip44.FromSeed(_SEED, Bip44Coins.SOLANA)
            .Purpose().Coin().Account(0)
            .Change(Bip44Changes.CHAIN_EXT)
            .AddressIndex(index)
        )
        return acc.PublicKey().ToAddress()

    if coin == "GRAM":
        acc = (
            Bip44.FromSeed(_SEED, Bip44Coins.TON)
            .Purpose().Coin().Account(0)
            .Change(Bip44Changes.CHAIN_EXT)
            .AddressIndex(index)
        )
        return acc.PublicKey().ToAddress()

    raise ValueError(f"No derivation for {coin}")


def coin_spec(coin: str) -> CoinSpec:
    coin = coin.upper()
    if coin not in COINS:
        raise ValueError(f"Unsupported coin: {coin}")
    return COINS[coin]
