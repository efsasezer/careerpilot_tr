import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { apiRequest } from "./client";

interface AuthContextValue {
  authenticated: boolean;
  isChecking: boolean;
  configError: string | null;
  signIn: (password: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

/** Oturum sunucuda tutulur; tarayıcıda yalnızca JavaScript'in okuyamadığı (HttpOnly) çerez bulunur. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [authenticated, setAuthenticated] = useState(false);
  const [isChecking, setIsChecking] = useState(true);
  const [configError, setConfigError] = useState<string | null>(null);

  useEffect(() => {
    apiRequest<{ authenticated: boolean; config_error: string | null }>("/auth/me")
      .then((state) => {
        setAuthenticated(state.authenticated);
        setConfigError(state.config_error);
      })
      .catch(() => setAuthenticated(false))
      .finally(() => setIsChecking(false));
    const expired = () => setAuthenticated(false);
    window.addEventListener("careerpilot:unauthorized", expired);
    return () => window.removeEventListener("careerpilot:unauthorized", expired);
  }, []);

  const signIn = useCallback(async (password: string) => {
    await apiRequest("/auth/login", { method: "POST", body: JSON.stringify({ password }) });
    setAuthenticated(true);
  }, []);

  const signOut = useCallback(async () => {
    await apiRequest("/auth/logout", { method: "POST" }).catch(() => undefined);
    setAuthenticated(false);
  }, []);

  const value = useMemo(
    () => ({ authenticated, isChecking, configError, signIn, signOut }),
    [authenticated, isChecking, configError, signIn, signOut],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
}
