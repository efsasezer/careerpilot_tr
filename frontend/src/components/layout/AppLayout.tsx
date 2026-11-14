import {
  CalendarDays,
  CircleHelp,
  ClipboardCheck,
  Compass,
  FileUser,
  GraduationCap,
  LayoutDashboard,
  LogOut,
  Menu,
  Radio,
  Search,
  ShieldCheck,
  X,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useHealth } from "../../services/api/hooks";

const navigation = [
  { to: "/", label: "Genel Bakış", icon: LayoutDashboard, end: true },
  { to: "/jobs", label: "Kamu İlanları", icon: Search },
  { to: "/matches", label: "Uygunluk Analizi", icon: ClipboardCheck },
  { to: "/calendar", label: "Başvuru Takvimi", icon: CalendarDays },
  { to: "/opportunities", label: "Eğitim & Fırsatlar", icon: GraduationCap },
  { to: "/sources", label: "Veri Kaynakları", icon: Radio },
  { to: "/profile", label: "Aday Profili", icon: FileUser },
];

export function AppLayout({
  children,
  onLogout,
}: {
  children: ReactNode;
  onLogout: () => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const health = useHealth();
  const readOnly = health.data?.demo_mode !== false;

  return (
    <div className="app-shell">
      {menuOpen && <button className="mobile-backdrop" aria-label="Menüyü kapat" onClick={() => setMenuOpen(false)} />}
      <aside className={`sidebar ${menuOpen ? "sidebar-open" : ""}`}>
        <div className="sidebar-brand">
          <div className="brand-mark"><Compass size={21} /></div>
          <div><strong>CareerPilot <span>TR</span></strong><small>Kamu kariyer platformu</small></div>
          <button className="icon-button mobile-close" onClick={() => setMenuOpen(false)} aria-label="Menüyü kapat"><X size={19} /></button>
        </div>
        <div className="sidebar-label">ÇALIŞMA ALANI</div>
        <nav className="main-nav" aria-label="Ana navigasyon">
          {navigation.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              onClick={() => setMenuOpen(false)}
              className={({ isActive }) => `nav-link ${isActive ? "nav-link-active" : ""}`}
            >
              <Icon size={18} strokeWidth={1.8} /><span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="security-card">
            <ShieldCheck size={17} />
            <span><strong>Özel oturum</strong><small>{readOnly ? "Salt okunur erişim" : "Profil düzenlenebilir"}</small></span>
          </div>
          <button className="nav-link nav-logout" onClick={onLogout}><LogOut size={18} /><span>Oturumu kapat</span></button>
          <div className="sidebar-version">CareerPilot TR · API {health.data?.version ?? "…"}</div>
        </div>
      </aside>
      <div className="main-column">
        <header className="topbar">
          <button className="icon-button mobile-menu" onClick={() => setMenuOpen(true)} aria-label="Menüyü aç"><Menu size={21} /></button>
          <div className="topbar-context"><span className="topbar-dot" /> Kişisel kariyer çalışma alanı</div>
          <div className="topbar-right">
            <span className="readonly-pill"><ShieldCheck size={14} /> {readOnly ? "Salt okunur" : "Düzenlenebilir"}</span>
            <NavLink to="/settings" className="icon-button" aria-label="Ayarlar"><CircleHelp size={18} /></NavLink>
          </div>
        </header>
        <main className="content-area">{children}</main>
      </div>
    </div>
  );
}
