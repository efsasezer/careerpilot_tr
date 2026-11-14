import { ExternalLink, MapPin } from "lucide-react";
import type { MatchedJob } from "../../types/api";
import { formatDate } from "../../utils/format";
import { MatchBadge } from "./MatchBadge";

export function MatchCard({ job }: { job: MatchedJob }) {
  const { match } = job;
  const documentReview = job.document_review;
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
        <span><MapPin size={14} />{job.city || "Kaynakta bulunamadı"}</span>
        <span>{job.source_name}</span>
        <span>İstihdam türü · {job.employment_type || "Kaynakta belirtilmedi"}</span>
        <span>Alım yöntemi · {job.recruitment_method || "Kaynakta belirtilmedi"}</span>
        <span>Kontenjan · {job.quota || "Kaynakta bulunamadı"}</span>
        <span>KPSS {job.kpss_score_type || "—"}{job.kpss_min_score !== null ? ` · taban ${job.kpss_min_score}` : ""}</span>
        <span>İlan tarihi · {formatDate(job.announcement_date, "Kaynakta bulunamadı")}</span>
        <span>Başvuru başlangıcı · {formatDate(job.application_start, "Kaynakta bulunamadı")}</span>
        <span>Son başvuru · {formatDate(job.application_deadline, "Kaynakta bulunamadı")}</span>
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
        <section className="document-review">
          <strong>İlan ve ek belge incelemesi</strong>
          <p>Ek belge taraması · {documentScanLabel(documentReview?.status ?? "not_scanned")}</p>
          {documentReview?.error && <p className="condition-warning">{documentReview.error}</p>}
          <details className="description-details">
            <summary>Ana ilan şartları</summary>
            <p>{job.description || "Ana ilan metni kaydedilmemiş."}</p>
          </details>
          {documentReview?.documents.length ? (
            <div className="document-list">
              {documentReview.documents.map((document) => (
                <article className="document-item" key={document.id}>
                  <div>
                    <strong>{document.title || "Resmî ek belge"}</strong>
                    <span> · {documentScanLabel(document.status)}</span>
                  </div>
                  <a className="text-link" href={document.url} target="_blank" rel="noreferrer">
                    İncelenen resmî belgeyi aç <ExternalLink size={14} />
                  </a>
                  {document.error && <p className="condition-warning">{document.error}</p>}
                  {document.positions.length > 0 && (
                    <div className="document-positions">
                      <strong>Ek belgeden çıkarılan pozisyonlar</strong>
                      {document.positions.map((position) => (
                        <section className="document-position" key={`${document.id}-${position.row_index}`}>
                          <h4>{position.position_title || `Tablo satırı ${position.row_index}`}</h4>
                          <p><strong>Kabul edilen öğrenim:</strong> {position.education_requirement || "Kaynakta belirtilmedi"}</p>
                          <p><strong>Kontenjan:</strong> {position.quota || "Kaynakta belirtilmedi"} · <strong>KPSS:</strong> {position.kpss_score_type || "Kaynakta belirtilmedi"}{position.kpss_min_score !== null ? ` / taban ${position.kpss_min_score}` : ""} · <strong>Yer:</strong> {position.city || "Kaynakta belirtilmedi"}</p>
                          {position.qualification_codes && <p><strong>Nitelik kodları:</strong> {position.qualification_codes}</p>}
                          {position.written_exam_invite_count !== null && <p><strong>Yazılı sınava çağrı sıralaması:</strong> Her pozisyon için en çok {position.written_exam_invite_count} katına kadar aday; bu bilgi uygunluk sınıflandırmasından ayrıdır.</p>}
                          {position.written_exam_invite_text && <details><summary>Belgedeki sınav çağrı açıklaması</summary><p>{position.written_exam_invite_text}</p></details>}
                        </section>
                      ))}
                    </div>
                  )}
                  {!document.positions.length && document.parsed_content_hash && (
                    <p className="muted">Belge okundu; yapılandırılmış pozisyon tablosu bulunamadı.</p>
                  )}
                </article>
              ))}
            </div>
          ) : documentReview?.status === "complete" ? (
            <p className="muted">Taranan ilan sayfasında ek belge bağlantısı bulunamadı.</p>
          ) : (
            <p className="muted">Ek belge bağlantıları henüz doğrulanmadı.</p>
          )}
        </section>
        {job.description && <details className="description-details"><summary>İlan açıklaması</summary><p>{job.description}</p></details>}
      </details>
      {job.source_url && (
        <div>
          <a className="text-link" href={job.source_url} target="_blank" rel="noreferrer">
            {job.source_name === "SBB Kamu İlanları" ? "Resmî SBB ilan listesine git" : "Resmî ilanı aç"}
            <ExternalLink size={14} />
          </a>
          {job.source_name === "SBB Kamu İlanları" && (
            <small className="muted">SBB ilan detay bağlantıları şu anda doğrulanamıyor; ilanı resmî listede arayın.</small>
          )}
        </div>
      )}
    </article>
  );
}

function documentScanLabel(status: string) {
  const labels: Record<string, string> = {
    not_scanned: "Henüz taranmadı",
    complete: "Tarama tamamlandı",
    read: "Okundu ve ayrıştırıldı",
    partially_read: "Kısmen okundu",
    unreadable: "Okunamadı",
    unavailable: "Kaynağa erişilemedi",
    partial: "Bazı belgeler okunamadı",
    discovered: "Bulundu, henüz okunmadı",
  };
  return labels[status] ?? status;
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
