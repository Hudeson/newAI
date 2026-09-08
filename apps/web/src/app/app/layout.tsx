"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/lib/auth";

const links = [
  { href: "/app", label: "文库" },
  { href: "/app/ask", label: "问答" },
  { href: "/app/edu", label: "学习" },
  { href: "/app/graph", label: "知识图谱" },
  { href: "/app/members", label: "成员" },
  { href: "/app/governance", label: "治理" },
];

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { token, loading, me, workspaces, workspaceId, setWorkspaceId, logout } =
    useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (!loading && !token) router.replace("/login");
  }, [loading, token, router]);

  if (loading || !token) {
    return <main className="main">正在加载工作区…</main>;
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          Atrium <span>KB</span>
        </div>
        <nav className="nav">
          {links.map((l) => {
            const active =
              l.href === "/app"
                ? pathname === "/app"
                : pathname === l.href || pathname.startsWith(`${l.href}/`);
            return (
              <Link key={l.href} href={l.href} className={active ? "active" : undefined}>
                {l.label}
              </Link>
            );
          })}
        </nav>
        <div className="stack" style={{ marginTop: "auto", gap: 12 }}>
          <div className="muted" style={{ color: "rgba(244,247,245,0.62)", padding: "0 10px" }}>
            <div style={{ color: "#f4f7f5", fontWeight: 600 }}>{me?.display_name || me?.email}</div>
            <small>{me?.role}</small>
          </div>
          <button className="btn ghost" onClick={logout} type="button">
            退出登录
          </button>
        </div>
      </aside>
      <div className="main">
        <div className="topbar">
          <div>
            <div className="muted" style={{ fontSize: "0.78rem", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 6 }}>
              工作区
            </div>
            <select
              className="select"
              value={workspaceId || ""}
              onChange={(e) => setWorkspaceId(e.target.value)}
            >
              {workspaces.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name} ({w.slug})
                </option>
              ))}
            </select>
          </div>
        </div>
        {children}
      </div>
    </div>
  );
}
