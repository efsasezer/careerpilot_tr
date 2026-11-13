import { useProfile } from "../services/api/hooks";
import type { ReactNode } from "react";
import { PageHeader } from "../components/shared/PageHeader";
import { QueryState } from "../components/shared/QueryState";
import { formatBoolean, formatTimestamp } from "../utils/format";

export default function ProfilePage() {
  const query = useProfile();
  const profile = query.data;
  return (
    <QueryState isLoading={query.isLoading} error={query.error}>
      {profile && <>
        <PageHeader eyebrow="KİŞİSEL ALAN" title="Aday profili" description="Mevcut yerel veritabanındaki profil alanları. Bu yayın salt okunurdur; değişiklikler API üzerinden kabul edilmez." />
        <section className="profile-hero panel"><div className="avatar-mark">{profile.department.slice(0, 1) || "A"}</div><div><span className="eyebrow">ADAY PROFİLİ</span><h2>{profile.department || "Bölüm belirtilmemiş"}</h2><p>{profile.degree} · {profile.university || "Üniversite belirtilmemiş"}</p></div><div className="score-highlight"><small>KPSS {profile.kpss_score_type}</small><strong>{profile.kpss_p3?.toFixed(2) ?? "—"}</strong></div></section>
        <div className="profile-sections">
          <ProfileSection title="Eğitim ve sınav"><Field label="Eğitim seviyesi" value={profile.degree} /><Field label="Bölüm" value={profile.department} /><Field label="Üniversite" value={profile.university} /><Field label="KPSS puan türü" value={profile.kpss_score_type} /><Field label="KPSS P3" value={profile.kpss_p3?.toFixed(2)} /><Field label="YDS / dil puanı" value={profile.yds_score} /></ProfileSection>
          <ProfileSection title="Tercihler ve deneyim"><Field label="Tercih edilen konumlar" value={profile.preferred_locations} /><Field label="Vardiyalı çalışma" value={formatBoolean(profile.accepts_shifts)} /><Field label="Yaş" value={profile.age} /><Field label="Mesleki deneyim (yıl)" value={profile.experience_years} /><Field label="Sürücü belgesi" value={formatBoolean(profile.driver_license)} /><Field label="Staj deneyimi" value={profile.internship_description} /></ProfileSection>
          <ProfileSection title="Beceriler ve belgeler"><Field label="Teknik beceriler" value={profile.skills} /><Field label="Programlama dili kanıtları" value={profile.programming_language_evidence} /><Field label="Sertifikalar" value={profile.certificates} /></ProfileSection>
          <ProfileSection title="Notlar ve güncelleme"><Field label="Kişisel notlar" value={profile.notes} /><Field label="Son güncelleme" value={formatTimestamp(profile.updated_at)} /></ProfileSection>
        </div>
        <p className="readonly-hint">Profil düzenleme bu dağıtımda kapalıdır. Mevcut profil verisi ve analizler salt okunur görüntülenir.</p>
      </>}
    </QueryState>
  );
}

function ProfileSection({ title, children }: { title: string; children: ReactNode }) {
  return <section className="panel profile-section"><h2>{title}</h2><div className="field-grid">{children}</div></section>;
}

function Field({ label, value }: { label: string; value: unknown }) {
  const display = value === null || value === undefined || value === "" ? "Belirtilmemiş" : String(value);
  return <div className="profile-field"><span>{label}</span><strong>{display}</strong></div>;
}
