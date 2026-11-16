import { useEffect, useState, type FormEvent } from "react";
import { BellRing, LogOut, Save, Send } from "lucide-react";
import { PageHeader } from "../components/shared/PageHeader";
import { QueryState } from "../components/shared/QueryState";
import { useNotificationSettings, useSaveNotificationSettings, useTestNotification } from "../services/api/hooks";
import type { MatchCategory, NotificationSettings } from "../types/api";

export default function SettingsPage({ onLogout }: { onLogout: () => void }) {
  const query = useNotificationSettings();
  const save = useSaveNotificationSettings();
  const test = useTestNotification();
  const [draft, setDraft] = useState<NotificationSettings | null>(null);
  const [saved, setSaved] = useState(false);
  const [permission, setPermission] = useState(() => ("Notification" in window ? Notification.permission : "unsupported"));

  useEffect(() => { if (query.data) setDraft(query.data); }, [query.data]);

  function set<K extends keyof NotificationSettings>(key: K, value: NotificationSettings[K]) {
    setSaved(false);
    setDraft((current) => (current ? { ...current, [key]: value } : current));
  }

  function toggleCategory(category: MatchCategory, checked: boolean) {
    if (!draft) return;
    set("notify_categories", checked ? [...new Set([...draft.notify_categories, category])] : draft.notify_categories.filter((item) => item !== category));
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!draft) return;
    const { email_available: _e, telegram_available: _t, ...body } = draft;
    save.mutate(body, { onSuccess: () => setSaved(true) });
  }

  return (
    <QueryState isLoading={query.isLoading || !draft} error={query.error}>
      {draft && (
        <>
          <PageHeader title="Ayarlar" description="Hangi ilanlar için, hangi kanaldan haber almak istediğinizi belirleyin." />
          <form className="form-sections" onSubmit={submit}>
            <fieldset className="form-sections">
              <section className="form-section">
                <div className="form-section-head"><h2>Ne zaman bildirim gelsin?</h2><p>Bildirimler her kaynak taramasından sonra oluşturulur.</p></div>
                <div className="check-stack">
                  <label className="check-field"><input type="checkbox" checked={draft.notify_categories.includes("UYGUN")} onChange={(event) => toggleCategory("UYGUN", event.target.checked)} /> Profilime tam uyan yeni ilanlar</label>
                  <label className="check-field"><input type="checkbox" checked={draft.notify_categories.includes("POTANSİYEL OLARAK UYGUN")} onChange={(event) => toggleCategory("POTANSİYEL OLARAK UYGUN", event.target.checked)} /> Doğrulanması gereken (olası uygun) yeni ilanlar</label>
                  <label className="check-field"><input type="checkbox" checked={draft.only_preferred_locations} onChange={(event) => set("only_preferred_locations", event.target.checked)} /> Yalnızca tercih ettiğim şehirlerdeki ilanlar</label>
                  <label className="field field-inline">
                    <span>Son başvuruya kaç gün kala hatırlatılsın?</span>
                    <input type="number" min={0} max={30} value={draft.deadline_reminder_days} onChange={(event) => set("deadline_reminder_days", Number(event.target.value) || 0)} />
                    <small>0 yazarsanız hatırlatma gönderilmez.</small>
                  </label>
                </div>
              </section>

              <section className="form-section">
                <div className="form-section-head"><h2>Bildirim kanalları</h2><p>Uygulama içi bildirimler her zaman açıktır. E-posta ve Telegram için sunucuda ilgili ayarın tanımlı olması gerekir.</p></div>
                <div className="check-stack">
                  <div className="channel">
                    <div><strong>Tarayıcı bildirimi</strong><p className="muted">Uygulama açıkken yeni bildirim geldiğinde masaüstü uyarısı gösterir.</p></div>
                    {permission === "granted" ? <span className="badge badge-ok">Açık</span>
                      : permission === "unsupported" ? <span className="badge badge-muted">Desteklenmiyor</span>
                      : <button type="button" className="button" onClick={() => Notification.requestPermission().then(setPermission)}><BellRing size={16} /> İzin ver</button>}
                  </div>
                  <div className="channel">
                    <label className="check-field"><input type="checkbox" checked={draft.email_enabled} onChange={(event) => set("email_enabled", event.target.checked)} /> E-posta</label>
                    <label className="field"><span>E-posta adresi</span><input type="email" value={draft.email_to} onChange={(event) => set("email_to", event.target.value)} placeholder="ad@ornek.com" /></label>
                    {!draft.email_available && <p className="field-note">Sunucuda SMTP ayarı yok (CAREERPILOT_SMTP_HOST); tanımlanana kadar e-posta gönderilmez.</p>}
                  </div>
                  <div className="channel">
                    <label className="check-field"><input type="checkbox" checked={draft.telegram_enabled} onChange={(event) => set("telegram_enabled", event.target.checked)} /> Telegram</label>
                    <label className="field"><span>Telegram sohbet kimliği (chat ID)</span><input value={draft.telegram_chat_id} onChange={(event) => set("telegram_chat_id", event.target.value)} placeholder="123456789" /></label>
                    {!draft.telegram_available && <p className="field-note">Sunucuda bot anahtarı yok (CAREERPILOT_TELEGRAM_BOT_TOKEN); tanımlanana kadar mesaj gönderilmez.</p>}
                  </div>
                </div>
                {save.error && <p className="notice notice-bad" role="alert">{save.error.message}</p>}
                {saved && <p className="notice notice-ok" role="status">Bildirim ayarları kaydedildi.</p>}
                {test.data && <p className="notice notice-info" role="status">Test sonucu: {Object.entries(test.data.channels).map(([channel, result]) => `${channel}: ${result}`).join(" · ")}</p>}
                {test.error && <p className="notice notice-bad" role="alert">{test.error.message}</p>}
                <div className="button-row">
                  <button type="submit" className="button button-primary" disabled={save.isPending}><Save size={16} /> Kaydet</button>
                  <button type="button" className="button" disabled={test.isPending} onClick={() => test.mutate()}><Send size={16} /> Test bildirimi gönder</button>
                </div>
              </section>
            </fieldset>

            <section className="form-section">
              <div className="form-section-head"><h2>Oturum</h2></div>
<p className="muted">Şifreniz tarayıcıda saklanmaz; oturum sunucuda tutulur ve “Oturumu kapat” ile geçersiz olur.</p>
              <div className="button-row"><button type="button" className="button" onClick={onLogout}><LogOut size={16} /> Oturumu kapat</button></div>
            </section>
          </form>
        </>
      )}
    </QueryState>
  );
}
