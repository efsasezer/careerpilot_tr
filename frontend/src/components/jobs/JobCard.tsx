import { Bookmark, Building2, CheckCheck, MapPin, UserCheck } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { CategoryBadge, DataStatusChip, DeadlineChip } from "../shared/Badges";
import { VerifyButtons } from "./VerifyButtons";
import { CATEGORY_LABEL, TRACKING_LABEL, formatDate, type JobGroup } from "../../utils/format";

export function useOpenJob() {
  const [params, setParams] = useSearchParams();
  return (jobId: number) => {
    const next = new URLSearchParams(params);
    next.set("ilan", String(jobId));
    setParams(next);
  };
}

export function JobCard({ group, onDecision }: { group: JobGroup; onDecision?: (decision: "eligible" | "not_eligible") => void }) {
  const open = useOpenJob();
  const job = group.primary;
  const multiple = group.positions.length > 1;
  const verified = group.positions.find((position) => position.verification)?.verification ?? null;
  const stale = group.positions.some((position) => position.verification?.stale);
  const jobLevel = verified?.scope === "job" ? verified : null;
  const reason = job.match.requirements.find((item) =>
    job.system_category === "UYGUN DEĞİL" ? item.status === "not_met" : job.system_category === "UYGUN" ? item.status === "met" : item.status === "unknown",
  )?.detail ?? job.match.reason;
  const applied = ["applied", "awaiting", "won", "lost"].includes(job.tracking);

  return (
    <article className={`job-card ${job.is_expired ? "job-card-closed" : ""}`}>
      <button type="button" className="job-card-main" onClick={() => open(group.jobId)}>
        <div className="job-card-top">
          <CategoryBadge category={group.category} />
          {group.category === "UYGUN" && group.positions.every((p) => p.category !== "UYGUN" || p.out_of_preference) && <span className="chip">Tercih dışı</span>}
          {verified && <span className="chip chip-accent"><UserCheck size={13} aria-hidden /> Elle doğrulandı</span>}
          {stale && <span className="chip chip-warn">İlan güncellendi</span>}
          <DeadlineChip daysLeft={job.days_left} status={job.application_status} />
          {job.match.kind === "academic" && <span className="chip">Akademik</span>}
          <DataStatusChip status={job.data_status} />
          {job.cancellation_notice && job.application_status !== "İptal Edildi" && <span className="chip chip-warn">İptal duyurusu var</span>}
          {job.tracking === "saved" && <span className="chip chip-accent"><Bookmark size={13} aria-hidden /> Kaydedildi</span>}
          {applied && <span className="chip chip-accent"><CheckCheck size={13} aria-hidden /> {TRACKING_LABEL[job.tracking]}</span>}
        </div>
        <h3>{multiple ? group.title : job.position}</h3>
        <p className="job-card-org"><Building2 size={15} aria-hidden /> {group.organization}</p>
        <p className="job-card-reason">{reason}</p>
        {verified && (
          <p className="job-card-decision">
            Sistem: {CATEGORY_LABEL[job.system_category]} · Siz: {verified.decision === "eligible" ? "Uygun" : "Uygun değil"}
          </p>
        )}
        <div className="job-card-meta">
          {multiple && (
            <span>{group.positions.length} kadro{group.suitableCount > 0 && group.category !== "UYGUN DEĞİL" ? ` · ${group.suitableCount} tanesi size açık` : ""}</span>
          )}
          {job.city && !multiple && <span><MapPin size={13} aria-hidden /> {job.city.split("\n")[0]}</span>}
          {job.kpss_score_type && <span>KPSS {job.kpss_score_type.split("/").slice(0, 3).join(", ")}{job.kpss_score_type.split("/").length > 3 ? "…" : ""}{job.kpss_min_score !== null ? ` · en az ${job.kpss_min_score}` : ""}</span>}
          <span>Son başvuru {formatDate(job.application_deadline, "belirtilmemiş")}</span>
          <span>{job.source_name.replace(" Kamu Memur Alım İlanları", "").replace(" Kamu İlanları", "").replace(" Genel Müdürlüğü", "")}</span>
        </div>
      </button>
      {(group.category === "POTANSİYEL OLARAK UYGUN" || jobLevel) && (
        <div className="job-card-verify">
          <span>{jobLevel ? "Kararınız:" : "Resmî ilandan kontrol ettiyseniz:"}</span>
          <VerifyButtons jobId={group.jobId} verification={jobLevel} compact onDecision={onDecision} />
        </div>
      )}
    </article>
  );
}
