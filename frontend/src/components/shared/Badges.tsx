import { CircleAlert, CircleCheck, CircleMinus, CircleX, Clock3, FileText } from "lucide-react";
import type { MatchCategory, RequirementStatus } from "../../types/api";
import { CATEGORY_LABEL, deadlineLabel } from "../../utils/format";

const TONE: Record<MatchCategory, string> = {
  UYGUN: "ok",
  "POTANSİYEL OLARAK UYGUN": "warn",
  "UYGUN DEĞİL": "bad",
};

export function CategoryBadge({ category }: { category: MatchCategory }) {
  const Icon = category === "UYGUN" ? CircleCheck : category === "UYGUN DEĞİL" ? CircleX : CircleAlert;
  return (
    <span className={`badge badge-${TONE[category]}`}>
      <Icon size={14} aria-hidden /> {CATEGORY_LABEL[category]}
    </span>
  );
}

export function DeadlineChip({ daysLeft, status }: { daysLeft: number | null; status: string }) {
  const closed = status === "Başvuru Sona Erdi" || status === "İptal Edildi";
  const urgent = !closed && status === "Başvuru Açık" && daysLeft !== null && daysLeft <= 3;
  return (
    <span className={`chip ${closed ? "chip-muted" : urgent ? "chip-urgent" : ""}`}>
      <Clock3 size={13} aria-hidden /> {deadlineLabel(daysLeft, status)}
    </span>
  );
}

const DATA_LABEL = {
  read: "Resmî metin okundu",
  partial: "Ek belge okunamadı",
  listing_only: "İlan metni okunamadı",
  ocr: "OCR ile okundu, kontrol et",
} as const;

export function DataStatusChip({ status, always = false }: { status: keyof typeof DATA_LABEL; always?: boolean }) {
  if (status === "read" && !always) return null;
  return <span className={`chip ${status === "read" ? "" : "chip-warn"}`}><FileText size={13} aria-hidden /> {DATA_LABEL[status]}</span>;
}

export const STATUS_LABEL: Record<RequirementStatus, string> = {
  met: "Karşılıyor", not_met: "Karşılamıyor", unknown: "Bilinmiyor", not_required: "Aranmıyor",
};

export function StatusDot({ status }: { status: RequirementStatus }) {
  const Icon = status === "met" ? CircleCheck : status === "not_met" ? CircleX : status === "not_required" ? CircleMinus : CircleAlert;
  const label = STATUS_LABEL[status];
  return <Icon size={17} className={`status-${status}`} aria-label={label} />;
}
