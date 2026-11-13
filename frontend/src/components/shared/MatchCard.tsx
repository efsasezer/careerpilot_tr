import { ExternalLink, MapPin } from "lucide-react";
import type { MatchedJob } from "../../types/api";
import { formatDate } from "../../utils/format";
import { MatchBadge } from "./MatchBadge";

export function MatchCard({ job }: { job: MatchedJob }) {
  const { match } = job;
  return (
    <article className="match-card">
      <div className="match-card-top">
        <div>
          <div className="match-card-kicker">{job.organization}</div>
          <h3>{job.position}</h3>
          <p className="muted">{job.title}</p>
        </div>
        <MatchBadge category={match.category} />
      </div>
      <p className="match-reason">{match.reason}</p>
      <div className="job-meta-grid">
        <span><MapPin size={14} />{job.city || "Konum belirtilmemiş"}</span>
        <span>{job.source_name}</span>
        <span>KPSS {job.kpss_score_type || "—"}{job.kpss_min_score !== null ? ` · taban ${job.kpss_min_score}` : ""}</span>
        <span>Son başvuru · {formatDate(job.application_deadline)}</span>
      </div>
      <details className="match-details">
        <summary>Uygunluk gerekçeleri ve ilan koşulları</summary>
        <div className="details-grid">
          <ConditionList title="Karşılanan şartlar" items={match.met_conditions} kind="success" />
          <ConditionList title="Eksik / doğrulanacak" items={match.unknown_conditions} kind="warning" />
          <ConditionList title="Karşılanmayan şartlar" items={match.failed_conditions} kind="danger" />
          <ConditionList title="Genel kamu koşulları" items={match.general_conditions} kind="neutral" />
        </div>
        <div className="detail-pair">
          <div><strong>Eğitim eşleşmesi</strong><p>{match.education.requirement || job.education_requirement || "Belirtilmemiş"}</p><small>{match.education.basis}</small></div>
          <div><strong>KPSS değerlendirmesi</strong><p>{match.kpss.candidate_score_type} {match.kpss.candidate_score ?? "—"} · {match.kpss.status}</p><small>İstenen tür: {match.kpss.score_types.join(", ") || "Belirtilmemiş"} · taban: {match.kpss.minimum_score ?? "yok"}</small></div>
        </div>
        {job.description && <details className="description-details"><summary>İlan açıklaması</summary><p>{job.description}</p></details>}
      </details>
      {job.source_url && <a className="text-link" href={job.source_url} target="_blank" rel="noreferrer">Resmî ilanı aç <ExternalLink size={14} /></a>}
    </article>
  );
}

function ConditionList({
  title,
  items,
  kind,
}: {
  title: string;
  items: string[];
  kind: "success" | "warning" | "danger" | "neutral";
}) {
  return (
    <section className={`condition-list condition-${kind}`}>
      <strong>{title}</strong>
      {items.length ? <ul>{items.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul> : <p className="muted">Kayıt yok</p>}
    </section>
  );
}
