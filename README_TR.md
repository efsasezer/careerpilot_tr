# CareerPilot – Kamu + Özel Sektör Kariyer Asistanı (v0.1)

Bu ilk sürümün amacı iki farklı kariyer kanalını tek uygulamada toplamak:

1. **Kamu:** KPSS merkezi yerleştirme, kurum ve belediye ilanlarını kaydetmek; puan türü ve asgari puan için yalnızca ön kontrol yapmak.
2. **Özel sektör:** Farklı şirketlerden ilanları kaydetmek; pozisyon gruplarına göre birden fazla ilanda geçen becerileri saymak.
3. **Profil:** Eğitim, bölüm, KPSS P3 ve mevcut becerileri saklamak.

> Bu sürüm ilan sitelerini henüz otomatik taramaz ve resmi başvuru yapmaz. Önce veri modelini ve toplu analiz mantığını çalışır hâle getiriyoruz. Kaynak entegrasyonları, PDF CV analizi, gelişmiş uygunluk kuralları, RAG, AI Agent, bildirimler ve öğrenme/tekrar sistemi sonraki aşamalardır.

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

## Herkese açık salt okunur demo

Uygulamayı internete açmadan önce her iki süreçte de demo modunu etkinleştir. Bu modda tüm GET uçları (aday profili ve eşleştirmeler dâhil) okunabilir; POST, PUT, PATCH ve DELETE istekleri engellenir.

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

Bir barındırma servisine dağıtırken `CAREERPILOT_DEMO_MODE=true` değişkenini mutlaka ayarla. Demo modu yazma işlemlerini engeller ancak GET yanıtlarındaki kişisel verileri gizlemez.

## Render API yayını

Proje kökündeki `render.yaml`, ücretsiz `backend.main:app` FastAPI servisini, `/health` sağlık kontrolünü ve `PORT` kullanan başlangıç komutunu tanımlar. Kalıcı disk kullanılmaz; SQLite dosyası uygulama koduyla birlikte dağıtım paketinde bulunur. Ücretsiz serviste yerel dosya sistemi kalıcı değildir; veritabanında çalışma sırasında yapılan değişiklikler yeniden başlatma veya yeni dağıtımda kaybolabilir. `autoDeploy: false` nedeniyle GitHub'a push tek başına otomatik dağıtım başlatmaz.

1. Değişiklikleri GitHub'a göndermeden önce deponun Private olduğunu doğrula; kişisel veritabanını yalnızca bu doğrulamadan sonra ekle.
2. Render'da **New → Blueprint** ile aynı depoyu seç ve `render.yaml` yapılandırmasını inceleyerek onayla.
3. Servisin deploy loglarında `/health` kontrolünün başarılı olduğunu doğrula.
4. Render servisinin `https://<servis-adı>.onrender.com` adresini Streamlit Community Cloud ayarlarında **Secrets** bölümüne ekle:

   ```toml
   API_URL = "https://<servis-adı>.onrender.com"
   ```

   Ön yüz `API_URL` ortam değişkenini, yoksa `API_URL` Streamlit secret'ını okur; yerel varsayılan `http://127.0.0.1:8000` olarak kalır. Arayüz backend `/health` yanıtından demo modunu algılar.

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

Bu sınıflandırma başvuru/atama garantisi vermez. Özellikle pozisyon bazında ayrıntılı nitelik, deneyim ve belge şartlarını resmî ilanın okunabilir HTML metni ve başvuru ekranından doğrula. İlan eşitlemesi PDF belgelerini indirmez veya okumaz.

## 6. Veri ve gizlilik

- İlan ve profil verileri bu proje klasöründeki `careerpilot.db` adlı yerel SQLite dosyasında tutulur.
- Gerçek CV'ni veya kişisel belgelerini GitHub'a yükleme.
- `.gitignore`, yerel veritabanını ve sanal ortamı Git dışında tutar.
- Gerçek kullanıcı verisi paylaşmadan önce kaynak sitelerin kullanım koşullarını ve kişisel veri yükümlülüklerini kontrol et.

## 7. Şu anki teknik yapı

- **Streamlit:** Web arayüzü
- **FastAPI:** Backend / REST API
- **SQLAlchemy + SQLite:** Veri saklama
- **Pandas:** Analiz tablosu
- **pytest:** Temel testler

## 8. Sonraki geliştirme aşamaları

1. Resmî ve izinli kaynaklardan kamu ilanı içe aktarma; kaynak, tarih ve son başvuru takibi.
2. Özel sektör ilanlarını çoklu kaynaklardan toplama, tekrarları ayıklama ve ilan tarihçesi.
3. Becerileri NLP/LLM ile çıkarma; zorunlu ve tercih sebebi becerileri ayırma; eval veri seti.
4. CV PDF okuma ve kanıt bazlı beceri eşleştirme.
5. PostgreSQL, Docker, n8n ve zamanlanmış otomasyon.
6. RAG bilgi hafızası, AI Agent, kişisel öğrenme planı ve aralıklı tekrar.
