import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";

function formatTime(iso) {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return iso;
  }
}

function BetRow({ b, highlight }) {
  return (
    <tr
      className={highlight ? (b.won ? "sd-flash-win" : "sd-flash-loss") : ""}
      data-testid="bet-row"
    >
      <td className="py-2 px-3 text-sm">
        <span className="font-black">{b.username}</span>
      </td>
      <td className="py-2 px-3 text-xs text-muted-foreground">{formatTime(b.created_at)}</td>
      <td className="py-2 px-3 text-right font-seg text-sm">{b.amount.toFixed(8).replace(/0+$/, "").replace(/\.$/, "")}</td>
      <td className="py-2 px-3 text-right text-xs font-bold">{b.coin}</td>
      <td className="py-2 px-3 text-right font-bold text-xs">
        {b.direction === "under" ? "<" : ">"} {b.target.toFixed(2)}
      </td>
      <td className={`py-2 px-3 text-right font-seg text-sm ${b.won ? "text-[#6ba22a]" : "text-[#d13563]"}`}>
        {b.roll.toFixed(2)}
      </td>
      <td className="py-2 px-3 text-right text-xs font-bold text-muted-foreground">
        ×{b.payout_multiplier.toFixed(3)}
      </td>
      <td
        className={`py-2 px-3 text-right font-seg text-sm ${b.won ? "text-[#6ba22a]" : "text-[#d13563]"}`}
      >
        {b.profit > 0 ? "+" : ""}
        {b.profit.toFixed(8).replace(/0+$/, "").replace(/\.$/, "")}
      </td>
    </tr>
  );
}

function BetTable({ rows, latestId }) {
  if (!rows?.length) {
    return (
      <div className="text-center text-sm text-muted-foreground py-10" data-testid="bets-empty">
        No bets yet — be the first to roll!
      </div>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="text-[11px] uppercase tracking-widest text-muted-foreground">
            <th className="py-2 px-3 text-left">User</th>
            <th className="py-2 px-3 text-left">Time</th>
            <th className="py-2 px-3 text-right">Bet</th>
            <th className="py-2 px-3 text-right">Coin</th>
            <th className="py-2 px-3 text-right">Target</th>
            <th className="py-2 px-3 text-right">Roll</th>
            <th className="py-2 px-3 text-right">Mult</th>
            <th className="py-2 px-3 text-right">Profit</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[color:var(--sd-lavender-2)]">
          {rows.map((b) => (
            <BetRow key={b.id} b={b} highlight={b.id === latestId} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function BetsTable({ latestBetId }) {
  const { user } = useAuth();
  const [all, setAll] = useState([]);
  const [mine, setMine] = useState([]);
  const [high, setHigh] = useState([]);
  const [tab, setTab] = useState("all");

  const loadAll = async () => {
    try {
      const { data } = await api.get("/bets/all", { params: { limit: 25 } });
      setAll(data);
    } catch {}
  };
  const loadMine = async () => {
    if (!user) return setMine([]);
    try {
      const { data } = await api.get("/bets/mine", { params: { limit: 25 } });
      setMine(data);
    } catch {}
  };
  const loadHigh = async () => {
    try {
      const { data } = await api.get("/bets/high-rollers", { params: { limit: 25 } });
      setHigh(data);
    } catch {}
  };

  useEffect(() => {
    loadAll();
    loadHigh();
    // eslint-disable-next-line
  }, []);

  useEffect(() => {
    loadMine();
    // eslint-disable-next-line
  }, [user]);

  useEffect(() => {
    if (!latestBetId) return;
    loadAll();
    loadMine();
    // eslint-disable-next-line
  }, [latestBetId]);

  useEffect(() => {
    const t = setInterval(() => {
      loadAll();
      if (tab === "high") loadHigh();
    }, 4000);
    return () => clearInterval(t);
    // eslint-disable-next-line
  }, [tab]);

  return (
    <div className="sd-panel p-4 md:p-6 mt-6" data-testid="bets-panel">
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="bg-[color:var(--sd-lavender)] rounded-full p-1">
          <TabsTrigger
            value="all"
            data-testid="tab-all-bets"
            className="rounded-full px-4 font-black tracking-widest text-xs"
          >
            RECENT
          </TabsTrigger>
          <TabsTrigger
            value="mine"
            data-testid="tab-my-bets"
            className="rounded-full px-4 font-black tracking-widest text-xs"
          >
            MY BETS
          </TabsTrigger>
          <TabsTrigger
            value="high"
            data-testid="tab-high-rollers"
            className="rounded-full px-4 font-black tracking-widest text-xs"
          >
            HIGH ROLLERS
          </TabsTrigger>
        </TabsList>

        <TabsContent value="all" className="mt-3">
          <BetTable rows={all} latestId={latestBetId} />
        </TabsContent>
        <TabsContent value="mine" className="mt-3">
          {user ? (
            <BetTable rows={mine} latestId={latestBetId} />
          ) : (
            <div className="text-center text-sm text-muted-foreground py-10">
              Log in to see your bet history.
            </div>
          )}
        </TabsContent>
        <TabsContent value="high" className="mt-3">
          <BetTable rows={high} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
