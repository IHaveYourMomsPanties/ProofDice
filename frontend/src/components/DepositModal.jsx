import React, { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogClose,
} from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Copy, ShieldAlert, Wallet as WalletIcon, Gift, X } from "lucide-react";
import { toast } from "sonner";

const COIN_COLOR = {
  BTC: "#f7931a",
  ETH: "#627eea",
  USDC: "#2775ca",
  USDT: "#26a17b",
  BNB: "#f3ba2f",
  POL: "#8247e5",
  SOL: "#14f195",
  GRAM: "#0098ea",
  SEPETH: "#8b98d6",
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
  const { refresh } = useAuth();
  const [assets, setAssets] = useState([]);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState(initialCoin);
  const [networkByAsset, setNetworkByAsset] = useState({}); // assetCode -> chain_id
  const [claiming, setClaiming] = useState(false);

  const claimTestCoins = async () => {
    setClaiming(true);
    try {
      const { data } = await api.post("/faucet/test-claim");
      toast.success(`+${data.credited} SEPETH credited — total ${data.balance.toFixed(6)}`);
      await refresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Faucet cooldown");
    } finally {
      setClaiming(false);
    }
  };

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    api
      .get("/wallet/addresses")
      .then(({ data }) => {
        setAssets(data.assets || []);
        // Default network per asset: prefer first wired, else first
        const next = {};
        for (const a of data.assets || []) {
          const wired = a.networks.find((n) => n.wired);
          next[a.asset] = (wired || a.networks[0])?.chain_id;
        }
        setNetworkByAsset(next);
      })
      .catch((e) => toast.error(e?.response?.data?.detail || "Failed to load addresses"))
      .finally(() => setLoading(false));
  }, [open]);

  useEffect(() => {
    if (initialCoin) setTab(initialCoin);
  }, [initialCoin]);

  const activeAsset = useMemo(
    () => assets.find((a) => a.asset === tab) || null,
    [assets, tab],
  );
  const activeNetwork = useMemo(() => {
    if (!activeAsset) return null;
    const chainId = networkByAsset[activeAsset.asset];
    return activeAsset.networks.find((n) => n.chain_id === chainId) || activeAsset.networks[0];
  }, [activeAsset, networkByAsset]);

  const copy = (text) => {
    if (!text) return;
    navigator.clipboard.writeText(text).then(
      () => toast.success("Address copied to clipboard"),
      () => toast.error("Copy failed"),
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-w-2xl max-h-[92vh] overflow-y-auto p-4 md:p-6"
        data-testid="deposit-modal"
      >
        {/* Big, obvious close button — the default 16px X in shadcn is
            near-invisible on mobile behind the QR image. */}
        <DialogClose
          data-testid="deposit-close-button"
          aria-label="Close"
          className="absolute right-3 top-3 z-10 w-10 h-10 rounded-full bg-[color:var(--sd-lavender)] hover:bg-[color:var(--sd-lavender-2)] flex items-center justify-center text-[color:var(--sd-purple-deep)] focus:outline-none focus:ring-2 focus:ring-[color:var(--sd-purple)]"
        >
          <X className="w-5 h-5" />
        </DialogClose>

        <DialogHeader className="pr-12">
          <DialogTitle className="flex items-center gap-2 text-[color:var(--sd-purple-deep)]">
            <WalletIcon className="w-5 h-5" />
            Deposit real crypto
          </DialogTitle>
          <DialogDescription>
            Send only the matching coin to the matching address on the matching
            chain. Sending the wrong coin, or the right coin on the wrong
            network, will be lost.
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="text-center text-sm text-muted-foreground py-8">
            Loading addresses…
          </div>
        ) : (
          <Tabs value={tab} onValueChange={setTab}>
            <TabsList className="flex flex-wrap gap-1 bg-[color:var(--sd-lavender)] p-1 rounded-xl h-auto">
              {assets.map((a) => (
                <TabsTrigger
                  key={a.asset}
                  value={a.asset}
                  data-testid={`deposit-tab-${a.asset.toLowerCase()}`}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-black tracking-widest"
                >
                  <CoinGlyph coin={a.asset} size={16} /> {a.asset}
                </TabsTrigger>
              ))}
            </TabsList>

            {assets.map((a) => (
              <TabsContent value={a.asset} key={a.asset} className="mt-4">
                {a.asset === "SEPETH" && (
                  <div
                    className="rounded-2xl p-4 mb-4 flex flex-col md:flex-row md:items-center justify-between gap-3"
                    style={{ background: "linear-gradient(135deg,#e4ecfa,#f5e6ff)" }}
                    data-testid="test-faucet-card"
                  >
                    <div className="flex items-start gap-3">
                      <div className="w-10 h-10 rounded-full bg-white flex items-center justify-center shrink-0">
                        <Gift className="w-5 h-5 text-[color:var(--sd-purple-deep)]" />
                      </div>
                      <div>
                        <div className="font-black tracking-widest text-xs uppercase text-[color:var(--sd-purple-deep)]">
                          Instant test faucet
                        </div>
                        <div className="text-sm text-[color:#2b2540] mt-0.5">
                          Get <b>0.01 SEPETH</b> credited straight to your balance —
                          no wallet, no gas, 1-minute cooldown. Perfect for
                          quick test rolls.
                        </div>
                      </div>
                    </div>
                    <button
                      onClick={claimTestCoins}
                      disabled={claiming}
                      data-testid="test-faucet-claim"
                      className="rounded-full px-5 py-2.5 text-xs font-black tracking-widest bg-[color:var(--sd-purple)] hover:bg-[color:var(--sd-purple-dark)] text-white shrink-0 disabled:opacity-60"
                    >
                      {claiming ? "..." : "CLAIM 0.01 SEPETH"}
                    </button>
                  </div>
                )}

                {/* Network sub-selector, only when there's more than one option */}
                {a.networks.length > 1 && (
                  <div className="mb-3">
                    <div className="text-[11px] font-black tracking-widest uppercase text-muted-foreground mb-1">
                      Network
                    </div>
                    <div className="flex flex-wrap gap-2" data-testid={`deposit-network-picker-${a.asset.toLowerCase()}`}>
                      {a.networks.map((n) => {
                        const active = networkByAsset[a.asset] === n.chain_id;
                        return (
                          <button
                            key={n.chain_id}
                            onClick={() =>
                              setNetworkByAsset((prev) => ({ ...prev, [a.asset]: n.chain_id }))
                            }
                            data-testid={`deposit-net-${a.asset.toLowerCase()}-${n.chain_id}`}
                            className={
                              "px-3 py-1.5 rounded-full text-xs font-black tracking-wider border-2 transition-colors " +
                              (active
                                ? "bg-[color:var(--sd-purple)] text-white border-[color:var(--sd-purple)]"
                                : "bg-white text-[color:var(--sd-purple-deep)] border-[color:var(--sd-lavender-2)] hover:bg-[color:var(--sd-lavender)]")
                            }
                          >
                            {n.chain}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                )}

                {activeNetwork && (
                  <div className="flex flex-col md:flex-row items-start gap-5">
                    <QRImage text={activeNetwork.address || ""} />
                    <div className="flex-1 space-y-3 w-full">
                      <div>
                        <div className="text-[11px] font-black tracking-widest uppercase text-muted-foreground">
                          {a.name}
                        </div>
                        <div className="text-sm font-bold text-[color:var(--sd-purple-deep)]">
                          Network: <span className="font-black">{activeNetwork.chain}</span>
                        </div>
                      </div>

                      <div>
                        <div className="text-[11px] font-black tracking-widest uppercase text-muted-foreground mb-1">
                          Your deposit address
                        </div>
                        <div
                          className="sd-mono bg-[color:var(--sd-lavender)] rounded-xl p-3 flex items-center justify-between gap-2"
                          data-testid={`deposit-address-${a.asset.toLowerCase()}`}
                        >
                          <span className="break-all">{activeNetwork.address || "—"}</span>
                          <button
                            onClick={() => copy(activeNetwork.address)}
                            className="shrink-0 rounded-full p-2 hover:bg-white"
                            data-testid={`deposit-copy-${a.asset.toLowerCase()}`}
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
                            {activeNetwork.min_deposit} {a.asset}
                          </span>
                        </div>
                        {activeNetwork.contract && (
                          <div className="break-all">
                            Token contract:{" "}
                            <span className="font-mono">{activeNetwork.contract}</span>
                          </div>
                        )}
                      </div>

                      {!activeNetwork.wired && (
                        <div
                          className="flex items-start gap-2 rounded-xl p-3 border border-amber-300 bg-amber-50 text-amber-900 text-xs"
                          data-testid={`deposit-pending-${a.asset.toLowerCase()}`}
                        >
                          <ShieldAlert className="w-4 h-4 mt-0.5 shrink-0" />
                          <div>
                            <b>{a.asset} deposit monitoring on {activeNetwork.chain} is not live yet.</b>{" "}
                            Your address is real and safe to receive to, but the site
                            will not credit balances until the watcher goes online.
                          </div>
                        </div>
                      )}

                      {activeNetwork.wired && (
                        <div className="flex items-center gap-2 text-xs font-black tracking-widest uppercase text-[color:#0b8a53]">
                          <span className="w-2 h-2 rounded-full bg-[#0fa968] animate-pulse" />
                          Watcher online — deposits credited after 12 confirmations
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </TabsContent>
            ))}
          </Tabs>
        )}

        {/* Sticky bottom Done bar — always visible on mobile scroll */}
        <div className="pt-4 mt-2 border-t border-[color:var(--sd-lavender-2)] flex justify-end">
          <DialogClose asChild>
            <button
              data-testid="deposit-done-button"
              className="rounded-full px-6 py-3 bg-[color:var(--sd-purple)] hover:bg-[color:var(--sd-purple-dark)] text-white font-black tracking-widest text-sm w-full md:w-auto"
            >
              DONE
            </button>
          </DialogClose>
        </div>
      </DialogContent>
    </Dialog>
  );
}
