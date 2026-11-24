import { ExternalLink, RefreshCw } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { PageHeader } from "../components/shared/PageHeader";
import { QueryState } from "../components/shared/QueryState";
import { useYlsy, useYlsySync } from "../services/api/hooks";
import type { YlsyCheck, YlsyField } from "../types/api";
import { formatDate, formatTimestamp } from "../utils/format";

const CHECK_LABEL: Record<YlsyCheck["status"], string> = { met: "Karşılıyor", not_met: "Karşılamıyor", unknown: "Doğrulanmalı", info: "Kendin doğrula" };
const CHECK_TONE: Record<YlsyCheck["status"], string> = { met: "badge-ok", not_met: "badge-bad", unknown: "badge-warn", info: "" };
const DECISION_TONE: Record<string, string> = { eligible: "notice-ok", not_eligible: "notice-bad", needs_verification: "notice-warn", no_fields: "notice-warn" };
const FIELD_STATUS: Record<string, string> = { met: "Uyuyor", not_met: "Uymuyor", unknown: "Doğrulanmalı" };

export default function YlsyPage() {
  const query = useYlsy();
  const sync = useYlsySync();
  const [showAll, setShowAll] = useState(false);
  const [filter, setFilter] = useState("");

  return (
    <QueryState isLoading={query.isLoading} error={query.error}>
      {query.data && (() => {
        const { assessment, announcements } = query.data;
        const fields = (assessment.fields ?? []).filter((field) =>
          !filter || `${field.group} ${field.institution} ${field.field} ${field.countries}`.toLocaleLowerCase("tr").includes(filter.toLocaleLowerCase("tr")));
        const groups = new Map<string, YlsyField[]>();
        for (const field of fields) groups.set(field.group, [...(groups.get(field.group) ?? []), field]);
        return (
          <>
            <PageHeader
              title="YLSY duyuruları"
              description={`Kaynak: ${query.data.source.name}. Duyurular her taramada kontrol edilir; yeni duyuru bildirim olarak gelir.`}
              action={<button className="button" disabled={sync.isPending} onClick={() => sync.mutate()}><RefreshCw size={16} className={sync.isPending ? "spin" : ""} /> Şimdi kontrol et</button>}
            />
            <p className={`notice ${query.data.current_year_announced ? "notice-ok" : "notice-info"}`}>{query.data.notice}</p>
            {query.data.sync?.status === "error" && (
              <p className="notice notice-bad" role="alert">
                Kaynak kontrol edilemedi: {query.data.sync.error} Bu, yeni duyuru olmadığı anlamına gelmez.
                {query.data.sync.last_success ? ` Son başarılı kontrol: ${formatTimestamp(query.data.sync.last_success)}.` : ""}
              </p>
            )}
            <p className="hint">
              Son kontrol: {formatTimestamp(query.data.sync?.checked_at ?? null, "henüz yapılmadı")} ·{" "}
              <a href={query.data.source.url} target="_blank" rel="noreferrer">Resmî duyuru sayfası <ExternalLink size={12} /></a>
            </p>

            <section className="panel ylsy-section">
              <h2>Şartlar ve durumun{assessment.cycle ? ` (${assessment.cycle} kılavuzuna göre)` : ""}</h2>
              {!assessment.available ? <p className="muted">{assessment.message}</p> : (
                <>
                  <p className={`notice ${DECISION_TONE[assessment.decision ?? ""] ?? "notice-info"}`}>{assessment.message}</p>
                  <p className="hint">
                    Kaynak: <a href={assessment.guide_url} target="_blank" rel="noreferrer">{assessment.guide_title} <ExternalLink size={12} /></a>
                    {assessment.guide_pdf && <> · <a href={assessment.guide_pdf} target="_blank" rel="noreferrer">Kılavuz (PDF) <ExternalLink size={12} /></a></>}
                    {assessment.guide_date ? ` · yayım ${formatDate(assessment.guide_date)}` : ""}
                  </p>
                  {assessment.application && (
                    <p className="hint">O dönemin başvuru tarihleri: {formatDate(assessment.application.start)} – {formatDate(assessment.application.end)}. Yeni dönemin tarihleri kılavuz yayımlanınca takvime eklenir ve hatırlatılır.</p>
                  )}
                  <ul className="check-list">
                    {(assessment.checks ?? []).map((check) => (
                      <li key={check.name}>
                        <div><strong>{check.name}</strong> <span className={`badge ${CHECK_TONE[check.status]}`}>{CHECK_LABEL[check.status]}</span></div>
                        <p>{check.detail}</p>
                        {check.evidence && <details><summary>Kılavuzdaki cümle</summary><p>{check.evidence}</p></details>}
                      </li>
                    ))}
                  </ul>
                  <Link to="/profile" className="text-link">ALES puan türü, sınav yılı, not ortalaması ve doğum tarihini profilden gir</Link>
                  {(assessment.read_errors ?? []).map((error) => <p className="field-error" key={error}>{error}</p>)}
                </>
              )}
            </section>

            {assessment.available && (assessment.fields?.length ?? 0) > 0 && (
              <section className="panel ylsy-section">
                <h2>Bölümünün kabul edildiği alanlar ({assessment.fields?.length})</h2>
                <p className="muted">Lisans alan kodu: {(assessment.department_codes ?? []).join(", ")}. Puan türü ve yaş sütunları profilindeki bilgilere göre doldurulur.</p>
                <input className="ylsy-filter" aria-label="Alanlarda ara" placeholder="Alan, kurum ya da ülke ara" value={filter} onChange={(event) => setFilter(event.target.value)} />
                <div className="table-wrap">
                  <table className="data-table">
                    <thead><tr><th>Alan</th><th>Adına öğrenim görülecek kurum</th><th>Seviye</th><th>Kont.</th><th>ALES türü</th><th>Puan türün</th><th>Yaş</th><th>Ülkeler</th></tr></thead>
                    <tbody>
                      {[...groups.entries()].slice(0, showAll || filter ? undefined : 6).flatMap(([group, rows]) => [
                        <tr key={group} className="table-group"><td colSpan={8}>{group}</td></tr>,
                        ...rows.map((row) => (
                          <tr key={`${row.area_code}-${row.institution}`}>
                            <td>{row.field}</td><td>{row.institution}</td><td>{row.level}</td><td>{row.quota}</td><td>{row.ales_types.join(" / ")}</td>
                            <td>{FIELD_STATUS[row.ales_type_status]}</td><td>{FIELD_STATUS[row.age_status]}</td><td>{row.countries}</td>
                          </tr>
                        )),
                      ])}
                    </tbody>
                  </table>
                </div>
                {!showAll && !filter && groups.size > 6 && <button className="text-button" onClick={() => setShowAll(true)}>Tüm grupları göster ({groups.size})</button>}
              </section>
            )}

            <section className="ylsy-section">
              <div className="section-head"><h2>Duyurular ({announcements.length})</h2></div>
              <ul className="announcement-list">
                {announcements.map((item) => (
                  <li key={item.id}>
                    <div className="announcement-meta">
                      <span className="chip chip-accent">{item.category_label}</span>
                      <span>{item.published_date ? formatDate(item.published_date) : "Tarih belirtilmemiş"}</span>
                      {!item.backfill && <span className="chip chip-warn">Yeni</span>}
                    </div>
                    <a href={item.url} target="_blank" rel="noreferrer"><strong>{item.title}</strong> <ExternalLink size={13} /></a>
                    {item.attachments.length > 0 && (
                      <details><summary>Ekler ({item.attachments.length})</summary>
                        <ul className="link-list">{item.attachments.map((file) => <li key={file.url}><a href={file.url} target="_blank" rel="noreferrer">{file.title} <ExternalLink size={12} /></a></li>)}</ul>
                      </details>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          </>
        );
      })()}
    </QueryState>
  );
}
