import { useMemo, useState, type FormEvent } from "react";
import { ArrowRightToLine, ChevronLeft, ChevronRight, Download, ExternalLink, Pencil, Plus, Trash2 } from "lucide-react";
import { useOpenJob } from "../jobs/JobCard";
import { QueryState } from "../shared/QueryState";
import { apiRequest } from "../../services/api/client";
import { useCalendar, useCompleteTask, useDeleteEvent, useDeleteTask, useEditEvent, useSaveTask, useTasks } from "../../services/api/hooks";
import type { CalendarData, CalendarEvent, TaskInput, TaskOccurrence } from "../../types/api";
import { addDays, formatLongDate, startOfWeek, todayIso, weekdayIndex } from "../../utils/format";
import { buildIcs } from "../../utils/ics";

export type CalendarView = "month" | "week" | "day" | "agenda";
const WEEKDAYS = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"];
const KIND_GROUPS: Array<[string, string, string[]]> = [
  ["application", "Başvuru", ["application_start", "application_deadline"]],
  ["exam", "Sınav / mülakat", ["exam", "interview"]],
  ["result", "Sonuç", ["result"]],
  ["documents", "Evrak / atama", ["documents", "appointment"]],
  ["task", "Görevlerim", ["task"]],
];
const monthTitle = new Intl.DateTimeFormat("tr-TR", { month: "long", year: "numeric", timeZone: "UTC" });
const shortDay = new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "short", weekday: "short", timeZone: "UTC" });
const asDate = (iso: string) => new Date(`${iso}T12:00:00Z`);

function range(view: CalendarView, cursor: string): [string, string] {
  if (view === "day") return [cursor, cursor];
  if (view === "week") return [startOfWeek(cursor), addDays(startOfWeek(cursor), 6)];
  if (view === "agenda") return [cursor, addDays(cursor, 60)];
  const first = `${cursor.slice(0, 7)}-01`;
  const start = startOfWeek(first);
  return [start, addDays(start, 41)];
}

function eventsOn(data: CalendarData | undefined, day: string, hidden: Set<string>) {
  const events = (data?.events ?? []).filter((event) => event.date <= day && (event.end_date ?? event.date) >= day && !hidden.has(event.kind));
  const tasks = hidden.has("task") ? [] : (data?.tasks ?? []).filter((task) => task.date === day);
  return { events, tasks };
}

export function CalendarViews({ view }: { view: CalendarView }) {
  const today = todayIso();
  const [cursor, setCursor] = useState(today);
  const [selectedDay, setSelectedDay] = useState<string | null>(null);
  const [hiddenGroups, setHiddenGroups] = useState<string[]>([]);
  const [taskForm, setTaskForm] = useState<{ id?: number; date: string } | null>(null);
  const [start, end] = range(view, cursor);
  const query = useCalendar(start, end);
  const hidden = useMemo(() => new Set(KIND_GROUPS.filter(([key]) => hiddenGroups.includes(key)).flatMap(([, , kinds]) => kinds)), [hiddenGroups]);
  const step = view === "month" ? 0 : view === "week" ? 7 : view === "day" ? 1 : 30;

  function move(direction: 1 | -1) {
    if (view === "month") {
      const date = asDate(`${cursor.slice(0, 7)}-15`);
      date.setUTCMonth(date.getUTCMonth() + direction);
      setCursor(`${date.toISOString().slice(0, 7)}-01`);
    } else setCursor(addDays(cursor, direction * step));
  }

  async function exportIcs() {
    const data = await apiRequest<CalendarData>(`/calendar?start=${addDays(today, -30)}&end=${addDays(today, 365)}`);
    const url = URL.createObjectURL(new Blob([buildIcs(data)], { type: "text/calendar;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "careerpilot-takvim.ics";
    link.click();
    URL.revokeObjectURL(url);
  }

  const title = view === "month" ? monthTitle.format(asDate(`${cursor.slice(0, 7)}-15`))
    : view === "day" ? formatLongDate(cursor)
    : `${shortDay.format(asDate(start))} – ${shortDay.format(asDate(end))}`;
  const days = view === "month" ? Array.from({ length: 42 }, (_, i) => addDays(start, i))
    : view === "week" ? Array.from({ length: 7 }, (_, i) => addDays(start, i)) : [];
  const detailDay = view === "day" ? cursor : selectedDay;

  return (
    <div className="calendar">
      <div className="calendar-toolbar">
        <div className="calendar-nav">
          <button className="button button-small" onClick={() => { setCursor(today); setSelectedDay(today); }}>Bugün</button>
          <button className="icon-button" aria-label="Önceki" onClick={() => move(-1)}><ChevronLeft size={18} /></button>
          <button className="icon-button" aria-label="Sonraki" onClick={() => move(1)}><ChevronRight size={18} /></button>
          <strong className="calendar-title">{title}</strong>
        </div>
        <div className="calendar-actions">
          <button className="button button-small" onClick={() => setTaskForm({ date: detailDay ?? today })}><Plus size={15} /> Görev ekle</button>
          <button className="button button-small" onClick={exportIcs}><Download size={15} /> .ics dışa aktar</button>
        </div>
      </div>
      <div className="calendar-filters" role="group" aria-label="Olay türü">
        {KIND_GROUPS.map(([key, label]) => (
          <label key={key} className={`legend legend-${key}`}>
            <input type="checkbox" checked={!hiddenGroups.includes(key)}
              onChange={(event) => setHiddenGroups(event.target.checked ? hiddenGroups.filter((item) => item !== key) : [...hiddenGroups, key])} />
            {label}
          </label>
        ))}
      </div>

      {taskForm && <TaskForm initialDate={taskForm.date} taskId={taskForm.id} onClose={() => setTaskForm(null)} />}

      <QueryState isLoading={query.isLoading} error={query.error}>
        {view === "month" && (
          <div className="month-grid" role="grid" aria-label={title}>
            {WEEKDAYS.map((name) => <div key={name} className="month-head">{name}</div>)}
            {days.map((day) => {
              const { events, tasks } = eventsOn(query.data, day, hidden);
              const items = [...events.map((event) => ({ key: `e${event.id}`, kind: event.kind, text: `${event.time ? `${event.time} ` : ""}${event.label} · ${event.organization}`, span: Boolean(event.end_date) && event.date !== day, done: false })),
                ...tasks.map((task) => ({ key: `t${task.task_id}`, kind: "task", text: `${task.start_time ? `${task.start_time} ` : ""}${task.title}`, span: false, done: task.done }))];
              return (
                <button key={day} role="gridcell" onClick={() => setSelectedDay(day)}
                  className={`month-cell ${day.slice(0, 7) !== cursor.slice(0, 7) ? "month-cell-out" : ""} ${day === today ? "month-cell-today" : ""} ${day === selectedDay ? "month-cell-selected" : ""}`}>
                  <span className="month-day">{Number(day.slice(8))}</span>
                  {items.slice(0, 3).map((item) => <span key={item.key} className={`pill pill-${item.kind} ${item.span ? "pill-span" : ""} ${item.done ? "pill-done" : ""}`}>{item.text}</span>)}
                  {items.length > 3 && <span className="pill-more">+{items.length - 3} daha</span>}
                </button>
              );
            })}
          </div>
        )}

        {view === "week" && (
          <div className="week-grid">
            {days.map((day) => {
              const { events, tasks } = eventsOn(query.data, day, hidden);
              return (
                <section key={day} className={`week-day ${day === today ? "week-day-today" : ""}`}>
                  <button className="week-day-head" onClick={() => setSelectedDay(day)}>{WEEKDAYS[weekdayIndex(day)]} {Number(day.slice(8))}</button>
                  <DayItems day={day} events={events} tasks={tasks} compact onEditTask={(id) => setTaskForm({ id, date: day })} />
                </section>
              );
            })}
          </div>
        )}

        {view === "agenda" && <Agenda data={query.data} start={start} end={end} hidden={hidden} onEditTask={(id, day) => setTaskForm({ id, date: day })} />}

        {detailDay && view !== "agenda" && (
          <section className="panel day-panel">
            <h2>{formatLongDate(detailDay)}</h2>
            <DayItems day={detailDay} {...eventsOn(query.data, detailDay, hidden)} onEditTask={(id) => setTaskForm({ id, date: detailDay })} />
          </section>
        )}
      </QueryState>
    </div>
  );
}

function Agenda({ data, start, end, hidden, onEditTask }: { data?: CalendarData; start: string; end: string; hidden: Set<string>; onEditTask: (id: number, day: string) => void }) {
  const days: string[] = [];
  for (let day = start; day <= end; day = addDays(day, 1)) {
    const { events, tasks } = eventsOn(data, day, hidden);
    if (events.some((event) => event.date === day) || tasks.length) days.push(day);
  }
  if (!days.length) return <p className="empty-state"><strong>Önümüzdeki 60 günde olay ya da görev yok</strong></p>;
  return (
    <div className="agenda">
      {days.map((day) => {
        const { events, tasks } = eventsOn(data, day, hidden);
        return (
          <section key={day} className="agenda-day">
            <h3>{formatLongDate(day)}</h3>
            <DayItems day={day} events={events.filter((event) => event.date === day)} tasks={tasks} onEditTask={(id) => onEditTask(id, day)} />
          </section>
        );
      })}
    </div>
  );
}

function DayItems({ day, events, tasks, compact = false, onEditTask }: {
  day: string; events: CalendarEvent[]; tasks: TaskOccurrence[]; compact?: boolean; onEditTask: (taskId: number) => void;
}) {
  const open = useOpenJob();
  const complete = useCompleteTask();
  const removeTask = useDeleteTask();
  const removeEvent = useDeleteEvent();
  const editEvent = useEditEvent();
  const saveTask = useSaveTask();
  const allTasks = useTasks();
  const [editing, setEditing] = useState<number | null>(null);
  const timed = [...events].sort((a, b) => (a.time || "00:00").localeCompare(b.time || "00:00"));
  if (!events.length && !tasks.length) return <p className="muted day-empty">{compact ? "—" : "Bu gün için olay ya da görev yok."}</p>;

  function moveToTomorrow(taskId: number) {
    const task = allTasks.data?.find((item) => item.id === taskId);
    if (task) saveTask.mutate({ ...task, task_date: addDays(day, 1) });
  }

  return (
    <ul className={`day-items ${compact ? "day-items-compact" : ""}`}>
      {timed.map((event) => (
        <li key={`e${event.id}`} className={`day-item day-item-${event.kind} ${event.cancelled ? "day-item-cancelled" : ""}`}>
          <div className="day-item-main">
            <span className="day-item-kind">{event.time || "Tüm gün"} · {event.label}{event.end_date && event.end_date !== event.date ? ` (${shortDay.format(asDate(event.date))} – ${shortDay.format(asDate(event.end_date))})` : ""}</span>
            <strong>{event.organization}</strong>
            {!compact && <span>{event.job_title}</span>}
            {!compact && event.url && <a href={event.url} target="_blank" rel="noreferrer">{event.url.replace(/^https?:\/\//, "")} <ExternalLink size={12} /></a>}
            {editing === event.id && (
              <form className="inline-form" onSubmit={(submit) => {
                submit.preventDefault();
                const form = new FormData(submit.currentTarget);
                editEvent.mutate({ id: event.id, kind: event.kind, event_date: String(form.get("date")), event_time: String(form.get("time") || ""), end_date: event.end_date, url: event.url },
                  { onSuccess: () => setEditing(null) });
              }}>
                <input type="date" name="date" defaultValue={event.date} aria-label="Tarih" required />
                <input type="time" name="time" defaultValue={event.time} aria-label="Saat" />
                <button className="button button-small button-primary" disabled={editEvent.isPending}>Kaydet</button>
              </form>
            )}
          </div>
          {!compact && (
            <div className="day-item-actions">
              <button className="button button-small" onClick={() => open(event.job_id)}>İlana git</button>
              <button className="icon-button" aria-label="Olayı düzenle" onClick={() => setEditing(editing === event.id ? null : event.id)}><Pencil size={15} /></button>
              <button className="icon-button" aria-label="Olayı sil" onClick={() => removeEvent.mutate(event.id)}><Trash2 size={15} /></button>
            </div>
          )}
        </li>
      ))}
      {tasks.map((task) => (
        <li key={`t${task.task_id}`} className={`day-item day-item-task ${task.done ? "day-item-done" : ""} priority-${task.priority}`}>
          <label className="day-item-main task-check">
            <input type="checkbox" checked={task.done} onChange={(event) => complete.mutate({ id: task.task_id, day, done: event.target.checked })} />
            <span>
              <span className="day-item-kind">{task.start_time ? `${task.start_time}${task.end_time ? `–${task.end_time}` : ""}` : "Görev"}{task.recurrence !== "none" ? " · tekrarlı" : ""}{task.priority === "high" ? " · öncelikli" : ""}</span>
              <strong>{task.title}</strong>
              {!compact && task.description && <span>{task.description}</span>}
            </span>
          </label>
          {!compact && (
            <div className="day-item-actions">
              {!task.done && task.recurrence === "none" && (
                <button className="icon-button" aria-label="Görevi yarına taşı" title="Yarına taşı" onClick={() => moveToTomorrow(task.task_id)}><ArrowRightToLine size={15} /></button>
              )}
              <button className="icon-button" aria-label="Görevi düzenle" onClick={() => onEditTask(task.task_id)}><Pencil size={15} /></button>
              <button className="icon-button" aria-label="Görevi sil" onClick={() => removeTask.mutate(task.task_id)}><Trash2 size={15} /></button>
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

function TaskForm({ initialDate, taskId, onClose }: { initialDate: string; taskId?: number; onClose: () => void }) {
  const tasks = useTasks();
  const save = useSaveTask();
  const existing = tasks.data?.find((task) => task.id === taskId);
  const [draft, setDraft] = useState<TaskInput>(() => existing ?? {
    title: "", description: "", task_date: initialDate, start_time: "", end_time: "", priority: "normal", recurrence: "none", weekdays: [], until: null,
  });
  const set = <K extends keyof TaskInput>(key: K, value: TaskInput[K]) => setDraft((current) => ({ ...current, [key]: value }));

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate({ ...draft, id: taskId }, { onSuccess: onClose });
  }

  return (
    <form className="panel task-form" onSubmit={submit}>
      <h2>{taskId ? "Görevi düzenle" : "Yeni görev"}</h2>
      <div className="form-grid">
        <label className="field field-wide"><span>Başlık</span><input value={draft.title} onChange={(event) => set("title", event.target.value)} required placeholder="Örn. İngilizce çalış" /></label>
        <label className="field field-wide"><span>Açıklama</span><textarea rows={2} value={draft.description} onChange={(event) => set("description", event.target.value)} /></label>
        <label className="field"><span>Tarih</span><input type="date" value={draft.task_date} onChange={(event) => set("task_date", event.target.value)} required /></label>
        <label className="field"><span>Öncelik</span>
          <select value={draft.priority} onChange={(event) => set("priority", event.target.value as TaskInput["priority"])}>
            <option value="low">Düşük</option><option value="normal">Normal</option><option value="high">Yüksek</option>
          </select>
        </label>
        <label className="field"><span>Başlangıç saati</span><input type="time" value={draft.start_time} onChange={(event) => set("start_time", event.target.value)} /></label>
        <label className="field"><span>Bitiş saati</span><input type="time" value={draft.end_time} onChange={(event) => set("end_time", event.target.value)} /></label>
        <label className="field"><span>Tekrar</span>
          <select value={draft.recurrence} onChange={(event) => set("recurrence", event.target.value as TaskInput["recurrence"])}>
            <option value="none">Tekrarlamaz</option><option value="daily">Her gün</option><option value="weekly">Her hafta</option>
            <option value="weekdays">Belirli günler</option><option value="monthly">Her ay</option>
          </select>
        </label>
        {draft.recurrence !== "none" && (
          <label className="field"><span>Bitiş tarihi (isteğe bağlı)</span><input type="date" value={draft.until ?? ""} onChange={(event) => set("until", event.target.value || null)} /></label>
        )}
        {draft.recurrence === "weekdays" && (
          <div className="field field-wide weekday-picker" role="group" aria-label="Günler">
            {WEEKDAYS.map((name, index) => (
              <label key={name} className="check-field">
                <input type="checkbox" checked={draft.weekdays.includes(index)}
                  onChange={(event) => set("weekdays", event.target.checked ? [...draft.weekdays, index] : draft.weekdays.filter((day) => day !== index))} />
                {name}
              </label>
            ))}
          </div>
        )}
      </div>
      {save.error && <p className="field-error" role="alert">{save.error.message}</p>}
      <div className="button-row">
        <button className="button button-primary" disabled={save.isPending}>Kaydet</button>
        <button type="button" className="button" onClick={onClose}>Vazgeç</button>
      </div>
    </form>
  );
}
