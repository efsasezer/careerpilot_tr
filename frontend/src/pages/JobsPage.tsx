import { useMemo, useState } from "react";
import { Search, X } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { JobCard } from "../components/jobs/JobCard";
import { PageHeader } from "../components/shared/PageHeader";
import { EmptyState, QueryState } from "../components/shared/QueryState";
import { useMatches } from "../services/api/hooks";
import type { MatchCategory } from "../types/api";
import { CATEGORY_LABEL, groupByJob, sortGroups, type JobGroup } from "../utils/format";

const CATEGORIES: MatchCategory[] = ["UYGUN", "POTANSİYEL OLARAK UYGUN", "UYGUN DEĞİL"];
const PAGE_SIZE = 30;

export default function JobsPage({ tracked = false }: { tracked?: boolean }) {
  const query = useMatches();
  const [params, setParams] = useSearchParams();
  const requested = params.get("durum") as MatchCategory | null;
  const category: MatchCategory | "all" = tracked ? "all" : requested && CATEGORIES.includes(requested) ? requested : "UYGUN";
  const [search, setSearch] = useState("");
  const [source, setSource] = useState("");
  const [status, setStatus] = useState(tracked ? "all" : "active");
  const [onlyPreferred, setOnlyPreferred] = useState(false);
  const [order, setOrder] = useState<"relevance" | "deadline" | "newest">("deadline");
  const [limit, setLimit] = useState(PAGE_SIZE);

  const all = query.data?.jobs ?? [];
  const sources = useMemo(() => [...new Set(all.map((job) => job.source_name))].sort(), [all]);
  const hasPreference = all.some((job) => job.location_match !== null);

  const { groups, counts } = useMemo(() => {
    const term = search.trim().toLocaleLowerCase("tr-TR");
    const visible = all.filter((job) => {
      if (tracked ? !(job.tracking === "saved" || job.tracking === "applied") : job.tracking === "hidden") return false;
      if (status === "active" && job.is_expired) return false;
      if (status === "open" && job.application_status !== "Başvuru Açık") return false;
      if (status === "upcoming" && job.application_status !== "Başvuru Başlamadı") return false;
      if (source && job.source_name !== source) return false;
      if (onlyPreferred && job.location_match === false) return false;
      if (term && !`${job.organization} ${job.title} ${job.position} ${job.city ?? ""} ${job.education_requirement}`.toLocaleLowerCase("tr-TR").includes(term)) return false;
      return true;
    });
    const grouped = groupByJob(visible);
    const counts = Object.fromEntries(CATEGORIES.map((key) => [key, grouped.filter((group) => group.category === key).length])) as Record<MatchCategory, number>;
    const selected: JobGroup[] = category === "all" ? grouped : grouped.filter((group) => group.category === category);
    return { groups: sortGroups(selected, tracked ? "deadline" : order), counts };
  }, [all, search, source, status, onlyPreferred, order, category, tracked]);

  function selectCategory(next: MatchCategory) {
    const updated = new URLSearchParams(params);
    updated.set("durum", next);
    setParams(updated);
    setLimit(PAGE_SIZE);
  }

  return (
    <QueryState isLoading={query.isLoading} error={query.error}>
      <PageHeader
        title={tracked ? "Takip listem" : "İlanlar"}
        description={tracked
          ? "Kaydettiğiniz ve başvurduğunuz ilanlar. Kaydedilen ilanların son başvurusu yaklaşınca bildirim alırsınız."
          : "Bütün kaynaklardaki kamu ilanları, profilinize göre sınıflandırılmış halde."}
      />

      {!tracked && (
        <div className="tabs" role="tablist" aria-label="Uygunluk durumu">
          {CATEGORIES.map((key) => (
            <button key={key} role="tab" aria-selected={category === key} className={category === key ? "tab tab-active" : "tab"} onClick={() => selectCategory(key)}>
              {CATEGORY_LABEL[key]} <span>{counts[key]}</span>
            </button>
          ))}
        </div>
      )}

      <div className="filter-bar">
        <label className="search-field">
          <Search size={17} aria-hidden />
          <span className="sr-only">İlanlarda ara</span>
          <input value={search} onChange={(event) => { setSearch(event.target.value); setLimit(PAGE_SIZE); }} placeholder="Kurum, pozisyon, şehir veya bölüm ara" />
          {search && <button type="button" className="icon-button" onClick={() => setSearch("")} aria-label="Aramayı temizle"><X size={16} /></button>}
        </label>
        <label className="select-field">
          <span>Başvuru</span>
          <select value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="active">Açık ve açılacak</option>
            <option value="open">Yalnızca açık</option>
            <option value="upcoming">Henüz açılmadı</option>
            <option value="all">Tümü (süresi dolanlar dahil)</option>
          </select>
        </label>
        <label className="select-field">
          <span>Kaynak</span>
          <select value={source} onChange={(event) => setSource(event.target.value)}>
            <option value="">Tüm kaynaklar</option>
            {sources.map((name) => <option key={name}>{name}</option>)}
          </select>
        </label>
        {!tracked && (
          <label className="select-field">
            <span>Sıralama</span>
            <select value={order} onChange={(event) => setOrder(event.target.value as typeof order)}>
              <option value="deadline">Son başvuru tarihi</option>
              <option value="newest">En yeni ilan</option>
            </select>
          </label>
        )}
        {hasPreference && (
          <label className="check-field">
            <input type="checkbox" checked={onlyPreferred} onChange={(event) => setOnlyPreferred(event.target.checked)} />
            Tercih ettiğim şehirler
          </label>
        )}
      </div>

      {groups.length ? (
        <>
          <p className="result-count">{groups.length} ilan</p>
          <div className="job-list">{groups.slice(0, limit).map((group) => <JobCard key={group.jobId} group={group} />)}</div>
          {groups.length > limit && (
            <button className="button load-more" onClick={() => setLimit(limit + PAGE_SIZE)}>Daha fazla göster ({groups.length - limit})</button>
          )}
        </>
      ) : (
        <EmptyState title={tracked ? "Henüz takip ettiğiniz ilan yok" : "Bu filtrelerle ilan bulunamadı"}>
          {tracked ? "Bir ilanı açıp “Kaydet” veya “Başvurdum” dediğinizde burada görünür." : "Aramayı veya filtreleri değiştirip yeniden deneyin."}
        </EmptyState>
      )}

      {!tracked && (query.data?.education_opportunities.length ?? 0) > 0 && (
        <section className="panel opportunities">
          <h2>Eğitim ve burs duyuruları</h2>
          <ul className="link-list">
            {query.data!.education_opportunities.map((item) => (
              <li key={item.id}>
                {item.source_url ? <a href={item.source_url} target="_blank" rel="noreferrer">{item.title}</a> : item.title}
                <span>{item.organization} · {item.application_status}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </QueryState>
  );
}
