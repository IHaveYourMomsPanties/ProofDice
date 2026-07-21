import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import { LOGIN } from "@/constants/testIds";

export default function LoginPage() {
  const nav = useNavigate();
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await login(email, password);
      toast.success("Welcome back!");
      nav("/");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Login failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="sd-panel w-full max-w-md p-8" data-testid="login-page">
        <div className="text-center mb-6">
          <div
            className="w-12 h-12 rounded-2xl mx-auto mb-3 flex items-center justify-center font-black text-white font-seg text-2xl"
            style={{ background: "linear-gradient(135deg,#7bc142,#ff6b57)" }}
          >
            8
          </div>
          <h1 className="text-2xl font-black tracking-widest text-[color:var(--sd-purple-deep)]">
            BETTERDICE
          </h1>
          <p className="text-sm text-muted-foreground mt-1">Welcome back — roll something.</p>
        </div>

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
              data-testid={LOGIN.emailInput}
              className="mt-1 w-full rounded-xl bg-[color:var(--sd-lavender)] px-4 py-3 outline-none focus:ring-2 focus:ring-[color:var(--sd-purple)]"
            />
          </label>
          <label className="block">
            <span className="text-xs font-black tracking-widest uppercase text-muted-foreground">
              Password
            </span>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              data-testid={LOGIN.passwordInput}
              className="mt-1 w-full rounded-xl bg-[color:var(--sd-lavender)] px-4 py-3 outline-none focus:ring-2 focus:ring-[color:var(--sd-purple)]"
            />
          </label>
          <button
            type="submit"
            disabled={busy}
            data-testid={LOGIN.submitButton}
            className="sd-roll-btn"
          >
            {busy ? "..." : "LOG IN"}
          </button>
        </form>

        <div className="mt-4 text-center text-sm text-muted-foreground">
          No account?{" "}
          <Link
            to="/register"
            data-testid={LOGIN.registerLink}
            className="font-black text-[color:var(--sd-purple)] hover:underline"
          >
            Sign up
          </Link>
        </div>
      </div>
    </div>
  );
}
