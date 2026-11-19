# Usta

[English](README.en.md) · Türkçe

Usta, bilgisayarında senin yerine iş yapan açık kaynak bir yapay zekâ yardımcısı. Ne istediğini yazarsın ("bana
pastanemin menüsünü gösteren bir sayfa yap"), Usta bir çalışma klasöründe dosyaları okur, yazar, komut çalıştırır ve
sonucu tarayıcıda açılan küçük bir panelde gösterir. Yaptığı her değişikliği iki tıklamayla geri alabilirsin.

Türkiye'de yazıldı, Apache-2.0 lisanslı. İki tür kullanıcıyı düşünüyoruz:

- Hiç kod yazmamış biri. Kur, aç, Türkçe yaz.
- Küçük, yerel bir modelle (4 GB ekran kartı yeter) iş görmek isteyen geliştirici.

Model sana kalmış: kendi bilgisayarındaki bir model (Ollama, llama.cpp) ya da bir internet servisi (DeepSeek,
OpenRouter, OpenAI, Gemini, Claude). OpenAI-uyumlu her uç nokta çalışır.

> Erken sürüm (0.8.x). Komutlar ve API değişebilir.

## Kurulum

Kod bilmiyorsan, Windows'taysan ya da tabletten kullanacaksan şuradan başla: [docs/baslangic.md](docs/baslangic.md).

Diğerleri için:

```bash
pip install usta          # ya da: uv tool install usta
cd benim-projem
usta                      # terminal açılır, panel tarayıcıda açılır
```

İlk açılışta bir model seçersin. Usta, modelin araç çağırmayı nasıl yaptığını kısa bir denemeyle öğrenir ve ona uygun
yolu kullanır.

Usta'yı hangi klasörde açtıysan çalışma alanı orasıdır. Dosyalar oraya yazılır, dışına yazılamaz.

## Neden bir tane daha?

Büyük modeller zaten iyi iş çıkarıyor. Küçük modeller ise yarı yolda bırakıyor: "dosyaya yazdım" deyip yazmıyorlar,
izin istiyorlar, bilgi uyduruyorlar. Usta'nın asıl işi bu açığı kapatmak. Bir değişikliği varsayılan yapmadan önce
ölçüyoruz, ölçmediğimiz şeyi iddia etmiyoruz.

Şu ana kadar ölçtüklerimiz:

- **Söz–eylem denetimi** (varsayılan açık). Model istenen dosyayı yazmadan bitirmek isterse kısa bir hatırlatma
  alıyor. 9B bir modelde görev başarısı 13/25'ten 19/25'e çıktı, saldırı başarısı değişmedi.
  [docs/olcumler/soz-eylem.md](docs/olcumler/soz-eylem.md)
- **Kodsuz kullanıcının site isteği** (deneysel, `USTA_SITE_STEPS=1`). İskeleti, kullanıcının verdiği bilgileri ve
  sayacı Usta koyuyor, model yalnız kısa bir metin yazıyor. 3 küçük modelle 45 denemenin 45'i doğru, 12–21 saniye.
  Aynı istekler tek seferde yazdırıldığında 45'te 10 tuttu. [docs/olcumler/site-istekleri.md](docs/olcumler/site-istekleri.md)
- Küçük modele "telefon, saat yazma" demek ona tam olarak telefon ve saat uyduruyor (5 denemede 5). Talimatlarımız bu
  yüzden olumlu yazılıyor. Aynı belgede.

Çalışmayanları da yazıyoruz. Düşünmeyi kısmak küçük modelde başarıyı düşürdü
([docs/olcumler/dusunme.md](docs/olcumler/dusunme.md)). Doğrulama kapısı ve devre kesici, zayıf modeli tek başına
kurtarmadı ([docs/arsiv/0.2.0-olcumleri.md](docs/arsiv/0.2.0-olcumleri.md)).

## Güvenlik

Kodu okuyamayan biri, yapay zekânın arka planda ne yaptığını denetleyemez. O yüzden kurallar modelin iyi niyetine
bırakılmıyor:

- Komutlar Docker kutusunda, ağı kapalı çalışır. Ağ yalnız senin izin verdiğin adreslere açılır.
- Yazma yalnız çalışma alanında. Her görevin değişikliği iki tıklamayla geri alınır.
- Okunan bir web sayfası ya da dosya Usta'ya "şu dosyaya yaz" dese, Usta önce sana sorar (kaynak izi kapısı).
- `.env`, anahtar ve parola dosyaları, sen istemeden okunmaz.
- Kendiliğinden çalışabilen dosyalar (`.vscode/`, git kancaları, CI) yazılmadan önce sorulur.
- Ek araçlar (MCP) ayrı bir kutuda çalışır. Panel yalnız bu bilgisayardan açılır.

Ayrıntılar, bulunup kapatılan açıklar ve açık bildirme yolu: [SECURITY.md](SECURITY.md).

## Neler var

- **Panel:** canlı akış, renkli değişiklik görünümü, geri alma, dosya gezgini, site önizlemesi, geçmiş görevler.
  Terminalde başlayan görev panelde de görünür.
- **Modlar:** `manuel` (her riskli adımda sorar), `oto` (sormadan yapar, yasaklar geçerli), `plan` (önce okur ve plan
  yazar; onaylarsan aşama aşama uygular).
- **Seni tanıyayım:** sana nasıl hitap edeceğini ve nasıl anlatacağını bir kez yazarsın.
- **Evdeki ortak hafıza:** evdeki birkaç bilgisayar aynı notları paylaşır. Eşleşme 6 haneli kodla yapılır, bağlantı
  şifrelidir, dışarıdan gelen not onaylanmadan kullanılmaz.
- **Beceriler:** sık yaptığın bir işi Usta'ya bir kez öğretirsin. Usta tarifi önerir, sen kaydedersin.
- **Başka yapay zekâ programları:** Claude Code, Codex, OpenCode, DeepSeek Harness ya da Hermes kuruluysa Usta işi onlara
  da verebilir. Her seferinde sorar, varsayılan olarak yalnız okuma izniyle verir.
- **Tablet ve telefon:** `usta --lan` ile evdeki ağdan PIN'le açılır.

Terminalde en çok kullanılan komutlar:

| Komut | |
|---|---|
| `/mod manuel\|oto\|plan` | çalışma modu |
| `/diff`, `/geri` | son görevin değişiklikleri, geri alma |
| `/model` | modeli değiştir |
| `/hafıza`, `/geçmiş` | proje notları, önceki görevler |
| `/token` | harcanan token ve bağlam doluluğu |

Tek bir görev için: `usta run "not.txt dosyasını özetle" -w ./klasor`. API sunucusu için: `usta serve`.
Denetim kaydı için: `usta audit show [kayıt]` son işlemleri gösterir (kayıt verilmezse en son değişeni), `usta audit verify` kaydın sonradan değiştirilmediğini denetler.

## Ölçüm araçları

- `usta lab`: aynı görevi temiz ve saldırılı haliyle (zehirli dosya, sahte talimat, sızdırma denemesi) çalıştırır.
  Modelin söylediğine değil, gerçekten yaptığı araç çağrılarına bakar. [docs/lab.md](docs/lab.md)
- `usta bench`: küçük yazılım görevlerini, ajanın göremediği testlerle doğrular.
- `usta probe`: modelin araç çağırma yeteneğini ölçer ve saklar.

## Geliştirme

```bash
git clone https://github.com/SoundByGAIA/usta.git && cd usta
uv venv && uv pip install -e '.[dev]'
make ci        # ruff + pytest
```

Kutu testleri için Docker ve `python:3.12-slim` imajı gerekir. Yoksa o testler atlanır. Katkı için:
[CONTRIBUTING.md](CONTRIBUTING.md). Mimari ve tehdit modeli: [docs/design.md](docs/design.md). Bütün ayarlar ve
deneysel seçenekler: [docs/ayarlar.md](docs/ayarlar.md).

## Lisans ve emek verenler

Apache-2.0, bkz. [LICENSE](LICENSE).

Ordis: Uğur Can Leba (Ordis mimarı, kurucu), Claude (Anthropic; Ordis mimarı, yapay zekâ ortak geliştirici), Berke
Dündar (güvenlik ve geliştirme, CTO), Ceren Yıldız (başöğretmen ve yerelleştirme). Adlar [NOTICE](NOTICE) dosyasında;
Apache-2.0 4(d) gereği türev çalışmalarda korunmalı.
