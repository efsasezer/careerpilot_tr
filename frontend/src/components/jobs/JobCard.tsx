import { Bookmark, Building2, CheckCheck, MapPin } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { CategoryBadge, DataStatusChip, DeadlineChip } from "../shared/Badges";
import { formatDate, type JobGroup } from "../../utils/format";

export function useOpenJob() {
  const [params, setParams] = useSearchParams();
  return (jobId: number) => {
    const next = new URLSearchParams(params);
    next.set("ilan", String(jobId));
    setParams(next);
  };
}

export function JobCard({ group }: { group: JobGroup }) {
  const open = useOpenJob();
  const job = group.primary;
  const multiple = group.positions.length > 1;
  const reason = job.match.requirements.find((item) =>
    group.category === "UYGUN DEĞİL" ? item.status === "not_met" : group.category === "UYGUN" ? item.status === "met" : item.status === "unknown",
  )?.detail ?? job.match.reason;

  return (
    <button type="button" className={`job-card ${job.is_expired ? "job-card-closed" : ""}`} onClick={() => open(group.jobId)}>
      <div className="job-card-top">
        <CategoryBadge category={group.category} />
        <DeadlineChip daysLeft={job.days_left} status={job.application_status} />
        <DataStatusChip status={job.data_status} />
        {job.cancellation_notice && job.application_status !== "İptal Edildi" && <span className="chip chip-warn">İptal duyurusu var</span>}
        {job.tracking === "saved" && <span className="chip chip-accent"><Bookmark size={13} aria-hidden /> Kaydedildi</span>}
        {job.tracking === "applied" && <span className="chip chip-accent"><CheckCheck size={13} aria-hidden /> Başvuruldu</span>}
      </div>
      <h3>{multiple ? group.title : job.position}</h3>
      <p className="job-card-org"><Building2 size={15} aria-hidden /> {group.organization}</p>
      <p className="job-card-reason">{reason}</p>
      <div className="job-card-meta">
        {multiple && (
          <span>{group.positions.length} pozisyon{group.suitableCount > 0 && group.category !== "UYGUN DEĞİL" ? ` · ${group.suitableCount} tanesi size açık` : ""}</span>
        )}
        {job.city && !multiple && <span><MapPin size={13} aria-hidden /> {job.city.split("\n")[0]}</span>}
        {job.kpss_score_type && <span>KPSS {job.kpss_score_type.split("/").slice(0, 3).join(", ")}{job.kpss_score_type.split("/").length > 3 ? "…" : ""}{job.kpss_min_score !== null ? ` · en az ${job.kpss_min_score}` : ""}</span>}
        <span>Son başvuru {formatDate(job.application_deadline, "belirtilmemiş")}</span>
        <span>{job.source_name.replace(" Kamu Memur Alım İlanları", "").replace(" Kamu İlanları", "").replace(" Genel Müdürlüğü", "")}</span>
      </div>
    </button>
  );
}
