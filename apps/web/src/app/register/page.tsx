"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function RegisterPage() {
  const { setSession } = useAuth();
  const router = useRouter();
  const [tenantName, setTenantName] = useState("Acme Knowledge");
  const [tenantSlug, setTenantSlug] = useState("acme");
  const [displayName, setDisplayName] = useState("Admin");
  const [email, setEmail] = useState("admin@acme.example");
  const [password, setPassword] = useState("password123");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const tok = await api.register({
        tenant_name: tenantName.trim(),
        tenant_slug: tenantSlug.trim(),
        email: email.trim(),
        password,
        display_name: displayName.trim(),
      });
      await setSession(tok.access_token);
      router.push("/app");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Register failed");
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
          <h1>Stand up a private knowledge atrium in minutes.</h1>
          <p style={{ color: "rgba(238,246,243,0.75)" }}>
            One tenant, one default workspace, ACL-ready from day one.
          </p>
        </div>
      </section>
      <section className="auth-panel">
        <form className="panel auth-card stack" onSubmit={onSubmit}>
          <h2>Create tenant</h2>
          <label className="field">
            Tenant name
            <input
              value={tenantName}
              onChange={(e) => setTenantName(e.target.value)}
              required
            />
          </label>
          <label className="field">
            Tenant slug
            <input
              value={tenantSlug}
              onChange={(e) => setTenantSlug(e.target.value)}
              pattern="^[a-z0-9-]+$"
              required
            />
          </label>
          <label className="field">
            Your name
            <input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
            />
          </label>
          <label className="field">
            Email
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </label>
          <label className="field">
            Password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={8}
              required
            />
          </label>
          {error ? <div className="error">{error}</div> : null}
          <button className="btn accent" disabled={busy} type="submit">
            {busy ? "Creating…" : "Create & enter"}
          </button>
          <p className="muted">
            Already have an account? <Link href="/login">Sign in</Link>
          </p>
        </form>
      </section>
    </div>
  );
}
