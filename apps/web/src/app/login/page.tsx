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
      setError(err instanceof ApiError ? err.message : "登录失败");
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
          <h1>你的知识，可检索、可追问、有出处。</h1>
          <p className="muted" style={{ color: "rgba(238,246,243,0.75)" }}>
            上传文档、生成学习总结，并在租户隔离下进行带引用的问答。
          </p>
        </div>
      </section>
      <section className="auth-panel">
        <form className="panel auth-card stack" onSubmit={onSubmit}>
          <h2>登录</h2>
          <p className="muted">请输入租户标识与账号。</p>
          <label className="field">
            租户标识
            <input
              className="input"
              value={tenantSlug}
              onChange={(e) => setTenantSlug(e.target.value)}
              required
            />
          </label>
          <label className="field">
            邮箱
            <input
              className="input"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </label>
          <label className="field">
            密码
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
            {busy ? "登录中…" : "进入"}
          </button>
          <p className="muted">
            新租户？ <Link href="/register">创建工作区</Link>
          </p>
        </form>
      </section>
    </div>
  );
}
