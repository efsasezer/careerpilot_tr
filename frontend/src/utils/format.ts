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
        category: position.match.category,
        suitableCount: 0,
      };
      groups.set(position.parent_job_id, group);
    }
    group.positions.push(position);
    if (position.match.category !== "UYGUN DEĞİL") group.suitableCount += 1;
    if (CATEGORY_RANK[position.match.category] < CATEGORY_RANK[group.category]) {
      group.category = position.match.category;
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
