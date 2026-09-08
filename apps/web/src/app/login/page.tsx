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
          <h1>知识有处可栖，回答有据可依。</h1>
          <p style={{ color: "rgba(244,247,245,0.78)" }}>
            上传、学习、检索与追问，都在租户边界之内完成。
          </p>
        </div>
      </section>
      <section className="auth-panel">
        <form className="panel auth-card stack" onSubmit={onSubmit}>
          <div>
            <div className="page-kicker">欢迎回来</div>
            <h2>登录</h2>
            <p className="muted">使用租户标识与账号进入工作区。</p>
          </div>
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
            {busy ? "登录中…" : "进入中庭"}
          </button>
          <p className="muted">
            新租户？ <Link href="/register">创建工作区</Link>
          </p>
        </form>
      </section>
    </div>
  );
}
