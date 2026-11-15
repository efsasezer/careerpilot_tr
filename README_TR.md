# CareerPilot TR – Kamu ilan takibi ve KPSS eşleştirme

KPSS ile atanmak isteyen bir aday için resmî kamu ilanı kaynaklarını tarar, her ilanı
adayın öğrenim durumu ve KPSS puanlarıyla karşılaştırır, uygun olanları listeler ve
yeni eşleşmeler ile yaklaşan son başvurular için bildirim üretir.

> Sonuçlar otomatik bir **ön elemedir**; başvuru ya da atama garantisi vermez.
> Başvurmadan önce resmî ilanı mutlaka okuyun.

## Neler yapar?

- **Dört resmî kaynağı tarar:** SBB Kamu İlanları, Kariyer Kapısı, İŞKUR kamu memur alım
  ilanları, Yerel Yönetimler Genel Müdürlüğü duyuruları.
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
.venv/bin/python -m playwright install chromium   # yalnızca Kariyer Kapısı taraması için
npm --prefix frontend ci
```

Windows'ta `.venv/bin/` yerine `.venv\Scripts\` kullanın.

## Çalıştırma

İki terminal açın:

```bash
sh scripts/run_api.sh
```

```bash
npm --prefix frontend run dev
```

- `scripts/run_api.sh`, `.env` dosyasını okur. `CAREERPILOT_ACCESS_TOKEN` tanımlı değilse
  rastgele bir anahtar üretip `.env` dosyasına yazar. Arayüze (`http://localhost:5173`) bu
  anahtarla girilir. Ayarların tamamı `.env.example` içinde açıklanmıştır.
- Betiği kullanmadan başlatmak için:
  `CAREERPILOT_ACCESS_TOKEN=... .venv/bin/python -m uvicorn backend.main:app`
- API belgeleri: `http://127.0.0.1:8000/docs`

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
  çoğunlukla İŞKUR/SBB üzerinden tam metniyle gelir ve tek kartta birleştirilir.
- SBB ilan bağlantıları oturuma özeldir; arayüz SBB liste sayfasına yönlendirir ve okunan
  resmî metni ilan ayrıntısında gösterir.
- ÖSYM merkezi yerleştirme (KPSS tercih kılavuzu) kadroları henüz taranmıyor.
- Uygulama tek aday profiliyle çalışır (çok kullanıcılı değildir).

## Testler

```bash
.venv/bin/python -m pytest -q
npm --prefix frontend test
npm --prefix frontend run build
```

Backend testleri geçici bir veritabanı kullanır; `careerpilot.db` dosyasına dokunmaz.

## Yayın (Render)

`render.yaml` üç servis tanımlar: FastAPI (`careerpilot-tr-api`), React statik sitesi
(`careerpilot-tr-web`) ve eski Streamlit arayüzü. Blueprint API'yi
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
legacy/, frontend/app.py   Eski Streamlit arayüzü (bakımı yapılmıyor)
```
