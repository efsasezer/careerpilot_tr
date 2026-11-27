import type { MatchCategory, MatchedPosition, Tracking } from "../types/api";

export function formatDate(value: string | null | undefined, missingLabel = "Belirtilmemiş") {
  if (!value) return missingLabel;
  const date = new Date(`${value.slice(0, 10)}T00:00:00`);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "short", year: "numeric" }).format(date);
}

export function formatTimestamp(value: string | null | undefined, missingLabel = "Henüz yok") {
  if (!value) return missingLabel;
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("tr-TR", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

export const DECISION_LABEL = { eligible: "Uygun", unsure: "Potansiyel uygun", not_eligible: "Uygun değil" } as const;
export const DECISION_CATEGORY = { eligible: "UYGUN", unsure: "POTANSİYEL OLARAK UYGUN", not_eligible: "UYGUN DEĞİL" } as const;

export const CATEGORY_LABEL: Record<MatchCategory, string> = {
  UYGUN: "Uygun",
  "POTANSİYEL OLARAK UYGUN": "Doğrulanmalı",
  "UYGUN DEĞİL": "Uygun değil",
};
const CATEGORY_RANK: Record<MatchCategory, number> = { UYGUN: 0, "POTANSİYEL OLARAK UYGUN": 1, "UYGUN DEĞİL": 2 };

export const TRACKING_LABEL: Record<Tracking, string> = {
  "": "Takip edilmiyor",
  saved: "Kaydedildi",
  applied: "Başvuruldu",
  awaiting: "Sonuç bekleniyor",
  won: "Kazandım",
  lost: "Olmadı",
  hidden: "Gizlendi",
};

export function deadlineLabel(daysLeft: number | null, status: string) {
  if (status === "İptal Edildi") return "İptal edildi";
  if (status === "Başvuru Sona Erdi") return "Süresi doldu";
  if (daysLeft === null) return status === "Tarih belirtilmemiş" ? "Tarih yok" : status;
  if (status === "Başvuru Başlamadı") return "Henüz açılmadı";
  if (daysLeft === 0) return "Bugün son gün";
  if (daysLeft === 1) return "Yarın son gün";
  return `${daysLeft} gün kaldı`;
}

/** Aynı ilanın pozisyonlarını tek kartta toplar. */
export interface JobGroup {
  jobId: number;
  title: string;
  organization: string;
  primary: MatchedPosition;
  positions: MatchedPosition[];
  category: MatchCategory;
  suitableCount: number;
}

export function groupByJob(positions: MatchedPosition[]): JobGroup[] {
  const groups = new Map<number, JobGroup>();
  for (const position of positions) {
    let group = groups.get(position.parent_job_id);
    if (!group) {
      group = {
        jobId: position.parent_job_id,
        title: position.title.split(" — ")[0],
        organization: position.organization,
        primary: position,
        positions: [],
        category: position.category,
        suitableCount: 0,
      };
      groups.set(position.parent_job_id, group);
    }
    group.positions.push(position);
    if (position.category !== "UYGUN DEĞİL") group.suitableCount += 1;
    if (CATEGORY_RANK[position.category] < CATEGORY_RANK[group.category]) {
      group.category = position.category;
      group.primary = position;
    }
  }
  return [...groups.values()];
}

export function sortGroups(groups: JobGroup[], order: "relevance" | "deadline" | "newest") {
  const deadline = (group: JobGroup) => group.primary.application_deadline ?? "9999";
  return [...groups].sort((a, b) => {
    if (order === "newest") return b.jobId - a.jobId;
    if (order === "relevance" && a.category !== b.category) return CATEGORY_RANK[a.category] - CATEGORY_RANK[b.category];
    return deadline(a).localeCompare(deadline(b));
  });
}

/** Tarihler Europe/Istanbul saat dilimine göre "YYYY-AA-GG" olarak üretilir. */
const ISTANBUL_DAY = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Istanbul", year: "numeric", month: "2-digit", day: "2-digit" });

export function todayIso(now: Date = new Date()) {
  return ISTANBUL_DAY.format(now);
}

export function addDays(iso: string, days: number) {
  const date = new Date(`${iso}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

export function weekdayIndex(iso: string) {
  return (new Date(`${iso}T12:00:00Z`).getUTCDay() + 6) % 7; // Pazartesi = 0
}

export function startOfWeek(iso: string) {
  return addDays(iso, -weekdayIndex(iso));
}

export function formatLongDate(iso: string) {
  return new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "long", year: "numeric", weekday: "long", timeZone: "UTC" })
    .format(new Date(`${iso}T12:00:00Z`));
}
