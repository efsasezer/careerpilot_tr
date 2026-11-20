export const CALENDAR_FILTERS = [
  ["application", "Başvuru tarihleri"],
  ["exam", "Sınav / mülakat"],
  ["result", "Sonuç"],
  ["documents", "Evrak / atama"],
  ["task", "Kişisel görevler"],
] as const;

export type CalendarFilter = (typeof CALENDAR_FILTERS)[number][0];

export const EVENT_FILTER_GROUP: Record<string, CalendarFilter> = {
  application_start: "application",
  application_deadline: "application",
  exam: "exam",
  interview: "exam",
  result: "result",
  documents: "documents",
  appointment: "documents",
};
