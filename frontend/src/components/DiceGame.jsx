import React, { useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { api } from "@/lib/api";
import { toast } from "sonner";
import DigitalDisplay from "@/components/DigitalDisplay";
import RollHistory from "@/components/RollHistory";
import { Minus, Plus, ChevronsDown, ChevronsUp, RefreshCw, Rocket } from "lucide-react";
import { useNavigate } from "react-router-dom";

const HOUSE_EDGE = 1.0; // 1%

function clampTarget(t) {
  return Math.max(1.01, Math.min(98.99, Number(t) || 50));
}

export default function DiceGame({ activeCoin, onNewBet }) {
  const { user, setUser } = useAuth();
  const nav = useNavigate();

  const [direction, setDirection] = useState("under");
  const [target, setTarget] = useState(50.5);
  const [amount, setAmount] = useState(0.00001);
  const [rolling, setRolling] = useState(false);
  const [lastRoll, setLastRoll] = useState(null); // { roll, won }
  const [displayValue, setDisplayValue] = useState(0);
  const [displayState, setDisplayState] = useState("idle"); // idle|rolling|win|loss
  const [history, setHistory] = useState([]);
  const rollingTimerRef = useRef(null);

  // Load recent bets (for the history strip)
  useEffect(() => {
    if (!user) {
      setHistory([]);
      return;
    }
    api
      .get("/bets/mine", { params: { limit: 7 } })
      .then(({ data }) => setHistory(data))
      .catch(() => {});
  }, [user]);

  // reset amount default per coin
  useEffect(() => {
    const defaults = {
      BTC: 0.00001,
      ETH: 0.0005,
      USDC: 1,
      USDT: 1,
      BNB: 0.005,
      SOL: 0.05,
      GRAM: 1,
    };
    setAmount(defaults[activeCoin] ?? 0.001);
  }, [activeCoin]);

  const winChance = useMemo(() => {
    if (direction === "under") return Number(target).toFixed(2);
    return (99.99 - Number(target)).toFixed(2);
  }, [direction, target]);
  const multiplier = useMemo(() => {
    const wc = parseFloat(winChance);
    if (!wc) return "0.000";
    return ((100 - HOUSE_EDGE) / wc).toFixed(3);
  }, [winChance]);
  const payout = useMemo(() => {
    return (parseFloat(multiplier) * Number(amount || 0)).toFixed(8);
  }, [multiplier, amount]);

  const fmtBal = (v) => Number(v ?? 0).toFixed(8).replace(/0+$/, "").replace(/\.$/, "");

  const doRoll = async () => {
    if (!user) {
      toast.info("Sign up to play — the roll is provably fair!");
      nav("/register");
      return;
    }
    if (amount <= 0) {
      toast.error("Bet amount must be positive");
      return;
    }
    if (amount > (user.balances?.[activeCoin] ?? 0)) {
      toast.error(`Insufficient ${activeCoin} balance — click DEPOSIT to add funds`);
      return;
    }
    setRolling(true);
    setDisplayState("rolling");
    // rapid flicker while waiting
    if (rollingTimerRef.current) clearInterval(rollingTimerRef.current);
    rollingTimerRef.current = setInterval(() => {
      setDisplayValue(Math.random() * 100);
    }, 60);

    try {
      const { data } = await api.post("/dice/roll", {
        coin: activeCoin,
        amount: Number(amount),
        target: Number(target),
        direction,
      });
      clearInterval(rollingTimerRef.current);
      setDisplayValue(data.roll);
      setDisplayState(data.won ? "win" : "loss");
      setLastRoll(data);
      // update balance locally
      setUser({
        ...user,
        balances: { ...user.balances, [activeCoin]: data.balance_after },
        nonce: data.nonce + 1,
        bets_count: (user.bets_count || 0) + 1,
      });
      // push into history
      setHistory((h) => [{ id: data.id, roll: data.roll, won: data.won }, ...h].slice(0, 20));
      onNewBet?.(data);
      if (data.won) {
        toast.success(`WIN ×${data.payout_multiplier.toFixed(3)}  +${data.profit.toFixed(8)} ${activeCoin}`);
      }
    } catch (e) {
      clearInterval(rollingTimerRef.current);
      setDisplayState("idle");
      toast.error(e?.response?.data?.detail || "Roll failed");
    } finally {
      setRolling(false);
    }
  };

  const setDir = (d) => {
    if (rolling) return;
    setDirection(d);
    // Auto-flip target to a symmetric equivalent when toggling
    if (d === "over" && target < 50) setTarget(clampTarget(99.99 - target));
    if (d === "under" && target > 50) setTarget(clampTarget(99.99 - target));
  };

  const nudge = (delta) => setAmount((a) => Math.max(0, +(Number(a) + delta).toFixed(8)));
  const halveBet = () => setAmount((a) => +(Number(a) / 2).toFixed(8));
  const doubleBet = () => setAmount((a) => +(Number(a) * 2).toFixed(8));
  const minBet = () => setAmount(activeCoin === "GRAM" || activeCoin === "USDC" || activeCoin === "USDT" ? 0.01 : 0.00000001);
  const maxBet = () => setAmount(+(user?.balances?.[activeCoin] ?? 0));

  return (
    <div className="sd-panel p-4 md:p-6" data-testid="dice-game">
      {/* Roll history */}
      <RollHistory rolls={history} />

      {/* Stat cards */}
      <div className="grid grid-cols-2 gap-3 mt-4">
        <div className="sd-stat-card" data-testid="stat-multiplier">
          <span>Multiplier</span>
          <span className="sd-stat-val">×{multiplier}</span>
        </div>
        <div className="sd-stat-card" data-testid="stat-chance">
          <span>Chance</span>
          <span className="sd-stat-val">{winChance}%</span>
        </div>
      </div>
      <div className="sd-stat-card mt-3" data-testid="stat-payout">
        <span>Payout</span>
        <span className="sd-stat-val flex items-center gap-2">
          <span
            className="sd-coin-symbol"
            style={{ background: "#0fa968", color: "#fff", width: 20, height: 20, fontSize: 10 }}
          >
            {activeCoin[0]}
          </span>
          {Number(payout).toFixed(8).replace(/0+$/, "").replace(/\.$/, "")}
        </span>
      </div>

      {/* Big digital display */}
      <div className="mt-4">
        <DigitalDisplay
          value={displayValue}
          state={rolling ? "rolling" : displayState}
        />
      </div>

      {/* Under / Over */}
      <div className="grid grid-cols-2 gap-3 mt-4">
        <button
          onClick={() => setDir("under")}
          className={`sd-uo-btn ${direction === "under" ? "active" : ""}`}
          data-testid="button-under"
        >
          UNDER {direction === "under" ? Number(target).toFixed(2) : (99.99 - Number(target)).toFixed(2)}
        </button>
        <button
          onClick={() => setDir("over")}
          className={`sd-uo-btn ${direction === "over" ? "active" : ""}`}
          data-testid="button-over"
        >
          OVER {direction === "over" ? Number(target).toFixed(2) : (99.99 - Number(target)).toFixed(2)}
        </button>
      </div>

      {/* Slider */}
      <div className="mt-5 px-1">
        <input
          type="range"
          min="1.01"
          max="98.99"
          step="0.01"
          value={target}
          onChange={(e) => setTarget(clampTarget(e.target.value))}
          className="sd-slider"
          data-testid="target-slider"
        />
        <div className="flex justify-between mt-1 text-xs text-muted-foreground font-semibold">
          <span>1</span><span>25</span><span>50</span><span>75</span><span>99</span>
        </div>
      </div>

      {/* Roll button */}
      <div className="mt-5 flex items-stretch gap-3">
        <button
          onClick={doRoll}
          disabled={rolling}
          className="sd-roll-btn flex-1"
          data-testid="roll-button"
        >
          {rolling ? "ROLLING…" : "ROLL"}
        </button>
        <button
          className="w-14 rounded-2xl bg-white border border-[color:var(--sd-lavender-2)] text-[color:var(--sd-purple-deep)] flex items-center justify-center font-black hover:bg-[color:var(--sd-lavender)]"
          title="Auto-roll (coming soon)"
          data-testid="auto-roll-button"
          onClick={() => toast.info("Auto-roll coming soon")}
        >
          <RefreshCw className="w-5 h-5" />
        </button>
        <button
          className="w-14 rounded-2xl flex items-center justify-center font-black text-white"
          style={{ background: "linear-gradient(135deg,#0fa968,#ff6b57)" }}
          title="Bonus boost (coming soon)"
          data-testid="bonus-boost-button"
          onClick={() => toast.info("Bonus boost coming soon")}
        >
          <Rocket className="w-5 h-5" />
        </button>
      </div>

      {/* Bet amount pill */}
      <div className="sd-bet-pill mt-4">
        <button
          onClick={halveBet}
          className="sd-icon-btn"
          title="Halve"
          data-testid="bet-halve"
        >
          <ChevronsDown className="w-4 h-4" />
        </button>
        <button onClick={() => nudge(-Number(amount) * 0.1)} className="sd-icon-btn" data-testid="bet-minus">
          <Minus className="w-4 h-4" />
        </button>
        <div className="flex items-center gap-2 flex-1 justify-center">
          <span
            className="sd-coin-symbol"
            style={{ background: "#0fa968", color: "#fff", width: 26, height: 26, fontSize: 12 }}
          >
            {activeCoin[0]}
          </span>
          <input
            className="sd-bet-input"
            type="number"
            step="0.00000001"
            min="0"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            data-testid="bet-amount-input"
          />
        </div>
        <button onClick={() => nudge(Number(amount) * 0.1 || 0.00001)} className="sd-icon-btn" data-testid="bet-plus">
          <Plus className="w-4 h-4" />
        </button>
        <button onClick={doubleBet} className="sd-icon-btn" title="Double" data-testid="bet-double">
          <ChevronsUp className="w-4 h-4" />
        </button>
      </div>
      <div className="flex items-center justify-between mt-2 text-xs text-muted-foreground px-1">
        <button onClick={minBet} className="hover:underline font-bold" data-testid="bet-min">
          MIN
        </button>
        <span>
          Balance:{" "}
          <span className="font-seg text-sm text-[color:var(--sd-purple-deep)]">
            {fmtBal(user?.balances?.[activeCoin] ?? 0)}
          </span>{" "}
          {activeCoin}
        </span>
        <button onClick={maxBet} className="hover:underline font-bold" data-testid="bet-max">
          MAX
        </button>
      </div>

      {/* Last roll result summary */}
      {lastRoll && (
        <div
          className={`mt-4 rounded-2xl p-4 ${lastRoll.won ? "sd-flash-win" : "sd-flash-loss"}`}
          style={{ background: lastRoll.won ? "rgba(123,193,66,0.12)" : "rgba(225,74,56,0.10)" }}
          data-testid="last-roll-summary"
        >
          <div className="flex items-center justify-between text-sm">
            <span className="font-black tracking-widest uppercase" style={{ color: lastRoll.won ? "#4d8b25" : "#b23628" }}>
              {lastRoll.won ? "You won" : "You lost"}
            </span>
            <span className="font-seg text-lg" style={{ color: lastRoll.won ? "#4d8b25" : "#b23628" }}>
              {lastRoll.roll.toFixed(2)} — {direction.toUpperCase()} {Number(target).toFixed(2)}
            </span>
          </div>
          <div className="flex items-center justify-between text-xs mt-1 text-muted-foreground">
            <span>×{lastRoll.payout_multiplier.toFixed(3)} @ {lastRoll.win_chance.toFixed(2)}%</span>
            <span className="font-bold">
              {lastRoll.profit > 0 ? "+" : ""}
              {lastRoll.profit.toFixed(8)} {activeCoin}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
