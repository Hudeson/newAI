"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function RegisterPage() {
  const { setSession } = useAuth();
  const router = useRouter();
  const [tenantName, setTenantName] = useState("我的知识库");
  const [tenantSlug, setTenantSlug] = useState("my-kb");
  const [displayName, setDisplayName] = useState("管理员");
  const [email, setEmail] = useState("admin@example.com");
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
      setError(err instanceof ApiError ? err.message : "注册失败");
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
          <h1>几分钟内搭建私有知识中庭。</h1>
          <p style={{ color: "rgba(238,246,243,0.75)" }}>
            一个租户、默认工作区，从第一天起就具备 ACL 能力。
          </p>
        </div>
      </section>
      <section className="auth-panel">
        <form className="panel auth-card stack" onSubmit={onSubmit}>
          <h2>创建租户</h2>
          <label className="field">
            租户名称
            <input
              value={tenantName}
              onChange={(e) => setTenantName(e.target.value)}
              required
            />
          </label>
          <label className="field">
            租户标识
            <input
              value={tenantSlug}
              onChange={(e) => setTenantSlug(e.target.value)}
              pattern="^[a-z0-9-]+$"
              required
            />
          </label>
          <label className="field">
            你的姓名
            <input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
            />
          </label>
          <label className="field">
            邮箱
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </label>
          <label className="field">
            密码
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
            {busy ? "创建中…" : "创建并进入"}
          </button>
          <p className="muted">
            已有账号？ <Link href="/login">登录</Link>
          </p>
        </form>
      </section>
    </div>
  );
}
