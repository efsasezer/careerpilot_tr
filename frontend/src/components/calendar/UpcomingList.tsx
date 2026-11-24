import { useMemo } from "react";
import { BriefcaseBusiness, Check, Clock3 } from "lucide-react";
import { useOpenJob } from "../jobs/JobCard";
import { EmptyState, QueryState } from "../shared/QueryState";
import { useCalendar, useCompleteTask } from "../../services/api/hooks";
import type { CalendarEvent } from "../../types/api";
import { addDays, formatLongDate, todayIso } from "../../utils/format";
import { EVENT_FILTER_GROUP, type CalendarFilter } from "./filters";

const DATE_FORMAT = new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "short" });

function daysFromToday(day: string, today: string) {
  return Math.round((Date.parse(`${day}T12:00:00Z`) - Date.parse(`${today}T12:00:00Z`)) / 86_400_000);
}

function timingLabel(event: CalendarEvent, days: number) {
  if (event.kind === "application_start") return days === 0 ? "Başvurular bugün açılıyor" : `Başvurular ${days} gün sonra açılıyor`;
  if (event.kind === "application_deadline") return days === 0 ? "Bugün son başvuru günü" : days === 1 ? "Yarın son başvuru günü" : `Son başvuruya ${days} gün kaldı`;
  return days === 0 ? "Bugün" : days === 1 ? "Yarın" : `${days} gün sonra`;
}

export function UpcomingList({ includeAll, hiddenFilters }: { includeAll: boolean; hiddenFilters: CalendarFilter[] }) {
  const today = todayIso();
  const end = addDays(today, 60);
  const query = useCalendar(today, end);
  const openJob = useOpenJob();
  const complete = useCompleteTask();
  const days = useMemo(() => {
    const grouped = new Map<string, { events: CalendarEvent[]; tasks: NonNullable<typeof query.data>["tasks"] }>();
    for (const event of query.data?.events ?? []) {
      if (!includeAll && event.category === "UYGUN DEĞİL") continue;
      const filter = EVENT_FILTER_GROUP[event.kind];
      if (filter && hiddenFilters.includes(filter)) continue;
      const row = grouped.get(event.date) ?? { events: [], tasks: [] };
      row.events.push(event);
      grouped.set(event.date, row);
    }
    for (const task of query.data?.tasks ?? []) {
      if (hiddenFilters.includes("task")) continue;
      const row = grouped.get(task.date) ?? { events: [], tasks: [] };
      row.tasks.push(task);
      grouped.set(task.date, row);
    }
    return [...grouped.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [query.data, includeAll, hiddenFilters]);

  return (
    <div className="upcoming-view">
      <div className="upcoming-intro">
        <div><strong>Önümüzdeki 60 gün</strong><span>İlan tarihleri otomatik eklenir. Kişisel görevler ayrı gösterilir.</span></div>
        <Clock3 size={20} aria-hidden />
      </div>
      <QueryState isLoading={query.isLoading} error={query.error}>
        {days.length ? (
          <div className="upcoming-list">
            {days.map(([day, items]) => (
              <section className="upcoming-day" key={day}>
                <div className="upcoming-date"><strong>{DATE_FORMAT.format(new Date(`${day}T12:00:00Z`))}</strong><span>{formatLongDate(day).split(",")[0]}</span></div>
                <div className="upcoming-items">
                  {items.events.map((event) => {
                    const remaining = daysFromToday(event.date, today);
                    return (
                      <article className={`upcoming-card upcoming-${event.kind}`} key={`e${event.id}`}>
                        <span className="upcoming-mark"><BriefcaseBusiness size={17} aria-hidden /></span>
                        <div className="upcoming-copy">
                          <span className="upcoming-label">{event.label} · {timingLabel(event, remaining)}</span>
                          <strong>{event.organization}</strong>
                          <span>{event.job_title}</span>
                          {event.time && <span className="upcoming-time">Saat {event.time}</span>}
                        </div>
                        {event.job_id !== null && <button className="button button-small" onClick={() => openJob(event.job_id as number)}>İlanı gör</button>}
                      </article>
                    );
                  })}
                  {items.tasks.map((task) => (
                    <article className={`upcoming-card upcoming-task ${task.done ? "upcoming-done" : ""}`} key={`t${task.task_id}`}>
                      <span className="upcoming-mark"><Check size={17} aria-hidden /></span>
                      <div className="upcoming-copy"><span className="upcoming-label">Kişisel görev{task.start_time ? ` · ${task.start_time}` : ""}</span><strong>{task.title}</strong>{task.description && <span>{task.description}</span>}</div>
                      <label className="upcoming-complete"><input type="checkbox" checked={task.done} onChange={(event) => complete.mutate({ id: task.task_id, day, done: event.target.checked })} /><span>{task.done ? "Tamamlandı" : "Tamamlandı işaretle"}</span></label>
                    </article>
                  ))}
                </div>
              </section>
            ))}
          </div>
        ) : <EmptyState title="Yaklaşan tarih yok">Resmî ilan tarihleri tarama sırasında otomatik eklenir.</EmptyState>}
      </QueryState>
    </div>
  );
}
