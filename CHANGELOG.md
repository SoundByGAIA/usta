# Değişiklik günlüğü

## 0.4.1 — geliştirici modu düğmesi ve katkıcı adları

Küçük düzeltme sürümü; model davranışı DEĞİŞMEDİ.

- **Geliştirici modu başlıkta görünür:** "Geliştirici modu: Kapalı/Açık" düğmesi artık her zaman üst çubukta; Ayarlar'daki seçici de aynı adı taşıyor. Önceden geçiş Ayarlar'da küçük bir "Görünüm" seçicisinin arkasındaydı ve bulunamıyordu.
- **Katkıcı adları:** `NOTICE` dosyası eklendi (Ordis; Uğur Can Leba ve Claude Ordis mimarları; Berke Dündar güvenlik ve geliştirme; Ceren Yıldız başöğretmen ve yerelleştirme); README'lerde ve paket yazarlarında da var. Apache-2.0 4(d) gereği türev çalışmalarda korunmalıdır.
- **Doğrulandı:** Claude (Anthropic) uyumluluk ucu gerçek anahtarla denendi: sohbet çalışıyor; `/v1/models` listesi `anthropic-version` başlığı ister, sabit model listesi geçerli.

## 0.4.0 — yeni kullanıcı dostu arayüz ve terminalsiz kullanım

İlk kodsuz kullanıcı testinin (Windows 10, [docs/kullanici-testi-2026-11-09.md](docs/kullanici-testi-2026-11-09.md)) ve geri bildirim turunun sonucu. Model davranışı DEĞİŞMEDİ; bu sürüm kullanılabilirlik işidir. Windows'taki yeni parçalar (masaüstü simgesi, arka plan modu, tek örnek, kapatma, bellek tespiti) 10 Kasım 2026'da gerçek Windows 10 + Python 3.14'te, yetkisiz token ile denendi ve geçti. `Usta-Kur.bat` yayından sonra denenecek.

- **Basit görünüm (varsayılan) ve Gelişmiş görünüm:** Basit görünümde yalnız yazı kutusu, başlangıç işleri, sonuç ve dosyalar var; araç/API/mod/çalışma alanı gibi gelişmiş öğeler gizli. Ayarlar'dan "Gelişmiş" seçilince hepsi döner. Mevcut kullanıcılar için de varsayılan "Basit"tir; Ayarlar → Görünüm'den değiştirilir.
- **Terminalsiz kullanım:** `python -m usta --kisayol` masaüstüne "Usta" simgesi koyar (Windows `.lnk`, Linux `.desktop`); simge Usta'yı pencere açmadan arka planda (`--arka-plan`) başlatıp tarayıcıyı açar. Zaten açıksa ikinci tıklama yeni süreç açmaz, tarayıcıyı yeniden bağlar. Ayarlar → "Usta'yı kapat" ile kapatılır. Arka plan modunun günlüğü `~/.usta/usta.log`. `kurulum/Usta-Kur.bat`: Python'u denetler, Usta'yı kurar, simgeyi koyar, açar (Windows).
- **Başlangıç işleri ve devam önerileri:** boş ekranda tıklanabilir 6 örnek iş; her sonuçtan sonra "Rengini değiştir" gibi öneriler.
- **Sonuç kartı:** görev bitince "Sonucu aç" (Sonuç sekmesi), "Dosyaları göster" (Dosya Gezgini'nde açar) ve sade "Yaptığı değişikliği geri al".
- **Düz Türkçe onaylar ve ilerleme:** "Usta `index.html` dosyasını yazmak istiyor" gibi cümleler (teknik ayrıntı katlı); okunan içerikten gelen hedefler için uyarı; akışta "Dosya yazılıyor: index.html" (ham araç adı yerine). Görev hataları (429, 402, 401…) anlaşılır cümlelere çevrilir.
- **Güven göstergesi:** üst çubukta "Bu bilgisayarda" / "Bulutta (servis)".
- **Yeni servisler:** Claude (Anthropic; model listesi sabit, çünkü uyumluluk ucunda `/models` doğrulanamadı; Anthropic bu yolu "deneme amaçlı" etiketler) ve OpenCode (ücretli ağ geçidi; `chat/completions` ile çalışan ücretli modeller süzülerek gösterilir; ücretsiz modeller yalnız OpenCode uygulamasında çalışır). Gerçek anahtarla ikisi de henüz denenmedi.
- **Beklenmeyen hata yakalayıcı:** ham Python hatası yerine kısa açıklama ve gizli bilgi içermeyen rapor dosyası (`~/.usta/rapor-*.txt`); yönetici yetkisiyle oluşmuş `.usta` klasörü için ayrı açıklama.
- Düzeltme: Ofis sekmesi ilk açılışta görünür kalıyordu (`display:flex`, `hidden` özniteliğini eziyordu).

## 0.3.2 — kodsuz kullanıcı testinin 1. turundan sihirbaz iyileştirmeleri

Notlar: [docs/kullanici-testi-2026-11-09.md](docs/kullanici-testi-2026-11-09.md). Model davranışı DEĞİŞMEDİ.

- **Karşılama ekranı:** "Yapay zekâ nerede çalışsın?" artık iki seçeneği artı/eksileriyle yan yana gösterir ve bilgisayarının belleğine bakarak bir öneri yazar.
- **Yerel model rehberi:** bilgisayarın belleği bulunur ve ona göre model önerilir (6 GB altı: yerel önerilmez; 6-12 GB: `qwen3:4b-instruct-2507-q4_K_M`, 2,5 GB; 12 GB ve üstü: `qwen2.5-coder:7b`, 4,7 GB; yalnız bizim çalıştırıp denediğimiz modeller). Ollama kurulu/açık değilse adım adım kurulum kartı; model yoksa **tek tıkla indirme** ve ilerleme çubuğu (Ollama `/api/pull`). Öneriler denenmiş modellerle sınırlıdır; büyük modeller önerilmez (ölçülmedi).
- **Servis başına anahtar anlatımı:** her servis için adım adım yönerge, resmî anahtar sayfasına tıklanabilir bağlantı ve açık bir not. "Ücretsiz seçenekler" ayrı gruplanır: Google Gemini (ücretsiz kota; ücretsiz katmanda verinin ürün geliştirmede kullanılabileceği uyarısıyla) ve OpenRouter (`openrouter/free`; `openrouter/auto` ücretlidir, uyarı yazar). DeepSeek ve OpenAI "ücretli" etiketli.
- **Bekleme geri bildirimi:** model seçilince yetenek ölçümü yarım dakika sürebiliyordu ve ekran sessizdi; artık "Modeli tanıyorum, bu yarım dakika sürebilir" yazar ve düğmeler kilitlenir.
- Not (eklenmeyenler): OpenCode'un ücretsiz modelleri resmî sayfasına göre yalnız OpenCode uygulamasında çalışır ("Free-tier chat models require OpenCode"), Usta gibi başka istemcilerden kullanılamaz; Claude'un OpenAI-uyumlu ucu "deneme amaçlı" etiketli ve `/models` desteği doğrulanamadığından eklenmedi.

## 0.3.1 — Windows'ta yönetici olmayan kullanıcı için açılış düzeltmeleri (ayrı yayınlanmadı; 0.3.2 ile birlikte çıktı)

İlk gerçek kodsuz kullanıcı testinin (Windows 10, normal hesap) bulduğu iki engel. Notlar: [docs/kullanici-testi-2026-11-09.md](docs/kullanici-testi-2026-11-09.md).

- **Windows'ta yönetici olmayan kullanıcıda Usta hiç açılmıyordu:** her çalışma alanı için sembolik bağ kuruluyordu, bu da Windows'ta yönetici yetkisi ister (`WinError 1314`). Ayrıcalık yoksa aynı işi gören dizin birleşimine (junction) düşülür. v0.3.0'ın Windows denemesi yönetici yetkili SSH oturumundan yapıldığı için bu görülmemişti; bu sürüm yetkisiz token ile sınandı.
- **Ev klasöründen başlatınca hata veriyordu:** `cmd` kullanıcı klasöründe (`C:\Users\Ad`) açılır; Usta orayı çalışma alanı sayıp "çalışma alanı olamaz" diye çıkıyordu. Klasör verilmediyse ve bulunduğun yer uygun değilse artık `~/Usta` klasörünü kendisi kurar, bunu açıkça söyler. `-w` ile açıkça verilen uygunsuz klasör yine hata verir.

## 0.3.0 — herkes için: kurulum sihirbazı, Windows, tablet/telefon

~20 kişilik kullanıcı geri bildiriminden doğdu: [docs/geri-bildirim-v0.3.md](docs/geri-bildirim-v0.3.md). Model
başarısı iddiası yoktur; bu sürüm kullanılabilirlik ve gizlilik işidir. Varsayılan model davranışı DEĞİŞMEDİ.

- **Kurulum sihirbazı:** model seçilmemişse (ya da `usta --setup`) portal sade bir sihirbazla açılır: "Bilgisayarımda" (Ollama'yı kendisi bulur) ya da "İnternet servisiyle" (DeepSeek, Gemini, OpenRouter, OpenAI; anahtar yapıştır). Sonunda modele bir "merhaba" gönderip çalıştığını gösterir. Hata mesajları kodsuz kullanıcıya göre ("Anahtar kabul edilmedi", "Hesabında bakiye yok görünüyor"). Servislerin model listesinden ses/görsel/gömme modelleri süzülür.
- **Windows uyumu (`compat.py`), gerçek Windows 10 + Python 3.14'te denendi (SSH ile 16 uçtan uca kontrol + gerçek terminal oturumu):** Windows'ta bulunmayan POSIX çağrıları (`os.O_NOFOLLOW`, `os.getuid`, `os.killpg`, `os.fchmod`) için güvenli karşılıklar; konsol UTF-8'e çevrilir ve renk kodları açılamazsa düz yazıya düşülür; `python -m usta` eklendi (Windows'ta `usta.exe` klasörü PATH'te olmayabilir). Gerçek denemenin bulduğu hatalar düzeltildi: ajanın yazdığı dosyalar sistem kodlamasıyla (cp1254) yazılıyordu, artık tüm metin dosyaları UTF-8 (kaynak taraması testi kodlamasız I/O'yu yasaklar); istemde `☺☻` işaret karakterleri (readline yokken); Docker yokken anlaşılmaz hata yerine açıklayıcı mesaj; sandbox `C:\...` yollarını reddediyordu (yalnız Windows'ta sürücü harfi serbest). Docker'lı komut çalıştırma ve `--lan` Windows'ta DENENMEDİ.
- **Düşünme ayarı:** kapalı / az / orta / çok (`reasoning_effort`); alanı tanımayan uç noktada kullanıcıya hata göstermeden bırakılır.
- **Bağlam ayarı:** portaldan; yerel Ollama'da gerçek `num_ctx`'li model varyantı oluşturma ("Bilgisayarımdaki model" kartı).
- **Yerel model bulma:** Ollama, LM Studio, llama.cpp, vLLM portlarını yalnız `127.0.0.1`'de arar ya da elle port.
- **Gizlilik ekranı:** istemlerin nereye gittiği (bu bilgisayar / yerel ağ / internet) gerçek duruma göre hesaplanır; ev dizinindeki dosyalar listelenir. "Telemetri yok" iddiası testle korunur: kaynakta ağa çıkabilen modüller bilinen bir listeden fazlaysa test kırılır; arayüz dışarıdan kaynak yüklemediği de test edilir.
- **Tablet/telefon (`usta --lan`), varsayılan KAPALI:** portal yerel ağa açılır; tablet 6 haneli, tek kullanımlık, 5 dakikalık bir kodla girer (5 yanlışta kilitlenir). Trafik şifrelenmez: yalnız güvenilir ağda kullanılır; sahte `Host` başlıkları reddedilir.
- **Ayarlar paneli:** boyut, düşünme, bağlam ve renk seçicileri üst çubuktan tek bir panele toplandı.
- `usta serve` modunda model değiştirme/sihirbaz yoktur (yalnız `usta` portal modunda).

## 0.2.2 — orta zorlukta bench ve kademeli yönlendirme (deneysel)

Ölçümler ve sınırlar: [docs/bench-orta-olcum.md](docs/bench-orta-olcum.md). Varsayılan davranış DEĞİŞMEDİ.

- **9 yeni orta zorlukta bench görevi** (`mid-*`, 6 dev + 3 final; 2-4 dosyalı hata ayıklama, imza değişikliği, durum makinesi, önbellek, ayrıştırıcı). Her görevin referans çözümü bağımsız doğrulandı (başlangıçta başarısız, çözümle geçer); istem-test tutarlılığı ayrı bir model tarafından denetlendi ve uyuşmayan 2 görev elendi. Eski bench doygundu (güçlü modelde hepsi geçiyor, 7B'de hepsi kalıyor); yenisi modelleri ayırt ediyor: 7B 0/18, Gemini 2.5 Flash 7→14/18 (B→C), Pro 15→16/18. C kolunun faydası orta güçteki modelde yönlü ama aralıklar örtüşüyor: **kanıtlanmadı**.
- **Kademeli yönlendirme (`cascade.py`), DENEYSEL, varsayılan değil:** ucuz modelle başla, bitirme kapısı/devre kesici takılınca ya da ucuz model düzenlemeden "bitti" derse güçlü modele devret. Bench'te `X-CASCADE` kolu; `usta bench run --arm X-CASCADE --strong-model … [--strong-endpoint … --strong-protocol … --strong-api-key-env …]`. Ölçüm: Flash→Pro 12/18 (tek model 14/18), 7B→Flash 14/18 ama bulut token tasarrufu ~%7 (gürültü): **fayda kanıtlanmadı**.
- Bench sonuçlarına `escalated` ve `strong_tokens` alanları eklendi.
- CI: `publish` iş akışı release yayımlanınca PyPI Trusted Publisher ile çalışır.
- Referans çözümler `tests/bench_solutions/` altında (pakete girmez).

## 0.2.1 — Ofis ve kaynak izi kapısı

Ölçümler ve sınırlar: [docs/v0.2.1-raporu.md](docs/v0.2.1-raporu.md). Rakiplerle dürüst karşılaştırma: [docs/comparison.md](docs/comparison.md).

- **Kaynak izi kapısı (`taint.py`), varsayılan AÇIK:** okunan içerikten türeyen yazma/komut hedefleri onay ister (oto modda reddedilir). 7B Lab'da gerçekleşen yetkisiz eylem 6→2/40; yanlış alarm gözlenmedi (7B Lab'da 40, DeepSeek Lab'da 44, bench'te 96 meşru koşu). Kanıt yönlüdür, istatistiksel olarak güçlü değildir (aralıklar örtüşüyor). Kapatmak: `--no-taint-gate` / `USTA_TAINT_GATE=0`. Bench'te `X-TAINT` kolu.
- Model çıktısı sınırında kesilen/bozuk araç argümanı artık görevi öldürmez: araç hatası olarak modele döner ("daha küçük parçalarla dene"). Daha önce `araç çağrısı çözümlenemedi` ile görev düşüyordu.
- Portal: **Ofis** sekmesi (piksel-sanat ofis animasyonu). Ajan olaylarını (araç çağrısı, onay isteği, bitiş) canlıda ve geçmiş oturum tekrarında gösterir; bağımlılık ve harici görsel yok; sayaçlar yalnız gerçek olaylardan gelir. Varsayılan sekme değişmedi (Akış).
- v0.2.0 öncesi (imajsız) MCP kayıtları için hata mesajı düzeltildi: "docker pull None" yerine `usta mcp add --image` ile yeniden kaydetme yönergesi.

## 0.2.0 — güvenilirlik ve ölçüm

Sonuçlar, maliyetler ve doğrulanamayan hipotezler: [docs/v0.2.0-raporu.md](docs/v0.2.0-raporu.md).

**Güvenlik (kırıcı değişiklik içerir)**
- MCP sunucuları varsayılan olarak **yalıtılmış Docker konteynerinde** çalışır (ağ kapalı, salt okunur kök, `cap_drop=ALL`, ev dizini/Docker soketi yok, sınırlar).
  Docker/imaj yoksa sunucu başlamaz, ana makineye düşülmez. `usta mcp add` artık `--image` ister; eski kayıtlar (imajsız) başlamaz ve nedenini söyler.
  Ana makinede çalıştırma ayrı bir uyumluluk modudur: `--isolation host --i-understand-host-risk`. `usta mcp prepare` paket/imaj sabitler.
  Plan modunda MCP sunucuları hiç başlatılmaz.
- Kalıcı hafıza notları kaynak izi taşır; şüpheli notlar onay ister (oto modda reddedilir).
- Hash'li kilit dosyaları (`make lock`), CI kilitten kurar; sandbox imaj sabitleme (`usta sandbox pin`).
- Geri alma yalnız dosyaları kapsar notu; doğrulama ortamı hatası (eksik bağımlılık) kod hatasından ayrıldı.

**Ölçüm ve gözlemlenebilirlik**
- `usta lab`: Reliability Lab (20 saldırı + 4 hata senaryosu, eşleştirilmiş temiz kontroller, ASR/deneme/gerçekleşme/yanlış ret/toparlanma/token/gecikme/tutarlılık).
- `usta bench`: başarısızlık sınıflandırması, adım izi, `replay`, `diagnose`, `regress`, eşleştirilmiş kol karşılaştırması, altyapı hata oranı, train/dev/final bölümleri
  (varsayılan **final hariç**), 8 yeni kolay görev, deneysel kollar X-BRK/X-CTX/X-ALL/X-FULL/X-SYM (A–D anlamları değişmedi).
- `usta probe --deep` ve `--protocol auto`: protokol başına yetenek profili (model revizyonu + yapılandırmaya bağlı).
- Yürütme aşamaları gözlemcisi ve terminal durumlar (`done` olayında `terminal`; denetim kaydında `phase`/`terminal`).
- Deneysel (varsayılan kapalı): Tree-sitter sembol araçları (`--symbol-tools`, `pip install 'usta[symbols]'`), onarım bütçesi zorlaması.

## 0.1.0 — ilk yayın adayı

Terminal + yerel portal, modlar (manuel / oto onay / plan), aşamalı plan uygulama, Docker sandbox + allowlist proxy,
kalıcı oturumlar, proje hafızası, MCP istemcisi ve kataloğu, beceriler, çok API desteği ve model değiştirme, dosya gezgini,
önizleme, `usta bench` ölçüm düzeneği (kollar A–D), doğrulama kapısı ve devre kesici, bağlam bütçesi ve kalibrasyonu.

Güvenlik: yayın öncesi bağımsız inceleme yapıldı; bulunan sorunlar kapatıldı (geri alma sembolik bağı izlemez, `.git`/`.usta`
korumalı, çalışma alanı sınırları, giriş kodu komut satırında görünmez, gövde sınırı ve Host denetimi, IPv6 NAT64 SSRF, maskeleme,
pypdf CVE'leri). Bilinen sınırlar için [SECURITY.md](SECURITY.md).

Ön ölçümler için [README](README.md); örneklem küçüktür, harness'ın başarıyı artırdığı iddia edilmez.
