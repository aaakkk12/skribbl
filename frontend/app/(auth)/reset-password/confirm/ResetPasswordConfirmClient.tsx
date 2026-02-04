"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { apiFetch } from "../../../../lib/api";

export default function ResetPasswordConfirmClient() {
  const searchParams = useSearchParams();
  const [uid, setUid] = useState("");
  const [token, setToken] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setUid(searchParams.get("uid") || "");
    setToken(searchParams.get("token") || "");
  }, [searchParams]);

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    setMessage("");

    if (!uid || !token) {
      setError("Reset link is missing or invalid.");
      return;
    }

    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }

    setLoading(true);
    try {
      const response = await apiFetch<{ detail: string }>(
        "/api/auth/password-reset/confirm/",
        {
          method: "POST",
          body: JSON.stringify({ uid, token, new_password: password }),
        }
      );
      setMessage(response.detail || "Password updated successfully.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reset failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="container">
      <section className="auth-card">
        <div className="nav-row">
          <div>
            <span className="kicker">Set a new password</span>
            <h1 className="hero-title" style={{ fontSize: "2.2rem" }}>
              Create a new password
            </h1>
          </div>
          <Link className="link" href="/login">
            Back to login
          </Link>
        </div>
        <form onSubmit={onSubmit} className="field" style={{ gap: "1rem" }}>
          <div className="field">
            <label htmlFor="password">New password</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="At least 8 characters"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="confirm">Confirm password</label>
            <input
              id="confirm"
              type="password"
              value={confirm}
              onChange={(event) => setConfirm(event.target.value)}
              placeholder="Re-enter password"
              required
            />
          </div>
          {message ? <p className="success">{message}</p> : null}
          {error ? <p className="error">{error}</p> : null}
          <div className="form-actions">
            <button className="button button-primary" type="submit" disabled={loading}>
              {loading ? "Updating..." : "Update password"}
            </button>
          </div>
        </form>
      </section>
    </main>
  );
}