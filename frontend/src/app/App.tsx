import { lazy, Suspense, useState, type FormEvent } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { Compass, LoaderCircle } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "../services/api/auth";
import { AppLayout } from "../components/layout/AppLayout";

const DashboardPage = lazy(() => import("../pages/DashboardPage"));
const JobsPage = lazy(() => import("../pages/JobsPage"));
const ProfilePage = lazy(() => import("../pages/ProfilePage"));
const SourcesPage = lazy(() => import("../pages/SourcesPage"));
const CalendarPage = lazy(() => import("../pages/CalendarPage"));
const NotificationsPage = lazy(() => import("../pages/NotificationsPage"));
const SettingsPage = lazy(() => import("../pages/SettingsPage"));
const YlsyPage = lazy(() => import("../pages/YlsyPage"));
const AccountPage = lazy(() => import("../pages/AccountPage"));

function SignInPage() {
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const { signIn, configError } = useAuth();

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage("");
    setBusy(true);
    try {
      await signIn(password);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Giriş yapılamadı.");
    } finally {
      setBusy(false);
      setPassword("");
    }
  }

  return (
    <main className="signin">
      <section className="signin-intro">
        <span className="brand-mark brand-mark-large"><Compass size={26} aria-hidden /></span>
        <h1>Size uyan kamu ilanını kaçırmayın.</h1>
        <p>CareerPilot TR resmî ilan kaynaklarını tarar, her kadroyu öğrenim durumunuz ve KPSS puanlarınızla karşılaştırır ve başvuru tarihlerini takviminize işler.</p>
      </section>
      <form onSubmit={submit} className="signin-form">
        <h2>Oturum aç</h2>
        {configError && <p className="notice notice-bad" role="alert">{configError}</p>}
        <label className="field">
          <span>Şifre</span>
          <input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required />
        </label>
        {message && <p className="field-error" role="alert">{message}</p>}
        <button className="button button-primary button-wide" disabled={busy}>
          {busy && <LoaderCircle className="spin" size={17} aria-hidden />} Giriş yap
        </button>
      </form>
    </main>
  );
}

export default function App() {
  const { authenticated, isChecking, signOut } = useAuth();
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  if (isChecking) return <div className="page-loading"><LoaderCircle className="spin" aria-hidden /> Oturum kontrol ediliyor…</div>;
  if (!authenticated) return <SignInPage />;

  async function logout() {
    await signOut();
    queryClient.clear();
    navigate("/");
  }

  return (
    <AppLayout onLogout={logout}>
      <Suspense fallback={<div className="page-loading"><LoaderCircle className="spin" aria-hidden /> Yükleniyor…</div>}>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/jobs" element={<JobsPage />} />
          <Route path="/tracked" element={<JobsPage mode="tracked" key="tracked" />} />
          <Route path="/saved" element={<JobsPage mode="saved" key="saved" />} />
          <Route path="/applied" element={<JobsPage mode="applied" key="applied" />} />
          <Route path="/calendar" element={<CalendarPage />} />
          <Route path="/ylsy" element={<YlsyPage />} />
          <Route path="/kariyer-kapisi" element={<AccountPage />} />
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
