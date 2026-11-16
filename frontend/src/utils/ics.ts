import type { CalendarData } from "../types/api";

const escape = (text: string) => text.replace(/\\/g, "\\\\").replace(/\n/g, "\\n").replace(/([,;])/g, "\\$1");
const compact = (iso: string) => iso.replace(/-/g, "");

function nextDay(iso: string) {
  const date = new Date(`${iso}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + 1);
  return date.toISOString().slice(0, 10);
}

/** Takvim verisini .ics (iCalendar) metnine çevirir. Saatler Europe/Istanbul olarak yazılır. */
export function buildIcs(data: CalendarData, stamp = new Date()): string {
  const now = stamp.toISOString().replace(/[-:]/g, "").slice(0, 15) + "Z";
  const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//CareerPilot TR//TR", "CALSCALE:GREGORIAN", "X-WR-TIMEZONE:Europe/Istanbul"];
  const add = (uid: string, title: string, day: string, time: string, endDay: string | null, endTime: string, description: string) => {
    lines.push("BEGIN:VEVENT", `UID:${uid}@careerpilot-tr`, `DTSTAMP:${now}`, `SUMMARY:${escape(title)}`);
    if (time) {
      lines.push(`DTSTART;TZID=Europe/Istanbul:${compact(day)}T${time.replace(":", "")}00`);
      if (endTime) lines.push(`DTEND;TZID=Europe/Istanbul:${compact(endDay ?? day)}T${endTime.replace(":", "")}00`);
    } else {
      lines.push(`DTSTART;VALUE=DATE:${compact(day)}`, `DTEND;VALUE=DATE:${compact(nextDay(endDay ?? day))}`);
    }
    if (description) lines.push(`DESCRIPTION:${escape(description)}`);
    lines.push("END:VEVENT");
  };
  for (const event of data.events) {
    add(`event-${event.id}`, `${event.label}: ${event.organization}`, event.date, event.time, event.end_date, "",
      [event.job_title, event.url, event.evidence].filter(Boolean).join("\n"));
  }
  for (const task of data.tasks) {
    add(`task-${task.task_id}-${task.date}`, task.title, task.date, task.start_time, null, task.end_time, task.description);
  }
  lines.push("END:VCALENDAR");
  return lines.join("\r\n");
}
