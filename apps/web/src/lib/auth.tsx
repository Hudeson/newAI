"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { api, type Me, type Workspace } from "@/lib/api";

const TOKEN_KEY = "kb_access_token";
const WORKSPACE_KEY = "kb_workspace_id";

type AuthState = {
  token: string | null;
  me: Me | null;
  workspaces: Workspace[];
  workspaceId: string | null;
  loading: boolean;
  setSession: (token: string) => Promise<void>;
  logout: () => void;
  setWorkspaceId: (id: string) => void;
  refresh: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceIdState] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const hydrate = useCallback(async (nextToken: string) => {
    const [profile, spaces] = await Promise.all([
      api.me(nextToken),
      api.workspaces(nextToken),
    ]);
    setMe(profile);
    setWorkspaces(spaces);
    const saved =
      typeof window !== "undefined" ? localStorage.getItem(WORKSPACE_KEY) : null;
    const chosen =
      spaces.find((w) => w.id === saved)?.id || spaces[0]?.id || null;
    setWorkspaceIdState(chosen);
    if (chosen) localStorage.setItem(WORKSPACE_KEY, chosen);
  }, []);

  useEffect(() => {
    const existing = localStorage.getItem(TOKEN_KEY);
    if (!existing) {
      setLoading(false);
      return;
    }
    setToken(existing);
    hydrate(existing)
      .catch(() => {
        localStorage.removeItem(TOKEN_KEY);
        setToken(null);
        setMe(null);
      })
      .finally(() => setLoading(false));
  }, [hydrate]);

  const setSession = useCallback(
    async (nextToken: string) => {
      localStorage.setItem(TOKEN_KEY, nextToken);
      setToken(nextToken);
      setLoading(true);
      try {
        await hydrate(nextToken);
      } finally {
        setLoading(false);
      }
    },
    [hydrate],
  );

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(WORKSPACE_KEY);
    setToken(null);
    setMe(null);
    setWorkspaces([]);
    setWorkspaceIdState(null);
  }, []);

  const setWorkspaceId = useCallback((id: string) => {
    setWorkspaceIdState(id);
    localStorage.setItem(WORKSPACE_KEY, id);
  }, []);

  const refresh = useCallback(async () => {
    if (!token) return;
    await hydrate(token);
  }, [hydrate, token]);

  const value = useMemo(
    () => ({
      token,
      me,
      workspaces,
      workspaceId,
      loading,
      setSession,
      logout,
      setWorkspaceId,
      refresh,
    }),
    [
      token,
      me,
      workspaces,
      workspaceId,
      loading,
      setSession,
      logout,
      setWorkspaceId,
      refresh,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
