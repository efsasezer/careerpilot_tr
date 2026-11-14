import { useState, type FormEvent, type ReactNode } from "react";
import { PageHeader } from "../components/shared/PageHeader";
import { QueryState } from "../components/shared/QueryState";
import { useHealth, useProfile, useUpdateProfile } from "../services/api/hooks";
import type { Profile, ProfileUpdate } from "../types/api";
import { formatBoolean, formatTimestamp } from "../utils/format";

export default function ProfilePage() {
  const query = useProfile();
  const health = useHealth();
  const updateProfile = useUpdateProfile();
  const profile = query.data;
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<ProfileUpdate | null>(null);
  const [saved, setSaved] = useState(false);
  const readOnly = health.data?.demo_mode !== false;

  function startEditing() {
    if (!profile) return;
    setDraft(toProfileUpdate(profile));
    setSaved(false);
    updateProfile.reset();
    setEditing(true);
  }

  function cancelEditing() {
    setEditing(false);
    setDraft(null);
    updateProfile.reset();
  }

  function updateField<K extends keyof ProfileUpdate>(
    key: K,
    value: ProfileUpdate[K],
  ) {
    setDraft((current) => current ? { ...current, [key]: value } : current);
  }

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft) return;
    updateProfile.mutate(draft, {
      onSuccess: () => {
        setEditing(false);
        setDraft(null);
        setSaved(true);
      },
    });
  }

  return (
    <QueryState isLoading={query.isLoading} error={query.error}>
      {profile && <>
        <PageHeader
          eyebrow="KİŞİSEL ALAN"
          title="Aday profili"
          description="Profil bilgilerini güncelle; kaydedince uygunluk analizleri yenilenir."
          action={!editing && (
            <button
              className={`button ${readOnly ? "button-disabled" : "button-outline"}`}
              onClick={startEditing}
              disabled={readOnly}
            >
              {readOnly ? "Salt okunur mod" : "Profili düzenle"}
            </button>
          )}
        />
        <section className="profile-hero panel">
          <div className="avatar-mark">{profile.department.slice(0, 1) || "A"}</div>
          <div>
            <span className="eyebrow">ADAY PROFİLİ</span>
            <h2>{profile.department || "Bölüm belirtilmemiş"}</h2>
            <p>{profile.degree} · {profile.university || "Üniversite belirtilmemiş"}</p>
          </div>
          <div className="score-highlight">
            <small>KPSS {profile.kpss_score_type}</small>
            <strong>{profile.kpss_p3?.toFixed(2) ?? "—"}</strong>
          </div>
        </section>

        {editing && draft ? (
          <form className="profile-sections" onSubmit={save}>
            <ProfileSection title="Eğitim ve sınav">
              <ProfileInput label="Eğitim seviyesi" value={draft.degree} onChange={(value) => updateField("degree", value)} />
              <ProfileInput label="Bölüm" value={draft.department} onChange={(value) => updateField("department", value)} />
              <ProfileInput label="Üniversite" value={draft.university} onChange={(value) => updateField("university", value)} />
              <ProfileInput label="KPSS puan türü" value={draft.kpss_score_type} onChange={(value) => updateField("kpss_score_type", value)} />
              <ProfileInput label="KPSS P3" type="number" min={0} max={100} step={0.01} value={draft.kpss_p3} onChange={(value) => updateField("kpss_p3", numberOrNull(value))} />
              <ProfileInput label="YDS / dil puanı" type="number" min={0} max={100} step={0.01} value={draft.yds_score} onChange={(value) => updateField("yds_score", numberOrNull(value))} />
            </ProfileSection>
            <ProfileSection title="Tercihler ve deneyim">
              <ProfileInput label="Tercih edilen konumlar" value={draft.preferred_locations} onChange={(value) => updateField("preferred_locations", value)} />
              <BooleanInput label="Vardiyalı çalışma" value={draft.accepts_shifts} onChange={(value) => updateField("accepts_shifts", value)} />
              <ProfileInput label="Yaş" type="number" min={0} step={1} value={draft.age} onChange={(value) => updateField("age", numberOrNull(value))} />
              <ProfileInput label="Mesleki deneyim (yıl)" type="number" min={0} step={0.5} value={draft.experience_years} onChange={(value) => updateField("experience_years", numberOrNull(value))} />
              <BooleanInput label="Sürücü belgesi" value={draft.driver_license} onChange={(value) => updateField("driver_license", value)} />
              <BooleanInput label="Staj deneyimi var" value={draft.has_internship} onChange={(value) => updateField("has_internship", value)} />
              <ProfileTextarea label="Staj deneyimi açıklaması" value={draft.internship_description} onChange={(value) => updateField("internship_description", value)} />
            </ProfileSection>
            <ProfileSection title="Beceriler ve belgeler">
              <ProfileTextarea label="Teknik beceriler" value={draft.skills} onChange={(value) => updateField("skills", value)} />
              <ProfileTextarea label="Programlama dili kanıtları" value={draft.programming_language_evidence} onChange={(value) => updateField("programming_language_evidence", value)} />
              <ProfileTextarea label="Sertifikalar" value={draft.certificates} onChange={(value) => updateField("certificates", value)} />
            </ProfileSection>
            <ProfileSection title="Notlar">
              <ProfileTextarea label="Kişisel notlar" value={draft.notes} onChange={(value) => updateField("notes", value)} />
            </ProfileSection>
            {updateProfile.error && (
              <p className="profile-save-error" role="alert">
                Kaydedilemedi: {updateProfile.error.message}
              </p>
            )}
            <div className="profile-edit-actions">
              <button type="button" className="button button-outline" onClick={cancelEditing}>
                İptal
              </button>
              <button type="submit" className="button button-primary" disabled={updateProfile.isPending}>
                {updateProfile.isPending ? "Kaydediliyor…" : "Değişiklikleri kaydet"}
              </button>
            </div>
          </form>
        ) : (
          <>
            {readOnly && (
              <p className="readonly-hint">
                Profil düzenlemek için backend&apos;de salt okunur demo modunu kapatın.
              </p>
            )}
            <div className="profile-sections">
              <ProfileSection title="Eğitim ve sınav">
                <Field label="Eğitim seviyesi" value={profile.degree} />
                <Field label="Bölüm" value={profile.department} />
                <Field label="Üniversite" value={profile.university} />
                <Field label="KPSS puan türü" value={profile.kpss_score_type} />
                <Field label="KPSS P3" value={profile.kpss_p3?.toFixed(2)} />
                <Field label="YDS / dil puanı" value={profile.yds_score} />
              </ProfileSection>
              <ProfileSection title="Tercihler ve deneyim">
                <Field label="Tercih edilen konumlar" value={profile.preferred_locations} />
                <Field label="Vardiyalı çalışma" value={formatBoolean(profile.accepts_shifts)} />
                <Field label="Yaş" value={profile.age} />
                <Field label="Mesleki deneyim (yıl)" value={profile.experience_years} />
                <Field label="Sürücü belgesi" value={formatBoolean(profile.driver_license)} />
                <Field label="Staj deneyimi" value={profile.internship_description} />
              </ProfileSection>
              <ProfileSection title="Beceriler ve belgeler">
                <Field label="Teknik beceriler" value={profile.skills} />
                <Field label="Programlama dili kanıtları" value={profile.programming_language_evidence} />
                <Field label="Sertifikalar" value={profile.certificates} />
              </ProfileSection>
              <ProfileSection title="Notlar ve güncelleme">
                <Field label="Kişisel notlar" value={profile.notes} />
                <Field label="Son güncelleme" value={formatTimestamp(profile.updated_at)} />
              </ProfileSection>
            </div>
            {saved && <p className="profile-save-success" role="status">Profil güncellendi.</p>}
          </>
        )}
      </>}
    </QueryState>
  );
}

function toProfileUpdate(profile: Profile): ProfileUpdate {
  const { id: _id, updated_at: _updatedAt, ...fields } = profile;
  return fields;
}

function numberOrNull(value: string): number | null {
  if (!value.trim()) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function ProfileSection({ title, children }: { title: string; children: ReactNode }) {
  return <section className="panel profile-section"><h2>{title}</h2><div className="field-grid">{children}</div></section>;
}

function ProfileInput({
  label,
  value,
  onChange,
  type = "text",
  min,
  max,
  step,
}: {
  label: string;
  value: string | number | null;
  onChange: (value: string) => void;
  type?: "text" | "number";
  min?: number;
  max?: number;
  step?: number;
}) {
  return (
    <label className="field-label profile-edit-field">
      {label}
      <input
        aria-label={label}
        type={type}
        min={min}
        max={max}
        step={step}
        value={value ?? ""}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

function BooleanInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean | null;
  onChange: (value: boolean | null) => void;
}) {
  return (
    <label className="field-label profile-edit-field">
      {label}
      <select
        aria-label={label}
        value={value === null ? "" : String(value)}
        onChange={(event) => onChange(
          event.target.value === "" ? null : event.target.value === "true",
        )}
      >
        <option value="">Belirtilmedi</option>
        <option value="true">Evet</option>
        <option value="false">Hayır</option>
      </select>
    </label>
  );
}

function ProfileTextarea({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="field-label profile-edit-field">
      {label}
      <textarea
        aria-label={label}
        rows={3}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

function Field({ label, value }: { label: string; value: unknown }) {
  const display = value === null || value === undefined || value === "" ? "Belirtilmemiş" : String(value);
  return <div className="profile-field"><span>{label}</span><strong>{display}</strong></div>;
}
