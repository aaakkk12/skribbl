"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { apiFetch } from "../../../lib/api";

type MeResponse = {
  profile_completed: boolean;
};

export default function LoginPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      await apiFetch("/api/auth/login/", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      const me = await apiFetch<MeResponse>("/api/auth/me/", { method: "GET" });
      const nextPath = searchParams.get("next");
      if (me.profile_completed && nextPath && nextPath.startsWith("/")) {
        router.push(nextPath);
      } else {
        router.push(me.profile_completed ? "/dashboard" : "/profile/setup");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="container auth-shell">
      <section className="auth-card auth-card-form">
        <div className="nav-row">
          <div>
            <span className="kicker">Welcome back</span>
            <h1 className="hero-title" style={{ fontSize: "2.4rem" }}>
              Sign in to your account
            </h1>
          </div>
          <Link className="link" href="/signup">
            Create account
          </Link>
        </div>
        <form onSubmit={onSubmit} className="field" style={{ gap: "1rem" }}>
          <div className="field">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@company.com"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="••••••••"
              required
            />
          </div>
          {error ? <p className="error">{error}</p> : null}
          <div className="form-actions">
            <button className="button button-primary" type="submit" disabled={loading}>
              {loading ? "Signing in..." : "Sign in"}
            </button>
            <Link className="link" href="/reset-password">
              Forgot password?
            </Link>
          </div>
        </form>
      </section>
    </main>
  );
}



