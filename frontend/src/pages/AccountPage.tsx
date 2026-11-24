import { ExternalLink, MonitorUp } from "lucide-react";
import { useOpenJob } from "../components/jobs/JobCard";
import { PageHeader } from "../components/shared/PageHeader";
import { EmptyState, QueryState } from "../components/shared/QueryState";
import { useAccount, useAccountImport } from "../services/api/hooks";
import { formatDate, formatTimestamp } from "../utils/format";

const MATCH_LABEL: Record<string, string> = { matched: "İlanla eşleşti", confirmed: "İlanla eşleşti", needs_review: "Eşleşme doğrulanmalı", unmatched: "İlan havuzunda yok" };
const SECTION_STATUS: Record<string, string> = { ok: "Okundu", empty: "Kayıt yok", not_found: "Menüde bulunamadı", unreadable: "Okunamadı", error: "Hata" };

export default function AccountPage() {
  const query = useAccount();
  const start = useAccountImport();
  const open = useOpenJob();

  return (
    <QueryState isLoading={query.isLoading} error={query.error}>
      {query.data && (() => {
        const data = query.data;
        const attempt = data.last_attempt;
        return (
          <>
            <PageHeader
              title="Kariyer Kapısı hesabım"
              description="Başvurularım, İptal Edilen Başvurularım ve Sınav Bilgilerim bölümlerini kendi oturumunla aktarır."
              action={<button className="button button-primary" disabled={!data.can_import_here || data.running || start.isPending} onClick={() => start.mutate()}>
                <MonitorUp size={16} /> {data.running ? "Aktarım sürüyor…" : "Tarayıcıyı aç ve aktar"}
              </button>}
            />
            {!data.verified && (
              <p className="notice notice-warn">
                Bu bağlantı henüz gerçek bir hesapla doğrulanmadı. Hesap sayfaları yalnızca giriş yapılınca görülebildiği için ilk aktarımda
                sayfa yapısı beklenenden farklı çıkabilir; öyle olursa burada “okunamadı” yazar, hiçbir kayıt uydurulmaz.
              </p>
            )}
            {!data.can_import_here && <p className="notice notice-info">{data.cannot_import_reason}</p>}
            {data.running && <p className="notice notice-info" role="status">{data.message}</p>}
            {start.error && <p className="field-error" role="alert">{start.error.message}</p>}

            <section className="panel ylsy-section">
              <h2>Nasıl çalışır</h2>
              <ul className="plain-list">
                <li>Bu bilgisayarda bir tarayıcı penceresi açılır; e-Devlet girişini <strong>sen</strong> yaparsın. Şifren uygulamaya ulaşmaz ve hiçbir yere kaydedilmez.</li>
                <li>Girişten sonra üç bölüm okunur, pencere kapanır ve oturum biter. Güvenlik doğrulamaları atlanmaz.</li>
                <li>e-Devlet oturumu kısa sürdüğü için aktarım kendiliğinden yinelenemez; güncellemek için bu düğmeye yeniden basman gerekir.</li>
                <li>Aynı kayıt ikinci kez eklenmez; durum ve sonuç bilgisi güncellenir. Sınav tarihleri takvime işlenir.</li>
              </ul>
              <dl className="fact-list">
                <div><dt>Son başarılı aktarım</dt><dd>{formatTimestamp(data.last_success, "Henüz yapılmadı")}</dd></div>
                {attempt && <div><dt>Son deneme</dt><dd>{formatTimestamp(attempt.at)}{attempt.error ? ` · ${attempt.error}` : ""}</dd></div>}
                {attempt && Object.entries(attempt.sections).map(([name, info]) => (
                  <div key={name}><dt>{{ applications: "Başvurularım", cancelled: "İptal Edilen Başvurularım", exams: "Sınav Bilgilerim" }[name] ?? name}</dt>
                    <dd>{SECTION_STATUS[info.status] ?? info.status}{info.count ? ` (${info.count})` : ""}{info.detail ? ` · ${info.detail}` : ""}</dd></div>
                ))}
              </dl>
              <a className="text-link" href="https://kariyerkapisi.gov.tr/isealim" target="_blank" rel="noreferrer">Kariyer Kapısı'nı kendin aç <ExternalLink size={13} /></a>
            </section>

            {data.items.length ? (
              <div className="table-wrap">
                <table className="data-table">
                  <thead><tr><th>Bölüm</th><th>Kurum / ilan</th><th>Başvuru</th><th>Durum</th><th>Sınav</th><th>Sonuç</th><th>Eşleşme</th></tr></thead>
                  <tbody>
                    {data.items.map((item) => (
                      <tr key={item.id}>
                        <td>{item.section_label}</td>
                        <td><strong>{item.organization}</strong><br />{item.title}</td>
                        <td>{item.applied_date ? formatDate(item.applied_date) : "—"}</td>
                        <td>{item.status || "—"}</td>
                        <td>{item.exam_date ? `${formatDate(item.exam_date)} ${item.exam_time}` : "—"}{item.exam_place ? <><br />{item.exam_place}</> : null}</td>
                        <td>{item.result || "—"}</td>
                        <td>{item.job_id ? <button className="text-button" onClick={() => open(item.job_id as number)}>{MATCH_LABEL[item.match_status]}</button> : MATCH_LABEL[item.match_status]}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <EmptyState title="Henüz aktarılmış kayıt yok">Aktarım yapılana kadar başvuruların ve sınav bilgilerin burada görünmez. Bu, başvurun olmadığı anlamına gelmez.</EmptyState>}
          </>
        );
      })()}
    </QueryState>
  );
}
