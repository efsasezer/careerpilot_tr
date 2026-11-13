import { useMemo, useState } from "react";
import { PageHeader } from "../components/shared/PageHeader";
import { MatchCard } from "../components/shared/MatchCard";
import { QueryState } from "../components/shared/QueryState";
import { useMatches } from "../services/api/hooks";
import type { MatchCategory } from "../types/api";

const categories: MatchCategory[] = ["UYGUN", "POTANSİYEL OLARAK UYGUN", "UYGUN DEĞİL"];

export default function MatchesPage() {
  const query = useMatches();
  const [active, setActive] = useState<MatchCategory>("UYGUN");
  const [search, setSearch] = useState("");
  const jobs = query.data?.jobs ?? [];
  const counts = query.data?.counts;
  const filtered = useMemo(() => jobs.filter((job) => {
    const term = search.trim().toLocaleLowerCase("tr-TR");
    return job.match.category === active && (!term || `${job.position} ${job.organization} ${job.match.reason}`.toLocaleLowerCase("tr-TR").includes(term));
  }), [jobs, active, search]);

  return (
    <QueryState isLoading={query.isLoading} error={query.error}>
      <PageHeader eyebrow="PROFİL EŞLEŞTİRMESİ" title="Uygunluk analizi" description="Her sonuç mevcut aday profiliniz ve backend uygunluk motorundan gelir. Sınıflandırma bu ekranda yeniden hesaplanmaz." />
      <div className="match-tabs" role="tablist">{categories.map((category) => <button key={category} role="tab" aria-selected={active === category} className={active === category ? "active" : ""} onClick={() => setActive(category)}><span>{category}</span><strong>{counts?.[category] ?? 0}</strong></button>)}</div>
      <div className="match-filter-row"><input aria-label="Analizlerde ara" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Kurum, pozisyon veya gerekçede ara" /><span>{filtered.length} analiz</span></div>
      <div className="analysis-list">{filtered.map((job) => <MatchCard key={job.id} job={job} />)}</div>
      {!filtered.length && <div className="panel empty-state"><strong>Bu kategoride sonuç yok</strong><span>Aramanızı değiştirin veya başka uygunluk sekmesi seçin.</span></div>}
    </QueryState>
  );
}
