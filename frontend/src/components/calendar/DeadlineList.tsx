import { useMemo } from "react";
import { useOpenJob } from "../jobs/JobCard";
import { CategoryBadge } from "../shared/Badges";
import { EmptyState, QueryState } from "../shared/QueryState";
import { useMatches } from "../../services/api/hooks";
import { groupByJob, type JobGroup } from "../../utils/format";
import type { CalendarFilter } from "./filters";

const monthFormat = new Intl.DateTimeFormat("tr-TR", { month: "long", year: "numeric" });
const dayFormat = new Intl.DateTimeFormat("tr-TR", { day: "numeric", weekday: "short" });

/** Son başvuru günleri listesi (önceki "Başvuru takvimi" görünümü, değiştirilmeden). */
export function DeadlineList({ includeAll, hiddenFilters }: { includeAll: boolean; hiddenFilters: CalendarFilter[] }) {
  const query = useMatches();
  const open = useOpenJob();

  const months = useMemo(() => {
    const groups = groupByJob((query.data?.jobs ?? []).filter((job) => !job.is_expired && job.tracking !== "hidden"))
      .filter(() => !hiddenFilters.includes("application"))
      .filter((group) => group.primary.application_deadline && (includeAll || group.category !== "UYGUN DEĞİL"))
      .sort((a, b) => a.primary.application_deadline!.localeCompare(b.primary.application_deadline!));
    const byMonth = new Map<string, JobGroup[]>();
    for (const group of groups) {
      const key = group.primary.application_deadline!.slice(0, 7);
      byMonth.set(key, [...(byMonth.get(key) ?? []), group]);
    }
    return [...byMonth.entries()];
  }, [query.data, includeAll, hiddenFilters]);

  return (
    <QueryState isLoading={query.isLoading} error={query.error}>
      <div className="list-toolbar">
        <p className="muted">İlanlar son başvuru tarihine göre sıralanır; en yakın tarih en üstte.</p>
      </div>
      {months.length ? months.map(([month, groups]) => (
        <section key={month} className="calendar-month">
          <h2>{monthFormat.format(new Date(`${month}-01T00:00:00`))}</h2>
          <ol className="calendar-list">
            {groups.map((group) => {
              const job = group.primary;
              const urgent = job.application_status === "Başvuru Açık" && job.days_left !== null && job.days_left <= 3;
              return (
                <li key={group.jobId}>
                  <button className="calendar-row" onClick={() => open(group.jobId)}>
                    <span className={`calendar-day ${urgent ? "calendar-day-urgent" : ""}`}>{dayFormat.format(new Date(`${job.application_deadline}T00:00:00`))}</span>
                    <span className="calendar-main">
                      <strong>{group.organization}</strong>
                      <span>{group.positions.length > 1 ? group.title : job.position}</span>
                    </span>
                    <span className="calendar-status">
                      {job.application_status === "Başvuru Başlamadı" ? "Henüz açılmadı" : job.days_left === 0 ? "Bugün son gün" : `${job.days_left} gün kaldı`}
                    </span>
                    <CategoryBadge category={group.category} />
                  </button>
                </li>
              );
            })}
          </ol>
        </section>
      )) : <EmptyState title="Takvimde ilan yok">Son başvuru tarihi belli olan uygun ilan bulunmuyor.</EmptyState>}
    </QueryState>
  );
}
