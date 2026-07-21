import React, { useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { ChevronDown, Scale, RotateCw } from "lucide-react";

export default function ProvablyFair() {
  const { user, refresh } = useAuth();
  const [open, setOpen] = useState(false);
  const [clientSeed, setClientSeed] = useState("");
  const [busy, setBusy] = useState(false);
  const [rotated, setRotated] = useState(null);

  const rotate = async () => {
    if (!user) {
      toast.info("Log in first to rotate seeds");
      return;
    }
    const seed = clientSeed.trim() || Math.random().toString(36).slice(2, 14);
    setBusy(true);
    try {
      const { data } = await api.post("/seeds/rotate", { client_seed: seed });
      setRotated(data);
      setClientSeed("");
      await refresh();
      toast.success("Seed rotated — new game starts fresh");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to rotate");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="sd-panel p-4 md:p-6 mt-6" data-testid="fairness-panel">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between"
        data-testid="fairness-toggle"
      >
        <div className="flex items-center gap-3">
          <div
            className="w-10 h-10 rounded-2xl flex items-center justify-center"
            style={{ background: "var(--sd-lavender)" }}
          >
            <Scale className="w-5 h-5 text-[color:var(--sd-purple-deep)]" />
          </div>
          <div className="text-left">
            <div className="font-black tracking-widest text-sm text-[color:var(--sd-purple-deep)]">
              PROVABLY FAIR
            </div>
            <div className="text-xs text-muted-foreground">
              HMAC-SHA256(server_seed, client_seed:nonce) → roll
            </div>
          </div>
        </div>
        <ChevronDown
          className={`w-5 h-5 transition-transform ${open ? "rotate-180" : ""} text-[color:var(--sd-purple-deep)]`}
        />
      </button>

      {open && (
        <div className="sd-fairness mt-4 space-y-3" data-testid="fairness-body">
          <Row label="Server seed (hashed)" value={user?.server_seed_hashed ?? "—"} testid="fair-server-hash" />
          <Row label="Client seed" value={user?.client_seed ?? "—"} testid="fair-client-seed" />
          <Row label="Nonce" value={String(user?.nonce ?? "—")} testid="fair-nonce" />

          {rotated && (
            <>
              <div className="pt-2 border-t border-dashed border-[color:var(--sd-lavender-2)]">
                <div className="text-xs font-black tracking-widest uppercase text-[color:var(--sd-purple-deep)] mb-2">
                  Previous seed revealed
                </div>
                <Row label="Previous server seed" value={rotated.previous_server_seed} testid="fair-prev-seed" />
                <Row label="Previous hash" value={rotated.previous_server_seed_hashed} testid="fair-prev-hash" />
              </div>
            </>
          )}

          <div className="pt-3 flex flex-col sm:flex-row gap-2">
            <input
              className="flex-1 rounded-xl bg-[color:var(--sd-lavender)] px-4 py-2 text-sm outline-none focus:ring-2 focus:ring-[color:var(--sd-purple)]"
              placeholder="New client seed (optional — random if empty)"
              value={clientSeed}
              onChange={(e) => setClientSeed(e.target.value)}
              data-testid="fair-new-client-seed"
              maxLength={64}
            />
            <button
              onClick={rotate}
              disabled={busy}
              className="rounded-xl bg-[color:var(--sd-purple)] hover:bg-[color:var(--sd-purple-dark)] text-white font-black tracking-widest text-sm px-4 py-2 flex items-center justify-center gap-2"
              data-testid="fair-rotate"
            >
              <RotateCw className="w-4 h-4" /> ROTATE SEEDS
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function Row({ label, value, testid }) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1">
      <div className="text-xs font-black tracking-widest uppercase text-muted-foreground">
        {label}
      </div>
      <div className="sd-mono" data-testid={testid}>{value}</div>
    </div>
  );
}
