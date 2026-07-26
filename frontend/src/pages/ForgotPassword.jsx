import React, { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { toast } from "sonner";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const { data } = await api.post("/auth/forgot-password", { email });
      setSent(true);
      toast.success(data?.message || "Check your inbox.");
    } catch (err) {
      // Backend always returns 200 for enumeration safety, but handle unexpected failure
      toast.error(err?.response?.data?.detail || "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="sd-panel w-full max-w-md p-8" data-testid="forgot-password-page">
        <div className="text-center mb-6">
          <div
            className="w-12 h-12 rounded-2xl mx-auto mb-3 flex items-center justify-center font-black text-white font-seg text-2xl"
            style={{ background: "linear-gradient(135deg,#7bc142,#ff6b57)" }}
          >
            8
          </div>
          <h1 className="text-2xl font-black tracking-widest text-[color:var(--sd-purple-deep)]">
            RESET PASSWORD
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Enter your email — we'll send a reset link.
          </p>
        </div>

        {sent ? (
          <div
            className="rounded-2xl p-4 border border-emerald-300 bg-emerald-50 text-emerald-900 text-sm"
            data-testid="forgot-password-sent"
          >
            <b>Check your inbox</b> (and spam folder). If an account exists for{" "}
            <span className="font-mono">{email}</span>, a reset link will
            arrive in a minute or two. The link expires in 30 minutes.
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-4">
            <label className="block">
              <span className="text-xs font-black tracking-widest uppercase text-muted-foreground">
                Email
              </span>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                data-testid="forgot-password-email-input"
                className="mt-1 w-full rounded-xl bg-[color:var(--sd-lavender)] px-4 py-3 outline-none focus:ring-2 focus:ring-[color:var(--sd-purple)]"
              />
            </label>
            <button
              type="submit"
              disabled={busy}
              data-testid="forgot-password-submit-button"
              className="sd-roll-btn"
            >
              {busy ? "..." : "SEND RESET LINK"}
            </button>
          </form>
        )}

        <div className="mt-4 text-center text-sm text-muted-foreground">
          <Link
            to="/login"
            data-testid="forgot-password-back-to-login-link"
            className="font-black text-[color:var(--sd-purple)] hover:underline"
          >
            Back to login
          </Link>
        </div>
      </div>
    </div>
  );
}
