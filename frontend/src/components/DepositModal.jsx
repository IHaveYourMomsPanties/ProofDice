import React, { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Copy, ExternalLink, ShieldAlert, Wallet as WalletIcon } from "lucide-react";
import { toast } from "sonner";

const COIN_COLOR = {
  BTC: "#f7931a",
  ETH: "#627eea",
  USDC: "#2775ca",
  USDT: "#26a17b",
  BNB: "#f3ba2f",
  SOL: "#14f195",
  GRAM: "#0098ea",
};

function CoinGlyph({ coin, size = 22 }) {
  return (
    <span
      className="inline-flex items-center justify-center rounded-full text-white font-black"
      style={{
        background: COIN_COLOR[coin] || "#888",
        width: size,
        height: size,
        fontSize: size * 0.5,
      }}
    >
      {coin[0]}
    </span>
  );
}

function QRImage({ text }) {
  const src = `https://api.qrserver.com/v1/create-qr-code/?size=220x220&margin=8&data=${encodeURIComponent(text || "")}`;
  return (
    <div
      className="rounded-2xl bg-white p-3 border border-[color:var(--sd-lavender-2)] inline-block"
      data-testid="deposit-qr"
    >
      <img src={src} alt="QR" width={220} height={220} />
    </div>
  );
}

export default function DepositModal({ open, onOpenChange, initialCoin = "ETH" }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState(initialCoin);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    api
      .get("/wallet/addresses")
      .then(({ data }) => setRows(data.addresses || []))
      .catch((e) => toast.error(e?.response?.data?.detail || "Failed to load addresses"))
      .finally(() => setLoading(false));
  }, [open]);

  useEffect(() => {
    if (initialCoin) setTab(initialCoin);
  }, [initialCoin]);

  const rowByCoin = useMemo(() => {
    const map = {};
    for (const r of rows) map[r.coin] = r;
    return map;
  }, [rows]);

  const copy = (text) => {
    navigator.clipboard.writeText(text).then(
      () => toast.success("Address copied to clipboard"),
      () => toast.error("Copy failed"),
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl" data-testid="deposit-modal">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-[color:var(--sd-purple-deep)]">
            <WalletIcon className="w-5 h-5" />
            Deposit real crypto
          </DialogTitle>
          <DialogDescription>
            Send only the matching coin to the matching address on the matching
            chain. Sending the wrong coin, or the right coin on the wrong network,
            will be lost.
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="text-center text-sm text-muted-foreground py-8">
            Loading addresses…
          </div>
        ) : (
          <Tabs value={tab} onValueChange={setTab}>
            <TabsList className="flex flex-wrap gap-1 bg-[color:var(--sd-lavender)] p-1 rounded-xl h-auto">
              {rows.map((r) => (
                <TabsTrigger
                  key={r.coin}
                  value={r.coin}
                  data-testid={`deposit-tab-${r.coin.toLowerCase()}`}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-black tracking-widest"
                >
                  <CoinGlyph coin={r.coin} size={16} /> {r.coin}
                </TabsTrigger>
              ))}
            </TabsList>

            {rows.map((r) => (
              <TabsContent value={r.coin} key={r.coin} className="mt-4">
                <div className="flex flex-col md:flex-row items-start gap-5">
                  <QRImage text={r.address || ""} />
                  <div className="flex-1 space-y-3 w-full">
                    <div>
                      <div className="text-[11px] font-black tracking-widest uppercase text-muted-foreground">
                        {r.name}
                      </div>
                      <div className="text-sm font-bold text-[color:var(--sd-purple-deep)]">
                        Network: <span className="font-black">{r.chain}</span>
                      </div>
                    </div>

                    <div>
                      <div className="text-[11px] font-black tracking-widest uppercase text-muted-foreground mb-1">
                        Your deposit address
                      </div>
                      <div
                        className="sd-mono bg-[color:var(--sd-lavender)] rounded-xl p-3 flex items-center justify-between gap-2"
                        data-testid={`deposit-address-${r.coin.toLowerCase()}`}
                      >
                        <span className="break-all">{r.address || "—"}</span>
                        <button
                          onClick={() => copy(r.address)}
                          className="shrink-0 rounded-full p-2 hover:bg-white"
                          data-testid={`deposit-copy-${r.coin.toLowerCase()}`}
                          title="Copy address"
                        >
                          <Copy className="w-4 h-4 text-[color:var(--sd-purple)]" />
                        </button>
                      </div>
                    </div>

                    <div className="text-xs text-muted-foreground space-y-1">
                      <div>
                        Minimum deposit:{" "}
                        <span className="font-black text-[color:var(--sd-purple-deep)]">
                          {r.min_deposit} {r.coin}
                        </span>
                      </div>
                      {r.contract && (
                        <div className="break-all">
                          Token contract:{" "}
                          <span className="font-mono">{r.contract}</span>
                        </div>
                      )}
                    </div>

                    {!r.wired && (
                      <div
                        className="flex items-start gap-2 rounded-xl p-3 border border-amber-300 bg-amber-50 text-amber-900 text-xs"
                        data-testid={`deposit-pending-${r.coin.toLowerCase()}`}
                      >
                        <ShieldAlert className="w-4 h-4 mt-0.5 shrink-0" />
                        <div>
                          <b>{r.coin} deposit monitoring is not live yet.</b>{" "}
                          Your address is real and safe to receive to, but the
                          site will not credit balances until the {r.chain}{" "}
                          watcher goes online. Please wait for the "Wired" tag
                          to appear before sending funds.
                        </div>
                      </div>
                    )}

                    {r.wired && (
                      <div
                        className="flex items-center gap-2 text-xs font-black tracking-widest uppercase text-[color:#0b8a53]"
                      >
                        <span className="w-2 h-2 rounded-full bg-[#0fa968] animate-pulse" />
                        Watcher online — deposits credited after 3 confirmations
                      </div>
                    )}
                  </div>
                </div>
              </TabsContent>
            ))}
          </Tabs>
        )}
      </DialogContent>
    </Dialog>
  );
}
