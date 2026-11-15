import { ExternalLink, RefreshCw } from "lucide-react";
import { PageHeader } from "../components/shared/PageHeader";
import { QueryState } from "../components/shared/QueryState";
import { useHealth, useSources, useStartSync, useSyncStatus } from "../services/api/hooks";
import { formatTimestamp } from "../utils/format";

export default function SourcesPage() {
  const query = useSources();
  const health = useHealth();
  const sync = useSyncStatus();
  const start = useStartSync();
  const readOnly = health.data?.read_only ?? true;
  const running = sync.data?.running ?? false;
  const report = sync.data?.report;
  const autoHours = health.data?.auto_sync_hours ?? 0;

  return (
    <QueryState isLoading={query.isLoading} error={query.error}>
      <PageHeader
        title="Kaynaklar"
        description={autoHours > 0
          ? `Resmî ilan kaynakları her ${autoHours} saatte bir otomatik taranır. İsterseniz şimdi de tarayabilirsiniz.`
          : "Resmî ilan kaynakları. Bu yayında otomatik tarama kapalı."}
        action={
          <button className="button button-primary" disabled={readOnly || running || start.isPending} onClick={() => start.mutate()}>
            <RefreshCw size={16} className={running ? "spin" : ""} /> {running ? "Taranıyor…" : "Şimdi tara"}
          </button>
        }
      />
      {readOnly && <p className="notice notice-info">Salt okunur yayında tarama başlatılamaz; kayıtlı ilanlar gösterilir.</p>}
      {start.error && <p className="notice notice-bad" role="alert">{start.error.message}</p>}
      {running && sync.data?.progress && (
        <p className="notice notice-info" role="status">
          {sync.data.progress.source} taranıyor{sync.data.progress.total ? ` (${sync.data.progress.current}/${sync.data.progress.total})` : ""}. Bu işlem birkaç dakika sürebilir; sayfadan ayrılabilirsiniz.
        </p>
      )}
      {!running && sync.data?.error && <p className="notice notice-bad" role="alert">Tarama tamamlanamadı: {sync.data.error}</p>}
      {!running && report && (
        <p className={`notice ${report.success ? "notice-ok" : "notice-warn"}`} role="status">
          Son tarama {formatTimestamp(sync.data?.finished_at)} tarihinde bitti:{" "}
          {Object.values(report.results).reduce((sum, item) => sum + item.imported, 0)} yeni ilan,{" "}
          {Object.values(report.results).reduce((sum, item) => sum + item.updated, 0)} güncelleme
          {report.notifications ? `, ${report.notifications.created} yeni bildirim` : ""}.
          {!report.success && " Bazı ilanların ayrıntısı okunamadı; aşağıdaki notlara bakın."}
        </p>
      )}

      <div className="source-grid">
        {(query.data ?? []).map((source) => {
          const tone = source.status === "Aktif" ? "ok" : source.status === "Hata" ? "bad" : source.status === "Kısmi" ? "warn" : "muted";
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
                <div><dt>Yeni / güncellenen</dt><dd>{source.last_created} / {source.last_updated}</dd></div>
                <div><dt>Ayrıntısı okunamayan</dt><dd>{source.last_detail_failed}</dd></div>
                <div><dt>Son tarama</dt><dd>{formatTimestamp(source.last_sync, "Henüz taranmadı")}</dd></div>
              </dl>
              {source.last_error && <p className="source-error">{source.last_error}</p>}
              <a className="text-link" href={source.url} target="_blank" rel="noreferrer">Resmî siteyi aç <ExternalLink size={14} /></a>
            </article>
          );
        })}
      </div>
    </QueryState>
  );
}
