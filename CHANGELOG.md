# Değişiklik günlüğü

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
