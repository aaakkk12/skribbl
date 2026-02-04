import Link from "next/link";

export default function Home() {
  return (
    <main className="container">
      <section className="hero">
        <span className="badge">ProAuth Stack</span>
        <h1 className="hero-title">A professional auth experience, shipped fast.</h1>
        <p className="hero-sub">
          Secure JWT cookies, seamless reset flows, and a polished UI that feels
          enterprise-ready. Django handles the heavy lifting while Next.js keeps
          the UX smooth.
        </p>
        <div className="hero-actions">
          <Link className="button button-primary" href="/signup">
            Create account
          </Link>
          <Link className="button button-ghost" href="/login">
            Sign in
          </Link>
        </div>
      </section>
      <section className="auth-card">
        <div className="auth-grid">
          <div>
            <h2 className="hero-title" style={{ fontSize: "2rem" }}>
              Built for teams who care about security and style.
            </h2>
            <p className="hero-sub">
              Cookie-based JWTs keep tokens out of local storage, SMTP reset
              links are ready for your provider, and the API is cleanly
              separated for future mobile or desktop clients.
            </p>
          </div>
          <div>
            <div className="field">
              <label>Included endpoints</label>
              <div className="helper">
                /api/auth/register · /login · /logout · /password-reset ·
                /password-reset/confirm · /me
              </div>
            </div>
            <div className="field" style={{ marginTop: "1rem" }}>
              <label>Frontend flows</label>
              <div className="helper">
                Signup, login, reset request, reset confirm, and a protected
                dashboard view.
              </div>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}



