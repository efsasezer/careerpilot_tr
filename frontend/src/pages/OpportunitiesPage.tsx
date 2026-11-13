import { ExternalLink, GraduationCap } from "lucide-react";
import { PageHeader } from "../components/shared/PageHeader";
import { QueryState } from "../components/shared/QueryState";
import { useMatches } from "../services/api/hooks";
import { formatDate } from "../utils/format";

export default function OpportunitiesPage() {
  const query = useMatches();
  const items = query.data?.education_opportunities ?? [];
  return (
    <QueryState isLoading={query.isLoading} error={query.error}>
      <PageHeader eyebrow="EĞİTİM VE GELİŞİM" title="Eğitim & diğer fırsatlar" description="İstihdam dışı eğitim, burs ve gelişim duyuruları." />
      {items.length ? <div className="opportunity-list">{items.map((item) => <article className="panel opportunity-card" key={item.id}><span className="opportunity-icon"><GraduationCap size={21} /></span><div className="opportunity-body"><div className="eyebrow">{item.source_name} · {item.organization}</div><h2>{item.title}</h2><p>{item.description}</p><div className="opportunity-meta"><span>{item.city}</span><span>{item.application_status}</span><span>{formatDate(item.application_start)} → {formatDate(item.application_deadline)}</span></div>{item.source_url && <a className="text-link" href={item.source_url} target="_blank" rel="noreferrer">Duyuru sayfası <ExternalLink size={14} /></a>}</div></article>)}</div> : <div className="panel empty-state"><GraduationCap size={23} /><strong>Kayıtlı fırsat bulunmuyor</strong></div>}
    </QueryState>
  );
}
