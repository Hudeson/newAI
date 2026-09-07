"use client";

import { useEffect, useState } from "react";
import { api, ApiError, type UserOut } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const ROLE_LABEL: Record<string, string> = {
  admin: "管理员",
  owner: "所有者",
  member: "成员",
};

const STATUS_LABEL: Record<string, string> = {
  active: "正常",
  disabled: "已停用",
  invited: "已邀请",
};

export default function MembersPage() {
  const { token, me } = useAuth();
  const [users, setUsers] = useState<UserOut[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!token) return;
    api
      .users(token)
      .then(setUsers)
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : "加载成员失败"),
      );
  }, [token]);

  return (
    <section className="panel stack">
      <h1>成员</h1>
      <p className="muted">当前租户成员名册（只读）。</p>
      {error ? <div className="error">{error}</div> : null}
      <table className="table">
        <thead>
          <tr>
            <th>姓名</th>
            <th>邮箱</th>
            <th>角色</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.user_id}>
              <td>
                {u.display_name || "—"}
                {u.user_id === me?.user_id ? "（我）" : ""}
              </td>
              <td>{u.email}</td>
              <td>
                <span className="badge">{ROLE_LABEL[u.role] || u.role}</span>
              </td>
              <td>{STATUS_LABEL[u.status] || u.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
