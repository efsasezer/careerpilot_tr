import { Activity, ExternalLink, Radio, RefreshCw } from "lucide-react";
import { PageHeader } from "../components/shared/PageHeader";
import { QueryState } from "../components/shared/QueryState";
import { useSources } from "../services/api/hooks";
import { formatTimestamp } from "../utils/format";
import { useHealth, useSyncSources } from "../services/api/hooks";

export default function SourcesPage() {
  const query = useSources();
  const health = useHealth();
  const sync = useSyncSources();
  const readOnly = health.data?.demo_mode !== false;
  return (
    <QueryState isLoading={query.isLoading} error={query.error}>
      <PageHeader eyebrow="VERİ ENTEGRASYONLARI" title="Veri kaynakları" description="Senkronizasyon yalnızca manuel başlatılır. Kontrol, liste sayfalarını tarar ve yalnızca yeni veya değişmiş ilanların detayını açar." />
      <div className="source-sync-control">
        <button
          className={`button ${readOnly ? "button-disabled" : "button-primary"}`}
          disabled={readOnly || sync.isPending}
          onClick={() => sync.mutate()}
        >
          <RefreshCw size={15} className={sync.isPending ? "spin" : ""} />
          {sync.isPending ? "Kaynaklar kontrol ediliyor…" : "Tüm kaynakları şimdi kontrol et"}
        </button>
        <p>Bir kaynak erişilemezse mevcut kayıtlar korunur; hata ve eksik detaylar ayrıca raporlanır.</p>
        {sync.isError && <p className="source-error" role="alert">{sync.error.message}</p>}
        {sync.data && <p role="status">{sync.data.success ? "Kontrol tamamlandı." : "Kontrol kısmen tamamlandı; kaynak hata ve detaylarını inceleyin."}</p>}
        {readOnly && <p>Yayındaki salt-okunur mod, veri değiştiren senkronizasyon işlemlerini kapatır.</p>}
      </div>
      <div className="source-grid">{(query.data ?? []).map((source) => {
        const hasError = Boolean(source.last_error) || source.status.toLocaleLowerCase("tr-TR").includes("hata");
        return <article className="panel source-card" key={source.name}>
          <div className="source-card-top"><span className="source-icon"><Radio size={19} /></span><span className={`source-status ${hasError ? "status-error" : ""}`}><Activity size={13} />{source.status}</span></div>
          <h2>{source.name}</h2><p>{source.description}</p>
          <div className="source-stats"><div><small>Kayıtlı ilan</small><strong>{source.job_count}</strong></div><div><small>Son bulunan</small><strong>{source.last_found}</strong></div><div><small>Son eklenen</small><strong>{source.last_created}</strong></div></div>
          {source.pages_checked !== undefined && <div className="source-last-sync"><span>Kontrol edilen sayfa / detay hatası</span><strong>{source.pages_checked} / {source.last_detail_failed ?? 0}</strong></div>}
          <div className="source-last-sync"><span>Son senkronizasyon</span><strong>{formatTimestamp(source.last_sync)}</strong></div>
          {source.last_error && <div className="source-error"><strong>Son hata</strong><p>{source.last_error}</p></div>}
          <a className="button button-outline button-wide" href={source.url} target="_blank" rel="noreferrer">Resmî kaynağı aç <ExternalLink size={14} /></a>
        </article>;
      })}</div>
    </QueryState>
  );
}
