import { useState } from "react";
import { CalendarViews, type CalendarView } from "../components/calendar/CalendarViews";
import { DeadlineList } from "../components/calendar/DeadlineList";
import { UpcomingList } from "../components/calendar/UpcomingList";
import { CALENDAR_FILTERS, type CalendarFilter } from "../components/calendar/filters";
import { PageHeader } from "../components/shared/PageHeader";

type CalendarTab = "upcoming" | "list" | CalendarView;
const TABS: Array<[CalendarTab, string]> = [
  ["upcoming", "Yaklaşanlar"], ["list", "Son başvuru"], ["month", "Ay"], ["week", "Hafta"], ["day", "Gün"], ["agenda", "Ajanda"],
];

export default function CalendarPage() {
  const [tab, setTab] = useState<CalendarTab>("upcoming");
  const [includeAll, setIncludeAll] = useState(false);
  const [hiddenFilters, setHiddenFilters] = useState<CalendarFilter[]>([]);
  return (
    <>
      <PageHeader title="Başvuru takvimi" description="İlanların başvuru başlangıç ve son günleri, sınavlar ve kişisel görevler." />
      <div className="tabs" role="tablist" aria-label="Takvim görünümü">
        {TABS.map(([key, label]) => (
          <button key={key} role="tab" aria-selected={tab === key} className={tab === key ? "tab tab-active" : "tab"} onClick={() => setTab(key)}>{label}</button>
        ))}
      </div>
      <details className="calendar-filter-panel">
        <summary>Görünüm filtreleri</summary>
        <div className="calendar-filter-options">
          <label className="check-field">
            <input type="checkbox" checked={includeAll} onChange={(event) => setIncludeAll(event.target.checked)} />
            Uygun olmayan ilanları da göster
          </label>
          {CALENDAR_FILTERS.map(([key, label]) => (
            <label key={key} className="check-field">
              <input type="checkbox" checked={!hiddenFilters.includes(key)}
                onChange={(event) => setHiddenFilters(event.target.checked ? hiddenFilters.filter((item) => item !== key) : [...hiddenFilters, key])} />
              {label}
            </label>
          ))}
        </div>
      </details>
      {tab === "upcoming" ? <UpcomingList includeAll={includeAll} hiddenFilters={hiddenFilters} />
        : tab === "list" ? <DeadlineList includeAll={includeAll} hiddenFilters={hiddenFilters} />
        : <CalendarViews view={tab} includeAll={includeAll} hiddenFilters={hiddenFilters} />}
    </>
  );
}
