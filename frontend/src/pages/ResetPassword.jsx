import React, { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, setToken } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";

export default function ResetPasswordPage() {
  const [params] = useSearchParams();
  const nav = useNavigate();
  const { refresh } = useAuth();
  const token = useMemo(() => params.get("token") || "", [params]);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (password !== confirm) {
      toast.error("Passwords don't match");
      return;
    }
    if (!token) {
      toast.error("Missing reset token — request a fresh link");
      return;
    }
    setBusy(true);
    try {
      const { data } = await api.post("/auth/reset-password", {
        token,
        new_password: password,
      });
      // Auto-login
      setToken(data.token);
      await refresh();
      toast.success("Password reset — you're logged in.");
      nav("/");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Reset failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="sd-panel w-full max-w-md p-8" data-testid="reset-password-page">
        <div className="text-center mb-6">
          <div
            className="w-12 h-12 rounded-2xl mx-auto mb-3 flex items-center justify-center font-black text-white font-seg text-2xl"
            style={{ background: "linear-gradient(135deg,#7bc142,#ff6b57)" }}
          >
            8
          </div>
          <h1 className="text-2xl font-black tracking-widest text-[color:var(--sd-purple-deep)]">
            NEW PASSWORD
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Pick a new password to finish the reset.
          </p>
        </div>

        {!token ? (
          <div
            className="rounded-2xl p-4 border border-amber-300 bg-amber-50 text-amber-900 text-sm"
            data-testid="reset-password-missing-token"
          >
            No reset token in the URL — please open the reset link from your
            email again, or{" "}
            <Link to="/forgot-password" className="font-black underline">
              request a new one
            </Link>.
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-4">
            <label className="block">
              <span className="text-xs font-black tracking-widest uppercase text-muted-foreground">
                New password
              </span>
              <input
                type="password"
                required
                minLength={6}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                data-testid="reset-password-input"
                className="mt-1 w-full rounded-xl bg-[color:var(--sd-lavender)] px-4 py-3 outline-none focus:ring-2 focus:ring-[color:var(--sd-purple)]"
              />
            </label>
            <label className="block">
              <span className="text-xs font-black tracking-widest uppercase text-muted-foreground">
                Confirm new password
              </span>
              <input
                type="password"
                required
                minLength={6}
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                data-testid="reset-password-confirm-input"
                className="mt-1 w-full rounded-xl bg-[color:var(--sd-lavender)] px-4 py-3 outline-none focus:ring-2 focus:ring-[color:var(--sd-purple)]"
              />
            </label>
            <button
              type="submit"
              disabled={busy}
              data-testid="reset-password-submit-button"
              className="sd-roll-btn"
            >
              {busy ? "..." : "SET NEW PASSWORD"}
            </button>
          </form>
        )}

        <div className="mt-4 text-center text-sm text-muted-foreground">
          <Link
            to="/login"
            data-testid="reset-password-back-to-login-link"
            className="font-black text-[color:var(--sd-purple)] hover:underline"
          >
            Back to login
          </Link>
        </div>
      </div>
    </div>
  );
}
