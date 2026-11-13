import { Activity, ExternalLink, Radio, RefreshCw } from "lucide-react";
import { PageHeader } from "../components/shared/PageHeader";
import { QueryState } from "../components/shared/QueryState";
import { useSources } from "../services/api/hooks";
import { formatTimestamp } from "../utils/format";

export default function SourcesPage() {
  const query = useSources();
  return (
    <QueryState isLoading={query.isLoading} error={query.error}>
      <PageHeader eyebrow="VERİ ENTEGRASYONLARI" title="Veri kaynakları" description="Kaynak durumları backend kayıtlarından gelir. Bu salt-okunur yayında senkronizasyon işlemleri devre dışıdır." />
      <div className="source-grid">{(query.data ?? []).map((source) => {
        const hasError = Boolean(source.last_error) || source.status.toLocaleLowerCase("tr-TR").includes("hata");
        return <article className="panel source-card" key={source.name}>
          <div className="source-card-top"><span className="source-icon"><Radio size={19} /></span><span className={`source-status ${hasError ? "status-error" : ""}`}><Activity size={13} />{source.status}</span></div>
          <h2>{source.name}</h2><p>{source.description}</p>
          <div className="source-stats"><div><small>Kayıtlı ilan</small><strong>{source.job_count}</strong></div><div><small>Son bulunan</small><strong>{source.last_found}</strong></div><div><small>Son eklenen</small><strong>{source.last_created}</strong></div></div>
          <div className="source-last-sync"><span>Son senkronizasyon</span><strong>{formatTimestamp(source.last_sync)}</strong></div>
          {source.last_error && <div className="source-error"><strong>Son hata</strong><p>{source.last_error}</p></div>}
          <a className="button button-outline button-wide" href={source.url} target="_blank" rel="noreferrer">Resmî kaynağı aç <ExternalLink size={14} /></a>
          <button className="button button-disabled button-wide" disabled title="Yayın salt okunur"><RefreshCw size={14} /> Senkronizasyon kapalı</button>
        </article>;
      })}</div>
    </QueryState>
  );
}
