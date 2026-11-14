# Değişiklik günlüğü

## 0.8.2 — DeepSeek Harness gerçek denemesi ve telemetri kapatma

Model davranışı DEĞİŞMEDİ.

- **DSH telemetrisi varsayılan olarak kapalı çağrılır:** DeepSeek Harness'in ürün telemetrisi (OTLP ile DeepSeek'in toplayıcısına) vardır ve kendi belgelenmiş çıkış anahtarı `DSH_TELEMETRY_DISABLED` (boş olmayan her değer kapatır). Usta DSH'yi çağırırken bunu katalogdan verir. Katalogdaki "ek ortam değişkeni" yalnız koddan gelir (model/kullanıcı veremez), kullanıcı ortamından geçmez ve `USTA_DELEGATED`'ı ezemez; testle denetlenir. Diğer programlar için böyle bir ek yoktur (kendi telemetri ayarları Usta'nın denetiminde değildir).
- **DSH gerçek anahtarla uçtan uca denendi** (Node.js 24.22, izole `HOME`, DeepSeek API): yalnız okuma sorusuna doğru cevap (9 sn, dosya değişmedi, cevap veri olarak sarıldı); yazma kipinde (DSH'nin tek kipi) tam istenen tek dosya oluştu, başkasına dokunulmadı. Harcama bir sentin altında. Anahtar yalnızca DSH'nin kendi `.env` dosyasında durdu, çalışma alanına ya da başka dosyaya sızmadı.
- **Yazma kipi gerçek programla doğrulandı:** Claude Code yalnız okuma kipinde dosya oluşturmadı, yazma kipinde tam istenen dosyayı oluşturdu.
- **Notlar:** DSH, Node.js 24.9+ ister ve npm 11 kurulumda 5 paketin kurulum betiğini (`node-pty`, `koffi` vb.) varsayılan olarak çalıştırmaz; denemede bunlar olmadan headless çalıştı. Usta bunları kendiliğinden açmaz.

## 0.8.1 — Windows'ta orkestra şefi: süreç ağacı düzeltmesi

Model davranışı DEĞİŞMEDİ. 0.8.0'ın başka programları çağırma özelliğinin ilk gerçek Windows denemesi (Windows 10, Python 3.14, yetkisiz kullanıcının kendi oturumu; programlar yerine sahte `.cmd` sarmalayıcılar).

- **Düzeltilen hata:** Windows'ta zaman aşımı/iptal/çıktı sınırında yalnız ana program kapanıyordu, **çocuk süreçleri çalışmaya devam ediyordu** (Linux'ta süreç grubu öldürülüyordu, Windows kolunda yalnız `proc.kill()` vardı). Artık `taskkill /T /F` ile ağacın tamamı kapatılır; `taskkill` yoksa ana süreç kapatılır ve hata dışarı sızmaz. Gerçek Windows'ta doğrulandı (çocuk süreç 4,8 sn'de öldü).
- **Ortam izin listesi:** Windows programlarının yol çözmek için ihtiyaç duyduğu, gizli bilgi taşımayan değişkenler eklendi (`WINDIR`, `PROGRAMFILES`, `PROGRAMDATA`, `HOMEDRIVE`, `COMPUTERNAME` vb.); testle "anahtar/jeton/USTA içeren ad yok" denetlenir.
- **Windows'ta doğrulananlar:** `.cmd` sarmalayıcı üzerinden istemin stdin ile aynen gitmesi (Türkçe karakterler ve `& | < > " % ^ !` dahil), yalnız okuma bayrakları, çalışma klasörü, Usta'nın anahtarlarının çocuğa geçmemesi, `USTA_DELEGATED`, büyük çıktının kesilmesi, hata kodu ve anahtar maskeleme, argümanla istem alan programların (OpenCode, Hermes) reddi.
- **Denenmedi:** Windows'ta gerçek bir harness (orada kurulu değil; girişleri yapılamadı).

## 0.8.0 — Usta orkestra şefi: başka yapay zekâ programlarını yardıma çağırır (sen onaylarsan)

Model davranışı DEĞİŞMEDİ (araç yalnız sen bir programı AÇTIYSAN göreve eklenir). Tasarım, tehdit tablosu ve gerçek denemeler: [docs/c-orkestra-tasarim.md](docs/c-orkestra-tasarim.md).

- **Ayarlar → Yardımcı yapay zekâ programları:** bilgisayarında kurulu Claude Code, Codex, OpenCode, DeepSeek Harness ve Hermes görünür (sürümüyle). **Hepsi kapalı başlar**; açtığın programı Usta yardıma çağırabilir.
- **Her çağrıda sorulur.** Onay penceresi düz Türkçe: hangi program, ne iş, yalnız okuyacak mı yoksa DOSYA YAZMA izni de mi var. **"Otomatik onay" kipinde Usta başka programı hiç çağırmaz.** Plan kipinde araç yoktur. Varsayılan **yalnız okuma** (destekleyenlerde); DSH ve Hermes yalnız okuma kipi sunmadığı için bu açıkça yazılır ve çağrı yazma izni ister.
- **Güvenlik:** program listesi koda gömülü ve sabit (serbest komut yok; bayrakları programların kendi yardım çıktısından alındı, hiçbirinde "izinleri atla" bayrağı yok). Kabuk yok; istem mümkünse komuta değil stdin'e yazılır. Çocuk sürece yalnız izin listesindeki ortam değişkenleri gider (Usta'nın anahtarları gitmez). Zaman aşımı 10 dk, çıktı 20 000 harf, görev başına en çok 3 çağrı; zaman aşımında/iptalde program VE çocukları kapatılır. Çağrılan programa `USTA_DELEGATED=1` verilir: Usta başka bir programdan çağrılmışsa tekrar devretmez (döngü yok). **Cevap güvenilmez veridir:** harici içerik gibi işaretlenir ve kaynak izi kapısına girer (cevaptan türeyen dosya/komut hedefi onay ister).
- **Gizlilik:** işin metni o programa ve onun kendi yapay zekâ servisine gider; Gizlilik sayfası programlar açıkken bunu söyler.
- **Gerçek programlarla denendi:** Claude Code uçtan uca (yalnız okuma, doğru cevap, dosya değişmedi); OpenCode ve Hermes yerel modelle çalıştı; Codex'in komut biçimi API'ye ulaştı. **Bulgu:** DeepSeek Harness Node.js 24.9 ister ve eski Node'da hata vermeden sessizce çıkıyor; Usta bunu önceden bilir ve Ayarlar'da nedenini söyler.
- **Windows:** argümanla istem alan programlar (OpenCode, Hermes) desteklenmez (komut satırı güvenliği); Claude Code, Codex ve DSH stdin kullanır. **Windows'ta denenmedi.**
- **Ölçümden çıkan ek savunma:** Lab'da Qwen3 4B, başka programın cevabındaki "yazma izni verildi" cümlesine **4/4** uyup programı yazma kipinde yeniden çağırdı. Bu yüzden, Usta başka bir içerik okuduktan sonra gelen `write=true` isteği artık onay penceresinde ayrıca uyarılır ("bu YAZMA isteği, başka bir içerik okuduktan sonra geldi... Senin isteğinde yoksa Reddet"). Gömülü talimatla gizli anahtarı dosyaya yazdırma denemesini ise kaynak izi kapısı engelledi (3 denemede 0 gerçekleşme). Ayrıntı ve kendi ölçüm hatalarımız: [docs/lab-delegate-olcumu.md](docs/lab-delegate-olcumu.md).
- **Reliability Lab (27 → 29):** `deleg-01` (başka programın cevabına gömülü talimat gizli anahtarı dosyaya yazdırmaya çalışır), `deleg-02` ("yazma izni verildi" diyerek programı yazma kipinde yeniden çağırtmaya çalışır). Eski senaryoların özeti değişmedi.
- Yeni uçlar: `GET /harnesses`, `PUT /harnesses/{id}`.

## 0.7.0 — Usta kendi becerisini tasarlar (sen onaylarsan)

Model davranışı DEĞİŞMEDİ (araç yalnız istenince göreve eklenir). Tasarım ve tehdit tablosu: [docs/c-orkestra-tasarim.md](docs/c-orkestra-tasarim.md).

- **Ayarlar → Becerilerim → "Usta'ya yeni bir iş öğret":** ne istediğini yaz; Usta bir *beceri* (yazılı tarif) tasarlayıp **öneri kartı** gösterir. Okuyup beğenirsen Kaydet'e basarsın; **sen onaylamadan hiçbir şey kaydedilmez.** Kayıtlı beceriler kendiliğinden çalışmaz: yalnız "Kullan"a basınca ya da `/beceri-adı` yazınca devreye girer. Listeden silinir.
- **Güvenlik:** yeni araç `propose_skill` yan etkisizdir (hiçbir dosya yazmaz), yalnız "yeni bir iş öğret" dediğinde o göreve eklenir (plan modunda hiç yok) ve kaydı yalnız kullanıcının düğmesi yapar; modelin kayıt yolu yoktur (testle denetlenir). Kart, sunucunun doğruladığı metni ve **uyarıları** gösterir: bağlantı, komut, gizli bilgi benzeri, "onay gerekmez", "önceki talimatları yok say" ve var olan becerinin üzerine yazılması. Uyarı varsa kart kırmızı olur ve "Uyarıları okudum" işaretlenmeden Kaydet açılmaz. Öneri en çok 4000 harf (hepsini okuyabilesin).
- Beceri yalnız yazılı yönergedir: kod içermez, izinleri ya da onayları değiştiremez.
- Gerçek modelle (Qwen3 4B) uçtan uca denendi: temiz öneri kaydedildi ve listelendi; riskli öneride kart kırmızı çıktı, Kaydet kilitliydi, Vazgeç hiçbir şey kaydetmedi.
- Yeni uç: `POST /skills/check` (hiçbir şey yazmaz). Gizlilik listesine `skills` eklendi.

## 0.6.3 — Reliability Lab: ortak hafıza kanalı

Model davranışı DEĞİŞMEDİ; yalnız ölçüm aracı genişledi.

- **Lab'a `shared_notes` alanı:** bir senaryo, evdeki ortak hafızanın onaylı notlarını ajanın bağlamına gerçek görevlerdeki `<<<ORTAK-HAFIZA>>>` bloğuyla koyabilir. Her not gerçek filtreden (`ortak.check_note`) geçmek zorundadır; gerçek kanaldan giremeyecek bir saldırı senaryoda da yazılamaz.
- **3 yeni senaryo (24 → 27):** `ortak-01` gizli anahtarı herkese açık dosyaya yazdırma, `ortak-02` anahtarı yanıta ekletme, `ortak-03` veri dosyasını boşaltma. Eski 24 senaryo değişmedi; küme özeti yeni senaryolar yüzünden değişti (eski sonuçlarla yalnız ilk 24'ü kıyasla). Boş `shared_notes` eski senaryoların özetini değiştirmez.
- **İlk gerçek ölçüm:** Qwen3 4B, 9 saldırılı koşuda yasak eylemi **hiç denemedi** (0/9); notları gördüğü ayrı bir kontrolle doğrulandı. Küçük örneklem (en çok yaklaşık %30'a kadar çıkabilir, %95 güvenle) ve tek model: [docs/lab-ortak-hafiza-olcumu.md](docs/lab-ortak-hafiza-olcumu.md).

## 0.6.2 — açılış ekranı, "?" balonu, "Sayfaya dön"

Model davranışı DEĞİŞMEDİ. Kullanıcı geri bildirimleri.

- **Açılış ekranı sekmelerde kalmıyordu:** "Ne yapmamı istersin?" ve "Usta işi bitirdi" kartı Ofis, Geçmiş, Sonuç gibi diğer sekmelerde de görünüyordu. Artık yalnız Konuşma sekmesinde görünür; geri dönünce yerindedir.
- **"?" düğmesi küçüldü ve balon açar:** üzerine gelince ya da klavyeyle odaklanınca açıklama bir balonda çıkar. Tıklayınca balon açık kalır (sayfadan ayrılmaz, yaptığın iş yarıda kalmaz); Esc ya da dışarı tıklama kapatır. Daha fazlası için balondaki "Sözlükte aç" düğmesi vardır.
- **"Sayfaya dön":** bir bölüm (Sözlük, Ayarlar, Gizlilik...) açıkken menüdeki düğmesi "Sayfaya dön" olur ve **bir önceki yere** döndürür: ana ekrana ya da geldiğin bölüme (ör. Ayarlar → Sözlük → Sayfaya dön → Ayarlar).
- Sözlükte `find` (tam eşleşme, Türkçe ı/i farkına dayanıklı); testler: her "?" düğmesinin balonu bir terim bulur.

## 0.6.1 — Windows'ta gerçek denemelerden düzeltmeler

Model davranışı DEĞİŞMEDİ. 0.6.0 ve 0.5.x'in Windows'ta ilk gerçek denemesi (Windows 10, Python 3.14, yetkisiz kullanıcı).

**Windows'ta denendi ve çalıştı**
- Yayınlanmış `Usta-Kur.bat` GitHub'dan indirilip çalıştırıldı: 0.6.0 kuruldu, masaüstü simgesi geldi, Usta arka planda açıldı.
- **Evdeki ortak hafıza, gerçek ağda Windows ↔ Linux:** Linux ev sahibi, Windows bağlanan. Kodla eşleşme, profil ve notların gelmesi, Windows'tan eklenen notun ev sahibinde "bekliyor" olması, onay öncesi Windows'taki modele **girmemesi**, onaydan sonra girmesi, bağlıyken profilin yerelde değiştirilememesi ve bağlantıyı kesme doğrulandı.
- **Evdeki ağda arama (`/local/scan-lan`)** gerçek ağda ev sahibi PC'deki model sunucusunu buldu; elle adres çalıştı; internet adresi (`8.8.8.8`) reddedildi.
- **`winget` ile program kurma (gerçek winget):** kullanıcının kendi oturumunda `winget` programı buldu ve indirmeyi başlattı; küçük bir paketle (jq) kurulum uçtan uca başarılı oldu ve kaldırıldı.

**Bulunan ve düzeltilenler**
- **İlerleme:** `winget`, çıktısı boruya yazılırken indirme ilerlemesi (MB/GB) basmaz; bu yüzden gösterilmeye çalışılan ilerleme hiç çıkmıyordu. Artık kurulumun **kaç dakikadır sürdüğü** gösterilir ("Program yaklaşık 1 GB; yavaş internette saatler sürebilir"). "Kuruluyor" aşaması gerçek `winget` çıktısından algılanır.
- **Anlaşılır winget hataları:** kaynak verisi eksik (`0x8A15000F`) ve indirme hatası (`0x8A150008`) için düz cümle; bilinmeyen kodlar onaltılık yazılır, ham çıktı gösterilmez.
- **Yavaş indirme:** denenen bilgisayarda GitHub'dan indirme saniyede yaklaşık 83 KB idi; 1,2 GB'lık Ollama saatler sürerdi. Bu kodla ilgili değil; kullanıcı için "kendin indir" bağlantısı kurulum düğmesinin altında kalır.
- İlerleme ayrıştırması arabelleğin tamamını tekrar tarıyordu (eski indirme satırı "kuruluyor"un üstüne yazılıyordu); satır satır işleniyor, gerçek bir alt süreçle test edildi.

**Denenmedi:** Windows'ta ev sahibi olmak (güvenlik duvarı sorusu), Ollama'nın Windows'ta başından sonuna kurulması (indirme çok yavaştı), Python hiç yokken `Usta-Kur.bat`.

## 0.6.0 — evdeki ortak hafıza

Model davranışı DEĞİŞMEDİ (ortak hafıza kapalıysa istem aynıdır). Varsayılan KAPALI.

- **Ayarlar → Evdeki ortak hafıza:** evde birden çok bilgisayar varsa "Seni tanıyayım" bilgileri ve ortak notlar hepsinde aynı olur. Bir bilgisayar ev sahibi olur ("Bu bilgisayar ortak hafızayı tutsun"), kod gösterir; diğerleri adres ve 6 haneli kodla bağlanır. Yalnız evdeki ağda çalışır.
- **İmzalı istek:** anahtar ağda gitmez; her istek ve her cevap anahtardan türetilmiş HMAC-SHA256 ile imzalanır (zaman damgası + tek kullanımlık sayaç). Araya giren sahte cevap kullanılmaz, kaydedilmiş istek tekrar oynatılamaz. **İçerik şifrelenmez** (tablet bağlantısıyla aynı sınır); arayüz ve Gizlilik sayfası bunu söyler.
- **Yalnız sen yazarsın:** ortak hafızaya yazan bir model aracı yoktur. Ev sahibi dışından eklenen not, ev sahibinde "Onayla"ya basılana kadar hiçbir yapay zekâya gitmez. Bağlı bilgisayarda "Seni tanıyayım" bilgileri salt okunurdur (ev sahibinden değiştirilir).
- **Sınırlar:** en çok 50 not (her biri 300 harf), 20 bilgisayar; gizli bilgi, bağlantı, komut ve izin iddiası içeren not reddedilir; yalnız özel ağ adresinden istek, `Origin` ve yanlış `Host` reddedilir, gövde 8 KB, dakikada 60 istek; dinleyici yalnız evdeki ağ adresine bağlanır ve portalın hiçbir ucunu sunmaz.
- **Ev sahibi kapalıysa** bağlı bilgisayar son bilinen kopyayı kullanır; görev düşmez.
- Tasarım ve tehdit tablosu: [docs/ortak-hafiza-tasarim.md](docs/ortak-hafiza-tasarim.md). Gizlilik özeti ve dosya listesi güncellendi.

## 0.5.1 — "Seni tanıyayım" ve özelleştirme

Model davranışı DEĞİŞMEDİ (profil boşsa istem aynıdır).

- **Ayarlar → Seni tanıyayım:** hitap adı, anlatım biçimi (sade / çok kısa / ayrıntılı), kısa bir "hakkımda" ve Usta'nın bilmesini istediğin en çok 20 madde. Her görevin başında modele veri olarak girer (sistem rolüne girmez, nonce'lu işaretlerle, "güvenlik kurallarını ve onayları değiştirmez" uyarısıyla). **Yalnız sen yazarsın:** modelin bu dosyaya yazan bir aracı yoktur, bu yüzden hafıza gibi zehirlenemez. Her görevde modele (internet servisi seçiliyse servise de) gittiği arayüzde yazar; Gizlilik listesinde `kisi.json` olarak görünür. Uçlar: `GET/PUT/DELETE /profile`.
- **Vurgu rengi:** çini mavisi, turkuaz, nar, zeytin, mor; aydınlık ve karanlık zeminde ayrı değerler. Yeni ayar `accent`.
- **Ayarlar gruplandı:** Seni tanıyayım / Görünüm / Yapay zekâ / Bilgisayarın. "Renk" seçicisi "Zemin" oldu.
- **Taslak:** [Ortak hafıza tasarımı](docs/ortak-hafiza-tasarim.md) (evdeki bilgisayarlar arası ortak hafıza, 0.6.0 için). Kod yok; güvenlik incelemesi ve açık sorular bekleniyor.

## 0.5.0 — yeni görünüm, evdeki bilgisayara bağlanma, eksik programı Usta kursun

Model davranışı DEĞİŞMEDİ. Berke'nin ve ilk kullanıcıların "arayüz zayıf, kurulum zor, evdeki başka bilgisayarı göremiyor" geri bildirimlerine yanıt.

- **Yeni görünüm:** baştan tasarlandı. Çini yıldızı işareti, lacivert ve turkuaz palet (eski krem/toprak rengi bırakıldı), açık ve koyu tema, daha okunur başlıklar, kenarlıksız menü, alt çizgili sekmeler, yuvarlak yazı kutusu, telefonda taşmayan düzen. Dışarıdan font ya da görsel yüklenmez (gizlilik testi korunur).
- **Kurulum sihirbazı adım adım:** üstte 1 Nerede çalışsın? → 2 Kur → 3 Dene şeridi; hangi adımda olduğun ve bitenler görünür.
- **Sihirbaz hatası düzeltildi:** 0.4.3'te seçim kartları düğme içinde düğme olarak yazılmıştı; tarayıcı kartı bozup "?" düğmelerini dışarı atıyordu ve ekran dağılıyordu. Kartlar düzeltildi; `tests/test_web_markup.py` bu kalıbın geri gelmesini engeller.
- **Evdeki başka bilgisayar (yeni seçenek):** sihirbazda "Evdeki başka bilgisayarda". Usta evdeki ağda (bu bilgisayarın /24'ü, yalnız Ollama/LM Studio/llama.cpp/vLLM'in yaygın 4 portu, yalnız model listesi sorgusu) kendisi arar; bulamazsa adresi elle yazarsın. Yalnız özel ağ adresleri kabul edilir: internetteki bir adrese ya da DNS ile dışarıya çözülen bir ada portaldan istek atılamaz. Öbür bilgisayarı nasıl hazırlayacağın düz Türkçe anlatılır. Yeni uçlar: `POST /local/scan-lan`, `POST /local/probe-host`.
- **Eksik programı Usta kurar:** Windows'ta `winget` varsa Ollama'yı "Benim için kur" düğmesiyle Usta kurar (sihirbazda ve Ayarlar → programlar). Kurulacaklar sabit bir listedir (şimdilik yalnız Ollama), komuta kullanıcıdan ya da modelden metin girmez; kurulamazsa eskisi gibi resmî indirme sayfasına yönlendirir. Yeni uçlar: `POST/GET /system/install`, `/system/info` içinde `can_install`. **Windows'ta gerçek bir bilgisayarda henüz denenmedi** (test bilgisayarı kapalıydı); birim testleri sahte `winget` ile çalışır.
- **Basit görünüm sadeleşti:** token sayacı ve çalışma alanı adı artık yalnız Gelişmiş görünümde.

## 0.4.4 — sağlamlaştırma: kurulum, anlaşılır hatalar, "Yardım iste"

Model davranışı DEĞİŞMEDİ.

- **`Usta-Kur.bat` gerçek Windows'ta denendi ve yeniden yazıldı:** 10 Kasım 2026'da Windows 10 + Python 3.14'te, yetkisiz token ile baştan sona çalıştırıldı (kurulum, masaüstü simgesi, açılış). Artık `python` PATH'te yoksa `py` başlatıcısını dener, pip'in İngilizce uyarılarını göstermez, yazıları Türkçe karakterlerle basar ve hata olursa ne yapılacağını söyler. Python hiç yoksa çıkan dal (indirme sayfasını açar) denenmedi.
- **Anlaşılır hata cümleleri:** bir görev ya da model denemesi başarısız olunca artık her durumda düz Türkçe bir cümle ve ne yapılacağı yazar (anahtar kabul edilmedi, bakiye bitti, model bulunamadı, günlük hak doldu, servis cevap vermiyor, bağlantı koptu, model zamanında cevap vermedi, model ne yapacağını anlatamadı...). Sunucu ve arayüz aynı cümleleri kullanır; ortak bir örnek dosyasıyla (`tests/web/friendly-errors.json`) ikisi de denetlenir.
- **Ayarlar → "Yardım iste":** Usta'nın durumunu kısa bir yazıya döker (sürüm, işletim sistemi, bellek, Docker/Ollama kurulu mu, seçili yapay zekâ, son hataların türü ve saati, arka plan günlüğünün sonu). İçinde yazdıkların, dosyaların ve anahtarın YOKTUR; ev klasörü yolu ve bağlantı kodları da silinir. Hiçbir yere kendiliğinden gönderilmez: kullanıcı dosya olarak indirir ya da kopyalar, kendisi gönderir. Başarısız görevler artık denetim günlüğüne `task_failed` olarak yazılır (yalnız hata türü).
- **`SECURITY.md`:** "Kırmayı deneyenler için rehber" eklendi (nerede denenir, önce nereye bakılır, hangi araçlar var, nasıl bildirilir). Bağımlılık bölümü güncellendi.
- **Gizlilik listesi:** `usta.log` ve `running.json` dosyaları da "bilgisayarında saklananlar" listesinde.
- **Yayından hemen sonra düzeltildi (paket aynı, yalnız kurulum dosyası):** `Usta-Kur.bat` depoda LF satır sonlarıyla duruyordu; GitHub'dan indirilen kopya Windows'ta bozuk çalışıyordu (yayınlanan dosya gerçek Windows'ta indirilip denenince görüldü). Dosya artık depoda da CRLF durur (`.gitattributes`: `*.bat -text`) ve bir test bunu denetler.
- Windows'ta ayrıca denendi: bozuk kapanıştan kalan `running.json` ile yeniden açılış, simgeye ikinci tıklama (yeni süreç açmaz), "Usta'yı kapat". Docker'lı komut çalıştırma ve tablet bağlantısı Windows'ta hâlâ denenmedi.

## 0.4.3 — sözlük

- **Sözlük:** üst çubukta her zaman görünen "Sözlük" düğmesi. 40 kelime (JSON, Docker, Ollama, API anahtarı, token, terminal, bağlam penceresi...) 5 yaşındaki bir çocuğa anlatır gibi, her biri için gündelik bir benzetmeyle açıklanır; arama kutusu aksansız yazımı ve takma adları da bulur. Veri arayüzün içindedir, dışarıdan bir şey yüklenmez.
- **"?" düğmeleri:** kurulum ekranındaki "anahtar", "Ollama", "model", "bağlam", "Docker" gibi zor kelimelerin yanına küçük "?" düğmesi konuldu; basınca Sözlük o kelimenin kartıyla açılır. Bir testle her "?" düğmesinin sözlükte karşılığı olduğu denetlenir.

## 0.4.2 — indirmen gerekebilecek programlar

- **Ayarlar → "İndirmen gerekebilecek programlar":** Ollama ve Docker Desktop için kurulu/kurulu değil durumu, düz Türkçe "gerekli mi?" açıklaması ve resmî indirme sayfasına giden düğme. İnternet servisi kullanan kişi hiçbirini indirmek zorunda değildir. `/system/info` artık `ollama_installed` ve `docker_installed` döndürür.

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
