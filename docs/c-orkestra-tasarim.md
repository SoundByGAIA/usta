# Usta'nın kendi becerisini yazması ve başka yapay zekâ programlarını yönetmesi (C): tasarım

Durum: **uygulanıyor.** C1 (beceri tasarımcısı) 0.7.0, C2 (orkestra şefi) 0.8.0. Rust bu belgenin kapsamı dışındadır
(ayrı proje).

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
- **Denetim kaydı:** program, mod, görev uzunluğu ve özeti (içerik değil), çıkış kodu, süre. Anahtar içermez.
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
