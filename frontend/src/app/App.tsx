import { lazy, Suspense, useState, type FormEvent } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { Compass, LoaderCircle } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../services/api/client";
import { useAuth } from "../services/api/auth";
import { AppLayout } from "../components/layout/AppLayout";

const DashboardPage = lazy(() => import("../pages/DashboardPage"));
const JobsPage = lazy(() => import("../pages/JobsPage"));
const ProfilePage = lazy(() => import("../pages/ProfilePage"));
const SourcesPage = lazy(() => import("../pages/SourcesPage"));
const CalendarPage = lazy(() => import("../pages/CalendarPage"));
const NotificationsPage = lazy(() => import("../pages/NotificationsPage"));
const SettingsPage = lazy(() => import("../pages/SettingsPage"));

function SignInPage() {
  const [accessKey, setAccessKey] = useState("");
  const [remember, setRemember] = useState(false);
  const [message, setMessage] = useState("");
  const { signIn, isChecking } = useAuth();

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage("");
    try {
      await signIn(accessKey.trim(), remember);
    } catch (error) {
      setMessage(
        error instanceof ApiError && error.status === 401 ? "Erişim anahtarı doğrulanamadı."
          : error instanceof ApiError ? error.message
          : "Sunucuya ulaşılamadı. API'nin çalıştığını kontrol edin.",
      );
    }
  }

  return (
    <main className="signin">
      <section className="signin-intro">
        <span className="brand-mark brand-mark-large"><Compass size={26} aria-hidden /></span>
        <h1>Size uyan kamu ilanını kaçırmayın.</h1>
        <p>CareerPilot TR resmî ilan kaynaklarını tarar, her ilanı öğrenim durumunuz ve KPSS puanlarınızla karşılaştırır ve uygun olanları size bildirir.</p>
      </section>
      <form onSubmit={submit} className="signin-form">
        <h2>Oturum aç</h2>
        <label className="field">
          <span>Erişim anahtarı</span>
          <input id="access-key" type="password" autoComplete="current-password" value={accessKey} onChange={(event) => setAccessKey(event.target.value)} required />
          <small>Sunucudaki CAREERPILOT_ACCESS_TOKEN değeri.</small>
        </label>
        <label className="check-field"><input type="checkbox" checked={remember} onChange={(event) => setRemember(event.target.checked)} /> Bu cihazda oturumu açık tut</label>
        {message && <p className="field-error" role="alert">{message}</p>}
        <button className="button button-primary button-wide" disabled={isChecking}>
          {isChecking && <LoaderCircle className="spin" size={17} aria-hidden />} Giriş yap
        </button>
      </form>
    </main>
  );
}

export default function App() {
  const { token, isChecking, signOut } = useAuth();
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  if (!token) {
    return isChecking ? <div className="page-loading"><LoaderCircle className="spin" aria-hidden /> Oturum doğrulanıyor…</div> : <SignInPage />;
  }

  function logout() {
    queryClient.clear();
    signOut();
    navigate("/");
  }

  return (
    <AppLayout onLogout={logout}>
      <Suspense fallback={<div className="page-loading"><LoaderCircle className="spin" aria-hidden /> Yükleniyor…</div>}>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/jobs" element={<JobsPage />} />
          <Route path="/tracked" element={<JobsPage tracked key="tracked" />} />
          <Route path="/calendar" element={<CalendarPage />} />
          <Route path="/notifications" element={<NotificationsPage />} />
          <Route path="/sources" element={<SourcesPage />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="/settings" element={<SettingsPage onLogout={logout} />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </AppLayout>
  );
}
