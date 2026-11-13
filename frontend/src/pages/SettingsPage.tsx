import { CheckCircle2, ExternalLink, LogOut, ShieldCheck } from "lucide-react";
import { PageHeader } from "../components/shared/PageHeader";
import { QueryState } from "../components/shared/QueryState";
import { getApiUrl } from "../services/api/client";
import { useHealth } from "../services/api/hooks";

export default function SettingsPage({ onLogout }: { onLogout: () => void }) {
  const health = useHealth();
  return (
    <QueryState isLoading={health.isLoading} error={health.error}>
      <PageHeader eyebrow="UYGULAMA" title="Ayarlar" description="API bağlantısı ve bu oturumun erişim durumunu görüntüleyin." />
      <section className="panel settings-panel"><div className="settings-title"><ShieldCheck size={19} /><div><h2>Bağlantı ve erişim</h2><p>Özel API anahtarı yalnızca mevcut tarayıcı belleğinde tutulur.</p></div></div><div className="settings-row"><span>Backend adresi</span><strong>{getApiUrl()}</strong></div><div className="settings-row"><span>API durumu</span><strong className="connected"><CheckCircle2 size={16} /> {health.data?.status === "ok" ? "Bağlı" : "Yanıt bekleniyor"}</strong></div><div className="settings-row"><span>API sürümü</span><strong>{health.data?.version}</strong></div><div className="settings-row"><span>Çalışma modu</span><strong>Salt okunur</strong></div><div className="settings-row"><span>Veri kaynağı</span><strong>FastAPI · careerpilot.db</strong></div><div className="settings-actions"><a className="button button-outline" href={`${getApiUrl()}/docs`} target="_blank" rel="noreferrer">API dokümantasyonu <ExternalLink size={14} /></a><button className="button button-danger" onClick={onLogout}><LogOut size={15} /> Oturumu kapat</button></div></section>
      <p className="readonly-hint">Profil, ilanlar ve analiz verileri özel erişim anahtarıyla okunur. Bu dağıtımda veri değiştiren API metotları devre dışıdır.</p>
    </QueryState>
  );
}
