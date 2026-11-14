# CareerPilot TR – Kamu Kariyer Asistanı

## Modern React arayüzü

Yeni arayüz `frontend/` altında React, TypeScript, Vite ve Tailwind ile
oluşturulmuştur. Eski Streamlit arayüzü yerel/Render uyumluluğu için
`frontend/app.py` konumunda kalır; kopyası `legacy/streamlit/` altındadır.
Render Blueprint, mevcut FastAPI ve Streamlit servislerine ek olarak React
statik sitesini `careerpilot-tr-web` adıyla tanımlar.

Ön koşul: Node.js 20 veya üstü ve npm.

```powershell
Set-Location frontend
npm ci
$env:VITE_API_URL = "http://127.0.0.1:8000"
npm run dev
```

Tarayıcıdaki Vite uygulaması `http://localhost:5173` adresinde açılır. Aday
profili ekranındaki **Profili düzenle** düğmesi yaş, KPSS puanı ve diğer profil
alanlarını `/profile` API'si üzerinden kaydeder; kayıttan sonra uygunluk
analizleri yenilenir. Bu işlem için yerel backend'i demo modu kapalı çalıştır.
Demo modu veri değiştiren istekleri engeller. Arayüz sunucu tarafından
hesaplanan uygunluk sonuçlarını kendisi yeniden hesaplamaz. Backend erişim
anahtarı statik dosyalara veya Vite değişkenlerine konmamalıdır. Giriş ekranında
sağlanan anahtar yalnızca tarayıcı belleğinde tutulur ve `/auth/check` ile
doğrulanır. Böylece API anahtarı frontend build'ine gömülmez.

Frontend doğrulaması:

```powershell
npm test
npm run build
```

Render statik sitesinin `VITE_API_URL` değeri `https://careerpilot-tr-api.onrender.com`
olarak ayarlanmıştır. Streamlit servisi ayrı kalır ve sunucu tarafındaki
`CAREERPILOT_ACCESS_TOKEN` değerini kullanır.

Bu ilk sürümün amacı iki farklı kariyer kanalını tek uygulamada toplamak:

1. **Kamu:** KPSS merkezi yerleştirme, kurum ve belediye ilanlarını kaydetmek; puan türü ve asgari puan için yalnızca ön kontrol yapmak.
2. **Özel sektör:** Farklı şirketlerden ilanları kaydetmek; pozisyon gruplarına göre birden fazla ilanda geçen becerileri saymak.
3. **Profil:** Eğitim, bölüm, KPSS P3 ve mevcut becerileri saklamak.

> Uygulama tanımlı kamu kaynaklarını tarayabilir; başvuru yapmaz. Aday CV'sini veya kişisel belgeleri okumaz.

## 1. Gerekenler

- Python 3.11 veya 3.12
- VS Code (önerilir)
- Terminal / PowerShell

## 2. Kurulum (Windows PowerShell)

ZIP'i çıkarttıktan sonra VS Code ile `careerpilot_tr` klasörünü aç. Terminal > New Terminal seç.

```powershell
py --version
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

PowerShell sanal ortamı etkinleştirmeyi engellerse, yalnızca o terminal oturumu için şu komutu çalıştırıp aktivasyonu tekrar dene:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## 3. Uygulamayı çalıştır

**Terminal 1 – API (backend):**

```powershell
uvicorn backend.main:app --reload
```

Tarayıcıda `http://127.0.0.1:8000/docs` adresini açarsan API uçlarını görebilirsin.

**Terminal 2 – Arayüz (frontend):**

VS Code'da Terminal > New Terminal ile ikinci terminal aç. Sanal ortam etkin değilse yeniden etkinleştir.

```powershell
streamlit run frontend/app.py
```

Arayüz normalde `http://localhost:8501` adresinde açılır.

## Salt okunur özel yayın

Uygulamayı internete açmadan önce her iki süreçte de demo modunu etkinleştir. Bu modda POST, PUT, PATCH ve DELETE istekleri engellenir. Profil ve uygunluk analizleri dâhil tüm GET uçları erişim anahtarı ister; yalnızca `/health` anahtarsızdır.

**Gizlilik uyarısı:** `/profile` kişisel aday bilgilerini, puanları, tercihleri ve notları döndürür; `/public/matches` bu profil ile hesaplanan sonuçları da gösterebilir. Bu uçlar erişim denetimi olmadan internete açılırsa herkes bu bilgileri okuyabilir. Kişisel veriler içeren `careerpilot.db` dosyasını GitHub'a veya herkese açık bir servise göndermeden önce deponun Private olduğunu doğrula ve bu verilerin paylaşılmasını ayrıca değerlendir.

Backend terminalinde:

```powershell
$env:CAREERPILOT_DEMO_MODE = "true"
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Frontend terminalinde:

```powershell
$env:CAREERPILOT_DEMO_MODE = "true"
$env:CAREERPILOT_API_URL = "http://127.0.0.1:8000"
streamlit run frontend/app.py --server.address 0.0.0.0
```

Yerel demo kullanımı için backend terminalinde ayrıca bir test anahtarı belirle ve arayüzde sorulduğunda gir:

```powershell
$env:CAREERPILOT_ACCESS_TOKEN = "yalnizca-yerel-test-anahtari"
```

Bu örnek anahtarı internette kullanma. Render'da üretilen erişim anahtarını herkese açık paylaşmak, profil ve analiz verilerini de herkese açar.

## Render Blueprint yayını

Proje kökündeki `render.yaml`, aynı GitHub deposundan iki ücretsiz Web Service tanımlar: mevcut `careerpilot-tr-api` FastAPI servisi ve ona bağlanan `careerpilot-tr-frontend` Streamlit servisi. Frontend servisindeki `API_URL`, `https://careerpilot-tr-api.onrender.com` değerine ayarlanmıştır; yerel geliştirmede kodun varsayılanı `http://127.0.0.1:8000` olarak kalır. Backend Blueprint'i `CAREERPILOT_ACCESS_TOKEN` için gizli bir değer üretir; Render `fromService` referansı bu değeri doğrudan frontend sunucusunun ortamına aktarır. Streamlit sunucusu anahtarı API isteklerine ekler; ziyaretçiden parola istenmez ve anahtar tarayıcıya verilmez. Veri değiştiren istekler kapalıdır. Bu nedenle yayındaki siteyi açan herkes profil ve uygunluk analizlerini görebilir; bu kişisel verilerin herkese açık olacağını göz önünde bulundur. `autoDeploy: false` nedeniyle GitHub'a push tek başına dağıtım başlatmaz; Render Blueprint değişikliklerini inceleyip uygulamak gerekir.

Render ücretsiz servislerinin yerel dosya sistemi kalıcı değildir; SQLite dosyasında çalışma sırasında yapılan değişiklikler yeniden başlatma veya yeni dağıtımda kaybolabilir. Frontend sağlık kontrolü `/_stcore/health`, API sağlık kontrolü `/health` yolunu kullanır.

Uygulama varsayılan olarak proje kökündeki `careerpilot.db` dosyasını kullanır. Dosya bulunamazsa uygulama boş veritabanı oluşturarak mevcut kayıtları gizlemek yerine açık hata verir. Bu veritabanı aday profili ve kişisel notlar içerdiğinden, depoya eklemeden önce GitHub deposunun Private olduğunu doğrula. Depo Private değilse veritabanını Git'e ekleme veya push etme.

## 4. İlk deneme sırası

1. **Profilim:** Eğitim seviyeni, bölümünü ve KPSS P3 puanını gir. Beceri alanına kanıtlayabildiğin teknolojileri yaz.
2. **Kamu İlanları:** Bir resmî ilanı kaydet. İlanın orijinal bağlantısını ve tüm özel koşullarını ekle.
3. **Özel Sektör İlanları:** Aynı pozisyon grubundan en az 10 farklı ilan kaydet. Her birinin becerilerini virgülle ayırarak yaz.
4. **Piyasa Analizi:** İlgili pozisyon grubunu seç. Beceri tablosu, seçili ilanların kaçında o becerinin geçtiğini gösterir.

Örnek: 10 Data Engineer ilanının 8'inde SQL varsa sonuç 8/10 = %80 olur. Bu, bütün Türkiye piyasasının istatistiği değil, sisteme eklediğin ilan örnekleminin sonucudur.

## 5. Kamu ilanlarında uygunluk sınıfları

Kamu ilanı incelemesi üç kategori üretir:

- **UYGUN:** Metinden doğrulanabilen tüm zorunlu şartlar profil bilgileriyle karşılanıyor.
- **POTANSİYEL OLARAK UYGUN:** Açık bir uyumsuzluk yok, ancak en az bir zorunlu şart veya profil bilgisi bilinmiyor.
- **UYGUN DEĞİL:** Mezuniyet bölümü, KPSS puan türü veya taban puan gibi açık bir zorunlu şart karşılanmıyor.

4001 kodu herhangi bir lisans mezuniyetini karşılar. Yalnızca dört yıllık eğitim/fakülte ifadesi, bütün lisans bölümlerinin kabul edildiği şeklinde yorumlanmaz; bölüm listesi metinde yoksa eğitim şartı bilinmiyor kabul edilir. KPSS taban puanı 87,60 veya altındaysa profil puanı yeterlidir. Puan türü farklıysa bu açık uyumsuzluk olarak sınıflandırılır.

YDS puanının KPSS ile birlikte sıralama hesabında kullanılması tek başına zorunlu bir YDS taban şartı değildir; ilan puanı olmayan aday için 0 puan verileceğini söylüyorsa bu durum uygunluk engeli sayılmaz. Adayın yaşı, deneyimi veya zorunlu sertifikaları gibi gerçekten zorunlu olup profilde bulunmayan bilgiler potansiyel sınıfında kalır. Güvenlik soruşturması ve arşiv araştırması kurum süreçleri olduğundan adayın eksik şartı sayılmaz.

Bu sınıflandırma başvuru/atama garantisi vermez. Özellikle pozisyon bazında ayrıntılı nitelik, deneyim ve belge şartlarını resmî ilanın ve eklerinin bağlantılarından doğrula.

## Resmî ilan eklerini inceleme

Kariyer Kapısı, SBB, İŞKUR ve Yerel Yönetimler ilanlarının resmî detay bağlantılarındaki PDF, DOCX ve HTML ekleri `backend.document_sync` ile taranır. Yalnızca gerçek ilan detay sayfaları taranır; genel bilgi ve rehber sayfaları ek olarak değerlendirilmez. PDF tabloları satır ve sütun geometrisi kullanılarak ayrıştırılır; her kadro satırı kendi kontenjan, KPSS türü/taban puanı, atanma yeri ve yazılı sınava çağrı bilgisiyle saklanır. Sınava çağrı sıralaması uygunluk sınıflandırmasından ayrı gösterilir. Kaynağın kayıtlarında ilana özgü detay bağlantısı yoksa belge taraması açıkça kullanılamıyor olarak raporlanır; ana liste bağlantısı ilan eki gibi kullanılmaz.

İlan kaynaklarını senkronize etmek ek belgeleri de kontrol eder. Yalnızca ekleri tekrar taramak için:

```powershell
python -m backend.document_sync
```

Tek bir ilan için `python -m backend.document_sync --job-id 5` kullanılabilir. Belge hash'i ve varsa ETag/Last-Modified bilgisi saklanır; sunucu değişiklik olmadığını doğrularsa belge gövdesi yeniden indirilmez. Geçici erişim veya ayrıştırma hataları önceki başarılı metni ve pozisyon satırlarını silmez. Tarama/okuma durumu ve resmî belge bağlantıları uygunluk analizindeki “İlan ve ek belge incelemesi” bölümünde görünür. Desteklenmeyen veya okunamayan belgeler incelenmiş gibi işaretlenmez.

Render demo modunda veri değiştiren POST istekleri kapalıdır. Bu nedenle belge taramasını yerel ortamda çalıştır; yayında daha önce saklanan ek-belge verileri varsa GET analizlerinde görüntülenir.

## 6. Veri ve gizlilik

- İlan ve profil verileri bu proje klasöründeki `careerpilot.db` adlı yerel SQLite dosyasında tutulur.
- Gerçek CV'ni veya kişisel belgelerini GitHub'a yükleme.
- `.gitignore`, yerel veritabanını ve sanal ortamı Git dışında tutar.
- Gerçek kullanıcı verisi paylaşmadan önce kaynak sitelerin kullanım koşullarını ve kişisel veri yükümlülüklerini kontrol et.

## 7. Şu anki teknik yapı

- **React, TypeScript, Vite ve Tailwind:** Yeni web arayüzü
- **Streamlit:** Mevcut/legacy web arayüzü
- **FastAPI:** Backend / REST API
- **SQLAlchemy + SQLite:** Veri saklama
- **TanStack Query, Recharts ve Lucide:** İstemci veri yönetimi, grafikler ve ikonlar
- **pytest:** Temel testler
- **Vitest ve Testing Library:** Frontend testleri

## 8. Sonraki geliştirme aşamaları

1. Resmî ve izinli kaynaklardan kamu ilanı içe aktarma; kaynak, tarih ve son başvuru takibi.
2. Özel sektör ilanlarını çoklu kaynaklardan toplama, tekrarları ayıklama ve ilan tarihçesi.
3. Becerileri NLP/LLM ile çıkarma; zorunlu ve tercih sebebi becerileri ayırma; eval veri seti.
4. CV PDF okuma ve kanıt bazlı beceri eşleştirme.
5. PostgreSQL, Docker, n8n ve zamanlanmış otomasyon.
6. RAG bilgi hafızası, AI Agent, kişisel öğrenme planı ve aralıklı tekrar.
