import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Plus, Save, Trash2 } from "lucide-react";
import { PageHeader } from "../components/shared/PageHeader";
import { QueryState } from "../components/shared/QueryState";
import { useHealth, useProfile, useUpdateProfile } from "../services/api/hooks";
import type { Profile, ProfileUpdate } from "../types/api";
import { formatTimestamp } from "../utils/format";

const DEGREES = ["Ortaöğretim (Lise)", "Ön Lisans", "Lisans", "Yüksek Lisans", "Doktora"];
const COMMON_SCORE_TYPES = ["P3", "P93", "P94", "P1", "P2", "P10", "P121"];

interface ScoreRow { type: string; score: string }

function toDraft(profile: Profile): ProfileUpdate {
  const { id: _id, updated_at: _updatedAt, ...fields } = profile;
  return fields;
}

export default function ProfilePage() {
  const query = useProfile();
  const health = useHealth();
  const update = useUpdateProfile();
  const readOnly = health.data?.read_only ?? true;
  const [draft, setDraft] = useState<ProfileUpdate | null>(null);
  const [scores, setScores] = useState<ScoreRow[]>([]);
  const [message, setMessage] = useState("");
  const [scoreError, setScoreError] = useState("");

  useEffect(() => {
    if (!query.data) return;
    setDraft(toDraft(query.data));
    const rows = Object.entries(query.data.kpss_scores).map(([type, score]) => ({ type, score: String(score) }));
    setScores(rows.length ? rows : [{ type: "P3", score: "" }]);
  }, [query.data]);

  function set<K extends keyof ProfileUpdate>(key: K, value: ProfileUpdate[K]) {
    setMessage("");
    setDraft((current) => (current ? { ...current, [key]: value } : current));
  }

  function save(event: FormEvent) {
    event.preventDefault();
    if (!draft) return;
    const kpss: Record<string, number> = {};
    for (const row of scores) {
      const type = row.type.trim().toUpperCase().replace(/^KPSS\s*-?/, "");
      if (!type && !row.score.trim()) continue;
      const score = Number(row.score.replace(",", "."));
      if (!/^P\d{1,3}$/.test(type) || !row.score.trim() || !Number.isFinite(score) || score < 0 || score > 100) {
        setScoreError("Puan türü P3, P93 gibi yazılmalı; puan 0 ile 100 arasında olmalı.");
        return;
      }
      kpss[type] = score;
    }
    setScoreError("");
    update.mutate({ ...draft, kpss_scores: kpss }, { onSuccess: () => setMessage("Profil kaydedildi. İlanlar yeni bilgilere göre yeniden değerlendirildi.") });
  }

  return (
    <QueryState isLoading={query.isLoading || !draft} error={query.error}>
      {draft && (
        <form onSubmit={save} className="profile-form">
          <PageHeader
            title="Profilim"
            description={`İlanlar bu bilgilere göre değerlendirilir. Boş bıraktığınız alanlar “doğrulanmalı” sonucu üretir. Son güncelleme: ${formatTimestamp(query.data?.updated_at, "henüz yok")}.`}
            action={<button type="submit" className="button button-primary" disabled={readOnly || update.isPending}><Save size={16} /> {update.isPending ? "Kaydediliyor…" : "Kaydet"}</button>}
          />
          {readOnly && <p className="notice notice-info">Salt okunur yayında profil değiştirilemez.</p>}
          {message && <p className="notice notice-ok" role="status">{message}</p>}
          {update.error && <p className="notice notice-bad" role="alert">Kaydedilemedi: {update.error.message}</p>}

          <fieldset disabled={readOnly} className="form-sections">
            <Section title="Öğrenim" help="Bölüm adını diplomanızdaki gibi yazın. İlanlarda farklı adla geçebilecek eşdeğer bölümleri ayrıca ekleyebilirsiniz.">
              <Field label="Öğrenim düzeyi">
                <select value={draft.degree} onChange={(event) => set("degree", event.target.value)}>
                  <option value="">Seçin</option>
                  {[...new Set([...DEGREES, draft.degree].filter(Boolean))].map((degree) => <option key={degree}>{degree}</option>)}
                </select>
              </Field>
              <Field label="Bölüm / program"><input value={draft.department} onChange={(event) => set("department", event.target.value)} placeholder="Örn. İktisat" /></Field>
              <Field label="Fakülte / yüksekokul"><input value={draft.faculty} onChange={(event) => set("faculty", event.target.value)} placeholder="Örn. İktisadi ve İdari Bilimler Fakültesi" /></Field>
              <Field label="Üniversite"><input value={draft.university} onChange={(event) => set("university", event.target.value)} /></Field>
              <Field label="Eşdeğer sayılan bölümler" wide help="Virgülle ayırın. Örn. Yazılım Mühendisliği, Bilgisayar Bilimleri Mühendisliği">
                <input value={draft.department_aliases} onChange={(event) => set("department_aliases", event.target.value)} />
              </Field>
            </Section>

            <Section title="KPSS puanları" help="Sahip olduğunuz bütün puan türlerini girin; ilan hangi türü istiyorsa o puanınız kullanılır.">
              <div className="score-rows">
                {scores.map((row, index) => (
                  <div className="score-row" key={index}>
                    <label><span>Puan türü</span>
                      <input list="score-types" value={row.type} onChange={(event) => setScores(scores.map((item, i) => (i === index ? { ...item, type: event.target.value } : item)))} placeholder="P3" />
                    </label>
                    <label><span>Puan</span>
                      <input inputMode="decimal" value={row.score} onChange={(event) => setScores(scores.map((item, i) => (i === index ? { ...item, score: event.target.value } : item)))} placeholder="0–100" />
                    </label>
                    <button type="button" className="icon-button" aria-label={`${row.type || "Puan"} satırını sil`} onClick={() => setScores(scores.filter((_, i) => i !== index))}><Trash2 size={17} /></button>
                  </div>
                ))}
                <datalist id="score-types">{COMMON_SCORE_TYPES.map((type) => <option key={type} value={type} />)}</datalist>
                {scoreError && <p className="field-error" role="alert">{scoreError}</p>}
                <button type="button" className="button" onClick={() => setScores([...scores, { type: "", score: "" }])}><Plus size={16} /> Puan türü ekle</button>
              </div>
            </Section>

            <Section title="Kişisel bilgiler" help="Yaş, cinsiyet ve ehliyet gibi bilgiler bazı kadroların özel şartlarında aranır.">
              <Field label="Yaş"><input type="number" min={15} max={80} value={draft.age ?? ""} onChange={(event) => set("age", numberOrNull(event.target.value))} /></Field>
              <Field label="Cinsiyet">
                <select value={draft.gender} onChange={(event) => set("gender", event.target.value)}>
                  <option value="">Belirtmek istemiyorum</option><option>Kadın</option><option>Erkek</option>
                </select>
              </Field>
              <Field label="Sürücü belgesi"><TriState value={draft.driver_license} onChange={(value) => set("driver_license", value)} yes="Var" no="Yok" /></Field>
              <Field label="Vardiyalı çalışma"><TriState value={draft.accepts_shifts} onChange={(value) => set("accepts_shifts", value)} yes="Kabul ediyorum" no="Kabul etmiyorum" /></Field>
              <Field label="Özel statü" help="Yalnızca bu statüdeki adaylara açık ilanlar için.">
                <select value={draft.special_status} onChange={(event) => set("special_status", event.target.value)}>
                  <option value="">Yok</option><option value="engelli">Engelli (EKPSS)</option><option value="eski hükümlü">Eski hükümlü / terörle mücadelede yaralanan</option>
                </select>
              </Field>
              <Field label="Tercih ettiğim şehirler" help="Virgülle ayırın veya “Türkiye geneli” yazın.">
                <input value={draft.preferred_locations} onChange={(event) => set("preferred_locations", event.target.value)} />
              </Field>
            </Section>

            <Section title="Dil, deneyim ve belgeler">
              <Field label="YDS / e-YDS puanı"><input type="number" min={0} max={100} step="0.01" value={draft.yds_score ?? ""} onChange={(event) => set("yds_score", numberOrNull(event.target.value))} /></Field>
              <Field label="Mesleki deneyim (yıl)"><input type="number" min={0} max={60} step="0.5" value={draft.experience_years ?? ""} onChange={(event) => set("experience_years", numberOrNull(event.target.value))} /></Field>
              <Field label="Sertifikalar" wide help="Virgülle ayırın."><textarea rows={2} value={draft.certificates} onChange={(event) => set("certificates", event.target.value)} /></Field>
              <Field label="Bildiğim programlama dilleri (belgeleyebildiklerim)" wide help="Bilişim personeli ilanlarında aranır; ilgili değilse boş bırakın.">
                <textarea rows={2} value={draft.programming_language_evidence} onChange={(event) => set("programming_language_evidence", event.target.value)} />
              </Field>
              <Field label="Notlar" wide><textarea rows={3} value={draft.notes} onChange={(event) => set("notes", event.target.value)} /></Field>
            </Section>
          </fieldset>
        </form>
      )}
    </QueryState>
  );
}

function numberOrNull(value: string): number | null {
  if (!value.trim()) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function Section({ title, help, children }: { title: string; help?: string; children: ReactNode }) {
  return (
    <section className="form-section">
      <div className="form-section-head"><h2>{title}</h2>{help && <p>{help}</p>}</div>
      <div className="form-grid">{children}</div>
    </section>
  );
}

function Field({ label, help, wide, children }: { label: string; help?: string; wide?: boolean; children: ReactNode }) {
  return (
    <label className={`field ${wide ? "field-wide" : ""}`}>
      <span>{label}</span>
      {children}
      {help && <small>{help}</small>}
    </label>
  );
}

function TriState({ value, onChange, yes, no }: { value: boolean | null; onChange: (value: boolean | null) => void; yes: string; no: string }) {
  return (
    <select value={value === null ? "" : String(value)} onChange={(event) => onChange(event.target.value === "" ? null : event.target.value === "true")}>
      <option value="">Belirtilmedi</option><option value="true">{yes}</option><option value="false">{no}</option>
    </select>
  );
}
