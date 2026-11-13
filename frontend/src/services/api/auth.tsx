import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { apiRequest } from "./client";

interface AuthContextValue {
  token: string | null;
  isChecking: boolean;
  error: string | null;
  signIn: (token: string) => Promise<void>;
  signOut: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [isChecking, setIsChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const signIn = useCallback(async (value: string) => {
    setIsChecking(true);
    setError(null);
    try {
      await apiRequest<{ authenticated: boolean }>("/auth/check", value);
      setToken(value);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Erişim doğrulanamadı.");
      throw reason;
    } finally {
      setIsChecking(false);
    }
  }, []);

  const signOut = useCallback(() => {
    setToken(null);
    setError(null);
  }, []);

  const value = useMemo(
    () => ({ token, isChecking, error, signIn, signOut }),
    [token, isChecking, error, signIn, signOut],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
}
