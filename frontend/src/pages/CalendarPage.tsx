import { useState } from "react";
import { CalendarViews, type CalendarView } from "../components/calendar/CalendarViews";
import { DeadlineList } from "../components/calendar/DeadlineList";
import { PageHeader } from "../components/shared/PageHeader";

const TABS: Array<["list" | CalendarView, string]> = [
  ["list", "Son başvuru listesi"], ["month", "Ay"], ["week", "Hafta"], ["day", "Gün"], ["agenda", "Ajanda"],
];

export default function CalendarPage() {
  const [tab, setTab] = useState<"list" | CalendarView>("list");
  return (
    <>
      <PageHeader title="Başvuru takvimi" description="Son başvuru günleri, sınav ve sonuç tarihleri ile kişisel görevleriniz." />
      <div className="tabs" role="tablist" aria-label="Takvim görünümü">
        {TABS.map(([key, label]) => (
          <button key={key} role="tab" aria-selected={tab === key} className={tab === key ? "tab tab-active" : "tab"} onClick={() => setTab(key)}>{label}</button>
        ))}
      </div>
      {tab === "list" ? <DeadlineList /> : <CalendarViews key={tab} view={tab} />}
    </>
  );
}
