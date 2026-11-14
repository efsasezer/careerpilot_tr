import { useMemo, useState } from "react";
import { LayoutGrid, List, Search, SlidersHorizontal, X } from "lucide-react";
import { PageHeader } from "../components/shared/PageHeader";
import { QueryState } from "../components/shared/QueryState";
import { MatchBadge } from "../components/shared/MatchBadge";
import { MatchCard } from "../components/shared/MatchCard";
import { useMatches } from "../services/api/hooks";
import type { MatchedJob, MatchCategory } from "../types/api";
import { formatDate } from "../utils/format";

type ViewMode = "cards" | "table";

export default function JobsPage() {
  const query = useMatches();
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("Tümü");
  const [status, setStatus] = useState("Tümü");
  const [source, setSource] = useState("Tümü");
  const [city, setCity] = useState("Tümü");
  const [method, setMethod] = useState("Tümü");
  const [kpss, setKpss] = useState("Tümü");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [sort, setSort] = useState("deadline");
  const [view, setView] = useState<ViewMode>("cards");
  const [selected, setSelected] = useState<MatchedJob | null>(null);

  const jobs = query.data?.jobs ?? [];
  const sources = [...new Set(jobs.map((job) => job.source_name).filter(Boolean))].sort();
  const cities = [...new Set(jobs.map((job) => job.city).filter((value): value is string => Boolean(value)))].sort();
  const methods = [...new Set(jobs.map((job) => job.recruitment_method).filter(Boolean))].sort();
  const scoreTypes = [...new Set(jobs.map((job) => job.kpss_score_type).filter(Boolean))].sort();

  const filtered = useMemo(() => {
    const term = search.trim().toLocaleLowerCase("tr-TR");
    const result = jobs.filter((job) => {
      const searchable = `${job.organization} ${job.title} ${job.position} ${job.city ?? ""} ${job.description} ${job.source_name}`.toLocaleLowerCase("tr-TR");
      return (!term || searchable.includes(term))
        && (category === "Tümü" || job.match.category === category)
        && (status === "Tümü" || job.application_status === status)
        && (source === "Tümü" || job.source_name === source)
        && (city === "Tümü" || job.city === city)
        && (method === "Tümü" || job.recruitment_method === method)
        && (kpss === "Tümü" || job.kpss_score_type === kpss)
        && (!fromDate || !job.application_deadline || job.application_deadline >= fromDate)
        && (!toDate || !job.application_deadline || job.application_deadline <= toDate);
    });
    return result.sort((a, b) => {
      if (sort === "organization") return a.organization.localeCompare(b.organization, "tr");
      if (sort === "category") return a.match.category.localeCompare(b.match.category, "tr");
      return (a.application_deadline || "9999").localeCompare(b.application_deadline || "9999");
    });
  }, [jobs, search, category, status, source, city, method, kpss, fromDate, toDate, sort]);

  const clearFilters = () => {
    setSearch(""); setCategory("Tümü"); setStatus("Tümü"); setSource("Tümü");
    setCity("Tümü"); setMethod("Tümü"); setKpss("Tümü"); setFromDate(""); setToDate("");
  };

  return (
    <QueryState isLoading={query.isLoading} error={query.error}>
      <PageHeader eyebrow="İLAN HAVUZU" title="Kamu ilanları" description="Profil analizleriyle zenginleştirilmiş ilanlarda ara, filtrele ve koşulları incele." />
      <section className="panel filter-panel">
        <div className="filter-heading"><div><SlidersHorizontal size={17} /><strong>Arama ve filtreler</strong></div><button className="text-button" onClick={clearFilters}><X size={14} /> Filtreleri temizle</button></div>
        <div className="filter-grid">
          <label className="search-field filter-search"><Search size={17} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Kurum, pozisyon, şehir veya anahtar kelime" /></label>
          <FilterSelect label="Uygunluk" value={category} onChange={setCategory} options={["Tümü", "UYGUN", "POTANSİYEL OLARAK UYGUN", "UYGUN DEĞİL"]} />
          <FilterSelect label="Başvuru durumu" value={status} onChange={setStatus} options={["Tümü", "Başvuru Açık", "Başvuru Başlamadı", "Başvuru Sona Erdi", "Tarih belirtilmemiş"]} />
          <FilterSelect label="Kaynak" value={source} onChange={setSource} options={["Tümü", ...sources]} />
          <FilterSelect label="Kurum / şehir" value={city} onChange={setCity} options={["Tümü", ...cities]} />
          <FilterSelect label="Alım yöntemi" value={method} onChange={setMethod} options={["Tümü", ...methods]} />
          <FilterSelect label="KPSS türü" value={kpss} onChange={setKpss} options={["Tümü", ...scoreTypes]} />
          <label className="field-label">Son başvuru başlangıcı<input type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} /></label>
          <label className="field-label">Son başvuru bitişi<input type="date" value={toDate} onChange={(event) => setToDate(event.target.value)} /></label>
        </div>
      </section>
      <div className="results-toolbar">
        <strong>{filtered.length} <span>pozisyon</span></strong>
        <div className="toolbar-right">
          <label className="sort-control">Sırala
            <select value={sort} onChange={(event) => setSort(event.target.value)}><option value="deadline">Son başvuru tarihi</option><option value="organization">Kurum adı</option><option value="category">Uygunluk</option></select>
          </label>
          <div className="view-toggle" aria-label="Görünüm seçimi"><button className={view === "cards" ? "selected" : ""} onClick={() => setView("cards")} aria-label="Kart görünümü"><LayoutGrid size={16} /></button><button className={view === "table" ? "selected" : ""} onClick={() => setView("table")} aria-label="Tablo görünümü"><List size={16} /></button></div>
        </div>
      </div>
      {!filtered.length ? <div className="panel empty-state"><Search size={24} /><strong>Sonuç bulunamadı</strong><span>Filtrelerinizi değiştirip tekrar deneyin.</span></div> : view === "cards" ? (
        <div className="job-grid">{filtered.map((job) => <button className="job-card-button" key={job.id} onClick={() => setSelected(job)}><div className="job-card"><div className="job-card-head"><span className="source-tag">{job.source_name}</span><MatchBadge category={job.match.category} /></div><h3>{job.position}</h3><p className="job-company">{job.organization}</p><div className="job-card-meta"><span>{job.city || "Kaynakta bulunamadı"}</span><span>İstihdam türü · {job.employment_type || "Kaynakta belirtilmedi"}</span></div><div className="job-card-meta"><span>Alım yöntemi · {job.recruitment_method || "Kaynakta belirtilmedi"}</span><span>Kontenjan · {job.quota || "Kaynakta bulunamadı"}</span></div><div className="job-card-foot"><span>{job.application_status}</span><strong>Son başvuru · {formatDate(job.application_deadline, "Kaynakta bulunamadı")}</strong></div><div className="job-card-meta"><span>İlan · {formatDate(job.announcement_date, "Kaynakta bulunamadı")}</span><span>Başvuru · {formatDate(job.application_start, "Kaynakta bulunamadı")}</span></div></div></button>)}</div>
      ) : (
        <div className="panel table-panel"><div className="table-scroll"><table><thead><tr><th>Pozisyon / kurum</th><th>Kaynak</th><th>Şehir</th><th>İstihdam türü</th><th>Alım yöntemi</th><th>İlan tarihi</th><th>Başvuru başlangıcı</th><th>Son başvuru</th><th>Uygunluk</th><th /></tr></thead><tbody>{filtered.map((job) => <tr key={job.id} onClick={() => setSelected(job)}><td><strong>{job.position}</strong><small>{job.organization}</small></td><td>{job.source_name}</td><td>{job.city || "Kaynakta bulunamadı"}</td><td>{job.employment_type || "Kaynakta belirtilmedi"}</td><td>{job.recruitment_method || "Kaynakta belirtilmedi"}</td><td>{formatDate(job.announcement_date, "Kaynakta bulunamadı")}</td><td>{formatDate(job.application_start, "Kaynakta bulunamadı")}</td><td>{formatDate(job.application_deadline, "Kaynakta bulunamadı")}</td><td><MatchBadge category={job.match.category} /></td><td><button className="text-button">Detay</button></td></tr>)}</tbody></table></div></div>
      )}
      {selected && <JobDialog job={selected} onClose={() => setSelected(null)} />}
    </QueryState>
  );
}

function FilterSelect({ label, value, options, onChange }: { label: string; value: string; options: string[]; onChange: (value: string) => void }) {
  return <label className="field-label">{label}<select value={value} onChange={(event) => onChange(event.target.value)}>{options.map((option) => <option key={option}>{option}</option>)}</select></label>;
}

function JobDialog({ job, onClose }: { job: MatchedJob; onClose: () => void }) {
  return <div className="dialog-backdrop" role="presentation" onClick={onClose}><section className="job-dialog" role="dialog" aria-modal="true" aria-label={`${job.position} ilan detayı`} onClick={(event) => event.stopPropagation()}><div className="dialog-header"><div><span className="eyebrow">{job.organization}</span><h2>{job.position}</h2></div><button className="icon-button" onClick={onClose} aria-label="Detayı kapat"><X size={19} /></button></div><MatchCard job={job} /></section></div>;
}

export const MATCH_FILTERS: MatchCategory[] = ["UYGUN", "POTANSİYEL OLARAK UYGUN", "UYGUN DEĞİL"];
