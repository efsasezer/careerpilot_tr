import { ArrowUpRight, CalendarClock, CircleCheck, CircleX, Clock3, FileText } from "lucide-react";
import { Link } from "react-router-dom";
import type { ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { PageHeader } from "../components/shared/PageHeader";
import { QueryState } from "../components/shared/QueryState";
import { MatchBadge } from "../components/shared/MatchBadge";
import { useMatches, useProfile, useSources } from "../services/api/hooks";
import { formatDate, formatTimestamp } from "../utils/format";

const COLORS = ["#087f8c", "#e7a83e", "#d66565"];

export default function DashboardPage() {
  const matches = useMatches();
  const profile = useProfile();
  const sources = useSources();
  const loading = matches.isLoading || profile.isLoading || sources.isLoading;
  const error = matches.error ?? profile.error ?? sources.error;

  return (
    <QueryState isLoading={loading} error={error}>
      {matches.data && profile.data && sources.data && (() => {
        const data = matches.data;
        const recent = [...data.jobs].sort((a, b) => (b.parent_job_id - a.parent_job_id)).slice(0, 5);
        const upcoming = data.jobs
          .filter((job) => job.application_status === "Başvuru Açık" || job.application_status === "Başvuru Başlamadı")
          .filter((job) => job.application_deadline)
          .sort((a, b) => (a.application_deadline || "").localeCompare(b.application_deadline || ""))
          .slice(0, 5);
        const matchChart = [
          { name: "Uygun", value: data.counts.UYGUN },
          { name: "Potansiyel", value: data.counts["POTANSİYEL OLARAK UYGUN"] },
          { name: "Uygun değil", value: data.counts["UYGUN DEĞİL"] },
        ];
        const sourceChart = sources.data.map((source) => ({ name: source.name.replace(" Kamu İlanları", ""), ilan: source.job_count }));
        const statusChart = [
          { name: "Başvuru açık", count: data.jobs.filter((job) => job.application_status === "Başvuru Açık").length },
          { name: "Başlamadı", count: data.jobs.filter((job) => job.application_status === "Başvuru Başlamadı").length },
          { name: "Sona erdi", count: data.jobs.filter((job) => job.application_status === "Başvuru Sona Erdi").length },
        ];
        return (
          <>
            <PageHeader eyebrow="ÇALIŞMA ALANI / GENEL BAKIŞ" title="Kariyer gündemin" description={`${profile.data.department || "Aday profili"} · Son veri güncellemesi ${formatTimestamp(profile.data.updated_at)}`} />
            <section className="metric-grid">
              <Metric icon={<FileText />} label="Kamu ilanı" value={data.counts.total} tone="ink" />
              <Metric icon={<CalendarClock />} label="Başvuru açık" value={statusChart[0].count} tone="teal" />
              <Metric icon={<CircleCheck />} label="Uygun" value={data.counts.UYGUN} tone="green" />
              <Metric icon={<Clock3 />} label="Potansiyel" value={data.counts["POTANSİYEL OLARAK UYGUN"]} tone="amber" />
              <Metric icon={<CircleX />} label="Uygun değil" value={data.counts["UYGUN DEĞİL"]} tone="red" />
            </section>
            <section className="chart-grid">
              <div className="panel chart-panel">
                <PanelTitle title="Uygunluk dağılımı" caption="Mevcut profil ve API analiz motoru" />
                <div className="chart-wrap">
                  <ResponsiveContainer width="100%" height={230}>
                    <PieChart><Pie data={matchChart} dataKey="value" nameKey="name" innerRadius={58} outerRadius={88} paddingAngle={3}>{matchChart.map((entry, index) => <Cell key={entry.name} fill={COLORS[index]} />)}</Pie><Tooltip /></PieChart>
                  </ResponsiveContainer>
                  <div className="chart-legend">{matchChart.map((item, index) => <div key={item.name}><i style={{ background: COLORS[index] }} />{item.name}<strong>{item.value}</strong></div>)}</div>
                </div>
              </div>
              <div className="panel chart-panel">
                <PanelTitle title="Başvuru durumu" caption="İlan pozisyonlarının güncel tarih sınıfları" />
                <ResponsiveContainer width="100%" height={250}>
                  <BarChart data={statusChart} margin={{ top: 16, right: 4, left: -20, bottom: 4 }}><CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#edf1f5" /><XAxis dataKey="name" tick={{ fontSize: 11 }} axisLine={false} tickLine={false} /><YAxis allowDecimals={false} tick={{ fontSize: 11 }} axisLine={false} tickLine={false} /><Tooltip /><Bar dataKey="count" name="İlan" fill="#087f8c" radius={[5, 5, 0, 0]} /></BarChart>
                </ResponsiveContainer>
              </div>
              <div className="panel chart-panel chart-wide">
                <PanelTitle title="Kaynaklara göre kayıtlı ilanlar" caption="Kaynak durum uç noktasından gelen gerçek sayılar" />
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={sourceChart} margin={{ top: 8, right: 12, left: -20, bottom: 4 }}><CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#edf1f5" /><XAxis dataKey="name" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} /><YAxis allowDecimals={false} tick={{ fontSize: 11 }} axisLine={false} tickLine={false} /><Tooltip /><Bar dataKey="ilan" name="İlan" fill="#173f5f" radius={[5, 5, 0, 0]} /></BarChart>
                </ResponsiveContainer>
              </div>
            </section>
            <section className="dashboard-lower">
              <div className="panel">
                <PanelTitle title="Son eklenen ilanlar" link="/jobs" linkLabel="Tüm ilanlar" />
                <div className="compact-list">{recent.map((job) => <Link className="compact-row" to="/jobs" key={job.id}><span className="compact-icon"><FileText size={16} /></span><span className="compact-main"><strong>{job.position}</strong><small>{job.organization} · {job.source_name}</small></span><MatchBadge category={job.match.category} /><ArrowUpRight size={16} className="row-arrow" /></Link>)}</div>
              </div>
              <div className="panel">
                <PanelTitle title="Yaklaşan başvurular" link="/calendar" linkLabel="Takvime git" />
                {upcoming.length ? <div className="compact-list">{upcoming.map((job) => <Link className="deadline-row" to="/calendar" key={job.id}><span className="deadline-date">{formatDate(job.application_deadline)}</span><span><strong>{job.position}</strong><small>{job.organization}</small></span></Link>)}</div> : <p className="empty-note">Tarihi yaklaşan ilan bulunmuyor.</p>}
              </div>
            </section>
            <section className="profile-strip">
              <div><span className="eyebrow">PROFİL ÖZETİ</span><strong>{profile.data.degree} · {profile.data.department}</strong><small>{profile.data.university}</small></div>
              <div className="profile-score"><small>KPSS {profile.data.kpss_score_type}</small><strong>{profile.data.kpss_p3?.toFixed(2) ?? "—"}</strong></div>
              <Link to="/profile" className="button button-outline">Profili görüntüle <ArrowUpRight size={15} /></Link>
            </section>
          </>
        );
      })()}
    </QueryState>
  );
}

function Metric({ icon, label, value, tone }: { icon: ReactNode; label: string; value: number; tone: string }) {
  return <div className={`metric-card metric-${tone}`}><span className="metric-icon">{icon}</span><span className="metric-label">{label}</span><strong>{value.toLocaleString("tr-TR")}</strong></div>;
}

function PanelTitle({ title, caption, link, linkLabel }: { title: string; caption?: string; link?: string; linkLabel?: string }) {
  return <div className="panel-title"><div><h2>{title}</h2>{caption && <p>{caption}</p>}</div>{link && <Link to={link}>{linkLabel} <ArrowUpRight size={14} /></Link>}</div>;
}
