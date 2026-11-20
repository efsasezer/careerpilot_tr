# CareerPilot TR – Kamu ilan takibi ve KPSS eşleştirme

Resmî kamu ilanı kaynaklarını tarar, her kadroyu adayın öğrenim durumu ve KPSS puanlarıyla
karşılaştırır, başvuru/sınav/sonuç tarihlerini takvime işler ve başvuru sürecini takip eder.

> Sonuçlar otomatik bir **ön elemedir**; başvuru ya da atama garantisi vermez.
> Başvurmadan önce resmî ilanı mutlaka okuyun.

## Neler yapar?

- **Altı resmî kaynak:** Kariyer Kapısı, İŞKUR kamu memur alım ilanları, SBB Kamu İlanları,
  Yerel Yönetimler Genel Müdürlüğü, İlan.gov.tr ve ÖSYM tercih duyuruları.
- **Kadro bazlı uygunluk:** İlan değil kadro değerlendirilir. Her şart için *Karşılıyor /
  Karşılamıyor / Bilinmiyor / Aranmıyor* sonucu, açıklaması ve ilan metninden kanıt cümlesi
  gösterilir. Yaş ve deneyim ilanın başvuru tarihine göre hesaplanır.
- **Elle doğrulama:** Her ilan ve kadro için “Doğruladım: Uygun / Uygun değil”. Kararınız
  sistemin kararından ayrı saklanır, her zaman önceliklidir; yeniden tarama, profil
  değişikliği ya da motor güncellemesi kararınızı değiştirmez. İlan sonradan güncellenirse
  karar silinmez, “İlan güncellendi, doğrulamanı gözden geçir” uyarısı çıkar.
- **Tarih çıkarımı (kural tabanlı):** Başvuru, sınav/mülakat, sonuç ve evrak tarihleri ilan
  metninden kanıt cümlesiyle çıkarılır. Metinde olmayan tarih üretilmez. Yapay zekâ modeli
  kullanılmaz.
- **Takvim:** “Başvuru takvimi” sayfasında Son başvuru listesi, Ay, Hafta, Gün ve Ajanda
  sekmeleri; kişisel ve tekrarlayan görevler; `.ics` dışa aktarma.
- **Takip:** Kaydet → Başvurdum → Sonuç bekleniyor → Kazandım / Olmadı, notlar.
- **Taranmış PDF'ler için OCR:** Sistem paketi gerektirmeyen OCR (RapidOCR). OCR ile okunan
  ilan otomatik “Uygun” olmaz; PDF uygulama içinde açılır ve elle doğrulanır.
- **Uygulama içi bildirimler:** Site açıldığında hesaplanır (bugün/yarın son gün, bugün
  açılan başvuru, bugünkü sınav/sonuç, bugünkü görevler, güncellenen ilanlar).

## Kurulum

Gerekenler: Python 3.11+, Node.js 20+.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium   # Kariyer Kapısı ve İlan.gov.tr taraması için
npm --prefix frontend ci
```

## Çalıştırma

İlk başlatmada script `.env` dosyasını oluşturur, sizden giriş şifresini gizli girişle
ister ve oturum anahtarını üretip bu dosyaya kaydeder. Değerler sonraki başlatmalarda
aynı kalır; `.env` Git'e eklenmez.
Yerel başlatma scripti kaynakları 12 saatte bir otomatik tarar. Bunu değiştirmek için
`.env` içindeki `CAREERPILOT_SYNC_INTERVAL_HOURS` değerini saat olarak ayarlayın; `0`
otomatik taramayı kapatır. İlk tarama uygulama başladıktan kısa süre sonra çalışır.

Windows PowerShell:

```powershell
./scripts/run_api.ps1
```

Sonraki çalıştırmalarda da aynı komutu kullanın. `.env` dosyasını silmeyin; silerseniz
yeni oturum anahtarı oluşturulur ve eski tarayıcı oturumları kapanır.

macOS / Linux:

```bash
sh scripts/run_api.sh
```

```bash
npm --prefix frontend run dev
```

Arayüz `http://localhost:5173` adresinde açılır ve API'ye aynı adresten `/api` üzerinden
ulaşır. Giriş, `.env` dosyasındaki `CAREERPILOT_PASSWORD` ile yapılır.

## Giriş ve güvenlik

| Ortam değişkeni | Zorunlu | Açıklama |
|---|---|---|
| `CAREERPILOT_PASSWORD` | Evet | Tek kullanıcılı giriş şifresi |
| `CAREERPILOT_SESSION_SECRET` | Evet | Oturum çerezini imzalayan anahtar (en az 16 karakter) |

- Şifre tarayıcıda saklanmaz. Sunucuda sabit zamanlı karşılaştırılır; başarılı girişte
  HttpOnly + SameSite=Lax (HTTPS'te Secure) çerezli, 14 günlük oturum açılır.
- Oturum sunucuda tutulur; “Oturumu kapat” onu sunucuda geçersiz kılar.
- 10 dakikada 5 hatalı denemeden sonra o adres 15 dakika bekletilir.
- Değişkenlerden biri eksikse uygulama açık erişime düşmez; giriş kapalı kalır ve hangi
  değişkenin eksik olduğu bildirilir.
- `/health` dışındaki bütün uçlar (okuma ve yazma) sunucuda oturum kontrolünden geçer.

## Veritabanı

Mevcut SQLite dosyası kullanılır: varsayılan yol proje kökündeki `careerpilot.db`
(`DATABASE_URL` ile değiştirilebilir). Şema değişikliğinden önce dosyanın yanına
`careerpilot.db.backup.<zaman>` adıyla yedek alınır.

Kullanıcı verisi ilan tablolarından ayrıdır ve tarama bu tablolara dokunmaz:
`candidate_profile`, `user_job_state` (kaydet/başvuru/notlar), `user_verifications`
(elle doğrulamalar), `user_tasks`, `user_sessions`, `app_settings`, kullanıcının düzenlediği
`job_events` kayıtları.

## Yayın (Render)

`render.yaml` iki servis tanımlar: API (`careerpilot-tr-api`) ve statik site
(`careerpilot-tr-web`). Statik site `/api/*` isteklerini API'ye yönlendirir; böylece oturum
çerezi aynı alan adında kalır. Render panelinde `careerpilot-tr-api` için
`CAREERPILOT_PASSWORD` değerini bir kez girin; `CAREERPILOT_SESSION_SECRET` Blueprint
tarafından bir kez üretilip Render'da saklanır. Normal deploylarda bu değerleri değiştirmeyin.
Şifreyi veya servis ayarlarını değiştirmek mevcut oturumları kapatır; yeniden giriş gerekir.
`autoDeploy: false` olduğu için branch'e push tek başına yayın yapmaz; Render panelinden
`careerpilot-tr-api` ve `careerpilot-tr-web` servislerini deploy edin.

**Veri kaybı riski:** Blueprint'te kalıcı disk yoktur. Render'ın ücretsiz planında dosya
sistemi her yeniden yayında ve servis yeniden başladığında sıfırlanır; yayında girilen
profil, doğrulamalar, görevler ve notlar **silinir** ve depodaki `careerpilot.db` geri gelir.
Seçenekler:

1. Render'da kalıcı disk (ücretli plan) ekleyip `DATABASE_URL=sqlite:////var/data/careerpilot.db`
   ve ilk açılış için `CAREERPILOT_DB_SEED_FROM_REPO=true` tanımlamak.
2. Uygulamayı kendi bilgisayarınızda çalıştırmak (veri kalıcıdır, bütün kaynaklara erişilir).
3. Yayını yalnızca görüntüleme için kullanıp verinin silinebileceğini kabul etmek.

Diğer sınırlar: SBB, Kariyer Kapısı ve Yerel Yönetimler yurt dışındaki sunuculardan gelen
istekleri kabul etmiyor; Render'daki “Şimdi tara” bu üç kaynağı güncelleyemeyebilir. OCR,
ücretsiz planın 512 MB bellek sınırına sığmadığı için Render'da varsayılan olarak kapalıdır
(`CAREERPILOT_OCR=on` ile açılabilir).

## Uygunluk sınıfları

- **Uygun:** Bütün zorunlu şartlar karşılanıyor ya da aranmıyor; bilinmeyen şart yok.
- **Doğrulanmalı:** Kesin bir uyumsuzluk yok ama en az bir şart bilinmiyor (ilan okunamadı,
  tablo ayrıştırılamadı ya da profilde ilgili bilgi “belirtilmedi”). Nedeni yazılır.
- **Uygun değil:** En az bir zorunlu şart kesin olarak karşılanmıyor.

Şehir ve kurum tercihleri resmî uygunluğu değiştirmez; şartları karşılayıp tercih dışı kalan
ilan “Uygun” sekmesinde “Tercih dışı” etiketiyle görünür. “Tercihen” ifadeleri zorunlu
sayılmaz. Genel şartlarda (“herhangi bir lisans programı”) bölüm farkı elenme sebebi değildir.

## Bilinen sınırlar

- OCR her taranmış PDF'i doğru okuyamaz; OCR ile okunan ya da okunamayan ilan “Doğrulanmalı”
  kalır ve elle doğrulama için PDF'i yanında sunulur.
- Yerel Yönetimler duyurularının ek belge sunucusunun (`webdosya.csb.gov.tr`) sertifikası
  doğrulanamadığı için ekleri indirilmez; aynı ilanlar çoğunlukla diğer kaynaklardan gelir.
- ÖSYM tercih kılavuzundaki kadrolar tek tek ayrıştırılmaz; kılavuz bağlantısı gösterilir.
- Tarih çıkarımı kural tabanlıdır; alışılmadık cümle yapılarındaki tarihleri kaçırabilir.
  Kaçan tarih ilan panelinden elle eklenebilir.
- Yapay zekâ modeli (metin ya da görüntü) kullanılmaz; ilgili isteğe bağlı adımlar eklenmedi.

## Otomatik günlük tarama (GitHub Actions)

`.github/workflows/gunluk-tarama.yml` günde iki kez tarama yapıp `careerpilot.db` dosyasını
depoya işler. GitHub ve Render sunucuları yurt dışında olduğu için SBB, Kariyer Kapısı ve
Yerel Yönetimler kaynakları bu ortamlarda engellenebilir. Bu üç kaynağın düzenli güncel
kalması için uygulamayı Türkiye'den erişebilen bilgisayarda açık tutun; yerel başlangıç
scripti 12 saatte bir tarar. Render'daki “Şimdi tara” düğmesi uzak sunucu erişim engelini
aşamaz. Komut satırından yerel tam tarama: `.venv/bin/python -m backend.sync`

## Testler

```bash
.venv/bin/python -m pytest -q
npm --prefix frontend test
npm --prefix frontend run build
```

Backend testleri geçici bir veritabanı kullanır; `careerpilot.db` dosyasına dokunmaz.
