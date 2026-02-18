"use client";

import Link from "next/link";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function Home() {
  const router = useRouter();

  useEffect(() => {
    router.prefetch("/login");
    router.prefetch("/signup");
  }, [router]);

  return (
    <main className="container landing-shell">
      <section className="landing-hero">
        <div className="landing-orbit landing-orbit-a" />
        <div className="landing-orbit landing-orbit-b" />
        <div className="landing-content">
          <span className="badge">Testing</span>
          <h1 className="hero-title">Sketch fast. Guess faster. Win smart.</h1>
          <p className="hero-sub">
            Multiplayer drawing game with secure auth, private rooms, live
            lobbies, and low-latency gameplay powered by Django, Next.js,
            WebSockets, and Redis.
          </p>
          <div className="hero-actions">
            <Link className="button button-primary" href="/signup">
              Create Account
            </Link>
            <Link className="button button-ghost" href="/login">
              Sign In
            </Link>
          </div>
        </div>
      </section>
    </main>
  );
}

