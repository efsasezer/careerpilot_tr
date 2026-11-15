import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { apiRequest } from "./client";

interface AuthContextValue {
  token: string | null;
  isChecking: boolean;
  signIn: (token: string, remember: boolean) => Promise<void>;
  signOut: () => void;
}

const STORAGE_KEY = "careerpilot.accessKey";
const AuthContext = createContext<AuthContextValue | null>(null);

function readStoredToken(): string | null {
  try {
    return sessionStorage.getItem(STORAGE_KEY) ?? localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function clearStoredToken() {
  try {
    sessionStorage.removeItem(STORAGE_KEY);
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* depolama kapalıysa yapılacak bir şey yok */
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [isChecking, setIsChecking] = useState(() => Boolean(readStoredToken()));

  // Sayfa yenilendiğinde saklanan anahtarı sunucuda doğrulayarak oturumu geri yükle.
  useEffect(() => {
    const stored = readStoredToken();
    if (!stored) return;
    apiRequest("/auth/check", stored)
      .then(() => setToken(stored))
      .catch(clearStoredToken)
      .finally(() => setIsChecking(false));
  }, []);

  const signIn = useCallback(async (value: string, remember: boolean) => {
    setIsChecking(true);
    try {
      await apiRequest("/auth/check", value);
      clearStoredToken();
      try {
        (remember ? localStorage : sessionStorage).setItem(STORAGE_KEY, value);
      } catch {
        /* yalnızca bellekte tutulur */
      }
      setToken(value);
    } finally {
      setIsChecking(false);
    }
  }, []);

  const signOut = useCallback(() => {
    clearStoredToken();
    setToken(null);
  }, []);

  const value = useMemo(() => ({ token, isChecking, signIn, signOut }), [token, isChecking, signIn, signOut]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
}
