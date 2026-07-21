import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import { REGISTER } from "@/constants/testIds";

export default function RegisterPage() {
  const nav = useNavigate();
  const { register } = useAuth();
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (password !== confirm) {
      toast.error("Passwords don't match");
      return;
    }
    setBusy(true);
    try {
      await register(username, email, password);
      toast.success(`Welcome, ${username}! Starter demo coins credited.`);
      nav("/");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Registration failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="sd-panel w-full max-w-md p-8" data-testid="register-page">
        <div className="text-center mb-6">
          <div
            className="w-12 h-12 rounded-2xl mx-auto mb-3 flex items-center justify-center font-black text-white font-seg text-2xl"
            style={{ background: "linear-gradient(135deg,#8dc63f,#e44870)" }}
          >
            8
          </div>
          <h1 className="text-2xl font-black tracking-widest text-[color:var(--sd-purple-deep)]">
            CREATE ACCOUNT
          </h1>
          <p className="text-sm text-muted-foreground mt-1">Free demo coins on signup.</p>
        </div>

        <form onSubmit={submit} className="space-y-4">
          <label className="block">
            <span className="text-xs font-black tracking-widest uppercase text-muted-foreground">
              Username
            </span>
            <input
              type="text"
              required
              minLength={3}
              maxLength={24}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              data-testid={REGISTER.nameInput}
              className="mt-1 w-full rounded-xl bg-[color:var(--sd-lavender)] px-4 py-3 outline-none focus:ring-2 focus:ring-[color:var(--sd-purple)]"
            />
          </label>
          <label className="block">
            <span className="text-xs font-black tracking-widest uppercase text-muted-foreground">
              Email
            </span>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              data-testid={REGISTER.emailInput}
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
              minLength={6}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              data-testid={REGISTER.passwordInput}
              className="mt-1 w-full rounded-xl bg-[color:var(--sd-lavender)] px-4 py-3 outline-none focus:ring-2 focus:ring-[color:var(--sd-purple)]"
            />
          </label>
          <label className="block">
            <span className="text-xs font-black tracking-widest uppercase text-muted-foreground">
              Confirm password
            </span>
            <input
              type="password"
              required
              minLength={6}
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              data-testid={REGISTER.passwordConfirmInput}
              className="mt-1 w-full rounded-xl bg-[color:var(--sd-lavender)] px-4 py-3 outline-none focus:ring-2 focus:ring-[color:var(--sd-purple)]"
            />
          </label>
          <button
            type="submit"
            disabled={busy}
            data-testid={REGISTER.submitButton}
            className="sd-roll-btn"
          >
            {busy ? "..." : "SIGN UP"}
          </button>
        </form>

        <div className="mt-4 text-center text-sm text-muted-foreground">
          Already have an account?{" "}
          <Link
            to="/login"
            data-testid={REGISTER.loginLink}
            className="font-black text-[color:var(--sd-purple)] hover:underline"
          >
            Log in
          </Link>
        </div>
      </div>
    </div>
  );
}
