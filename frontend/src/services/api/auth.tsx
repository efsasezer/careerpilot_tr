import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { apiRequest, getApiUrl } from "./client";

interface AuthContextValue {
  token: string | null;
  isChecking: boolean;
  signIn: (token: string, remember: boolean) => Promise<void>;
  signOut: () => void;
}

const STORAGE_KEY = "careerpilot.accessKey";
const LOCAL_TOKEN = "yerel";
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
  const [isChecking, setIsChecking] = useState(true);

  // Sayfa yenilendiğinde saklanan anahtarı sunucuda doğrulayarak oturumu geri yükle.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const stored = readStoredToken();
      try {
        if (stored) {
          await apiRequest("/auth/check", stored);
          if (!cancelled) setToken(stored);
          return;
        }
        // Yerel geliştirmede sunucu anahtar istemiyorsa giriş ekranı atlanır.
        const health = await fetch(`${getApiUrl()}/health`).then((response) => response.json());
        if (!cancelled && health.auth_required === false) {
          await apiRequest("/auth/check", LOCAL_TOKEN);
          if (!cancelled) setToken(LOCAL_TOKEN);
        }
      } catch {
        if (stored) clearStoredToken();
      } finally {
        if (!cancelled) setIsChecking(false);
      }
    })();
    return () => { cancelled = true; };
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
