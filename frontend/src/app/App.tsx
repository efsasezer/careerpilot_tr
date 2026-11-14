import { lazy, Suspense, useState, type FormEvent } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { Compass, LoaderCircle, LockKeyhole, ShieldCheck } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError, getApiUrl } from "../services/api/client";
import { useAuth } from "../services/api/auth";
import { AppLayout } from "../components/layout/AppLayout";

const DashboardPage = lazy(() => import("../pages/DashboardPage"));
const JobsPage = lazy(() => import("../pages/JobsPage"));
const MatchesPage = lazy(() => import("../pages/MatchesPage"));
const ProfilePage = lazy(() => import("../pages/ProfilePage"));
const SourcesPage = lazy(() => import("../pages/SourcesPage"));
const CalendarPage = lazy(() => import("../pages/CalendarPage"));
const OpportunitiesPage = lazy(() => import("../pages/OpportunitiesPage"));
const SettingsPage = lazy(() => import("../pages/SettingsPage"));

function SignInPage() {
  const [accessKey, setAccessKey] = useState("");
  const [message, setMessage] = useState("");
  const { signIn, isChecking } = useAuth();

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage("");
    try {
      await signIn(accessKey.trim());
    } catch (error) {
      setMessage(
        error instanceof ApiError && error.status === 401
          ? "Erişim anahtarı doğrulanamadı."
          : error instanceof Error
            ? error.message
            : "API bağlantısı kurulamadı.",
      );
    }
  }

  return (
    <main className="signin-shell">
      <section className="signin-card">
        <div className="brand-mark brand-mark-large"><Compass size={25} /></div>
        <p className="eyebrow">KAMU KARİYER PLATFORMU</p>
        <h1>CareerPilot <span>TR</span></h1>
        <p className="signin-copy">
          İlanlar, profil ve kişisel uygunluk analizleri özel erişim anahtarıyla
          korunur. Anahtar tarayıcı oturumunda tutulur; kalıcı olarak kaydedilmez.
        </p>
        <form onSubmit={submit} className="signin-form">
          <label htmlFor="access-key">Özel erişim anahtarı</label>
          <input
            id="access-key"
            autoComplete="current-password"
            type="password"
            value={accessKey}
            onChange={(event) => setAccessKey(event.target.value)}
            placeholder="Erişim anahtarını girin"
            required
          />
          {message && <p className="form-error" role="alert">{message}</p>}
          <button className="button button-primary button-wide" disabled={isChecking}>
            {isChecking ? <LoaderCircle className="spin" size={17} /> : <LockKeyhole size={17} />}
            Güvenli oturum aç
          </button>
        </form>
        <div className="privacy-note"><ShieldCheck size={17} /> Özel erişim anahtarı</div>
        <p className="api-address">API · {getApiUrl()}</p>
      </section>
    </main>
  );
}

function AuthenticatedApp() {
  const { token, signOut } = useAuth();
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  if (!token) return <SignInPage />;

  function logout() {
    queryClient.clear();
    signOut();
    navigate("/");
  }

  return (
    <AppLayout onLogout={logout}>
      <Suspense fallback={<div className="page-loading"><LoaderCircle className="spin" /> Yükleniyor…</div>}>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/jobs" element={<JobsPage />} />
          <Route path="/matches" element={<MatchesPage />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="/sources" element={<SourcesPage />} />
          <Route path="/calendar" element={<CalendarPage />} />
          <Route path="/opportunities" element={<OpportunitiesPage />} />
          <Route path="/settings" element={<SettingsPage onLogout={logout} />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </AppLayout>
  );
}

export default function App() {
  return <AuthenticatedApp />;
}
