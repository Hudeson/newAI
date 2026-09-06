"use client";

import { useEffect, useState } from "react";
import { api, ApiError, type UserOut } from "@/lib/api";
import { useAuth } from "@/lib/auth";

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
        setError(err instanceof ApiError ? err.message : "Failed to load members"),
      );
  }, [token]);

  return (
    <section className="panel stack">
      <h1>Members</h1>
      <p className="muted">Read-only roster for the current tenant (E6.5).</p>
      {error ? <div className="error">{error}</div> : null}
      <table className="table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Email</th>
            <th>Role</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.user_id}>
              <td>
                {u.display_name || "—"}
                {u.user_id === me?.user_id ? " (you)" : ""}
              </td>
              <td>{u.email}</td>
              <td>
                <span className="badge">{u.role}</span>
              </td>
              <td>{u.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
