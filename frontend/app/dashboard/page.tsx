"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { apiFetch } from "../../lib/api";

type User = {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
};

export default function DashboardPage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const load = async () => {
      try {
        const data = await apiFetch<User>("/api/auth/me/", { method: "GET" });
        setUser(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Not authorized");
        router.push("/login");
      }
    };
    load();
  }, [router]);

  const handleLogout = async () => {
    await apiFetch("/api/auth/logout/", { method: "POST" });
    router.push("/login");
  };

  return (
    <main className="container">
      <section className="auth-card dashboard">
        <div className="nav-row">
          <div>
            <span className="kicker">Dashboard</span>
            <h1 className="hero-title" style={{ fontSize: "2.2rem" }}>
              {user ? `Welcome, ${user.first_name || user.email}` : "Welcome"}
            </h1>
          </div>
          <Link className="link" href="/">
            Home
          </Link>
        </div>
        {error ? (
          <p className="error">{error}</p>
        ) : (
          <p className="helper">
            You are signed in with a secure JWT cookie. This page is protected by
            the Django API.
          </p>
        )}
        <div className="form-actions">
          <Link className="button button-ghost" href="/rooms">
            Go to rooms
          </Link>
          <button className="button button-primary" type="button" onClick={handleLogout}>
            Log out
          </button>
        </div>
      </section>
    </main>
  );
}



