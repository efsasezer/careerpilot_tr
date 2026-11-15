import { CircleAlert, CircleCheck, CircleX, Clock3 } from "lucide-react";
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

export function StatusDot({ status }: { status: RequirementStatus }) {
  const Icon = status === "met" ? CircleCheck : status === "not_met" ? CircleX : CircleAlert;
  const label = status === "met" ? "Karşılanıyor" : status === "not_met" ? "Karşılanmıyor" : "Doğrulanmalı";
  return <Icon size={17} className={`status-${status}`} aria-label={label} />;
}
