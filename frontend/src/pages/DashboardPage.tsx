import { ArrowRight, BellRing, CircleAlert, CircleCheck, Clock3, UserRoundPen } from "lucide-react";
import { Link } from "react-router-dom";
import { JobCard } from "../components/jobs/JobCard";
import { PageHeader } from "../components/shared/PageHeader";
import { EmptyState, QueryState } from "../components/shared/QueryState";
import { useMatches, useNotifications, useProfile, useSyncStatus } from "../services/api/hooks";
import type { Profile } from "../types/api";
import { formatTimestamp, groupByJob, sortGroups } from "../utils/format";

/** Profilde eksik olup en çok ilanı "doğrulanmalı" durumunda bırakan bilgiler. */
const PROFILE_HINTS: Record<string, { filled: (profile: Profile) => boolean; label: string }> = {
  "Sürücü belgesi": { filled: (p) => p.driver_license !== null, label: "Sürücü belgesi bilginizi girin" },
  YDS: { filled: (p) => p.yds_score !== null, label: "Yabancı dil puanınızı girin" },
  Deneyim: { filled: (p) => p.experience_years !== null, label: "Mesleki deneyim sürenizi girin" },
  Yaş: { filled: (p) => p.age !== null, label: "Yaşınızı girin" },
  Cinsiyet: { filled: (p) => Boolean(p.gender), label: "Cinsiyet bilginizi girin" },
  Vardiya: { filled: (p) => p.accepts_shifts !== null, label: "Vardiyalı çalışma tercihinizi belirtin" },
};

export default function DashboardPage() {
  const matches = useMatches();
  const profile = useProfile();
  const notifications = useNotifications();
  const sync = useSyncStatus();

  return (
    <QueryState isLoading={matches.isLoading || profile.isLoading} error={matches.error ?? profile.error}>
      {matches.data && profile.data && (() => {
        const active = matches.data.jobs.filter((job) => !job.is_expired && job.tracking !== "hidden");
        const groups = groupByJob(active);
        const suitable = groups.filter((group) => group.category === "UYGUN");
        const potential = groups.filter((group) => group.category === "POTANSİYEL OLARAK UYGUN");
        const closing = sortGroups(
          groups.filter((group) => group.category !== "UYGUN DEĞİL" && group.primary.application_status === "Başvuru Açık"
            && group.primary.days_left !== null && group.primary.days_left <= 7 && group.primary.tracking !== "applied"),
          "deadline",
        );
        const top = sortGroups([...suitable, ...potential], "relevance").slice(0, 6);
        const scores = Object.entries(profile.data.kpss_scores);
        const profileEmpty = !profile.data.department || scores.length === 0;

        const hintCounts = new Map<string, number>();
        for (const group of potential) {
          for (const name of new Set(group.primary.match.requirements.filter((item) => item.status === "unknown").map((item) => item.name))) {
            if (PROFILE_HINTS[name] && !PROFILE_HINTS[name].filled(profile.data)) hintCounts.set(name, (hintCounts.get(name) ?? 0) + 1);
          }
        }
        const hints = [...hintCounts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3);
        const lastSync = sync.data?.finished_at;

        return (
          <>
            <PageHeader
              title={suitable.length ? `Size uygun ${suitable.length} açık ilan var` : "Şu an tam uyan açık ilan yok"}
              description={profileEmpty
                ? "Eşleştirme için önce profilinizi doldurun: bölümünüz ve KPSS puanlarınız yeterli."
                : `${profile.data.degree} · ${profile.data.department} · ${scores.map(([type, score]) => `${type} ${score}`).join(", ")}`}
              action={<Link to="/profile" className="button"><UserRoundPen size={16} /> Profili düzenle</Link>}
            />

            {profileEmpty && (
              <div className="notice notice-warn">
                <CircleAlert size={18} aria-hidden />
                <div><strong>Profiliniz eksik</strong><p>Bölüm ve KPSS puanı olmadan ilanlar yalnızca “doğrulanmalı” olarak görünür.</p></div>
                <Link to="/profile" className="button button-primary">Profili doldur</Link>
              </div>
            )}

            <section className="stat-row" aria-label="Özet sayılar">
              <Link to="/jobs?durum=UYGUN" className="stat stat-ok"><CircleCheck size={18} aria-hidden /><strong>{suitable.length}</strong><span>Uygun ilan</span></Link>
              <Link to="/jobs?durum=POTANS%C4%B0YEL+OLARAK+UYGUN" className="stat stat-warn"><CircleAlert size={18} aria-hidden /><strong>{potential.length}</strong><span>Doğrulanmalı</span></Link>
              <Link to="/calendar" className="stat"><Clock3 size={18} aria-hidden /><strong>{closing.length}</strong><span>7 gün içinde kapanıyor</span></Link>
              <Link to="/notifications" className="stat"><BellRing size={18} aria-hidden /><strong>{notifications.data?.unread ?? 0}</strong><span>Okunmamış bildirim</span></Link>
            </section>

            <div className="dashboard-grid">
              <section>
                <div className="section-head">
                  <h2>Öne çıkan ilanlar</h2>
                  <Link to="/jobs">Tümünü gör <ArrowRight size={15} /></Link>
                </div>
                {top.length ? <div className="job-list">{top.map((group) => <JobCard key={group.jobId} group={group} />)}</div>
                  : <EmptyState title="Gösterilecek ilan yok">Kaynaklar tarandığında profilinize uyan ilanlar burada listelenir.</EmptyState>}
              </section>

              <aside className="side-stack">
                <section className="panel">
                  <h2>Son başvurusu yaklaşanlar</h2>
                  {closing.length ? (
                    <ul className="deadline-list">
                      {closing.slice(0, 6).map((group) => (
                        <li key={group.jobId}>
                          <Link to={`?ilan=${group.jobId}`}>
                            <strong>{group.organization}</strong>
                            <span>{group.primary.days_left === 0 ? "Bugün son gün" : `${group.primary.days_left} gün kaldı`}</span>
                          </Link>
                        </li>
                      ))}
                    </ul>
                  ) : <p className="muted">Önümüzdeki 7 günde kapanan uygun ilan yok.</p>}
                </section>

                {hints.length > 0 && (
                  <section className="panel">
                    <h2>Sonuçları netleştirin</h2>
                    <p className="muted">Profilinizde eksik olan bu bilgiler bazı ilanları “doğrulanmalı” durumunda bırakıyor.</p>
                    <ul className="hint-list">
                      {hints.map(([name, count]) => (
                        <li key={name}><Link to="/profile">{PROFILE_HINTS[name].label}</Link><span>{count} ilan</span></li>
                      ))}
                    </ul>
                  </section>
                )}

                <section className="panel">
                  <h2>Veri durumu</h2>
                  <dl className="fact-list">
                    <div><dt>Taranan açık ilan</dt><dd>{groups.length}</dd></div>
                    <div><dt>Pozisyon</dt><dd>{active.length}</dd></div>
                    <div><dt>Son tarama</dt><dd>{sync.data?.running ? "Sürüyor…" : formatTimestamp(lastSync, "Bu oturumda yapılmadı")}</dd></div>
                  </dl>
                  <Link to="/sources" className="text-link">Kaynakları yönet <ArrowRight size={14} /></Link>
                </section>
              </aside>
            </div>
          </>
        );
      })()}
    </QueryState>
  );
}
