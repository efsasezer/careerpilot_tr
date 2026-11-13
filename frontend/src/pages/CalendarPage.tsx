import { useMemo, useState } from "react";
import { CalendarDays, List } from "lucide-react";
import { PageHeader } from "../components/shared/PageHeader";
import { QueryState } from "../components/shared/QueryState";
import { MatchBadge } from "../components/shared/MatchBadge";
import { useMatches } from "../services/api/hooks";
import type { MatchedJob } from "../types/api";
import { formatDate } from "../utils/format";

export default function CalendarPage() {
  const query = useMatches();
  const [mode, setMode] = useState<"list" | "month">("list");
  const [month, setMonth] = useState(new Date().toISOString().slice(0, 7));
  const jobs = useMemo(() => (query.data?.jobs ?? [])
    .filter((job) => job.application_start || job.application_deadline)
    .sort((a, b) => (a.application_deadline || a.application_start || "").localeCompare(b.application_deadline || b.application_start || "")), [query.data]);
  const selectedMonth = jobs.filter((job) => (job.application_deadline || job.application_start || "").startsWith(month));

  return (
    <QueryState isLoading={query.isLoading} error={query.error}>
      <PageHeader eyebrow="BAŞVURU TAKİBİ" title="Başvuru takvimi" description="Başlangıç ve son başvuru tarihleri bulunan pozisyonları takip edin." />
      <div className="calendar-toolbar"><div className="view-toggle"><button className={mode === "list" ? "selected" : ""} onClick={() => setMode("list")}><List size={16} /> Liste</button><button className={mode === "month" ? "selected" : ""} onClick={() => setMode("month")}><CalendarDays size={16} /> Ay görünümü</button></div>{mode === "month" && <input aria-label="Takvim ayı" type="month" value={month} onChange={(event) => setMonth(event.target.value)} />}</div>
      {mode === "list" ? <div className="panel table-panel"><div className="table-scroll"><table><thead><tr><th>İlan / kurum</th><th>Durum</th><th>Başlangıç</th><th>Son başvuru</th><th>Uygunluk</th></tr></thead><tbody>{jobs.map((job) => <CalendarRow key={job.id} job={job} />)}</tbody></table></div>{!jobs.length && <p className="empty-note">Tarihli ilan bulunmuyor.</p>}</div> : <div className="calendar-list">{selectedMonth.map((job) => <CalendarEvent key={job.id} job={job} />)}{!selectedMonth.length && <div className="panel empty-state"><strong>Bu ay için başvuru tarihi yok</strong></div>}</div>}
      <div className="calendar-summary"><CalendarDays size={17} /> Tarihli {jobs.length} pozisyon · açık {jobs.filter((job) => job.application_status === "Başvuru Açık").length} · başlayacak {jobs.filter((job) => job.application_status === "Başvuru Başlamadı").length} · sona eren {jobs.filter((job) => job.application_status === "Başvuru Sona Erdi").length}</div>
    </QueryState>
  );
}

function CalendarRow({ job }: { job: MatchedJob }) {
  return <tr><td><strong>{job.position}</strong><small>{job.organization}</small></td><td>{job.application_status}</td><td>{formatDate(job.application_start)}</td><td>{formatDate(job.application_deadline)}</td><td><MatchBadge category={job.match.category} /></td></tr>;
}

function CalendarEvent({ job }: { job: MatchedJob }) {
  return <article className="panel calendar-event"><div className="calendar-event-date"><strong>{(job.application_deadline || job.application_start || "").slice(8, 10)}</strong><small>{formatDate(job.application_deadline || job.application_start).split(" ").slice(1).join(" ")}</small></div><div className="calendar-event-main"><span className="eyebrow">{job.organization}</span><h3>{job.position}</h3><p>{job.application_status} · Son başvuru {formatDate(job.application_deadline)}</p></div><MatchBadge category={job.match.category} /></article>;
}
