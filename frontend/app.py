import os
from datetime import date, datetime
import pandas as pd
import requests
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

try:
    API_URL = (
        os.getenv("API_URL")
        or os.getenv("CAREERPILOT_API_URL")
        or st.secrets.get("API_URL")
        or st.secrets.get("CAREERPILOT_API_URL")
        or "http://127.0.0.1:8000"
    ).rstrip("/")
except StreamlitSecretNotFoundError:
    API_URL = (
        os.getenv("API_URL")
        or os.getenv("CAREERPILOT_API_URL")
        or "http://127.0.0.1:8000"
    ).rstrip("/")
DEMO_MODE = os.getenv("CAREERPILOT_DEMO_MODE", "").strip().casefold() in {"1", "true", "yes", "on"}

st.set_page_config(
    page_title="CareerPilot TR — Kamu Kariyer Platformu",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Profesyonel ve Modern UI Tasarımı
st.markdown("""
<style>
    /* Google / Inter Font Ailesi ve Temel Stiller */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    .main-header {
        background: linear-gradient(135deg, #1E293B 0%, #0F172A 100%);
        color: white;
        padding: 1.5rem 2rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    }
    .main-header h1 {
        font-size: 1.8rem;
        font-weight: 800;
        margin: 0;
        color: #F8FAFC;
    }
    .main-header p {
        font-size: 0.95rem;
        color: #94A3B8;
        margin: 0.3rem 0 0 0;
    }
    
    /* Rozet Tasarımları */
    .badge-uygun {
        background-color: #DCFCE7;
        color: #15803D;
        border: 1px solid #BBF7D0;
        padding: 4px 12px;
        border-radius: 20px;
        font-weight: 700;
        font-size: 0.8rem;
        display: inline-block;
    }
    .badge-potansiyel {
        background-color: #FEF3C7;
        color: #B45309;
        border: 1px solid #FDE68A;
        padding: 4px 12px;
        border-radius: 20px;
        font-weight: 700;
        font-size: 0.8rem;
        display: inline-block;
    }
    .badge-degil {
        background-color: #FEE2E2;
        color: #B91C1C;
        border: 1px solid #FECACA;
        padding: 4px 12px;
        border-radius: 20px;
        font-weight: 700;
        font-size: 0.8rem;
        display: inline-block;
    }
    
    /* Başvuru Durum Rozetleri */
    .status-acik {
        background-color: #ECFDF5;
        color: #047857;
        border: 1px solid #A7F3D0;
        padding: 3px 10px;
        border-radius: 6px;
        font-weight: 600;
        font-size: 0.78rem;
    }
    .status-baslamadi {
        background-color: #EFF6FF;
        color: #1D4ED8;
        border: 1px solid #BFDBFE;
        padding: 3px 10px;
        border-radius: 6px;
        font-weight: 600;
        font-size: 0.78rem;
    }
    .status-sonaerdi {
        background-color: #F1F5F9;
        color: #64748B;
        border: 1px solid #CBD5E1;
        padding: 3px 10px;
        border-radius: 6px;
        font-weight: 600;
        font-size: 0.78rem;
    }
    
    .badge-method {
        background-color: #EEF2FF;
        color: #4338CA;
        border: 1px solid #C7D2FE;
        padding: 3px 10px;
        border-radius: 6px;
        font-weight: 600;
        font-size: 0.78rem;
    }
    
    /* Bilgi Satırları */
    .card-meta {
        background: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 8px;
        padding: 0.6rem 0.8rem;
        margin: 0.6rem 0;
        font-size: 0.88rem;
    }
    
    .reason-box-uygun {
        background-color: #F0FDF4;
        border-left: 4px solid #22C55E;
        padding: 0.6rem 0.8rem;
        border-radius: 4px;
        font-size: 0.88rem;
        color: #166534;
        margin: 0.5rem 0;
    }
    .reason-box-potansiyel {
        background-color: #FFFBEB;
        border-left: 4px solid #F59E0B;
        padding: 0.6rem 0.8rem;
        border-radius: 4px;
        font-size: 0.88rem;
        color: #92400E;
        margin: 0.5rem 0;
    }
    .reason-box-degil {
        background-color: #FEF2F2;
        border-left: 4px solid #EF4444;
        padding: 0.6rem 0.8rem;
        border-radius: 4px;
        font-size: 0.88rem;
        color: #991B1B;
        margin: 0.5rem 0;
    }
</style>
""", unsafe_allow_html=True)


# ============================================================
# API İstemci Yardımcıları
# ============================================================

def api_get(path, params=None):
    response = requests.get(f"{API_URL}{path}", params=params, timeout=45)
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=45)
def public_api_get(path, params=None):
    return api_get(path, params)


def api_post(path, payload):
    response = requests.post(f"{API_URL}{path}", json=payload, timeout=12)
    response.raise_for_status()
    return response.json()


def api_post_action(path, timeout=180):
    response = requests.post(f"{API_URL}{path}", timeout=timeout)
    response.raise_for_status()
    return response.json()


def api_put(path, payload):
    response = requests.put(f"{API_URL}{path}", json=payload, timeout=12)
    response.raise_for_status()
    return response.json()


def show_api_error(error):
    st.error(f"⚠️ Backend bağlantı hatası: {error}\n\nFastAPI sunucusunun (8000 portunda) çalıştığını kontrol edin.")


# ============================================================
# Kenar Çubuğu (Sidebar)
# ============================================================

with st.sidebar:
    st.markdown("### 🧭 **CareerPilot TR**")
    st.caption("Kamu Personeli Alımları & Nitelik Eşleştirme")
    st.divider()

    try:
        health = api_get("/health")
        DEMO_MODE = DEMO_MODE or health.get("demo_mode", False)
        st.success("🟢 API Bağlantısı Aktif")
    except Exception:
        st.error("🔴 API Bağlantısı Yok (Port 8000)")
        st.stop()

    page = st.radio(
        "Görünüm Seçin",
        [
            "📊 Genel Bakış",
            "🏛️ Kamu İlanları",
            "📅 Başvuru Takvimi",
            "🔗 Kaynaklar",
        ] if DEMO_MODE else [
            "📊 Genel Bakış",
            "🏛️ Kamu İlanları",
            "📅 Başvuru Takvimi",
            "🔗 Kaynaklar",
            "🎓 Eğitim & Diğer Fırsatlar",
            "👤 Aday Profili",
            "⚙️ Ayarlar",
        ],
        index=0,
    )
    st.divider()

    if DEMO_MODE:
        st.info("Salt okunur demo")
    else:
        try:
            p = api_get("/profile")
            st.markdown("##### 📌 Aday Özeti")
            st.markdown(f"**Bölüm:** {p.get('department') or 'Bilgisayar Mühendisliği'}")
            st.markdown(f"**Üniversite:** {p.get('university') or 'İstanbul Topkapı Üniversitesi'}")
            st.markdown(f"**KPSS P3:** `{p.get('kpss_p3', 87.60):.2f}`")
            shift_status = "✅ Kabul Ediyor" if p.get("accepts_shifts") else ("❌ Kabul Etmiyor" if p.get("accepts_shifts") is False else "⚠️ Bilinmiyor")
            st.markdown(f"**Vardiya:** {shift_status}")
        except Exception:
            pass


# ============================================================
# 1. KAMU İLANLARI (POZİSYON BAZLI İŞ FIRSATLARI)
# ============================================================

if DEMO_MODE and page == "📊 Genel Bakış":
    st.markdown("""
    <div class="main-header">
        <h1>CareerPilot TR</h1>
        <p>Resmî kamu ilanlarını tek yerde takip edin</p>
    </div>
    """, unsafe_allow_html=True)
    st.info("Salt okunur demo — aday profili, ilan yönetimi ve kaynak güncelleme işlemleri kapalıdır.")

    try:
        summary = public_api_get("/public/summary")
        sources = public_api_get("/sources")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Toplam ilan", summary["total"])
        c2.metric("Başvuruya açık", summary["open"])
        c3.metric("Yakında başlayacak", summary["upcoming"])
        c4.metric("Son 7 günde eklenen", summary["new_last_7_days"])

        st.caption(
            "İlan verisinin son güncellenmesi: "
            + (summary["last_updated"] or "Tarih bilgisi bulunmuyor")
        )
        st.subheader("Kaynakların durumu")
        source_cols = st.columns(2)
        for index, src in enumerate(sources):
            with source_cols[index % 2]:
                st.markdown(f"**{src['name']}**")
                st.caption(src["description"])
                st.write(f"Durum: {src['status']} · Kayıtlı ilan: {src['job_count']}")
                st.markdown(f"[Resmî kaynağı aç]({src['url']})")

        st.subheader("Son eklenen ilanlar")
        for job in summary["latest"]:
            with st.container(border=True):
                st.markdown(f"**{job['organization']}** — {job['title']}")
                st.caption(
                    f"{job['source_name']} · {job['application_status']} · "
                    f"Son başvuru: {job['application_deadline'] or 'Belirtilmemiş'}"
                )
                if job["source_url"]:
                    st.markdown(f"[Resmî ilan detayına git]({job['source_url']})")
    except Exception as exc:
        show_api_error(exc)

elif page == "📊 Genel Bakış":
    st.markdown("""
    <div class="main-header">
        <h1>CareerPilot TR</h1>
        <p>Genel bakış, kaynak durumu ve son güncellemeler</p>
    </div>
    """, unsafe_allow_html=True)

    try:
        data = api_get("/public/matches")
        jobs = data["jobs"]
        sources = api_get("/sources")

        total = len(jobs)
        suitable = sum(1 for j in jobs if j["match"]["category"] == "UYGUN")
        potential = sum(1 for j in jobs if j["match"]["category"] == "POTANSİYEL OLARAK UYGUN")
        new_count = sum(1 for j in jobs if j.get("application_status") == "Başvuru Açık")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Toplam ilan", total)
        c2.metric("Başvuruya açık ilan", new_count)
        c3.metric("Başvuruya başlayacak ilan", sum(1 for j in jobs if j.get("application_status") == "Başvuru Başlamadı"))
        c4.metric("Yeni eklenen ilan", sum(1 for j in jobs if j["match"]["category"] in ["UYGUN", "POTANSİYEL OLARAK UYGUN"]))

        st.subheader("Kaynakların durumu")
        for src in sources:
            with st.container(border=True):
                st.markdown(f"**{src['name']}**")
                st.caption(f"Son kontrol: {src['last_sync'] or 'Henüz yapılmadı'}")
                st.write(f"Bulunan ilan: {src['job_count']}")
                st.write(f"Son senkronizasyon: {src['status']}")
                st.write(f"Bağlantı: {src['url']}")

        st.subheader("Son eklenen ilanlar")
        for job in jobs[:8]:
            with st.container(border=True):
                st.markdown(f"**{job['organization']}** — {job['title']}")
                st.caption(f"Kaynak: {job['source_name']} | Durum: {job['application_status']}")
                if job.get('source_url'):
                    st.markdown(f"[İlan detayına git]({job['source_url']})")

    except Exception as exc:
        show_api_error(exc)

elif DEMO_MODE and page == "🏛️ Kamu İlanları":
    st.markdown("""
    <div class="main-header">
        <h1>Kamu İlanları</h1>
        <p>Resmî ilan kaynaklarından derlenen açık veriler</p>
    </div>
    """, unsafe_allow_html=True)
    st.caption("Salt okunur demo — uygunluk eşleştirmesi ve profil bilgileri paylaşılmaz.")

    try:
        sources = public_api_get("/sources")
        source_names = ["Tüm kaynaklar"] + [item["name"] for item in sources]
        c1, c2 = st.columns([2, 1])
        query = c1.text_input("İlan ara", placeholder="Kurum, pozisyon, şehir veya anahtar kelime")
        selected_source = c2.selectbox("Kaynak", source_names)
        statuses = ["Tümü", "Başvuru Açık", "Başvuru Başlamadı", "Başvuru Sona Erdi"]
        selected_status = st.selectbox("Başvuru durumu", statuses)
        params = {"limit": 100}
        if query.strip():
            params["q"] = query.strip()
        if selected_source != "Tüm kaynaklar":
            params["source"] = selected_source
        if selected_status != "Tümü":
            params["status"] = selected_status
        response = public_api_get("/public/listings", params)
        st.caption(f"{response['total']} ilan")

        for job in response["items"]:
            with st.container(border=True):
                st.markdown(f"#### {job['title']}")
                st.write(f"**Kurum:** {job['organization']} · **Kaynak:** {job['source_name']}")
                c1, c2, c3 = st.columns(3)
                c1.write(f"Başvuru: {job['application_status']}")
                c2.write(f"Şehir: {job['city'] or 'Belirtilmemiş'}")
                c3.write(f"Son tarih: {job['application_deadline'] or 'Belirtilmemiş'}")
                if job["source_url"]:
                    st.link_button("Resmî ilan detayına git", job["source_url"])
    except Exception as exc:
        show_api_error(exc)

elif page == "🏛️ Kamu İlanları":
    st.markdown("""
    <div class="main-header">
        <h1>🏛️ Kamu Personeli Alım İlanları</h1>
        <p>4001, Bilgisayar Mühendisliği, Bilişim ve mühendislik kadroları için pozisyon bazlı analiz</p>
    </div>
    """, unsafe_allow_html=True)

    try:
        data = api_get("/public/matches")
        jobs = data["jobs"]
        counts = data["counts"]

        # Filtreleme Alanı
        with st.expander("🔍 Arama ve Detaylı Filtreler", expanded=True):
            f1, f2, f3 = st.columns([2, 1, 1])
            search_query = f1.text_input("Kurum veya Pozisyon Ara", placeholder="Örn: Türkşeker, Bilgisayar Mühendisi, VHKİ, DOKA...").strip().lower()
            
            # Uygunluk kategorisi filtresi (varsayılan: UYGUN + POTANSİYEL)
            cat_options = ["UYGUN", "POTANSİYEL OLARAK UYGUN", "UYGUN DEĞİL"]
            selected_categories = f2.multiselect("Uygunluk Durumu", cat_options, default=["UYGUN", "POTANSİYEL OLARAK UYGUN"])

            # Başvuru durumu filtresi
            status_options = ["Tümü", "Başvuru Açık", "Başvuru Başlamadı", "Başvuru Sona Erdi"]
            selected_status = f3.selectbox("Başvuru Takvimi", status_options, index=0)

            f4, f5, f6 = st.columns(3)
            all_methods = sorted(list(set(j.get("recruitment_method") or "Belirtilmemiş" for j in jobs)))
            selected_methods = f4.multiselect("Alım Yöntemi", all_methods, default=[])

            all_cities = sorted(list(set(j.get("city") or "Belirtilmemiş" for j in jobs if j.get("city"))))
            selected_cities = f5.multiselect("Şehir / Görev Yeri", all_cities, default=[])

            all_kpss = sorted(list(set(j.get("kpss_score_type") or "Belirtilmemiş" for j in jobs if j.get("kpss_score_type"))))
            selected_kpss = f6.multiselect("KPSS Puan Türü", all_kpss, default=[])

        # Filtreleri Uygula
        filtered_jobs = []
        for j in jobs:
            if selected_categories and j["match"]["category"] not in selected_categories:
                continue
            if selected_status != "Tümü" and j.get("application_status") != selected_status:
                continue
            if search_query:
                t = (j.get("title") or "").lower()
                o = (j.get("organization") or "").lower()
                p = (j.get("position") or "").lower()
                if search_query not in t and search_query not in o and search_query not in p:
                    continue
            if selected_methods and (j.get("recruitment_method") or "Belirtilmemiş") not in selected_methods:
                continue
            if selected_cities and (j.get("city") or "Belirtilmemiş") not in selected_cities:
                continue
            if selected_kpss and (j.get("kpss_score_type") or "Belirtilmemiş") not in selected_kpss:
                continue

            filtered_jobs.append(j)

        # Sekmeli Görünüm (Kategoriye Göre)
        st.markdown(f"**Listelenen Pozisyon:** {len(filtered_jobs)} / Toplam {len(jobs)}")
        
        tab_tum, tab_uygun_pot, tab_degil = st.tabs([
            f"📋 Filtrelenen Pozisyonlar ({len(filtered_jobs)})",
            f"🎯 Yalnızca Başvurulabilir (Uygun + Potansiyel: {counts['UYGUN'] + counts['POTANSİYEL OLARAK UYGUN']})",
            f"❌ Uygun Olmayan Pozisyonlar ({counts['UYGUN DEĞİL']})"
        ])

        def render_job_cards(card_list):
            if not card_list:
                st.info("Bu kritere uygun pozisyon bulunamadı.")
                return

            for job in card_list:
                cat = job["match"]["category"]
                app_status = job.get("application_status", "Başvuru Açık")
                
                badge_class = "badge-uygun" if cat == "UYGUN" else ("badge-potansiyel" if cat == "POTANSİYEL OLARAK UYGUN" else "badge-degil")
                status_class = "status-acik" if app_status == "Başvuru Açık" else ("status-baslamadi" if app_status == "Başvuru Başlamadı" else "status-sonaerdi")
                reason_box_class = "reason-box-uygun" if cat == "UYGUN" else ("reason-box-potansiyel" if cat == "POTANSİYEL OLARAK UYGUN" else "reason-box-degil")

                with st.container(border=True):
                    # Kart Üst Başlık & Rozetler
                    col_h1, col_h2 = st.columns([3, 2])
                    with col_h1:
                        st.markdown(f"#### **{job['position']}**")
                        st.markdown(f"🏛️ **{job['organization']}**")
                    with col_h2:
                        st.markdown(
                            f'<div style="text-align: right;">'
                            f'<span class="{badge_class}">{cat}</span> '
                            f'<span class="{status_class}">{app_status}</span> '
                            f'<span class="badge-method">{job.get("recruitment_method") or "Kurum Alımı"}</span>'
                            f'</div>',
                            unsafe_allow_html=True
                        )

                    # Neden Uygun / Potansiyel / Değil Açıklaması
                    st.markdown(
                        f'<div class="{reason_box_class}">'
                        f'<strong>Analiz Kararı:</strong> {job["match"]["reason"]}'
                        f'</div>',
                        unsafe_allow_html=True
                    )

                    # Temel Nitelik Parametreleri
                    c1, c2, c3, c4 = st.columns(4)
                    c1.markdown(f"📍 **Görev Yeri:** {job.get('city') or 'Belirtilmemiş'}")
                    c2.markdown(f"👥 **Kontenjan:** {job.get('quota') or 'Belirtilmemiş'}")
                    
                    kpss_str = job.get('kpss_score_type') or 'Belirtilmemiş'
                    if job.get('kpss_min_score') is not None:
                        kpss_str += f" (Taban: {job['kpss_min_score']:g})"
                    c3.markdown(f"📊 **KPSS:** {kpss_str}")

                    start_str = job.get('application_start') or 'Belirtilmemiş'
                    end_str = job.get('application_deadline') or 'Belirtilmemiş'
                    c4.markdown(f"📅 **Takvim:** {start_str} → {end_str}")

                    # Ayrıntılı Uygunluk Şartları Akordeonu
                    with st.expander("🔎 Şartların ve Koşulların Detaylı Dökümü"):
                        d1, d2 = st.columns(2)
                        with d1:
                            st.markdown("##### 🎓 Öğrenim & Mezuniyet Şartı")
                            edu = job["match"]["education"]
                            st.write(f"- **İlandaki Şart:** {edu['requirement'] or job.get('education_requirement') or 'Belirtilmemiş'}")
                            st.write(f"- **Bilgisayar Mühendisliği Durumu:** `{edu['computer_engineering']}`")
                            st.write(f"- **Açıklama:** {edu['basis']}")

                            st.markdown("##### 📊 KPSS Değerlendirmesi")
                            kpss = job["match"]["kpss"]
                            st.write(f"- **İstenen Türler:** {', '.join(kpss['score_types']) or job.get('kpss_score_type') or 'Belirtilmemiş'}")
                            st.write(f"- **İstenen Taban:** {kpss['minimum_score'] if kpss['minimum_score'] is not None else 'Belirtilmemiş'}")
                            st.write(f"- **Aday Puanı:** {kpss['candidate_score_type']} = {kpss['candidate_score']}")
                            st.write(f"- **Sonuç:** `{'Şart Karşılanıyor' if kpss['status'] == 'met' else ('Karşılanmıyor' if kpss['status'] == 'not_met' else 'Bilinmiyor')}`")

                        with d2:
                            st.markdown("##### 📋 Profil Koşulları Uyumu")
                            if job["match"]["met_conditions"]:
                                st.markdown("**✅ Doğrulanan & Karşılanan Şartlar:**")
                                for m in job["match"]["met_conditions"]:
                                    st.write(f"- {m}")

                            if job["match"]["unknown_conditions"]:
                                st.markdown("**⏳ Profilde Eksik / Kılavuzdan Doğrulanacak Şartlar:**")
                                for u in job["match"]["unknown_conditions"]:
                                    st.write(f"- {u}")

                            if job["match"]["failed_conditions"]:
                                st.markdown("**❌ Karşılanmayan Zorunlu Koşullar:**")
                                for f_cond in job["match"]["failed_conditions"]:
                                    st.write(f"- {f_cond}")

                            if job["match"]["general_conditions"]:
                                st.markdown("**🏛️ Genel Kamu Hükümleri:**")
                                for g in job["match"]["general_conditions"]:
                                    st.write(f"- {g}")

                        if job.get("source_url"):
                            st.markdown(f"🔗 [Resmî İlan Sayfasına Git]({job['source_url']})")

        with tab_tum:
            render_job_cards(filtered_jobs)

        with tab_uygun_pot:
            uygun_pot_list = [j for j in jobs if j["match"]["category"] in ["UYGUN", "POTANSİYEL OLARAK UYGUN"]]
            render_job_cards(uygun_pot_list)

        with tab_degil:
            degil_list = [j for j in jobs if j["match"]["category"] == "UYGUN DEĞİL"]
            render_job_cards(degil_list)

    except Exception as exc:
        show_api_error(exc)


# ============================================================
# 2. EĞİTİM & YURT DIŞI FIRSATLARI (İSTİHDAM DIŞI DUYURULAR)
# ============================================================

elif page == "🎓 Eğitim & Diğer Fırsatlar":
    st.markdown("""
    <div class="main-header">
        <h1>🎓 Kamu Eğitim, Burs & Yurt Dışı Fırsatları</h1>
        <p>Kamu personeli istihdamı dışındaki yüksek lisans, burs ve gelişim duyuruları</p>
    </div>
    """, unsafe_allow_html=True)

    try:
        data = api_get("/public/matches")
        edu_list = data.get("education_opportunities", [])

        if edu_list:
            st.info("Bu duyurular personel istihdam kadrosu değildir; mevcut personeller veya araştırmacılar için eğitim ve burs imkanlarını kapsar.")
            for opp in edu_list:
                with st.container(border=True):
                    c1, c2 = st.columns([3, 1])
                    with c1:
                        st.markdown(f"#### **{opp['title']}**")
                        st.markdown(f"🏛️ **{opp['organization']}** • 📍 {opp['city']}")
                    with c2:
                        st.markdown(f'<span class="status-acik">{opp["application_status"]}</span>', unsafe_allow_html=True)

                    st.markdown(f"📅 **Başvuru Takvimi:** {opp['application_start'] or 'Belirtilmemiş'} → {opp['application_deadline'] or 'Belirtilmemiş'}")
                    if opp.get("source_url"):
                        st.markdown(f"🔗 [Resmî Duyuru Bağlantısı]({opp['source_url']})")
                    with st.expander("Duyuru Açıklamasını Gör"):
                        st.write(opp["description"])
        else:
            st.info("Kayıtlı eğitim fırsatı bulunmuyor.")

    except Exception as exc:
        show_api_error(exc)


# ============================================================
# 3. GENEL ÖZET & DASHBOARD
# ============================================================

elif page == "📊 Genel Özet & Dashboard":
    st.markdown("""
    <div class="main-header">
        <h1>📊 Genel Özet & Analiz Paneli</h1>
        <p>Aday profili uyumu, yaklaşan son başvuru tarihleri ve pozisyon dağılımı</p>
    </div>
    """, unsafe_allow_html=True)

    try:
        data = api_get("/public/matches")
        counts = data["counts"]
        jobs = data["jobs"]
        p = data["profile"]

        # Sayısal Metrikler
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Toplam Pozisyon", counts["total"])
        c2.metric("✅ Tam Uygun", counts["UYGUN"])
        c3.metric("⏳ Potansiyel Uygun", counts["POTANSİYEL OLARAK UYGUN"])
        c4.metric("❌ Uygun Değil", counts["UYGUN DEĞİL"])
        c5.metric("🎓 Eğitim Duyurusu", counts["education_count"])

        st.divider()

        col_left, col_right = st.columns([3, 2])

        with col_left:
            st.subheader("⏰ Yaklaşan Başvuru Takvimi")
            active_jobs = [j for j in jobs if j.get("application_status") in ["Başvuru Açık", "Başvuru Başlamadı"]]
            
            # Tarihe göre sırala
            dated = []
            for j in active_jobs:
                dl = j.get("application_deadline")
                if dl:
                    try:
                        d_val = date.fromisoformat(dl)
                        days = (d_val - date.today()).days
                        dated.append((days, d_val, j))
                    except Exception:
                        pass
            dated.sort(key=lambda x: x[0])

            if dated:
                for days, d_val, j in dated[:6]:
                    cat = j["match"]["category"]
                    b_cls = "badge-uygun" if cat == "UYGUN" else ("badge-potansiyel" if cat == "POTANSİYEL OLARAK UYGUN" else "badge-degil")
                    status_badge = f'<span class="status-baslamadi">Başvuru Başlamadı</span>' if j.get("application_status") == "Başvuru Başlamadı" else f'<span class="status-acik">{days} Gün Kaldı</span>'

                    with st.container(border=True):
                        cols = st.columns([3, 1])
                        with cols[0]:
                            st.markdown(f"**{j['position']}** — {j['organization']}")
                            st.markdown(f'<span class="{b_cls}">{cat}</span> • <span class="badge-method">{j.get("recruitment_method")}</span>', unsafe_allow_html=True)
                        with cols[1]:
                            st.markdown(f"📅 **{d_val.strftime('%d.%m.%Y')}**")
                            st.markdown(status_badge, unsafe_allow_html=True)
            else:
                st.info("Aktif başvuru takvimi bulunamadı.")

        with col_right:
            st.subheader("👤 Aday Profil Özeti")
            with st.container(border=True):
                st.markdown(f"**Mezuniyet:** {p.get('degree', 'Lisans')} - **{p.get('department', 'Bilgisayar Mühendisliği')}**")
                st.markdown(f"**Üniversite:** {p.get('university', 'İstanbul Topkapı Üniversitesi')}")
                st.markdown(f"**KPSS:** {p.get('kpss_score_type', 'P3')} = **{p.get('kpss_score', 87.60):.2f}**")
                st.markdown(f"**Vardiyalı Çalışma:** {'✅ Kabul Ediyor' if p.get('accepts_shifts') else '❌ Kabul Etmiyor'}")
                st.markdown(f"**Staj:** {p.get('internship_description') or 'KOTON ve Sonitel'}")

                missing = []
                if p.get('yds_score') is None: missing.append("YDS Puanı")
                if p.get('experience_years') is None: missing.append("Doğrulanmış Mesleki Deneyim")
                if p.get('certificates') is None: missing.append("Sertifikalar")
                if p.get('age') is None: missing.append("Yaş")
                if p.get('driver_license') is None: missing.append("Sürücü Belgesi")

                if missing:
                    st.warning(f"**Profilde Eksik Alanlar ({len(missing)}):** {', '.join(missing)}\n\n*Bu alanlar girilmediğinde ilgili zorunlu şartları olan ilanlar 'Potansiyel' olarak listelenir.*")
                else:
                    st.success("Tüm profil alanları tamamlanmış!")

    except Exception as exc:
        show_api_error(exc)


# ============================================================
# 4. ADAY PROFİLİ EKRANI
# ============================================================

elif page == "📅 Başvuru Takvimi":
    st.markdown("""
    <div class="main-header">
        <h1>Başvuru Takvimi</h1>
        <p>Başvuru süresi bilinen ilanları tarihe göre görüntüleyin</p>
    </div>
    """, unsafe_allow_html=True)
    try:
        params = {"limit": 100}
        if DEMO_MODE:
            response = public_api_get("/public/listings", params)
            jobs = response["items"]
        else:
            response = api_get("/public/matches")
            jobs = response["jobs"]

        dated_jobs = [
            job for job in jobs
            if job.get("application_start") or job.get("application_deadline")
        ]
        dated_jobs.sort(key=lambda job: job.get("application_deadline") or job.get("application_start"))
        if not dated_jobs:
            st.info("Başlangıç veya bitiş tarihi belirtilmiş ilan bulunmuyor.")
        for job in dated_jobs:
            with st.container(border=True):
                st.markdown(f"**{job['title']}** — {job['organization']}")
                st.caption(
                    f"{job.get('source_name', 'Kaynak belirtilmemiş')} · {job['application_status']} · "
                    f"{job.get('application_start') or 'Başlangıç belirtilmemiş'} → "
                    f"{job.get('application_deadline') or 'Bitiş belirtilmemiş'}"
                )
                if job.get("source_url"):
                    st.link_button("Resmî ilan detayına git", job["source_url"])
    except Exception as exc:
        show_api_error(exc)

elif page == "👤 Aday Profili":
    st.markdown("""
    <div class="main-header">
        <h1>👤 Aday Profili</h1>
        <p>Bilgilerinizi kaydedin; tüm kamu kadroları için uygunluk kararları anında güncellensin</p>
    </div>
    """, unsafe_allow_html=True)

    try:
        profile = api_get("/profile")

        with st.form("profile_form"):
            st.subheader("1. Eğitim ve Mezuniyet")
            col1, col2 = st.columns(2)
            degree = col1.selectbox("Eğitim Seviyesi", ["Lisans", "Ön Lisans", "Yüksek Lisans", "Doktora"], index=0)
            department = col2.text_input("Bölüm", value=profile.get("department", "Bilgisayar Mühendisliği"))

            col3, col4 = st.columns(2)
            university = col3.text_input("Üniversite", value=profile.get("university", "İstanbul Topkapı Üniversitesi"))
            locations = col4.text_input("Tercih Edilen Yerler", value=profile.get("preferred_locations", "Türkiye geneli"))

            st.divider()
            st.subheader("2. KPSS ve Dil Bilgileri")
            col5, col6, col7 = st.columns(3)
            kpss_type = col5.selectbox("KPSS Puan Türü", ["P3", "P1", "P2", "P93", "P94"], index=0)
            kpss_p3 = col6.number_input("KPSS Puanı", min_value=0.0, max_value=100.0, value=float(profile.get("kpss_p3") or 87.60), step=0.01)
            yds_val = profile.get("yds_score")
            yds_score = col7.number_input("YDS / Dil Puanı (Bilinmiyorsa 0 bırakın)", min_value=0.0, max_value=100.0, value=float(yds_val or 0.0), step=1.0)

            st.divider()
            st.subheader("3. Çalışma Tercihleri, Deneyim ve Staj")
            col8, col9, col10 = st.columns(3)
            age_val = profile.get("age")
            age = col8.number_input("Yaş (Bilinmiyorsa 0 bırakın)", min_value=0, max_value=100, value=int(age_val or 0), step=1)
            
            exp_val = profile.get("experience_years")
            experience_years = col9.number_input("Mesleki Deneyim Yılı (Bilinmiyorsa 0 bırakın)", min_value=0.0, max_value=50.0, value=float(exp_val or 0.0), step=0.5)

            shift_opts = ["Kabul Ediyor", "Kabul Etmiyor", "Bilinmiyor"]
            cur_shift = "Kabul Ediyor" if profile.get("accepts_shifts") is True else ("Kabul Etmiyor" if profile.get("accepts_shifts") is False else "Bilinmiyor")
            shift_choice = col10.selectbox("Vardiyalı Çalışma", shift_opts, index=shift_opts.index(cur_shift))

            col11, col12 = st.columns(2)
            driver_opts = ["Var", "Yok", "Bilinmiyor"]
            cur_driver = "Var" if profile.get("driver_license") is True else ("Yok" if profile.get("driver_license") is False else "Bilinmiyor")
            driver_choice = col11.selectbox("Sürücü Belgesi", driver_opts, index=driver_opts.index(cur_driver))

            internship_desc = col12.text_input("Staj Deneyimleri", value=profile.get("internship_description", "KOTON ve Sonitel staj deneyimleri"))

            st.divider()
            st.subheader("4. Sertifikalar ve Programlama Dili Kanıtı")
            certificates = st.text_area("Sertifikalar (virgülle ayırın)", value=profile.get("certificates", ""), placeholder="Örn: Cisco CCNA, AWS Cloud...")
            prog_langs = st.text_area("Programlama Dili Kanıtı / Bilgisi", value=profile.get("programming_language_evidence", ""), placeholder="Örn: Python, Java, SQL...")
            skills = st.text_area("Diğer Beceriler", value=profile.get("skills", ""), placeholder="Örn: Docker, Git, Linux, Flutter...")

            submitted = st.form_submit_button("💾 Profil Bilgilerini Kaydet", type="primary", use_container_width=True)

            if submitted:
                accepts_shifts_val = True if shift_choice == "Kabul Ediyor" else (False if shift_choice == "Kabul Etmiyor" else None)
                driver_license_val = True if driver_choice == "Var" else (False if driver_choice == "Yok" else None)

                payload = {
                    "degree": degree,
                    "department": department,
                    "university": university,
                    "preferred_locations": locations,
                    "kpss_score_type": kpss_type,
                    "kpss_p3": kpss_p3 if kpss_p3 > 0 else None,
                    "yds_score": yds_score if yds_score > 0 else None,
                    "age": age if age > 0 else None,
                    "experience_years": experience_years if experience_years > 0 else None,
                    "accepts_shifts": accepts_shifts_val,
                    "driver_license": driver_license_val,
                    "has_internship": True if internship_desc.strip() else None,
                    "internship_description": internship_desc,
                    "certificates": certificates,
                    "programming_language_evidence": prog_langs,
                    "skills": skills,
                }
                api_put("/profile", payload)
                st.success("✅ Profiliniz veritabanına kaydedildi! Uygunluk analizleri otomatik yenilendi.")
                st.rerun()

    except Exception as exc:
        show_api_error(exc)


# ============================================================
# 5. KAYNAKLAR & SENKRONİZASYON
# ============================================================

elif page == "🔗 Kaynaklar":
    st.markdown("""
    <div class="main-header">
        <h1>🔗 Resmî Veri Kaynakları</h1>
        <p>Kariyer Kapısı, SBB, İŞKUR ve Yerel Yönetimler kaynaklarının durumu</p>
    </div>
    """, unsafe_allow_html=True)

    try:
        sources = api_get("/sources")

        for src in sources:
            with st.container(border=True):
                s1, s2 = st.columns([3, 1])
                with s1:
                    st.markdown(f"### 🌐 {src['name']}")
                    st.caption(f"Adres: {src['url']}")
                    st.write(src["description"])
                with s2:
                    st.markdown(f"**Durum:** `{src['status']}`")
                    st.markdown(f"**Kayıtlı İlan:** `{src['job_count']}`")
                    st.markdown(f"**Son Eşitleme:** `{src['last_sync'] or 'Henüz yapılmadı'}`")

                if src.get("last_error"):
                    st.warning(f"⚠️ Son Tarama Uyarısı: {src['last_error']}")

        if not DEMO_MODE:
            st.divider()
            st.subheader("Manuel Senkronizasyon")
            st.info("Kariyer Kapısı ve yeni kaynaklar için tek tek veya toplu senkronizasyon yapılabilir. PDF dosyaları kesinlikle indirilmez ve okunmaz.")

            if st.button("🚀 Tüm Kaynakları Güncelle", type="primary"):
                with st.spinner("Kaynaklar eşitleniyor, lütfen bekleyin..."):
                    try:
                        res = api_post_action("/sources/sync-all")
                        st.success("✅ Tüm kaynaklar senkronize edildi!")
                        st.json(res)
                    except Exception as exc:
                        show_api_error(exc)

            if st.button("🚀 Kariyer Kapısı Senkronizasyonunu Başlat"):
                with st.spinner("Kariyer Kapısı taranıyor, lütfen bekleyin..."):
                    try:
                        res = api_post_action("/sources/kariyer-kapisi/sync")
                        st.success("✅ Senkronizasyon tamamlandı!")
                        st.json(res)
                        st.rerun()
                    except Exception as exc:
                        show_api_error(exc)

    except Exception as exc:
        show_api_error(exc)


# ============================================================
# 6. ÖZEL SEKTÖR
# ============================================================

elif page == "💼 Özel Sektör & Beceri Analizi":
    st.markdown("""
    <div class="main-header">
        <h1>💼 Özel Sektör Beceri Analizi</h1>
        <p>Teknoloji pozisyonları için aranan ortak beceri ve araç frekansları</p>
    </div>
    """, unsafe_allow_html=True)

    tab1, tab2 = st.tabs(["📊 Beceri Talepleri", "➕ Özel Sektör İlanları"])

    with tab1:
        cats = ["Tüm özel sektör ilanları", "Backend Developer", "Data Analyst", "Data Engineer", "AI / ML Engineer", "Mobile Developer"]
        c_sel = st.selectbox("Pozisyon Seçin", cats)
        try:
            params = {} if c_sel == "Tüm özel sektör ilanları" else {"category": c_sel}
            res = api_get("/analytics/skills", params)
            st.metric("İncelenen İlan", res["job_count"])
            if res["skills"]:
                df = pd.DataFrame(res["skills"]).rename(columns={"skill": "Beceri", "count": "İlan Sayısı", "percentage": "Oran (%)"})
                st.dataframe(df, use_container_width=True, hide_index=True)
                st.bar_chart(df.set_index("Beceri")["Oran (%)"])
            else:
                st.info("Bu grupta henüz ilan bulunmuyor.")
        except Exception as exc:
            show_api_error(exc)

    with tab2:
        try:
            p_jobs = api_get("/jobs", {"sector": "private"})
            if p_jobs:
                for pj in p_jobs:
                    with st.container(border=True):
                        st.markdown(f"**{pj['title']}** — {pj['organization']} ({pj.get('city') or 'Belirtilmemiş'})")
                        st.caption(f"İstenen Beceriler: {pj.get('skills') or 'Belirtilmemiş'}")
            else:
                st.info("Kayıtlı özel sektör ilanı yok.")
        except Exception as exc:
            show_api_error(exc)
