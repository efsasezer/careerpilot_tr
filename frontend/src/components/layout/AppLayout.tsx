import { Bell, Bookmark, BookmarkCheck, CalendarDays, Compass, LayoutDashboard, ListChecks, LogOut, Menu, Radio, RefreshCw, SendHorizontal, Settings, UserRound, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { JobDrawer } from "../jobs/JobDrawer";
import { useMatches, useNotifications, useSyncStatus } from "../../services/api/hooks";

const navigation = [
  { to: "/", label: "Özet", icon: LayoutDashboard, end: true },
  { to: "/jobs", label: "İlanlar", icon: ListChecks },
  { to: "/tracked", label: "Takip listem", icon: Bookmark },
  { to: "/saved", label: "Kaydettiklerim", icon: BookmarkCheck },
  { to: "/applied", label: "Başvurduklarım", icon: SendHorizontal },
  { to: "/calendar", label: "Başvuru takvimi", icon: CalendarDays },
  { to: "/notifications", label: "Bildirimler", icon: Bell },
  { to: "/sources", label: "Kaynaklar", icon: Radio },
  { to: "/profile", label: "Profilim", icon: UserRound },
  { to: "/settings", label: "Ayarlar", icon: Settings },
];

export function AppLayout({ children, onLogout }: { children: ReactNode; onLogout: () => void }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const matches = useMatches();
  const counts = { "/saved": new Set<number>(), "/applied": new Set<number>() };
  for (const job of matches.data?.jobs ?? []) {
    if (job.tracking === "saved") counts["/saved"].add(job.parent_job_id);
    if (["applied", "awaiting", "won", "lost"].includes(job.tracking)) counts["/applied"].add(job.parent_job_id);
  }
  const notifications = useNotifications();
  const sync = useSyncStatus();
  const queryClient = useQueryClient();
  const unread = notifications.data?.unread ?? 0;
  const running = sync.data?.running ?? false;

  // Tarama bittiğinde listeleri yenile.
  const wasRunning = useRef(false);
  useEffect(() => {
    if (wasRunning.current && !running) {
      for (const key of ["matches", "sources", "notifications"]) queryClient.invalidateQueries({ queryKey: [key] });
    }
    wasRunning.current = running;
  }, [running, queryClient]);

  // Yeni bildirim geldiğinde (izin verildiyse) tarayıcı bildirimi göster.
  const lastUnread = useRef<number | null>(null);
  useEffect(() => {
    if (notifications.data === undefined) return;
    const previous = lastUnread.current;
    lastUnread.current = unread;
    if (previous !== null && unread > previous && "Notification" in window && Notification.permission === "granted") {
      const latest = notifications.data.items.find((item) => !item.read);
      new Notification(latest?.title ?? "CareerPilot TR", { body: latest?.body ?? `${unread - previous} yeni bildirim` });
    }
  }, [unread, notifications.data]);

  return (
    <div className="app-shell">
      {menuOpen && <button className="mobile-backdrop" aria-label="Menüyü kapat" onClick={() => setMenuOpen(false)} />}
      <aside className={`sidebar ${menuOpen ? "sidebar-open" : ""}`}>
        <div className="brand">
          <span className="brand-mark"><Compass size={20} aria-hidden /></span>
          <span><strong>CareerPilot TR</strong><small>Kamu ilan takibi</small></span>
          <button className="icon-button mobile-only" onClick={() => setMenuOpen(false)} aria-label="Menüyü kapat"><X size={19} /></button>
        </div>
        <nav aria-label="Ana menü">
          {navigation.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} onClick={() => setMenuOpen(false)} className={({ isActive }) => `nav-link ${isActive ? "nav-link-active" : ""}`}>
              <Icon size={18} strokeWidth={1.8} aria-hidden />
              <span>{label}</span>
              {to === "/notifications" && unread > 0 && <span className="nav-count">{unread > 99 ? "99+" : unread}</span>}
              {(to === "/saved" || to === "/applied") && counts[to].size > 0 && <span className="nav-count nav-count-soft">{counts[to].size}</span>}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <button className="nav-link" onClick={onLogout}><LogOut size={18} strokeWidth={1.8} aria-hidden /><span>Oturumu kapat</span></button>
        </div>
      </aside>
      <div className="main-column">
        <header className="topbar">
          <button className="icon-button mobile-only" onClick={() => setMenuOpen(true)} aria-label="Menüyü aç"><Menu size={21} /></button>
          {running && (
            <span className="sync-pill" role="status">
              <RefreshCw size={14} className="spin" aria-hidden />
              {sync.data?.progress?.source ?? "Kaynaklar"} taranıyor
              {sync.data?.progress?.total ? ` · ${sync.data.progress.current}/${sync.data.progress.total}` : ""}
            </span>
          )}
          <NavLink to="/notifications" className="icon-button bell" aria-label={`Bildirimler${unread ? `, ${unread} okunmamış` : ""}`}>
            <Bell size={19} />
            {unread > 0 && <span className="bell-dot" />}
          </NavLink>
        </header>
        <main className="content">{children}</main>
      </div>
      <JobDrawer />
    </div>
  );
}
