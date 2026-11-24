import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Plus, Save, Trash2 } from "lucide-react";
import { PageHeader } from "../components/shared/PageHeader";
import { QueryState } from "../components/shared/QueryState";
import { useProfile, useUpdateProfile } from "../services/api/hooks";
import type { Profile, ProfileUpdate } from "../types/api";
import { formatTimestamp } from "../utils/format";

const LEVELS = ["Ortaöğretim (Lise)", "Ön Lisans", "Lisans", "Yüksek Lisans", "Doktora"];
const COMMON_SCORE_TYPES = ["P3", "P93", "P94", "P1", "P2", "P10", "P121"];
const MILITARY = ["Yapıldı", "Muaf", "Tecilli", "Yapılmadı", "Yükümlü değil"];

interface ScoreRow { type: string; score: string }
type Education = Profile["educations"][number];
type Experience = Profile["experiences"][number];

function toDraft(profile: Profile): ProfileUpdate {
  const { id: _id, updated_at: _updatedAt, ...fields } = profile;
  // Eski kayıtlarda yalnızca tek bölüm alanı vardı; eğitim listesine taşınır.
  if (!fields.educations.length && (fields.department || fields.degree)) {
    fields.educations = [{ level: fields.degree, school: fields.university, department: fields.department, year: "" }];
  }
  return fields;
}

function totalExperience(items: Experience[]) {
  let months = 0;
  const now = new Date();
  for (const item of items) {
    if (!/^\d{4}-\d{2}$/.test(item.start)) continue;
    const [startYear, startMonth] = item.start.split("-").map(Number);
    const [endYear, endMonth] = /^\d{4}-\d{2}$/.test(item.end) ? item.end.split("-").map(Number) : [now.getFullYear(), now.getMonth() + 1];
    months += Math.max(0, (endYear - startYear) * 12 + (endMonth - startMonth));
  }
  return months ? `${Math.floor(months / 12)} yıl ${months % 12} ay` : "—";
}

const listToText = (items?: string[]) => (items ?? []).join(", ");
const textToList = (text: string) => text.split(",").map((item) => item.trim()).filter(Boolean);

export default function ProfilePage() {
  const query = useProfile();
  const update = useUpdateProfile();
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
  const setEducation = (index: number, patch: Partial<Education>) =>
    draft && set("educations", draft.educations.map((item, i) => (i === index ? { ...item, ...patch } : item)));
  const setExperience = (index: number, patch: Partial<Experience>) =>
    draft && set("experiences", draft.experiences.map((item, i) => (i === index ? { ...item, ...patch } : item)));
  const setPreference = (key: keyof Profile["preferences"], text: string) =>
    draft && set("preferences", { ...draft.preferences, [key]: textToList(text) });

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
    const educations = draft.educations.filter((item) => item.level || item.department || item.school);
    const top = [...educations].sort((a, b) => LEVELS.indexOf(b.level) - LEVELS.indexOf(a.level))[0];
    update.mutate({
      ...draft,
      educations,
      experiences: draft.experience_state === "none" ? [] : draft.experiences.filter((item) => item.organization || item.start),
      // Tek alanlı eski sürümlerle uyum: en yüksek düzeydeki kayıt ana öğrenim sayılır.
      degree: top?.level ?? "", department: top?.department ?? "", university: top?.school ?? "",
      kpss_scores: kpss,
    }, { onSuccess: () => setMessage("Profil kaydedildi. İlanlar yeni bilgilere göre yeniden değerlendirildi; elle verdiğiniz kararlar değişmedi.") });
  }

  return (
    <QueryState isLoading={query.isLoading || !draft} error={query.error}>
      {draft && (
        <form onSubmit={save} className="profile-form">
          <PageHeader
            title="Profilim"
            description={`İlanlar bu bilgilere göre değerlendirilir. “Belirtilmedi” bıraktığınız alan, ilan o şartı arıyorsa “bilinmiyor” sayılır; karşılamıyor sayılmaz. Son güncelleme: ${formatTimestamp(query.data?.updated_at, "henüz yok")}.`}
            action={<button type="submit" className="button button-primary" disabled={update.isPending}><Save size={16} /> {update.isPending ? "Kaydediliyor…" : "Kaydet"}</button>}
          />
          {message && <p className="notice notice-ok" role="status">{message}</p>}
          {update.error && <p className="notice notice-bad" role="alert">{update.error.message}</p>}

          <div className="form-sections">
            <Section title="Eğitim" help="Bölüm adını diplomanızdaki gibi yazın. Birden fazla mezuniyetiniz varsa hepsini ekleyin.">
              <div className="record-list field-wide">
                {draft.educations.map((item, index) => (
                  <div className="record-row record-row-education" key={index}>
                    <label><span>Düzey</span>
                      <select value={item.level} onChange={(event) => setEducation(index, { level: event.target.value })}>
                        <option value="">Seçin</option>
                        {[...new Set([...LEVELS, item.level].filter(Boolean))].map((level) => <option key={level}>{level}</option>)}
                      </select>
                    </label>
                    <label><span>Okul</span><input value={item.school} onChange={(event) => setEducation(index, { school: event.target.value })} /></label>
                    <label><span>Bölüm / program</span><input value={item.department} onChange={(event) => setEducation(index, { department: event.target.value })} placeholder="Örn. Bilgisayar Mühendisliği" /></label>
                    <label><span>Mezuniyet yılı</span><input inputMode="numeric" value={item.year} onChange={(event) => setEducation(index, { year: event.target.value })} /></label>
                    <button type="button" className="icon-button" aria-label="Eğitim kaydını sil" onClick={() => set("educations", draft.educations.filter((_, i) => i !== index))}><Trash2 size={17} /></button>
                  </div>
                ))}
                <button type="button" className="button" onClick={() => set("educations", [...draft.educations, { level: "", school: "", department: "", year: "" }])}><Plus size={16} /> Eğitim ekle</button>
              </div>
              <Field label="Fakülte / yüksekokul" help="Bazı ilanlar fakülte adıyla alım yapar."><input value={draft.faculty} onChange={(event) => set("faculty", event.target.value)} placeholder="Örn. Mühendislik Fakültesi" /></Field>
              <Field label="Eşdeğer sayılan bölümler" help="Virgülle ayırın. Örn. Yazılım Mühendisliği"><input value={draft.department_aliases} onChange={(event) => set("department_aliases", event.target.value)} /></Field>
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

            <Section title="Mesleki deneyim" help="Deneyim süresi, ilanın başvuru tarihine göre hesaplanır.">
              <Field label="Deneyim durumu" wide>
                <select value={draft.experience_state} onChange={(event) => set("experience_state", event.target.value as ProfileUpdate["experience_state"])}>
                  <option value="">Henüz belirtilmedi</option><option value="has">Deneyimim var</option><option value="none">Mesleki deneyimim yok</option>
                </select>
              </Field>
              {draft.experience_state === "has" && (
                <div className="record-list field-wide">
                  {draft.experiences.map((item, index) => (
                    <div className="record-row record-row-experience" key={index}>
                      <label><span>Kurum</span><input value={item.organization} onChange={(event) => setExperience(index, { organization: event.target.value })} /></label>
                      <label><span>Pozisyon</span><input value={item.position} onChange={(event) => setExperience(index, { position: event.target.value })} /></label>
                      <label><span>Başlangıç</span><input type="month" value={item.start} onChange={(event) => setExperience(index, { start: event.target.value })} /></label>
                      <label><span>Bitiş (sürüyorsa boş)</span><input type="month" value={item.end} onChange={(event) => setExperience(index, { end: event.target.value })} /></label>
                      <button type="button" className="icon-button" aria-label="Deneyim kaydını sil" onClick={() => set("experiences", draft.experiences.filter((_, i) => i !== index))}><Trash2 size={17} /></button>
                    </div>
                  ))}
                  <p className="muted">Toplam süre: {totalExperience(draft.experiences)}</p>
                  <button type="button" className="button" onClick={() => set("experiences", [...draft.experiences, { organization: "", position: "", start: "", end: "" }])}><Plus size={16} /> Deneyim ekle</button>
                </div>
              )}
            </Section>

            <Section title="Kişisel bilgiler" help="Yalnızca ilan o şartı arıyorsa kullanılır. Hepsi isteğe bağlıdır.">
              <Field label="Doğum tarihi" help="Yaş şartı ilanın başvuru tarihine göre hesaplanır."><input type="date" value={draft.birth_date ?? ""} onChange={(event) => set("birth_date", event.target.value || null)} /></Field>
              <Field label="Cinsiyet">
                <select value={draft.gender} onChange={(event) => set("gender", event.target.value)}>
                  <option value="">Henüz belirtilmedi</option><option>Kadın</option><option>Erkek</option>
                </select>
              </Field>
              <Field label="Askerlik durumu">
                <select value={draft.military_status} onChange={(event) => set("military_status", event.target.value)}>
                  <option value="">Henüz belirtilmedi</option>{MILITARY.map((item) => <option key={item}>{item}</option>)}
                </select>
              </Field>
              <Field label="Sürücü belgesi"><TriState value={draft.driver_license} onChange={(value) => set("driver_license", value)} yes="Var" no="Yok" /></Field>
              <Field label="Vardiyalı çalışma"><TriState value={draft.accepts_shifts} onChange={(value) => set("accepts_shifts", value)} yes="Kabul ediyorum" no="Kabul etmiyorum" /></Field>
              <Field label="Özel statü (isteğe bağlı)" help="Yalnızca bu statüdeki adaylara açık ilanlar için.">
                <select value={draft.special_status} onChange={(event) => set("special_status", event.target.value)}>
                  <option value="">Belirtmek istemiyorum / yok</option><option value="engelli">Engelli (EKPSS)</option><option value="eski hükümlü">Eski hükümlü / terörle mücadelede yaralanan</option>
                </select>
              </Field>
            </Section>

            <Section title="Dil ve belgeler">
              <Field label="YDS / e-YDS puanı" help="Yoksa boş bırakın (belirtilmedi)."><input type="number" min={0} max={100} step="0.01" value={draft.yds_score ?? ""} onChange={(event) => set("yds_score", numberOrNull(event.target.value))} /></Field>
              <Field label="ALES puanı" help="YLSY / 1416 bursları ve akademik ilanlar için."><input type="number" min={0} max={100} step="0.01" value={draft.ales_score ?? ""} onChange={(event) => set("ales_score", numberOrNull(event.target.value))} /></Field>
              <Field label="ALES puan türü" help="Sonuç belgendeki tür. Seçilmezse uygunluk kararı verilmez.">
                <select value={draft.ales_score_type} onChange={(event) => set("ales_score_type", event.target.value as typeof draft.ales_score_type)}>
                  <option value="">Henüz doğrulamadım</option><option value="sayisal">Sayısal (SAY)</option><option value="sozel">Sözel (SÖZ)</option><option value="esit_agirlik">Eşit Ağırlık (EA)</option>
                </select>
              </Field>
              <Field label="ALES sınav yılı"><input type="number" min={2000} max={2100} value={draft.ales_year ?? ""} onChange={(event) => set("ales_year", numberOrNull(event.target.value))} /></Field>
              <Field label="Lisans not ortalaması (4'lük)"><input type="number" min={0} max={4} step="0.01" value={draft.gpa ?? ""} onChange={(event) => set("gpa", numberOrNull(event.target.value))} /></Field>
              <Field label="Yabancı dil"><input value={draft.foreign_language} onChange={(event) => set("foreign_language", event.target.value)} placeholder="Örn. İngilizce (B2)" /></Field>
              <Field label="Sertifikalar" wide help="Virgülle ayırın."><textarea rows={2} value={draft.certificates} onChange={(event) => set("certificates", event.target.value)} /></Field>
              <Field label="Belgeleyebildiğim programlama dilleri" wide help="Bilişim personeli ilanlarında aranır; ilgili değilse boş bırakın.">
                <textarea rows={2} value={draft.programming_language_evidence} onChange={(event) => set("programming_language_evidence", event.target.value)} />
              </Field>
            </Section>

            <Section title="Tercihlerim" help="Tercihler resmî uygunluğu değiştirmez; şartları karşılayıp tercih dışı kalan ilan “Uygun – Tercih dışı” olarak görünür.">
              <Field label="İlgilendiğim şehirler" help="Virgülle ayırın. Boşsa Türkiye geneli."><input value={listToText(draft.preferences.cities)} onChange={(event) => setPreference("cities", event.target.value)} /></Field>
              <Field label="İstemediğim yerler" help="Virgülle ayırın."><input value={listToText(draft.preferences.excluded)} onChange={(event) => setPreference("excluded", event.target.value)} /></Field>
              <Field label="Kurum türleri" help="Örn. belediye, üniversite, bakanlık"><input value={listToText(draft.preferences.institution_types)} onChange={(event) => setPreference("institution_types", event.target.value)} /></Field>
              <Field label="Anahtar kelimeler" help="Örn. bilişim, yazılım"><input value={listToText(draft.preferences.keywords)} onChange={(event) => setPreference("keywords", event.target.value)} /></Field>
              <Field label="Notlar" wide><textarea rows={3} value={draft.notes} onChange={(event) => set("notes", event.target.value)} /></Field>
            </Section>
          </div>
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
      <option value="">Henüz belirtilmedi</option><option value="true">{yes}</option><option value="false">{no}</option>
    </select>
  );
}
