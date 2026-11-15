import { useEffect, useState } from "react";
import { Bookmark, CheckCheck, ExternalLink, EyeOff, X } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { CategoryBadge, DeadlineChip, StatusDot } from "../shared/Badges";
import { QueryState } from "../shared/QueryState";
import { useHealth, useJobDetail, useSetTracking } from "../../services/api/hooks";
import type { JobDetail, MatchedPosition, Tracking } from "../../types/api";
import { formatDate } from "../../utils/format";

const ORDER = { UYGUN: 0, "POTANSİYEL OLARAK UYGUN": 1, "UYGUN DEĞİL": 2 } as const;

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
  const health = useHealth();
  const tracking = useSetTracking();
  const readOnly = health.data?.read_only ?? true;
  const [current, setCurrent] = useState<Tracking>(job.tracking);
  const [notes, setNotes] = useState(job.notes);
  const positions = [...job.positions].sort((a, b) => ORDER[a.match.category] - ORDER[b.match.category]);
  const [selectedId, setSelectedId] = useState(positions[0].id);
  const selected = positions.find((item) => item.id === selectedId) ?? positions[0];
  const documents = job.document_review?.documents ?? [];

  function setTracking(value: Tracking) {
    const next = current === value ? "" : value;
    setCurrent(next);
    tracking.mutate({ jobId: job.id, tracking: next, notes });
  }

  return (
    <div className="drawer-body">
      <p className="drawer-org">{job.organization}</p>
      <h2>{job.title}</h2>
      <div className="drawer-chips">
        <CategoryBadge category={selected.match.category} />
        <DeadlineChip daysLeft={selected.days_left} status={selected.application_status} />
      </div>

      <div className="drawer-actions">
        <button className={`button ${current === "saved" ? "button-active" : ""}`} disabled={readOnly} onClick={() => setTracking("saved")}>
          <Bookmark size={16} /> {current === "saved" ? "Kaydedildi" : "Kaydet"}
        </button>
        <button className={`button ${current === "applied" ? "button-active" : ""}`} disabled={readOnly} onClick={() => setTracking("applied")}>
          <CheckCheck size={16} /> {current === "applied" ? "Başvuruldu" : "Başvurdum"}
        </button>
        <button className={`button ${current === "hidden" ? "button-active" : ""}`} disabled={readOnly} onClick={() => setTracking("hidden")}>
          <EyeOff size={16} /> {current === "hidden" ? "Gizlendi" : "İlgilenmiyorum"}
        </button>
        {job.source_url && (
          <a className="button button-primary" href={job.source_url} target="_blank" rel="noreferrer">
            Resmî ilana git <ExternalLink size={15} />
          </a>
        )}
      </div>
      {job.source_name === "SBB Kamu İlanları" && (
        <p className="hint">SBB ilan bağlantıları oturuma özeldir; açılan listede kurum adını arayın. İlanın resmî metni aşağıda yer alıyor.</p>
      )}

      {positions.length > 1 && (
        <section className="drawer-section">
          <h3>Pozisyonlar ({positions.length})</h3>
          <div className="position-list">
            {positions.map((item) => (
              <button key={item.id} className={`position-row ${item.id === selected.id ? "position-row-active" : ""}`} onClick={() => setSelectedId(item.id)}>
                <span>{item.position}</span>
                <CategoryBadge category={item.match.category} />
              </button>
            ))}
          </div>
        </section>
      )}

      <PositionDetail position={selected} showTitle={positions.length > 1} />

      <section className="drawer-section">
        <h3>Notlarım</h3>
        <label className="sr-only" htmlFor="job-notes">İlan notu</label>
        <textarea id="job-notes" rows={3} value={notes} disabled={readOnly} onChange={(event) => setNotes(event.target.value)}
          onBlur={() => notes !== job.notes && tracking.mutate({ jobId: job.id, tracking: current, notes })}
          placeholder={readOnly ? "Salt okunur modda not eklenemez" : "Hazırlanacak belgeler, hatırlatmalar…"} />
      </section>

      {(documents.length > 0 || selected.also_listed.length > 0) && (
        <section className="drawer-section">
          <h3>Kaynaklar ve belgeler</h3>
          <ul className="link-list">
            {documents.map((document) => (
              <li key={document.id}>
                <a href={document.url} target="_blank" rel="noreferrer">{document.title || "Resmî belge"} <ExternalLink size={13} /></a>
                <span>{document.status === "read" ? "Okundu" : document.status === "partially_read" ? "Kısmen okundu" : "Otomatik okunamadı, bağlantıdan açın"}</span>
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

function PositionDetail({ position, showTitle }: { position: MatchedPosition; showTitle: boolean }) {
  const facts: Array<[string, string | null]> = [
    ["Başvuru", position.application_start || position.application_deadline
      ? `${formatDate(position.application_start, "?")} – ${formatDate(position.application_deadline, "?")}` : null],
    ["Kontenjan", position.quota],
    ["Görev yeri", position.city],
    ["KPSS", position.kpss_score_type ? `${position.kpss_score_type.replace(/\//g, ", ")}${position.kpss_min_score !== null ? ` · en az ${position.kpss_min_score}` : ""}` : null],
    ["Alım yöntemi", position.recruitment_method === "Kaynakta belirtilmedi" ? null : position.recruitment_method],
    ["İstihdam türü", position.employment_type === "Kaynakta belirtilmedi" ? null : position.employment_type],
  ];
  return (
    <>
      <section className="drawer-section">
        <h3>{showTitle ? position.position : "Şartlar ve profiliniz"}</h3>
        <ul className="requirement-list">
          {position.match.requirements.map((item, index) => (
            <li key={`${item.name}-${index}`}>
              <StatusDot status={item.status} />
              <div><strong>{item.name}</strong><p>{item.detail}</p></div>
            </li>
          ))}
        </ul>
        {position.match.general_conditions.length > 0 && (
          <p className="hint">Genel şartlar: {position.match.general_conditions.join(", ")}.</p>
        )}
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
