"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function LoginPage() {
  const { setSession, token, loading } = useAuth();
  const router = useRouter();
  const [tenantSlug, setTenantSlug] = useState("acme");
  const [email, setEmail] = useState("admin@acme.example");
  const [password, setPassword] = useState("password123");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (!loading && token) {
    router.replace("/app");
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const tok = await api.login({
        tenant_slug: tenantSlug.trim(),
        email: email.trim(),
        password,
      });
      await setSession(tok.access_token);
      router.push("/app");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-screen">
      <section className="auth-hero">
        <div className="auth-hero-content">
          <div className="brand">
            Atrium <span>KB</span>
          </div>
          <h1>Your knowledge, grounded and answerable.</h1>
          <p className="muted" style={{ color: "rgba(238,246,243,0.75)" }}>
            Upload documents, learn summaries, and ask with citations — tenant-isolated by
            design.
          </p>
        </div>
      </section>
      <section className="auth-panel">
        <form className="panel auth-card stack" onSubmit={onSubmit}>
          <h2>Sign in</h2>
          <p className="muted">Use your tenant slug and account.</p>
          <label className="field">
            Tenant slug
            <input
              className="input"
              value={tenantSlug}
              onChange={(e) => setTenantSlug(e.target.value)}
              required
            />
          </label>
          <label className="field">
            Email
            <input
              className="input"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </label>
          <label className="field">
            Password
            <input
              className="input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
          {error ? <div className="error">{error}</div> : null}
          <button className="btn accent" disabled={busy} type="submit">
            {busy ? "Signing in…" : "Continue"}
          </button>
          <p className="muted">
            New tenant? <Link href="/register">Create workspace</Link>
          </p>
        </form>
      </section>
    </div>
  );
}
