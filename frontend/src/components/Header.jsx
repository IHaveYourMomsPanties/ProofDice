import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { api } from "@/lib/api";
import { toast } from "sonner";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Gift, LogOut, User as UserIcon, Wallet, ChevronDown, Menu } from "lucide-react";

const COINS = ["BTC", "LTC", "DOGE", "ETH"];
const COIN_COLOR = {
  BTC: "#f7931a",
  LTC: "#345d9d",
  DOGE: "#c2a633",
  ETH: "#627eea",
};

function CoinGlyph({ coin }) {
  return (
    <span className="sd-coin-symbol" style={{ background: COIN_COLOR[coin] || "#fff", color: "#fff" }}>
      {coin[0]}
    </span>
  );
}

function fmt(v) {
  return Number(v ?? 0).toFixed(8).replace(/0+$/, "").replace(/\.$/, "");
}

export default function Header({ activeCoin, setActiveCoin }) {
  const { user, logout, refresh } = useAuth();
  const nav = useNavigate();
  const [claiming, setClaiming] = useState(false);

  const claim = async () => {
    if (!user) {
      nav("/login");
      return;
    }
    setClaiming(true);
    try {
      const { data } = await api.post("/faucet/claim");
      toast.success("Faucet claimed — demo coins credited!");
      await refresh();
      void data;
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Faucet cooldown");
    } finally {
      setClaiming(false);
    }
  };

  const balance = user?.balances?.[activeCoin] ?? 0;

  return (
    <header className="sd-header sticky top-0 z-40" data-testid="app-header">
      <div className="max-w-[1400px] mx-auto flex items-center gap-3 px-4 md:px-8 py-3">
        {/* Logo */}
        <Link to="/" data-testid="logo-link" className="flex items-center gap-2 mr-2">
          <div
            className="w-9 h-9 rounded-xl flex items-center justify-center font-black text-white"
            style={{ background: "linear-gradient(135deg,#7bc142,#ff6b57)" }}
          >
            <span className="font-seg text-lg">8</span>
          </div>
          <span
            className="hidden sm:block text-white font-black tracking-wider text-lg"
            style={{ letterSpacing: "0.14em" }}
          >
            BETTER<span className="opacity-70">DICE</span>
          </span>
        </Link>

        {/* Balance + coin selector */}
        <div className="flex items-center gap-2 ml-1">
          <div
            className="hidden md:flex items-center gap-3 bg-white/10 rounded-full pl-2 pr-1 py-1"
            data-testid="header-balance"
          >
            <CoinGlyph coin={activeCoin} />
            <span className="font-seg text-white text-lg" style={{ letterSpacing: "0.06em" }}>
              {fmt(balance)}
            </span>
            <DropdownMenu>
              <DropdownMenuTrigger
                data-testid="coin-selector"
                className="sd-coin-pill outline-none"
              >
                {activeCoin} <ChevronDown className="w-4 h-4" />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" data-testid="coin-selector-menu">
                <DropdownMenuLabel>Select coin</DropdownMenuLabel>
                <DropdownMenuSeparator />
                {COINS.map((c) => (
                  <DropdownMenuItem
                    key={c}
                    onClick={() => setActiveCoin(c)}
                    data-testid={`coin-option-${c.toLowerCase()}`}
                    className="flex items-center gap-3"
                  >
                    <CoinGlyph coin={c} />
                    <div className="flex-1">{c}</div>
                    <span className="font-seg text-sm text-muted-foreground">
                      {fmt(user?.balances?.[c] ?? 0)}
                    </span>
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>

          {/* Mobile: compact balance chip */}
          <div className="md:hidden flex items-center gap-2 bg-white/12 rounded-full px-2 py-1">
            <CoinGlyph coin={activeCoin} />
            <span className="font-seg text-white text-sm">{fmt(balance)}</span>
          </div>
        </div>

        <div className="flex-1" />

        {/* Faucet */}
        <button
          onClick={claim}
          disabled={claiming}
          data-testid="faucet-button"
          className="hidden sm:inline-flex items-center gap-2 rounded-full bg-white/12 hover:bg-white/20 text-white font-bold px-4 py-2 text-sm tracking-wide"
        >
          <Gift className="w-4 h-4" />
          {claiming ? "..." : "FAUCET"}
        </button>

        {/* User area */}
        {user ? (
          <DropdownMenu>
            <DropdownMenuTrigger
              data-testid="user-menu-trigger"
              className="w-10 h-10 rounded-full bg-white/12 hover:bg-white/20 text-white flex items-center justify-center outline-none"
            >
              <UserIcon className="w-4 h-4" />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel className="flex flex-col">
                <span className="font-black">{user.username}</span>
                <span className="text-xs text-muted-foreground">{user.email}</span>
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={claim} data-testid="user-menu-faucet">
                <Gift className="w-4 h-4 mr-2" /> Claim faucet
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => nav("/")} data-testid="user-menu-play">
                <Wallet className="w-4 h-4 mr-2" /> Play dice
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={() => {
                  logout();
                  toast.success("Logged out");
                  nav("/");
                }}
                data-testid="logout-button"
              >
                <LogOut className="w-4 h-4 mr-2" /> Log out
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        ) : (
          <div className="flex items-center gap-2">
            <Link
              to="/login"
              data-testid="header-login-link"
              className="text-white font-bold px-3 py-2 rounded-full hover:bg-white/12 text-sm tracking-wide"
            >
              LOG IN
            </Link>
            <Link
              to="/register"
              data-testid="header-register-link"
              className="bg-white text-[color:var(--sd-purple-deep)] font-black px-4 py-2 rounded-full hover:bg-white/90 text-sm tracking-wide"
            >
              SIGN UP
            </Link>
          </div>
        )}
      </div>
    </header>
  );
}
