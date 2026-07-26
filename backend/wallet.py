"""Custodial HD wallet + coin/network registry for BetterDice.io.

Design change (Phase 2 Step 1b, chain pivot):
  - Users see 8 **assets**: BTC, ETH, USDC, USDT, BNB, POL, SOL, GRAM
  - Each asset can be deposited on one or more **networks**:
      BTC   -> Bitcoin
      ETH   -> Ethereum
      USDC  -> Ethereum, Polygon
      USDT  -> Ethereum, BNB, Polygon
      BNB   -> BNB Chain
      POL   -> Polygon
      SOL   -> Solana
      GRAM  -> TON
  - Balances are stored per-asset (single value regardless of deposit network),
    which matches every major crypto casino & centralised exchange.

HD derivation:
  - EVM chains (Ethereum, BNB, Polygon) share a single address per user
    (m/44'/60'/0'/0/i) since they all use the same secp256k1 curve.
  - BTC uses BIP84 native segwit.
  - SOL and GRAM use their coin-specific BIP44 paths.
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
# Assets — the user-facing coin balances
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AssetSpec:
    code: str
    name: str
    decimals: int
    color: str
    min_bet: float
    is_test: bool = False


ASSETS: dict[str, AssetSpec] = {
    "BTC":    AssetSpec("BTC",    "Bitcoin",         8,  "#f7931a", 0.00000001),
    "ETH":    AssetSpec("ETH",    "Ethereum",       18,  "#627eea", 0.00001),
    "USDC":   AssetSpec("USDC",   "USD Coin",        6,  "#2775ca", 0.01),
    "USDT":   AssetSpec("USDT",   "Tether",          6,  "#26a17b", 0.01),
    "BNB":    AssetSpec("BNB",    "BNB",            18,  "#f3ba2f", 0.0001),
    "POL":    AssetSpec("POL",    "Polygon",        18,  "#8247e5", 0.01),
    "SOL":    AssetSpec("SOL",    "Solana",          9,  "#14f195", 0.0001),
    "GRAM":   AssetSpec("GRAM",   "Gram",            9,  "#0098ea", 0.01),
    # ------------------------------------------------------------------
    # Test coin — Sepolia ETH. Free from any Sepolia faucet.
    # Behaves exactly like a real EVM asset; useful for QA and demos.
    # ------------------------------------------------------------------
    "SEPETH": AssetSpec("SEPETH", "Sepolia ETH",    18,  "#8b98d6", 0.00001, is_test=True),
}
SUPPORTED_COINS: list[str] = list(ASSETS.keys())


# ---------------------------------------------------------------------------
# Networks — where each asset can actually be deposited
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class NetworkSpec:
    asset: str
    chain: str                 # display label (e.g. 'Ethereum', 'BNB Chain', 'Polygon')
    chain_id: str              # short id ('eth', 'bnb', 'polygon', 'btc', 'sol', 'ton')
    addr_kind: str             # 'evm' | 'btc' | 'sol' | 'ton'
    contract: Optional[str]    # ERC-20 contract for stables, None for native
    wired: bool                # deposit-watcher live?
    min_deposit: float


NETWORKS: list[NetworkSpec] = [
    # BTC
    NetworkSpec("BTC", "Bitcoin", "btc", "btc", None, wired=False, min_deposit=0.00005),

    # Native ETH
    NetworkSpec("ETH", "Ethereum", "eth", "evm", None, wired=True, min_deposit=0.001),

    # USDC on Ethereum + Polygon
    NetworkSpec(
        "USDC", "Ethereum", "eth", "evm",
        os.environ.get("USDC_ETH_ADDRESS", "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"),
        wired=True, min_deposit=1.0,
    ),
    NetworkSpec(
        "USDC", "Polygon", "polygon", "evm",
        os.environ.get("USDC_POLYGON_ADDRESS", "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"),
        wired=True, min_deposit=1.0,
    ),

    # USDT on Ethereum + BNB + Polygon
    NetworkSpec(
        "USDT", "Ethereum", "eth", "evm",
        os.environ.get("USDT_ETH_ADDRESS", "0xdAC17F958D2ee523a2206206994597C13D831ec7"),
        wired=True, min_deposit=1.0,
    ),
    NetworkSpec(
        "USDT", "BNB Chain", "bnb", "evm",
        os.environ.get("USDT_BNB_ADDRESS", "0x55d398326f99059fF775485246999027B3197955"),
        wired=True, min_deposit=1.0,
    ),
    NetworkSpec(
        "USDT", "Polygon", "polygon", "evm",
        os.environ.get("USDT_POLYGON_ADDRESS", "0xc2132D05D31c914a87C6611C10748AEb04B58e8F"),
        wired=True, min_deposit=1.0,
    ),

    # Native BNB
    NetworkSpec("BNB", "BNB Chain", "bnb", "evm", None, wired=True, min_deposit=0.005),

    # Native POL (Polygon)
    NetworkSpec("POL", "Polygon", "polygon", "evm", None, wired=True, min_deposit=1.0),

    # SOL & GRAM & (BTC) — not yet wired
    NetworkSpec("SOL",  "Solana", "sol", "sol", None, wired=False, min_deposit=0.02),
    NetworkSpec("GRAM", "TON",    "ton", "ton", None, wired=False, min_deposit=1.0),

    # Test coin — Sepolia (Ethereum testnet). Uses same EVM derivation as ETH mainnet.
    NetworkSpec("SEPETH", "Ethereum Sepolia", "sepolia", "evm", None, wired=True, min_deposit=0.0001),
]


def networks_for(asset: str) -> list[NetworkSpec]:
    asset = asset.upper()
    return [n for n in NETWORKS if n.asset == asset]


# ---------------------------------------------------------------------------
# Seed handling
# ---------------------------------------------------------------------------
_MNEMONIC = os.environ.get("HOT_WALLET_MNEMONIC")
if not _MNEMONIC:
    raise RuntimeError("HOT_WALLET_MNEMONIC missing from backend/.env — cannot derive addresses")
_SEED = Bip39SeedGenerator(_MNEMONIC).Generate()


# ---------------------------------------------------------------------------
# Derivation (address depends on addr_kind, not on which specific EVM chain)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=4096)
def _derive_by_kind(addr_kind: str, index: int) -> str:
    if addr_kind == "evm":
        return (
            Bip44.FromSeed(_SEED, Bip44Coins.ETHEREUM)
            .Purpose().Coin().Account(0)
            .Change(Bip44Changes.CHAIN_EXT)
            .AddressIndex(index)
            .PublicKey().ToAddress()
        )
    if addr_kind == "btc":
        return (
            Bip84.FromSeed(_SEED, Bip84Coins.BITCOIN)
            .Purpose().Coin().Account(0)
            .Change(Bip44Changes.CHAIN_EXT)
            .AddressIndex(index)
            .PublicKey().ToAddress()
        )
    if addr_kind == "sol":
        return (
            Bip44.FromSeed(_SEED, Bip44Coins.SOLANA)
            .Purpose().Coin().Account(0)
            .Change(Bip44Changes.CHAIN_EXT)
            .AddressIndex(index)
            .PublicKey().ToAddress()
        )
    if addr_kind == "ton":
        return (
            Bip44.FromSeed(_SEED, Bip44Coins.TON)
            .Purpose().Coin().Account(0)
            .Change(Bip44Changes.CHAIN_EXT)
            .AddressIndex(index)
            .PublicKey().ToAddress()
        )
    raise ValueError(f"Unknown addr_kind: {addr_kind}")


def derive_network_address(net: NetworkSpec, index: int) -> str:
    return _derive_by_kind(net.addr_kind, index)


# Back-compat shim — some legacy callers ask for an address by (asset, index).
# Return the first wired-or-first network's address for that asset.
def derive_address(asset: str, index: int) -> str:
    nets = networks_for(asset)
    if not nets:
        raise ValueError(f"Unsupported asset: {asset}")
    net = next((n for n in nets if n.wired), nets[0])
    return derive_network_address(net, index)


def asset_spec(code: str) -> AssetSpec:
    code = code.upper()
    if code not in ASSETS:
        raise ValueError(f"Unsupported asset: {code}")
    return ASSETS[code]


# Legacy alias kept so any older imports still work
COINS = ASSETS
coin_spec = asset_spec
