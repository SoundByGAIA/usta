# Kodsuz kullanıcı testi: Windows 10, ilk kurulum (2026-11-09 akşam)

Test eden: Ceren (hiç kod bilmiyor, Windows 10, Python 3.14 kurulu, Docker/Ollama yok). Gözlemci: Can (yanında) ve Claude
(yalnız okuma: Usta denetim günlüğü, süreçler; hiçbir şeye dokunulmaz). Sürüm: usta 0.3.0 (PyPI).
Kural: gözlenen her şey olduğu gibi yazılır, yorum ve çözüm altta ayrı durur. Düzeltme testten SONRA yapılır.

## Zaman çizelgesi (gözlem)

| Saat | Ne yaptı / ne gördü | Takıldı mı? | Kaynak (Can / günlük) |
|---|---|---|---|
| 21:50 | Başlangıç: usta paketi kurulu değil, ~/.usta yok, portal kapalı | - | günlük |
| 21:55 | cmd açtı, `python -m pip install usta` yazdı (süreç 21:56'da göründü) | hayır | günlük |
| 21:58 | pip bitti (yaklaşık 2 dk), `usta 0.3.0` kurulu | hayır | günlük |
| 21:58:25 | `python -m usta` yazdı; 8 sn içinde süreç yok, portal açılmadı, `~/.usta` boş | **evet: açılmadı** | günlük, sonra pty ile yeniden üretildi |
| 22:00-22:10 | Birkaç kez `python -m usta` denedi; her seferinde süreç 24 sn içinde bitti. Fotoğraf: `OSError [WinError 1314] Gereken ayrıcalık istemci tarafından sağlanmıyor ... os.symlink` (projects.register); bir önceki denemede `usta` yazınca "'usta' is not recognized" | **evet: açılmadı** | fotoğraf (Can) |
| 22:16 | Claude 0.3.1 düzeltmesini yerel wheel ile Ceren'in PC'sine yükledi (yayın izni verilmedi) | - | günlük |
| 22:20 | 0.3.1 ile `python -m usta` yazdı: süreç ayakta kaldı, portal 8765'te açıldı, `~/.usta` içinde login/workspaces/token oluştu (ilk kez çökmedi) | hayır | günlük |
| 22:30:53 | `apis.json` oluştu (sihirbazda İnternet servisi → OpenRouter, anahtar girildi); Ceren portal açıldıktan sonra yaklaşık 10 dk anahtarı almakla uğraştı | ? | günlük |
| 22:37:49 | `apis.json` yeniden yazıldı (anahtar ikinci kez girildi/güncellendi, ilki olmamış olabilir) | muhtemelen | günlük |
| 22:39:06 | Model `openrouter/auto-beta` seçildi, yetenek ölçümü bitti (9 küçük istek) | ? | günlük (profiles.json) |
| 22:39:41 | 35 sn sonra ikinci kez model değiştirdi: `openrouter/auto` (nihai seçim). Ekran 30+ sn boyunca sessiz kalmış olabilir | ? | günlük |

## Bulgular

| # | Bulgu | Ağırlık (engelledi / yavaşlattı / kozmetik) | Olası düzeltme |
|---|---|---|---|
| 1 | **Usta açılmadan çıkıyor.** cmd `C:\Users\Ceren`'de açılır; Usta onu çalışma alanı sayar ama `~/.usta` içinde olduğundan `check_root` reddeder: "çalışma alanı olamaz ... Bir proje klasörüne girip öyle başlat." Kodsuz kullanıcı "proje klasörü"nü bilmez; kılavuz da söylemiyor. Önce "Model seçilmedi: sihirbazı tamamla" yazıp hemen ardından hata basıyor (çelişkili). | **engelledi** | **Can'ın beklentisi:** kullanıcı nerede başlatırsa başlatsın Usta açılmalı; proje klasörü içinden başlatırsa o oturum gelir, ana klasörden (C:\Users\Ceren) başlatırsa da açılmalı. Çalışma klasörü verilmediyse ve cwd uygun değilse otomatik `~/Usta` oluştur ve kullan, bunu açıkça söyle. Kılavuza `mkdir Usta` yedek adımı ekle. |
| 2 | **Windows'ta yönetici olmayan kullanıcıda Usta hiç açılmıyor:** `projects.register` her çalışma alanı için `os.symlink` kuruyor, bu Windows'ta yönetici/Geliştirici Modu ister (WinError 1314). Yetkisiz kullanıcı hiçbir klasörden başlatamaz. | **engelledi** | Ayrıcalık yoksa dizin birleşimi (junction) yedeği. **0.3.1'de düzeltildi**, yetkisiz token ile gerçek Windows'ta sınandı. |
| 3 | Ceren önce `usta` yazdı: "'usta' is not recognized as an internal or external command" (İngilizce, Python Scripts klasörü PATH'te değil). Kılavuzdaki `python -m usta` yerine doğal içgüdü program adını yazmak. | yavaşlattı | Kılavuzun ve ekran metinlerinin her yerinde yalnız `python -m usta`; ya da Windows'ta ilk açılışta bu komutu açıkça gösteren bir kısayol (`usta.bat` / masaüstü simgesi). |
| 4 | **Test yöntemi dersi:** v0.3.0'ın Windows denemesi yönetici yetkili SSH'tan yapıldığı için symlink izni vardı ve 17/17 geçti; gerçek kullanıcı (yetkisiz) engellendi. | (yöntem) | Windows denemelerini yetkisiz token ile yap (`runas /trustlevel:0x20000`). |
| 5 | Python 3.13+ Windows'ta `mkdir(mode=0o700)` dizini yalnız oluşturanın sahibine açar. Usta bir kez yönetici olarak çalıştırılıp `~/.usta` yönetici sahibiyle oluşursa sonraki normal çalıştırma `PermissionError: ...\.usta\token` verir (Claude'un yönetici SSH denemeleri bunu tetikledi, Ceren'in ikinci denemesinde göründü). | yavaşlattı (nadir) | Hata yakalanıp "`.usta` klasörünü sil" diye açıklanmalı; kılavuz "yönetici olarak açma" desin. |
| 6 | **Model seçince 30+ sn ekran sessiz:** "Bunu kullan"a basınca Usta modeli tanımak için 9 istek atıyor (yetenek profili); sihirbazda bu sırada hiçbir ilerleme metni yok. Ceren 35 sn arayla iki model seçti. (Doğrulanacak: ikinci seçim bu yüzden mi?) | yavaşlattı | **0.3.2'de yapıldı.** "Modeli tanıyorum, yarım dakika sürebilir" yazısı, düğmeyi kilitle; ya da profili arka planda yap. |
| 7 | **OpenRouter'da yüzlerce model, öneri yok:** sihirbaz Gemini/DeepSeek için öneri veriyor, OpenRouter ve OpenAI'da `prefer` boş; kodsuz kullanıcı ilk sıradakini seçmiş olabilir (`openrouter/auto-beta`). | yavaşlattı | **0.3.2'de yapıldı, düzeltmeyle:** `openrouter/auto` ÜCRETLİ yönlendiricidir (Ceren onu seçmişti); önerilen `openrouter/free` (fiyatı 0/0, doğrulandı). Plan notu: OpenRouter için `openrouter/auto` öner; listeyi sade tut, "emin değilsen ilkini seç" yerine tek net öneri. |
| 8 | **API anahtarı almak en büyük engel:** Ceren'in anahtarı yoktu, nasıl alınacağını portal açıldıktan sonra yaklaşık 10 dk'da kendi öğrendi (Can'ın aktarımı). Sihirbaz yalnız "sitesinde hesap aç, API keys bölümünden al" diyor; adres yok, adım yok, ücretsiz mi ücretli mi belli değil. | **yavaşlattı (10 dk)** | **0.3.2'de yapıldı** (adım adım anlatım, tıklanabilir bağlantı, ücretsiz/ücretli ayrımı). Plan: Her servis için 3-4 adımlık, adresli kısa anlatım (tıklanabilir bağlantı); "ücretsiz kotası var mı" notu; anahtarı kopyalama ipucu. Gizlilik testi dış bağlantıyı değil dış kaynak yüklemeyi yasaklamalı. |

## Ceren'in kendi sözleri (olduğu gibi)

- (Can aktardı) "Bulamadı, API keyi yoktu, almayı öğrendi."
- (Can aktardı, sihirbaz hakkında) "Yapay zeka nerede çalışsın? Her iki seçeneğin artıları ve eksileri ve önerileri yazan bir karşılama ekranı olmalı. Yerelde çalışacaksa modeli nasıl, neye göre indirmesi gerektiğini bilmiyorum." → 0.3.2'de yapıldı (karşılama ekranı + bellek tespiti + model önerisi + tek tıkla indirme).

## Gözlemci notları (Claude)

- 22:01-22:03: izleme günlüğündeki dört "portal dinliyor" olayı Claude'un kendi pty denemeleriydi (Desktop/Documents/Downloads/Yeni klasör); Ceren'in değildi. Test PC'sinde gözlemciyi karıştırmamak için bundan sonra yalnız okuma.
- Masaüstü\\Yeni klasör (21:58, Ceren açtı) içinden Usta, gerçek terminalde sorunsuz açıldı (Claude'un yeniden üretimi); klasör adında boşluk ve `ö` sorun çıkarmadı.

## Sonuç (1. tur, 2026-11-09 gece)

Ceren kurulumdan sihirbazın sonuna ve model seçimine kadar kendi başına geldi, sonra uyudu (yaklaşık 2,5 saat sonra).
İlk görev (Usta'ya bir iş yazdırma) henüz denenmedi; 2. tur yarın gece.

- **Hiç takılmadan geçilen:** cmd açma, `python -m pip install usta` (2 dk), `python -m usta` komutunu yazma.
- **Engelleyen (düzeltildi, 0.3.1, yerel):** Bulgu 1 (ev klasöründen başlatma), Bulgu 2 (Windows'ta yetkisiz kullanıcıda symlink).
- **Yavaşlatan (açık):** Bulgu 3 (`usta` yazınca "tanınmıyor"), 6 (model seçince 30 sn sessizlik), 7 (OpenRouter'da öneri yok), 8 (API anahtarı almak ~10 dk).
- **Kapanış:** 22:43'te Can pencereyi kapattı (çökme değil).
- **Yarın için:** 0.3.2 (3, 5, 6, 7, 8 + servis eklemeleri) hazırlanıp Can onayıyla yayınlanır; Ceren PyPI'den kurar; ilk görev ve sihirbaz sonrası akış izlenir.

