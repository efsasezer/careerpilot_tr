import { ExternalLink, RefreshCw } from "lucide-react";
import { useOpenJob } from "../components/jobs/JobCard";
import { PageHeader } from "../components/shared/PageHeader";
import { QueryState } from "../components/shared/QueryState";
import { useDiagnose, useRetryReading, useSources, useStartSync, useSyncStatus, useSystemStatus } from "../services/api/hooks";
import { formatTimestamp } from "../utils/format";

export default function SourcesPage() {
  const query = useSources();
  const retry = useRetryReading();
  const sync = useSyncStatus();
  const start = useStartSync();
  const open = useOpenJob();
  const system = useSystemStatus();
  const diagnose = useDiagnose();
  const running = sync.data?.running ?? false;
  const report = sync.data?.report;
  const hasOpenIssues = (query.data ?? []).some((source) =>
    source.status === "Hata" || source.status === "Uyarı" || source.last_detail_failed > 0,
  );

  return (
    <QueryState isLoading={query.isLoading} error={query.error}>
      <PageHeader
        title="Kaynaklar"
        description="Resmî ilan kaynakları. “Şimdi tara” bütün kaynakları yeniden okur; yalnızca yeni ya da değişen ilanların ayrıntısı indirilir."
        action={
          <>
            <button className="button" disabled={diagnose.isPending} onClick={() => diagnose.mutate()}>{diagnose.isPending ? "Ölçülüyor…" : "Erişim testi"}</button>
            <button className="button button-primary" disabled={running || start.isPending} onClick={() => start.mutate()}>
              <RefreshCw size={16} className={running ? "spin" : ""} /> {running ? "Taranıyor…" : "Şimdi tara"}
            </button>
          </>
        }
      />
      {start.error && <p className="notice notice-bad" role="alert">{start.error.message}</p>}
      {system.data && (
        <p className="hint">
          Tarama ortamı: {system.data.scan_origin} · otomatik tarama: {system.data.auto_scan_hours ? `${system.data.auto_scan_hours} saatte bir` : "kapalı (elle ya da zamanlanmış komutla)"}
          {" "}· son tarama: {formatTimestamp(system.data.last_scan_at, "henüz yok")} · saatler Türkiye saatine göredir.
        </p>
      )}
      {diagnose.error && <p className="notice notice-bad" role="alert">{diagnose.error.message}</p>}
      {diagnose.data && (
        <section className="panel diagnose-panel">
          <h2>Erişim testi — {diagnose.data.origin} (çıkış ülkesi: {diagnose.data.location.country})</h2>
          <p className="muted">
            Bu sunucudan her kaynağa bağlantı katman katman ölçüldü. Tarayıcı (Kariyer Kapısı ve İlan.gov.tr için gerekli):{" "}
            <strong>{diagnose.data.browser.ok ? "çalışıyor" : "çalışmıyor"}</strong> — {diagnose.data.browser.detail}
          </p>
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Kaynak</th><th>DNS</th><th>Bağlantı</th><th>Sertifika</th><th>HTTP</th><th>Sonuç</th></tr></thead>
              <tbody>
                {diagnose.data.targets.map((target) => {
                  const cell = (part?: { ok: boolean; seconds: number }) => (part ? `${part.ok ? "tamam" : "HATA"} (${part.seconds} sn)` : "—");
                  return (
                    <tr key={target.name}>
                      <td>{target.name}</td><td>{cell(target.dns)}</td><td>{cell(target.tcp)}</td><td>{cell(target.tls)}</td>
                      <td>{target.http ? `${target.http.status ?? "yanıt yok"} (${target.http.seconds} sn)` : "—"}</td><td>{target.verdict}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {diagnose.data.location.country !== "TR" && (
            <p className="hint">Bu sunucu Türkiye dışında. Yalnızca Türkiye'den erişime izin veren kaynaklar buradan taranamaz; bu bir yazılım hatası değildir ve aşılmaya çalışılmaz. Bu kaynaklar Türkiye'deki bir bilgisayardan taranıp aynı veritabanına yazılabilir.</p>
          )}
        </section>
      )}
      {running && sync.data?.progress && (
        <p className="notice notice-info" role="status">
          {sync.data.progress.source} taranıyor{sync.data.progress.total ? ` (${sync.data.progress.current}/${sync.data.progress.total})` : ""}. Bu işlem birkaç dakika sürebilir; sayfadan ayrılabilirsiniz.
        </p>
      )}
      {!running && sync.data?.error && <p className="notice notice-bad" role="alert">Tarama tamamlanamadı: {sync.data.error}</p>}
      {!running && report && (
        <p className={`notice ${report.success || !hasOpenIssues ? "notice-ok" : "notice-warn"}`} role="status">
          Son tarama {formatTimestamp(sync.data?.finished_at)} tarihinde bitti:{" "}
          {Object.values(report.results).reduce((sum, item) => sum + item.imported, 0)} yeni ilan,{" "}
          {Object.values(report.results).reduce((sum, item) => sum + item.updated, 0)} güncelleme
          {report.notifications ? `, ${report.notifications.created} yeni bildirim` : ""}.
          {!report.success && hasOpenIssues && " Bazı ilanların ayrıntısı okunamadı; aşağıdaki notlara bakın."}
        </p>
      )}

      <div className="source-grid">
        {(query.data ?? []).map((source) => {
          const tone = source.status === "Aktif" ? "ok" : source.status === "Hata" ? "bad" : source.status === "Kısmi" || source.status === "Uyarı" ? "warn" : "muted";
          return (
            <article className="panel source-card" key={source.name}>
              <div className="source-head">
                <h2>{source.name}</h2>
                <span className={`badge badge-${tone}`}>{source.status}</span>
              </div>
              <p className="muted">{source.description}</p>
              <dl className="fact-list">
                <div><dt>Kayıtlı ilan</dt><dd>{source.job_count}</dd></div>
                <div><dt>Son taramada bulunan</dt><dd>{source.last_found}</dd></div>
                <div><dt>Yeni / güncellenen / değişmeyen</dt><dd>{source.last_created} / {source.last_updated} / {source.last_unchanged}</dd></div>
                <div><dt>Kontrol edilen sayfa</dt><dd>{source.pages_checked}</dd></div>
                <div><dt>Ayrıntısı okunamayan</dt><dd>{source.last_detail_failed}</dd></div>
                <div><dt>Son kontrol</dt><dd>{formatTimestamp(source.last_sync, "Henüz taranmadı")}</dd></div>
                <div><dt>Son başarılı tarama</dt><dd>{formatTimestamp(source.last_success, "Henüz yok")}{source.last_success_origin ? ` · ${source.last_success_origin}` : ""}</dd></div>
                {source.read_from_other_source > 0 && <div><dt>Metni başka kaynaktan okunan</dt><dd>{source.read_from_other_source}</dd></div>}
              </dl>
              {source.stale && (
                <p className="notice notice-bad">
                  Bu kaynak {source.days_since_success === null ? "hiç başarıyla taranmadı" : `${source.days_since_success} gündür başarıyla taranamıyor`}.
                  Listedeki ilanlar son başarılı taramadan kalmadır; yeni ilanlar eksik olabilir.
                </p>
              )}
              {source.access_hint && <p className="notice notice-warn">{source.access_hint}</p>}
              {source.last_error && <p className="source-error">{source.error_kind_label ? `${source.error_kind_label}: ` : ""}{source.last_error}</p>}
              {source.failed_items.length > 0 && (
                <details className="failed-items">
                  <summary>Ayrıntısı okunamayan {source.failed_items.length} ilan (ilan havuzunda “Doğrulanmalı” olarak duruyor)</summary>
                  <ul>
                    {source.failed_items.map((item) => (
                      <li key={item.job_id}>
                        <button type="button" className="link-button" onClick={() => open(item.job_id)}>{item.title}</button>
                        <span>{item.reason}</span>
                        <button type="button" className="button button-small" disabled={retry.isPending} onClick={() => retry.mutate(item.job_id)}>
                          {retry.isPending && retry.variables === item.job_id ? "Okunuyor…" : "OCR'la yeniden dene"}
                        </button>
                      </li>
                    ))}
                  </ul>
                  {retry.data && <p className="hint">{retry.data.status === "failed" ? `Okunamadı: ${retry.data.error}` : "Belge okundu; ilan yeniden değerlendirildi."}</p>}
                </details>
              )}
              <a className="text-link" href={source.url} target="_blank" rel="noreferrer">Resmî siteyi aç <ExternalLink size={14} /></a>
            </article>
          );
        })}
      </div>
    </QueryState>
  );
}
