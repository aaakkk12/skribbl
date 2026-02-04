"use client";

import { useState } from "react";
import Link from "next/link";
import { apiFetch } from "../../../lib/api";

export default function ResetPasswordPage() {
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    setMessage("");
    setLoading(true);
    try {
      const response = await apiFetch<{ detail: string }>("/api/auth/password-reset/", {
        method: "POST",
        body: JSON.stringify({ email }),
      });
      setMessage(response.detail || "Check your inbox for a reset link.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="container">
      <section className="auth-card">
        <div className="nav-row">
          <div>
            <span className="kicker">Password help</span>
            <h1 className="hero-title" style={{ fontSize: "2.2rem" }}>
              Reset your password
            </h1>
          </div>
          <Link className="link" href="/login">
            Back to login
          </Link>
        </div>
        <p className="helper">
          Enter your email and we will send you a secure reset link.
        </p>
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
          {message ? <p className="success">{message}</p> : null}
          {error ? <p className="error">{error}</p> : null}
          <div className="form-actions">
            <button className="button button-primary" type="submit" disabled={loading}>
              {loading ? "Sending..." : "Send reset link"}
            </button>
          </div>
        </form>
      </section>
    </main>
  );
}



