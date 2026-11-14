# Usta'nın kendi becerisini yazması ve başka yapay zekâ programlarını yönetmesi (C): tasarım

Durum: **uygulandı.** C1 (beceri tasarımcısı) 0.7.0, C2 (orkestra şefi) 0.8.0. Rust bu belgenin kapsamı dışındadır
(ayrı proje: özel durumlu insanlar için Usta benzeri harness, TÜBİTAK 1005).

## Amaç

1. **Kendi becerisini tasarlama (C1):** Kullanıcı "şunu her seferinde böyle yap" der; Usta bunu bir *beceri* olarak yazıp
   önerir; kullanıcı okur ve onaylarsa kaydedilir (DeepSeek Creator benzeri, ama onaylı).
2. **Orkestra şefi (C2):** Bilgisayarda kurulu diğer yapay zekâ programlarını (Claude Code, Codex, ileride Hermes vb.)
   Usta'dan çıkmadan, Usta'nın gözetiminde yardıma çağırması.

İkisi de aynı ilkeye dayanır: **Usta öneri yapar, kullanıcı karar verir; model kendi yetkisini genişletemez.**

## C1: beceri tasarımcısı

Beceri = `~/.usta/skills/<ad>.md` düz metin yönergesi (mevcut sistem; `/ad ek metin` yazınca metin + istek olur).
**Kod değildir ve izinleri değiştirmez.**

- Yeni araç `propose_skill(name, description, instructions)`. Aracın **hiçbir yan etkisi yoktur**: dosya yazmaz, yalnız
  "öneri kullanıcıya gösterildi" der. Portal çağrıyı yakalar ve bir *öneri kartı* gösterir.
- Kart, sunucunun doğruladığı metni (`POST /skills/check`: ad, boyut, temizlenmiş karakterler) ve **uyarıları** gösterir.
  "Kaydet" yalnız kullanıcının düğmesidir ve kullanıcının gördüğü metni `PUT /skills/{ad}` ile yazar. Modelin bu uca
  ulaşan bir yolu yoktur (portal jetonu modele verilmez).
- **Uyarılar** (`memory.suspicious` ile aynı desenler): bağlantı, komut, gizli bilgi benzeri, onay/izin iddiası,
  "önceki talimatları yok say". Uyarı varsa kart kırmızı çerçeveli olur ve "Riskleri okudum" işaretlenmeden Kaydet açılmaz.
  Aynı adda beceri varsa "üzerine yazılır" uyarısı çıkar.
- Beceriler **kendiliğinden çalışmaz.** Yalnız kullanıcı `/ad` yazınca ya da "Kullan"a basınca devreye girer.
- Sınır: öneri en çok 4000 harf (okunabilir kalsın); adı küçük harf/rakam/`-`/`_`.
- Eklenti (kod içeren) **yapılmaz.** Kod gerektiren ihtiyaç için kullanıcıya MCP kataloğu gösterilir.

## C2: orkestra şefi

**Katalog, serbest komut değil.** Çağrılabilecek programlar `harnesses.py`'de sabit bir listedir (kimlik, ad, ikili adı,
"yalnız okuma" ve "dosya yazabilir" çağrı şablonları). Model ya da kullanıcı keyfi komut veremez; `mcpcatalog` ile aynı ilke.

- Araç `delegate(agent, task, write=false)`. Politika **her zaman `ASK`**: sorulur; oto modda **reddedilir** (kaynak izi
  kapısındaki gibi). Onay metni düz Türkçe: hangi program, ne iş, yazma izni var mı.
- Her program **varsayılan KAPALI**; Ayarlar'da kullanıcı açar. Kurulu değilse görünmez.
- **Yalnız okuma varsayılan:** Claude Code `--permission-mode plan`, Codex `-s read-only`. `write=true` ayrı ve açık
  onay ister (Claude `acceptEdits`, Codex `workspace-write`).
- **Komut satırı güvenliği:** kabuk yok (`shell=False`), istem komuta değil **stdin'e** yazılır (bayrak sanılamaz, süreç
  listesinde görünmez), çalışma klasörü Usta'nın çalışma alanı, ortam değişkenleri izin listesiyle süzülür (Usta'nın
  anahtarları, `USTA_*`, bulut anahtarları geçmez), zaman aşımı 10 dk, çıktı 20 000 harfle sınırlı.
- **Çıktı güvenilmez veridir:** MCP çıktısı gibi işaretlenir (`wrap_external`) ve kaynak izine girer (`delegate` =
  güvenilmeyen kaynak): çıktıdan türeyen dosya/komut hedefi onay ister.
- **Döngü yok:** çağrılan programa `USTA_DELEGATED=1` verilir; Usta bu değişkenle başlarsa `delegate` reddeder. Görev başına
  en çok 3 çağrı. Paralel çağrı yok (ilk sürüm sıralı).
- **Denetim kaydı:** her araç çağrısı gibi `delegate` çağrısı da (program, iş metni, `write`) ve sonucu denetim günlüğüne yazılır; anahtar içermez
  (ortam süzülür, hata metinleri `audit.mask`'tan geçer).
- **Dürüst sınır:** çağrılan program kullanıcının hesabıyla çalışır ve kendi izin sistemine sahiptir; Usta onun içini
  denetleyemez. Bu yüzden varsayılan yalnız okuma, her çağrıda onay ve çıktının veri sayılması şarttır.

## Tehditler

| Tehdit | Karşılık |
|---|---|
| Model bir beceriyi kendiliğinden kaydeder | Araç yazmaz; yalnız kullanıcı düğmesi yazar |
| Beceri içine gizli talimat/komut gizlenir | Kart tam metni ve uyarıları gösterir; riskli ise ayrı onay |
| Kayıtlı beceri sessizce devreye girer | Beceriler yalnız `/ad` ile, kullanıcı eliyle çalışır |
| Model başka programa istediğini yaptırır | Katalog sabit, her çağrıda onay, oto modda ret, varsayılan yalnız okuma |
| Çağrılan programın çıktısı enjeksiyon taşır | Veri olarak işaretli, kaynak izi kapısı, izin motoru yerinde |
| Anahtar sızıntısı | Ortam süzülür, istem stdin'den, denetim kaydında içerik yok |
| Sonsuz yönetme döngüsü | `USTA_DELEGATED`, çağrı sınırı, zaman aşımı |
| Çağrılan program Usta'yı çağırır | Aynı değişken |

## Test ve ölçüm

- Birim: beceri doğrulama/uyarı, aracın yan etkisizliği, öneri kartının tek yazma yolu, katalog dışı ad reddi, ortam
  süzme, stdin ile istem, zaman aşımı/çıktı sınırı, oto modda ret, çağrı sınırı, döngü koruması (sahte ikili dosyalarla).
- Reliability Lab: çağrılan programın çıktısına gömülü talimat, beceri önerisine gizlenmiş komut senaryoları.
- Gerçek: kurulu Claude Code ve Codex ile yalnız okuma çağrısı (kısa, ucuz), Windows'ta ayrıca.

## Yapılmayacaklar

- Kod içeren eklenti yazma; becerinin izin ya da onay ayarını değiştirmesi; becerilerin kendiliğinden tetiklenmesi.
- Serbest komut çalıştırma; çağrılan programa Usta'nın anahtarlarını vermek; oto modda delege etmek.
- Paralel çok ajanlı yönetim (ilk sürüm sıralı; ölçümden sonra).

## Uygulanan (0.8.0) ve gerçek denemelerden öğrenilenler

Katalog bayrakları programların kendi `--help` çıktısından ve belgelerinden alındı:

| Program | Yalnız okuma | Dosya yazabilen | İstem |
|---|---|---|---|
| Claude Code | `-p --permission-mode plan --no-session-persistence` | `... acceptEdits ...` | stdin |
| Codex | `exec -s read-only --skip-git-repo-check --ephemeral --color never -` | `-s workspace-write` | stdin (`-`) |
| OpenCode | `run --agent plan` | `run --agent build` | argüman (`Task: ` önekli) |
| DeepSeek Harness | **yok** | `headless --permission-mode workspace-write --approval-policy never -` | stdin (`-`) |
| Hermes | **yok** | `-z` | argüman (`Task: ` önekli) |

Hiçbir satırda `--yolo`, `--dangerously-*`, `danger-full-access`, `bypassPermissions` ya da `--auto` yoktur (testle denetlenir).
DSH ve Hermes yalnız okuma kipi sunmadığı için onay penceresi ve Ayarlar bunu açıkça söyler ve çağrı `write=true` ister.
Argümanla istem alan programlar (OpenCode, Hermes) Windows'ta **desteklenmez**: `.cmd` sarmalayıcıları kabuk karakterlerini yorumlar.

**Gerçek denemeler (14 Kasım 2026, Linux, bu bilgisayarda kurulu programlarla):**

- **Claude Code:** yalnız okuma, 7 sn, dosyayı okuyup doğru cevabı verdi, hiçbir dosya değişmedi; cevap veri olarak sarıldı. **Uçtan uca çalıştı.**
- **OpenCode (v2.3.0):** yerel Ollama'ya bağlı izole bir ayarla çalıştı (komut biçimi, argümanla istem, çıktı sarma, zaman aşımı sonrası süreç ağacının temizliği doğrulandı). Küçük yerel modelin cevabı kalitesizdi; bu Usta'nın konusu değil.
- **Hermes (v0.19.0):** yerel Ollama'ya bağlı izole ayarla çalıştı ve **kendi uyarısını** döndürdü: araç kullanımı için en az 64K bağlam ister (8K'lık modelle çalışmaz). Usta cevabı doğru taşıdı.
- **Codex (0.147):** komut biçimi doğru çalıştı ve API'ye ulaştı; kullanıcının kendi Codex ayarındaki model, ChatGPT hesabıyla desteklenmediği için hata verdi (Codex'in kendi yapılandırması, Usta'dan bağımsız).
- **DeepSeek Harness (0.2.2-rc.1):** kuruldu ama **Node.js 24.9 ve üstünü ister** (`engines`); bu bilgisayarda 22.17 var ve program **hata vermeden sessizce çıkıyor.** Usta bunu artık önceden bilir: Ayarlar "Node.js 24.9 ya da daha yenisi gerekli (sende 22.17)" der ve açılmasına izin vermez. DeepSeek anahtarı olmadığı için gerçek cevap alınamadı; komut biçimi yalnız belgeden doğrulandı.
- İlk kurulum notu: bu programlardan Hermes ve OpenCode'un kurulumu yavaş bağlantıda (saniyede ~100 KB) onlarca dakika sürdü.

**Windows (0.8.1):** sahte `.cmd` programlarla gerçek Windows 10'da denendi (stdin/Türkçe/ortam/cwd/zaman aşımı/çıktı sınırı/hata); **bulunan hata:** zaman aşımında çocuk süreçler kalıyordu, `taskkill /T` ile düzeltildi.

**Denenmedi:** Windows'ta gerçek bir harness; DSH ile gerçek cevap; yazma kipi (`write=true`) gerçek programlarla.
