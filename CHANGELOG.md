# Değişiklik günlüğü

## Yayınlanmamış

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
