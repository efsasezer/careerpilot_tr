import { useEffect, useState } from "react";
import { Bookmark, CalendarPlus, CheckCheck, ExternalLink, EyeOff, FileText, Trash2, X } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { CategoryBadge, DataStatusChip, DeadlineChip, STATUS_LABEL, StatusDot } from "../shared/Badges";
import { QueryState } from "../shared/QueryState";
import { VerifyButtons } from "./VerifyButtons";
import { getApiUrl } from "../../services/api/client";
import {
  useAcknowledgeUpdate, useAddEvent, useDeleteEvent, useJobDetail, useRetryReading, useSetTracking, useSetVerification,
} from "../../services/api/hooks";
import type { JobDetail, MatchedPosition, Tracking } from "../../types/api";
import { CATEGORY_LABEL, TRACKING_LABEL, formatDate, formatTimestamp } from "../../utils/format";

const ORDER = { UYGUN: 0, "POTANSİYEL OLARAK UYGUN": 1, "UYGUN DEĞİL": 2 } as const;
const APPLIED_FLOW: Tracking[] = ["applied", "awaiting", "won", "lost"];

export function JobDrawer() {
  const [params, setParams] = useSearchParams();
  const raw = params.get("ilan");
  const jobId = raw && /^\d+$/.test(raw) ? Number(raw) : null;
  const detail = useJobDetail(jobId);

  function close() {
    const next = new URLSearchParams(params);
    next.delete("ilan");
    setParams(next);
  }

  useEffect(() => {
    if (jobId === null) return;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && close();
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  });

  if (jobId === null) return null;
  return (
    <div className="drawer-backdrop" onClick={close} role="presentation">
      <aside className="drawer" role="dialog" aria-modal="true" aria-label="İlan ayrıntısı" onClick={(event) => event.stopPropagation()}>
        <button className="icon-button drawer-close" onClick={close} aria-label="Kapat"><X size={20} /></button>
        <QueryState isLoading={detail.isLoading} error={detail.error}>
          {detail.data && <DrawerBody key={detail.data.id} job={detail.data} />}
        </QueryState>
      </aside>
    </div>
  );
}

function DrawerBody({ job }: { job: JobDetail }) {
  const tracking = useSetTracking();
  const verify = useSetVerification();
  const acknowledge = useAcknowledgeUpdate();
  const retry = useRetryReading();
  const [notes, setNotes] = useState(job.notes);
  const [verifyNote, setVerifyNote] = useState(job.job_verification?.note ?? "");
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [pdfError, setPdfError] = useState("");
  const positions = [...job.positions].sort((a, b) => ORDER[a.category] - ORDER[b.category]);
  const [selectedId, setSelectedId] = useState(positions[0].id);
  const selected = positions.find((item) => item.id === selectedId) ?? positions[0];
  const documents = job.document_review?.documents ?? [];
  const current = job.tracking;
  const stale = positions.find((item) => item.verification?.stale)?.verification ?? null;
  const needsManual = selected.data_status === "listing_only" || selected.data_status === "ocr";
  const hasResultDate = job.events.some((event) => event.kind === "result");

  useEffect(() => () => { if (pdfUrl) URL.revokeObjectURL(pdfUrl); }, [pdfUrl]);

  function setTracking(value: Tracking) {
    tracking.mutate({ jobId: job.id, tracking: current === value ? "" : value, notes });
  }

  async function showPdf() {
    setPdfError("");
    try {
      const response = await fetch(`${getApiUrl()}/jobs/${job.id}/document.pdf`, { credentials: "include" });
      if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? "PDF alınamadı.");
      setPdfUrl(URL.createObjectURL(await response.blob()));
    } catch (error) {
      setPdfError(error instanceof Error ? error.message : "PDF alınamadı.");
    }
  }

  return (
    <div className="drawer-body">
      <p className="drawer-org">{job.organization}</p>
      <h2>{job.title}</h2>
      <div className="drawer-chips">
        <CategoryBadge category={selected.category} />
        {selected.category === "UYGUN" && selected.out_of_preference && <span className="chip">Tercih dışı</span>}
        <DeadlineChip daysLeft={selected.days_left} status={selected.application_status} />
        <DataStatusChip status={selected.data_status} always />
        {selected.review_required && <span className="chip chip-warn">İnceleme gerekli</span>}
      </div>

      {selected.cancellation_notice && (
        <p className="notice notice-warn drawer-notice">
          {selected.application_status === "İptal Edildi"
            ? `Bu ilan iptal edildi (${selected.cancellation_notice}).`
            : `Bu kurum bir iptal duyurusu yayımladı (${selected.cancellation_notice}). Hangi alımı kapsadığı otomatik belirlenemedi; ilanın geçerli olup olmadığını resmî kaynaktan doğrulayın.`}
        </p>
      )}

      {stale && (
        <div className="notice notice-warn drawer-notice">
          <div>
            <strong>İlan güncellendi, doğrulamanı gözden geçir</strong>
            <p>Değişen: {stale.changes.join(", ")}. Kararınız korunuyor ve siz değiştirmedikçe değişmez.</p>
          </div>
          <button className="button button-small" disabled={acknowledge.isPending} onClick={() => acknowledge.mutate(job.id)}>Gözden geçirdim, karar geçerli</button>
        </div>
      )}

      <div className="drawer-actions">
        <button className={`button ${current === "saved" ? "button-active" : ""}`} onClick={() => setTracking("saved")}>
          <Bookmark size={16} /> {current === "saved" ? "Kaydedildi" : "Kaydet"}
        </button>
        <button className={`button ${APPLIED_FLOW.includes(current) ? "button-active" : ""}`} onClick={() => setTracking("applied")}>
          <CheckCheck size={16} /> {APPLIED_FLOW.includes(current) ? "Başvuruldu" : "Başvurdum"}
        </button>
        <button className={`button ${current === "hidden" ? "button-active" : ""}`} onClick={() => setTracking("hidden")}>
          <EyeOff size={16} /> {current === "hidden" ? "Gizlendi" : "İlgilenmiyorum"}
        </button>
        {job.source_url && (
          <a className="button button-primary" href={job.source_url} target="_blank" rel="noreferrer">
            Resmî ilana git <ExternalLink size={15} />
          </a>
        )}
      </div>
      {tracking.error && <p className="field-error" role="alert">{tracking.error.message}</p>}
      {APPLIED_FLOW.includes(current) && (
        <div className="flow">
          <span>Başvuru durumu:</span>
          {APPLIED_FLOW.map((step) => (
            <button key={step} className={`chip chip-button ${current === step ? "chip-accent" : ""}`} onClick={() => tracking.mutate({ jobId: job.id, tracking: step, notes })}>
              {TRACKING_LABEL[step]}
            </button>
          ))}
        </div>
      )}
      {APPLIED_FLOW.includes(current) && !hasResultDate && <AddEvent jobId={job.id} prompt="Sonuç tarihi eklemek ister misin?" kind="result" />}

      <section className="drawer-section">
        <h3>Kendi kararınız</h3>
        <p className="muted">
          Sistem: {CATEGORY_LABEL[selected.system_category]} · Siz: {job.job_verification ? (job.job_verification.decision === "eligible" ? "Uygun" : "Uygun değil") : "Henüz bakmadım"}
          {job.job_verification?.verified_at ? ` (${formatTimestamp(job.job_verification.verified_at)})` : ""}
        </p>
        <VerifyButtons jobId={job.id} verification={job.job_verification} note={verifyNote} />
        <label className="field verify-note">
          <span>Kısa not (isteğe bağlı)</span>
          <input value={verifyNote} onChange={(event) => setVerifyNote(event.target.value)} placeholder="Neye bakarak karar verdiniz?"
            onBlur={() => job.job_verification && verifyNote !== job.job_verification.note
              && verify.mutate({ jobId: job.id, decision: job.job_verification.decision, note: verifyNote })} />
        </label>
        <p className="hint">Kararınız sistemin hesabından ayrı saklanır; yeniden tarama ve profil değişikliği kararınızı değiştirmez.</p>
      </section>

      {(needsManual || job.has_pdf) && (
        <section className="drawer-section">
          <h3>Resmî belge</h3>
          {selected.data_status === "listing_only" && <p className="notice notice-warn">İlan metni otomatik okunamadı (taranmış PDF olabilir). Tahminle karar verilmedi; PDF'i açıp yukarıdan elle doğrulayın.</p>}
          {selected.data_status === "ocr" && <p className="notice notice-warn">Bu ilan taranmış PDF'ten OCR ile okundu (güven %{Math.round((selected.ocr_confidence ?? 0) * 100)}). Harf ve sayılar hatalı olabilir; PDF ile karşılaştırıp elle doğrulayın.</p>}
          <div className="button-row">
            {job.has_pdf && <button className="button" onClick={showPdf}><FileText size={16} /> Resmî PDF'i aç</button>}
            {needsManual && <button className="button" disabled={retry.isPending} onClick={() => retry.mutate(job.id)}>{retry.isPending ? "Okunuyor…" : "OCR'la yeniden dene"}</button>}
          </div>
          {retry.data && <p className="hint">{retry.data.status === "failed" ? `Okunamadı: ${retry.data.error}` : retry.data.status === "ocr" ? "OCR ile okundu; şartları kontrol edin." : "Belge okundu."}</p>}
          {pdfError && <p className="field-error" role="alert">{pdfError}</p>}
          {pdfUrl && <iframe className="pdf-frame" src={pdfUrl} title="Resmî ilan PDF'i" />}
        </section>
      )}

      {positions.length > 1 && (
        <section className="drawer-section">
          <h3>Kadrolar ({positions.length})</h3>
          <div className="position-list">
            {positions.map((item) => (
              <button key={item.id} className={`position-row ${item.id === selected.id ? "position-row-active" : ""}`} onClick={() => setSelectedId(item.id)}>
                <span>{item.position}{item.quota ? ` · ${item.quota} kişi` : ""}</span>
                <CategoryBadge category={item.category} />
              </button>
            ))}
          </div>
        </section>
      )}

      <PositionDetail jobId={job.id} position={selected} multiple={positions.length > 1} />

      <section className="drawer-section">
        <h3>Tarihler</h3>
        {job.events.length ? (
          <ul className="event-list">
            {job.events.map((event) => <EventRow key={event.id} event={event} />)}
          </ul>
        ) : <p className="muted">İlan metninde tarih belirtilmemiş. Tahmini tarih üretilmez.</p>}
        <AddEvent jobId={job.id} prompt="Tarih ekle" kind="exam" />
      </section>

      <section className="drawer-section">
        <h3>Notlarım</h3>
        <label className="sr-only" htmlFor="job-notes">İlan notu</label>
        <textarea id="job-notes" rows={3} value={notes} onChange={(event) => setNotes(event.target.value)}
          onBlur={() => notes !== job.notes && tracking.mutate({ jobId: job.id, tracking: current, notes })}
          placeholder="Hazırlanacak belgeler, hatırlatmalar…" />
      </section>

      {(documents.length > 0 || selected.also_listed.length > 0) && (
        <section className="drawer-section">
          <h3>Kaynaklar ve belgeler</h3>
          <ul className="link-list">
            {documents.map((document) => (
              <li key={document.id}>
                <a href={document.url} target="_blank" rel="noreferrer">{document.title || "Resmî belge"} <ExternalLink size={13} /></a>
                <span>{document.status === "read" ? "Okundu" : document.status === "ocr" ? "OCR ile okundu, kontrol edin" : document.status === "partially_read" ? "Kısmen okundu" : "Otomatik okunamadı, bağlantıdan açın"}</span>
              </li>
            ))}
            {selected.also_listed.map((other) => (
              <li key={other.source_name}>
                {other.source_url ? <a href={other.source_url} target="_blank" rel="noreferrer">{other.source_name} <ExternalLink size={13} /></a> : other.source_name}
                <span>Aynı ilan bu kaynakta da yayımlandı</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {job.description && (
        <details className="drawer-section drawer-text">
          <summary>Resmî ilan metni</summary>
          <pre>{job.description}</pre>
        </details>
      )}
      <p className="hint">Bu değerlendirme otomatik bir ön elemedir; başvurmadan önce resmî ilanı mutlaka okuyun.</p>
    </div>
  );
}

function EventRow({ event }: { event: JobDetail["events"][number] }) {
  const remove = useDeleteEvent();
  return (
    <li>
      <div>
        <strong>{event.label}</strong>
        <span>
          {formatDate(event.date)}{event.end_date ? ` – ${formatDate(event.end_date)}` : ""}{event.time ? ` · ${event.time}` : " · tüm gün"}
          {event.previous_date ? ` (önceki: ${formatDate(event.previous_date)})` : ""}
        </span>
        {event.url && <a href={event.url} target="_blank" rel="noreferrer">{event.url.replace(/^https?:\/\//, "")} <ExternalLink size={12} /></a>}
        {event.evidence && <details><summary>Bu bilgi nereden alındı?</summary><p>{event.evidence}</p></details>}
      </div>
      <button className="icon-button" aria-label={`${event.label} olayını sil`} disabled={remove.isPending} onClick={() => remove.mutate(event.id)}><Trash2 size={16} /></button>
    </li>
  );
}

function AddEvent({ jobId, prompt, kind }: { jobId: number; prompt: string; kind: string }) {
  const add = useAddEvent();
  const [open, setOpen] = useState(false);
  const [selectedKind, setSelectedKind] = useState(kind);
  const [day, setDay] = useState("");
  if (!open) return <button className="text-button" onClick={() => setOpen(true)}><CalendarPlus size={15} /> {prompt}</button>;
  return (
    <form className="inline-form" onSubmit={(event) => { event.preventDefault(); if (day) add.mutate({ jobId, kind: selectedKind, event_date: day }, { onSuccess: () => { setOpen(false); setDay(""); } }); }}>
      <select aria-label="Olay türü" value={selectedKind} onChange={(event) => setSelectedKind(event.target.value)}>
        <option value="exam">Sınav</option><option value="interview">Sözlü / mülakat</option><option value="result">Sonuç açıklanacak</option>
        <option value="documents">Evrak teslimi</option><option value="appointment">Atama</option>
      </select>
      <input type="date" aria-label="Tarih" value={day} onChange={(event) => setDay(event.target.value)} required />
      <button className="button button-small button-primary" disabled={add.isPending}>Ekle</button>
      <button type="button" className="button button-small" onClick={() => setOpen(false)}>Vazgeç</button>
      {add.error && <span className="field-error" role="alert">{add.error.message}</span>}
    </form>
  );
}

function PositionDetail({ jobId, position, multiple }: { jobId: number; position: MatchedPosition; multiple: boolean }) {
  const facts: Array<[string, string | null]> = [
    ["Başvuru", position.application_start || position.application_deadline
      ? `${formatDate(position.application_start, "?")} – ${formatDate(position.application_deadline, "?")}` : null],
    ["Kontenjan", position.quota],
    ["Görev yeri", position.city],
    ["KPSS", position.kpss_score_type ? `${position.kpss_score_type.replace(/\//g, ", ")}${position.kpss_min_score !== null ? ` · en az ${position.kpss_min_score}` : ""}` : null],
    ["Alım yöntemi", position.recruitment_method === "Kaynakta belirtilmedi" ? null : position.recruitment_method],
    ["İstihdam türü", position.employment_type === "Kaynakta belirtilmedi" ? null : position.employment_type],
  ];
  const checked = position.match.requirements.filter((item) => item.status !== "not_required");
  const notRequired = position.match.requirements.filter((item) => item.status === "not_required");
  return (
    <>
      <section className="drawer-section">
        <h3>{multiple ? `${position.position}: şartlar ve profiliniz` : "Şartlar ve profiliniz"}</h3>
        {multiple && (
          <div className="position-verify">
            <span className="muted">Bu kadro için kararınız:</span>
            <VerifyButtons jobId={jobId} positionId={position.id} verification={position.verification?.scope === "position" ? position.verification : null} compact />
          </div>
        )}
        <ul className="requirement-list">
          {checked.map((item, index) => (
            <li key={`${item.name}-${index}`}>
              <StatusDot status={item.status} />
              <div>
                <strong>{item.name} <span className={`status-text status-${item.status}`}>{STATUS_LABEL[item.status]}</span></strong>
                <p>{item.detail}</p>
                {item.evidence && <blockquote>“{item.evidence}”</blockquote>}
              </div>
            </li>
          ))}
        </ul>
        {notRequired.length > 0 && <p className="hint">İlan metninde aranmıyor: {notRequired.map((item) => item.name).join(", ")}.</p>}
        {position.basis && (
          <p className="hint">
            Dayanak: <a href={position.basis.document_url} target="_blank" rel="noreferrer">{position.basis.document_title}</a>, kadro tablosu {position.basis.table_row}. satır.
          </p>
        )}
        {position.match.kpss.status === "met" && (
          <p className="hint">
            Taban puanı karşılamak yalnızca başvuru şartıdır; sınava çağrılma{position.written_exam_invite_count ? ` (kontenjanın ${position.written_exam_invite_count} katı aday)` : ""} ve yerleşme puan sıralamasına bağlıdır.
          </p>
        )}
        {position.match.general_conditions.length > 0 && <p className="hint">Genel şartlar: {position.match.general_conditions.join(", ")}.</p>}
      </section>
      <section className="drawer-section">
        <h3>İlan bilgileri</h3>
        <dl className="fact-grid">
          {facts.filter(([, value]) => value).map(([label, value]) => (
            <div key={label}><dt>{label}</dt><dd>{value}</dd></div>
          ))}
        </dl>
        {position.education_requirement && (
          <div className="quote"><span>Aranan öğrenim</span><p>{position.education_requirement}</p></div>
        )}
      </section>
    </>
  );
}
