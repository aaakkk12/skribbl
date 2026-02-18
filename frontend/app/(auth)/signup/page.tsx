"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { apiFetch } from "../../../lib/api";

export default function SignupPage() {
  const router = useRouter();
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      await apiFetch("/api/auth/register/", {
        method: "POST",
        body: JSON.stringify({
          email,
          password,
          first_name: firstName,
          last_name: lastName,
        }),
      });
      await apiFetch("/api/auth/login/", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      router.push("/profile/setup");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Signup failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="container auth-shell">
      <section className="auth-card auth-card-form">
        <div className="nav-row">
          <div>
            <span className="kicker">Get started</span>
            <h1 className="hero-title" style={{ fontSize: "2.4rem" }}>
              Create your account
            </h1>
          </div>
          <Link className="link" href="/login">
            Already have an account?
          </Link>
        </div>
        <form onSubmit={onSubmit} className="field" style={{ gap: "1rem" }}>
          <div className="auth-grid">
            <div className="field">
              <label htmlFor="firstName">First name</label>
              <input
                id="firstName"
                value={firstName}
                onChange={(event) => setFirstName(event.target.value)}
                placeholder="Aisha"
              />
            </div>
            <div className="field">
              <label htmlFor="lastName">Last name</label>
              <input
                id="lastName"
                value={lastName}
                onChange={(event) => setLastName(event.target.value)}
                placeholder="Khan"
              />
            </div>
          </div>
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
              placeholder="At least 8 characters"
              required
            />
          </div>
          {error ? <p className="error">{error}</p> : null}
          <div className="form-actions">
            <button className="button button-primary" type="submit" disabled={loading}>
              {loading ? "Creating..." : "Create account"}
            </button>
            <span className="helper">By signing up you agree to our terms.</span>
          </div>
        </form>
      </section>
    </main>
  );
}



