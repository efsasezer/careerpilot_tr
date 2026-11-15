# CareerPilot TR – Kamu ilan takibi ve KPSS eşleştirme

KPSS ile atanmak isteyen bir aday için resmî kamu ilanı kaynaklarını tarar, her ilanı
adayın öğrenim durumu ve KPSS puanlarıyla karşılaştırır, uygun olanları listeler ve
yeni eşleşmeler ile yaklaşan son başvurular için bildirim üretir.

> Sonuçlar otomatik bir **ön elemedir**; başvuru ya da atama garantisi vermez.
> Başvurmadan önce resmî ilanı mutlaka okuyun.

## Neler yapar?

- **Altı resmî kaynağı tarar:** Kariyer Kapısı, İŞKUR kamu memur alım ilanları, SBB Kamu
  İlanları, Yerel Yönetimler Genel Müdürlüğü duyuruları, İlan.gov.tr (Kamu Personel Alım
  ve Sınavları) ve ÖSYM'nin KPSS merkezi yerleştirme (tercih) duyuruları.
- **İlan havuzu uygunluktan bağımsızdır:** Bulunan her ilan önce kaydedilir, sonra
  değerlendirilir. Uygun olmayan, ayrıntısı okunamayan ya da henüz değerlendirilemeyen ilan
  da listede kalır; veri/belge durumu ve “inceleme gerekli” bilgisi ayrıca gösterilir.
- **İlanın resmî metnini okur:** PDF/DOCX ilan metinleri ve kadro tabloları ayrıştırılır;
  her kadro satırı (unvan, nitelik, kontenjan, KPSS türü, taban puan, cinsiyet) ayrı
  pozisyon olarak değerlendirilir.
- **Profile göre sınıflandırır:** Uygun / Doğrulanmalı / Uygun değil. Her şart (öğrenim,
  KPSS, yabancı dil, yaş, deneyim, ehliyet, cinsiyet, özel statü…) ayrı ayrı gerekçesiyle
  gösterilir. Motor belirli bir bölüme bağlı değildir.
- **Aynı ilanı tekilleştirir:** Bir ilan birden çok kaynakta yayımlandıysa tek kart olur.
- **Bildirim gönderir:** Uygulama içi bildirim merkezi, tarayıcı bildirimi; isteğe bağlı
  e-posta (SMTP) ve Telegram. Son başvuruya N gün kala hatırlatma.
- **Takip:** İlanı kaydet, “başvurdum” olarak işaretle, gizle, not ekle; başvuru takvimi.
- **Otomatik tarama:** Sunucu çalışırken kaynaklar varsayılan olarak 6 saatte bir taranır.

## Kurulum

Gerekenler: Python 3.11+, Node.js 20+.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium   # Kariyer Kapısı ve İlan.gov.tr taraması için
npm --prefix frontend ci
```

Windows'ta `.venv/bin/` yerine `.venv\Scripts\` kullanın.

## Çalıştırma

İki terminal açın:

```bash
.venv/bin/python -m uvicorn backend.main:app --reload
```

```bash
npm --prefix frontend run dev
```

Arayüz `http://localhost:5173` adresinde açılır. **Yerelde erişim anahtarı gerekmez:**
`CAREERPILOT_ACCESS_TOKEN` tanımlı değilse API yalnızca bu bilgisayardan (127.0.0.1) gelen
isteklere yanıt verir ve arayüz giriş ekranını atlar. Başka bir makineden gelen, bir vekil
sunucu üzerinden iletilen ya da Render üzerindeki istekler anahtar olmadan reddedilir.
Yayında anahtar zorunludur; yerelde de anahtar istemek için `.env` dosyasına
`CAREERPILOT_ACCESS_TOKEN` yazın. `sh scripts/run_api.sh`, `.env` dosyasını yükleyip aynı
komutu çalıştırır. API belgeleri: `http://127.0.0.1:8000/docs`

İlk kullanım: **Profilim** sayfasında öğrenim düzeyi, bölüm, fakülte ve bütün KPSS
puanlarınızı girin → **Kaynaklar › Şimdi tara** → **İlanlar**.

## Bildirim kanalları

| Kanal | Nasıl açılır |
|---|---|
| Uygulama içi | Her zaman açık (Bildirimler sayfası, zil simgesi) |
| Tarayıcı | Ayarlar › “İzin ver” (uygulama açıkken masaüstü uyarısı) |
| E-posta | `.env` içine `CAREERPILOT_SMTP_*` değerlerini yazın, Ayarlar'da adresinizi girin |
| Telegram | @BotFather ile bot oluşturun, anahtarı `CAREERPILOT_TELEGRAM_BOT_TOKEN` olarak yazın, bota bir mesaj atın, sohbet kimliğinizi Ayarlar'a girin |

Ayarlar sayfasındaki **Test bildirimi gönder** düğmesi kanalı dener. Bir kanal hata
verirse bekleyen bildirimler sonraki taramada yeniden gönderilir.

## Uygunluk sınıfları

- **Uygun:** Metinden okunabilen bütün zorunlu şartlar profille karşılanıyor.
- **Doğrulanmalı:** Açık bir uyumsuzluk yok; ancak en az bir şart metinden okunamadı ya da
  profilde ilgili bilgi eksik (ör. ehliyet, yabancı dil puanı). Profili tamamladıkça azalır.
- **Uygun değil:** Bölüm, öğrenim düzeyi, KPSS puan türü/taban puanı gibi açık bir zorunlu
  şart karşılanmıyor; ya da ilan akademik kadro / özel statü (engelli, eski hükümlü) ilanı.

Kurallar `backend/eligibility.py` içindedir: “tercihen” ifadeleri zorunlu sayılmaz;
profilde olmayan bilgi uydurulmaz; kadro tablosundaki her satır yalnızca kendi şartlarıyla
değerlendirilir; 2001/3001/4001 nitelik kodları “herhangi bir program” olarak tanınır.
İlanda yakın bir bölüm adı geçiyorsa (ör. Yazılım Mühendisliği) profildeki **Eşdeğer
sayılan bölümler** alanına ekleyebilirsiniz.

## Bilinen sınırlar

- Taranmış görüntü olan (metin katmanı olmayan) PDF ilanlar okunamaz; bu ilanlar listede
  “Doğrulanmalı” olarak kalır ve Kaynaklar sayfasında raporlanır. OCR yoktur.
- Yerel Yönetimler duyurularının ek belgeleri (`webdosya.csb.gov.tr`) sunucunun sertifika
  zinciri doğrulanamadığı için indirilmez; bağlantı kullanıcıya gösterilir. Aynı ilanlar
  çoğunlukla İŞKUR/SBB/İlan.gov.tr üzerinden tam metniyle gelir ve tek kartta birleştirilir.
  (İlan.gov.tr de ara sertifikasını göndermez; orada eksik ara sertifika resmî adresinden
  indirilerek zincir güvenilir köke kadar doğrulanır. Sertifika doğrulaması hiç kapatılmaz.)
- Hiçbir kayıt silinmez. İlan olmayan eski kayıtlar, iptal duyuruları ve aynı kaynaktaki
  kopyalar `archived_reason` ile arşivlenir; `/jobs` yanıtında görünmeye devam eder.
- SBB ilan bağlantıları oturuma özeldir; arayüz SBB liste sayfasına yönlendirir ve okunan
  resmî metni ilan ayrıntısında gösterir.
- ÖSYM merkezi yerleştirmede tercih dönemi duyurusu yakalanır ve bildirilir; ancak tercih
  kılavuzundaki kadrolar tek tek ayrıştırılmaz. Kılavuz bağlantısı ilanla birlikte gösterilir.
- Akademik kadrolar (araştırma/öğretim görevlisi) KPSS ile alınmaz. Bölümünüz aranıyorsa
  “Doğrulanmalı” olarak gösterilir (ALES, dil ve lisansüstü şartları ilandan doğrulanmalı);
  İlanlar sayfasındaki “Akademik ilanları gizle” seçeneğiyle listeden çıkarılabilir.
- Uygulama tek aday profiliyle çalışır (çok kullanıcılı değildir).

## Testler

```bash
.venv/bin/python -m pytest -q
npm --prefix frontend test
npm --prefix frontend run build
```

Backend testleri geçici bir veritabanı kullanır; `careerpilot.db` dosyasına dokunmaz.

## Yayın (Render)

`render.yaml` iki servis tanımlar: FastAPI (`careerpilot-tr-api`) ve React statik sitesi
(`careerpilot-tr-web`). Blueprint API'yi
`CAREERPILOT_DEMO_MODE=true` ile **salt okunur** yayımlar: depodaki `careerpilot.db`
gösterilir; tarama, profil düzenleme ve bildirim gönderimi kapalıdır (Render'ın ücretsiz
dosya sistemi kalıcı değildir). Tarama ve bildirimlerin çalıştığı bir yayın için kalıcı
disk veya harici veritabanı (`DATABASE_URL`) ile demo modunu kapatmak gerekir.

**Gizlilik:** `careerpilot.db` aday profilini içerir ve depoda izlenmektedir. Depoyu
herkese açık yapmadan önce bu dosyayı kaldırın. Erişim anahtarını paylaşmayın; `VITE_`
değişkenlerine gizli değer koymayın.

## Yapı

```text
backend/
  main.py           FastAPI uçları, erişim denetimi
  eligibility.py    Şart çıkarma ve profil karşılaştırma motoru
  matching.py       İlan → pozisyon ayrıştırma, tekilleştirme, sonuç önbelleği
  sync.py           Kaynak taraması, arka plan çalıştırıcı, zamanlayıcı
  notifications.py  Bildirim üretimi ve e-posta/Telegram gönderimi
  documents.py      PDF/DOCX/HTML metin ve kadro tablosu ayrıştırma
  sources/          Kaynak bağdaştırıcıları (sbb, iskur, yerel_yonetimler, kariyer_kapisi)
frontend/src/       React + TypeScript arayüzü (Vite)
tests/              pytest testleri
```
