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

Üretimde **PostgreSQL** kullanılır (`DATABASE_URL`). Gerekçe: Render'ın ücretsiz servisinde dosya sistemi her
yeniden başlatmada sıfırlanır, yani SQLite dosyasındaki profil, kayıtlar ve notlar kalıcı değildir; ayrıca web
servisi ile başka bir ortamdaki tarayıcının aynı veriye aynı anda yazabilmesi gerekir. Yerel geliştirmede
`DATABASE_URL` tanımlı değilse proje kökündeki `careerpilot.db` (SQLite) kullanılır.

- **Sağlayıcı.** Herhangi bir PostgreSQL olur. Render'ın *ücretsiz* Postgres'i oluşturulduktan 30 gün sonra
  silinir; kalıcı veri için ücretli Render Postgres ya da ücretsiz katmanı süresiz olan bir sağlayıcı (ör. Neon,
  Supabase) kullanın. Adres `postgres://…` ya da `postgresql://…` biçiminde verilebilir.
- **Şema göçü.** Uygulama her açılışta `backend/migrate.py` çalıştırır: yalnızca eksik tablo, sütun ve indeks
  eklenir; hiçbir şey silinmez; kaç kez çalışırsa çalışsın sonuç aynıdır. SQLite'ta şema değişmeden önce dosyanın
  yedeği alınır. Uygulanan sürüm `schema_migrations` tablosundadır.
- **İlk veri.** `CAREERPILOT_DB_SEED_FROM_REPO=true` iken boş PostgreSQL veritabanı, depodaki `careerpilot.db`
  dosyasından bir kez doldurulur. Aktarım tek işlemdir ve satır sayıları ile içerik özeti kaynağınkiyle aynı
  değilse geri alınır. Dolu veritabanına dokunulmaz.
- **Yedek ve geri yükleme.**

  ```bash
  python -m backend.dbtools check                                  # taşma ve sahipsiz kayıt denetimi
  python -m backend.dbtools backup --out yedek.json.gz             # DATABASE_URL'deki veritabanını yedekler
  python -m backend.dbtools restore --in yedek.json.gz --url HEDEF # yalnızca BOŞ hedefe, doğrulamalı
  python -m backend.dbtools copy --from sqlite:///careerpilot.db --to postgresql://…
  ```

  Bu komutlar kaynağı yalnızca okur ve dolu bir hedefin üzerine yazmaz.
- **Tablolar.** İlan verisi (`jobs`, `source_listings`, `job_documents`, `document_positions`), tarama geçmişi
  (`source_sync_history`, `scan_locks`), tarihler (`job_events`), sonuç takibi (`result_*`), duyurular
  (`announcements`) ve kullanıcı verisi (`candidate_profile`, `user_job_state`, `user_verifications`, `user_tasks`,
  `notifications`, `app_settings`) ayrıdır. Tarama, kullanıcı tablolarına yazmaz.
- `careerpilot.db` depoda yalnızca ilk veri kaynağı olarak durur; üretim verisi artık Git üzerinden taşınmaz.
  PostgreSQL'e geçildikten sonra dosya depodan kaldırılabilir.

## Yayın (Render)

1. Bir PostgreSQL veritabanı oluşturun ve bağlantı adresini alın.
2. `careerpilot-tr-api` servisinde ortam değişkenlerini girin:
   `DATABASE_URL` (PostgreSQL adresi), `CAREERPILOT_PASSWORD`, `CAREERPILOT_SESSION_SECRET` (Render üretir),
   `CAREERPILOT_DB_SEED_FROM_REPO=true`, `CAREERPILOT_SYNC_INTERVAL_HOURS=6`,
   `PLAYWRIGHT_BROWSERS_PATH=/opt/render/project/src/.playwright-browsers`.
3. Build komutu: `pip install -r requirements.txt && python -m playwright install chromium`.
4. Önce API'yi, sonra `careerpilot-tr-web` sitesini yayınlayın.
5. Giriş yapıp **Kaynaklar › Erişim testi**ni çalıştırın. Test, o sunucudan her kaynağa DNS, bağlantı, sertifika
   ve HTTP katmanlarını ayrı ayrı ölçer ve tarayıcının (Chromium) açılıp açılmadığını gösterir.
   - Tarayıcı açılmıyorsa servis Docker ile çalıştırılmalıdır: depodaki `Dockerfile` Chromium'u sistem
     kitaplıklarıyla kurar (yerelde derlenip denenmiştir). Render'da mevcut servisin çalışma ortamı
     değiştirilemediği için Docker tabanlı yeni bir web servisi oluşturulur.

**Otomatik tarama.** `CAREERPILOT_SYNC_INTERVAL_HOURS` tanımlıysa servis, son taramadan o kadar saat geçtiğinde
kendisi tarar; tarama arka planda çalışır ve arayüzü kilitlemez. Aynı anda tek tarama çalışır: kilit veritabanında
tutulur (`scan_locks`), bu yüzden birden çok servis örneği ya da başka bir ortamdaki tarayıcı çakışmaz. Ücretsiz
Render servisi 15 dakika kullanılmayınca uyur; uyurken tarama yapılmaz, servis uyandığında gecikmiş tarama başlar.
Kesintisiz zamanlama için ücretli bir Render Cron Job'da `python -m backend.sync` çalıştırılabilir.

**Konuma bağlı kaynaklar.** SBB Kamu İlanları, Kariyer Kapısı ve Yerel Yönetimler, Türkiye dışındaki sunuculardan
gelen istekleri reddediyor ya da yanıtsız bırakıyor (HTTP 403, bağlantı zaman aşımı). Render'ın Türkiye'de bölgesi
yoktur; bu erişim kuralı yazılımla aşılmaz ve aşılmaya çalışılmaz. Bu üç kaynak, Türkiye'deki bir bilgisayardan
aynı veritabanına taranabilir:

```bash
DATABASE_URL=postgresql://… python -m backend.sync
```

macOS'ta bunu 6 saatte bir kendiliğinden çalıştırmak için: `sh scripts/tarayici_kur.sh` (kaldırmak için
`sh scripts/tarayici_kur.sh kaldir`). Kaynaklar sayfası her kaynağın en son hangi ortamdan başarıyla tarandığını
ve kaç gündür taranamadığını gösterir.

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

## GitHub Actions

Veritabanını depoya yazan zamanlanmış tarama kaldırılmıştır; üretim verisi PostgreSQL'dedir. `gunluk-tarama.yml`
yalnızca elle, deneme amacıyla çalıştırılabilir ve hiçbir şey kaydetmez.

## Testler

Gerçek PostgreSQL testleri (aktarım, yedek/geri yükleme, uygulamanın uçtan uca çalışması) yalnızca
`CAREERPILOT_TEST_POSTGRES_URL` tanımlıyken çalışır:

```bash
docker run -d --name careerpilot-pg-test -e POSTGRES_PASSWORD=test -p 55432:5432 postgres:16-alpine
CAREERPILOT_TEST_POSTGRES_URL=postgresql://postgres:test@localhost:55432/postgres pytest tests/test_postgres.py
```

```bash
.venv/bin/python -m pytest -q
npm --prefix frontend test
npm --prefix frontend run build
```

Backend testleri geçici bir veritabanı kullanır; `careerpilot.db` dosyasına dokunmaz.

## Sonuç takibi, YLSY duyuruları ve Kariyer Kapısı hesabı

**Sonuç takibi.** Her taramada (elle "Şimdi tara", `python -m backend.sync` ve günlük GitHub Actions) başvurusu biten
ilanların kurum sitesi kontrol edilir. Adres ilan metninden alınır ("sonuçlar www.kurum.gov.tr adresinde ilan edilecektir");
metinde adres yoksa ilan panelindeki "Sonuç takibi" bölümünden elle eklenebilir. Bulunan duyuru; kadro türü, kişi sayısı,
yıl, yayım tarihi ve duyuruda geçen ilan tarihleriyle eşleştirilir. Emin olunamayan duyuru "Eşleşme doğrulanmalı" olarak
gösterilir. Durumlar ayrı tutulur: sonuç bulundu, kontrol edildi ama yok, henüz tarihi gelmedi, kaynak kontrol edilemedi,
resmî adres bilinmiyor. robots.txt'e uyulur; sonuç listelerindeki kişi adları saklanmaz. Kapatmak için:
`CAREERPILOT_DISABLE_RESULT_CHECK=true`.

**YLSY duyuruları.** Kaynak yalnızca MEB Yükseköğretim ve Yurt Dışı Eğitim Genel Müdürlüğü'dür (yyegm.meb.gov.tr, RSS akışı
ve duyuru sayfaları). Başlığında "YLSY" ya da "1416" geçen duyurular eklenir. Kılavuz yayımlandığında şartlar ve tercih
tabloları okunur; adayın ALES puanı, puan türü, sınav yılı, not ortalaması ve doğum tarihi profilden alınır. Puan türü
girilmeden uygunluk kararı verilmez.

**Kariyer Kapısı hesabı.** `python -m backend.kk_account` ya da arayüzdeki "Tarayıcıyı aç ve aktar" düğmesi bu bilgisayarda
görünür bir tarayıcı açar. e-Devlet girişini kullanıcı yapar; şifre okunmaz ve saklanmaz, oturum pencereyle birlikte kapanır.
Sunucuda (Render, GitHub Actions) çalışmaz ve kendiliğinden yinelenemez. Hesap sayfalarının yapısı yalnızca oturum açıkken
görülebildiğinden ilk gerçek aktarıma kadar "doğrulanmadı" olarak işaretlidir.
