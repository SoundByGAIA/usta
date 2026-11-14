# Usta'yı başlat (adım adım, sade anlatım)

Usta, ne istediğini yazdığında bunu senin için yapan bir yapay zekâ yardımcısıdır (ör. "bir hesap makinesi sayfası yap").
Önce bilgisayarına bir kez kurarsın, sonra tarayıcıdan kullanırsın. Aşağıdaki adımları sırayla yap.

## Windows'ta kurulum

### En kolay yol (tek tık)

1. `kurulum/Usta-Kur.bat` dosyasını indir: bu sayfadaki bağlantıya sağ tıkla → "Bağlantıyı farklı kaydet" (adres: `https://raw.githubusercontent.com/SoundByGAIA/usta/main/kurulum/Usta-Kur.bat`).
2. İndirdiğin dosyaya **çift tıkla**. Windows "bilinmeyen yayıncı" derse "Yine de çalıştır"a bas.
3. Dosya Python'u kontrol eder (yoksa nasıl kuracağını söyler), Usta'yı kurar ve masaüstüne **"Usta"** simgesi koyar. Sonunda Usta kendiliğinden açılır. Siyah pencerede bir süre yazı çıkmayabilir; kapatma, çalışıyor.
4. Bundan sonra Usta'yı açmak için **masaüstündeki "Usta" simgesine çift tıkla**. Siyah pencere açılmaz; tarayıcın açılır. İşin bitince Usta'daki **Ayarlar → "Usta'yı kapat"** düğmesine bas.

### Elle kurulum (üstteki çalışmazsa)

**1. Python'u kur** (bir kerelik; bilgisayarında varsa atla)
- Tarayıcıda `python.org` adresine git, sarı "Download Python" düğmesine bas, inen dosyayı aç.
- Açılan pencerenin **en altındaki** "Add python.exe to PATH" kutusunu **işaretle**. Bunu unutma.
- "Install Now"a bas ve bitmesini bekle.

**2. Siyah pencereyi aç**
- Klavyede Windows tuşuna bas, `cmd` yaz, Enter'a bas.

**3. Usta'yı indir**
- Siyah pencereye şunu yaz ve Enter'a bas: `python -m pip install usta`
- Yazılar akar, biraz bekle. "WARNING ... is not on PATH" gibi sarı bir uyarı çıkarsa **yok say**.

**4. Masaüstü simgesi koy ve çalıştır**
- Şunu yaz ve Enter'a bas: `python -m usta --kisayol`
- Masaüstüne "Usta" simgesi gelir. Ona çift tıkla, tarayıcın açılır.
- (Simge istemezsen: `python -m usta` yaz; bu sefer siyah pencere açık kalmalı, kapatırsan Usta kapanır.)

## İlk açılışta: kurulum ekranı

(Hangi yoldan kurduysan, Usta ilk açıldığında bu ekranı gösterir.)

- Tarayıcıda "Yapay zekâ nerede çalışsın?" ekranı çıkar. Üstteki şerit hangi adımda olduğunu gösterir (1 Nerede çalışsın? → 2 Kur → 3 Dene). Üç seçeneğin artıları ve eksileri yazılıdır, altında da senin bilgisayarına göre bir öneri vardır.
  - **İnternet servisiyle** (çoğu kişi için önerilir): Daha güçlü ve hızlıdır. Bir servisten **anahtar** almalısın (uzun bir şifre gibi bir yazı). Ekran, her servis için adımları ve anahtar sayfasının bağlantısını gösterir; yaklaşık 5-10 dakika sürer. **Ücretsiz seçenekler:** Google Gemini ve OpenRouter (ücretsiz katmanlarında günlük istek sınırı düşüktür ve yazdıkların servis tarafından ürün geliştirmede kullanılabilir). DeepSeek, OpenAI, Claude (Anthropic) ve OpenCode ücretlidir.
  - **Bu bilgisayarda**: Ücretsizdir ve yazdıkların bilgisayarından çıkmaz. Ekran bilgisayarının belleğine bakıp sana bir model önerir ve adım adım yürütür: önce Ollama programını kurarsın (Windows'ta "Benim için kur" düğmesi varsa Usta kurar), sonra "İndir" düğmesiyle modeli indirirsin (2-5 GB, ilerleme çubuğu görünür). Küçük modeller basit işlerde iyidir, zor işlerde başarısız olabilir.
  - **Evdeki başka bilgisayarda**: Evde güçlü bir bilgisayarın varsa yapay zekâ onda çalışır. Usta evdeki ağı birkaç saniyede kendisi tarar; bulamazsa öbür bilgisayarın adresini (ör. `192.168.1.20`) kendin yazarsın. Öbür bilgisayarda Ollama'da **Settings → "Expose Ollama to the network"** kutusu (LM Studio'da **Developer → "Serve on Local Network"**) açık olmalı. Yalnız evdeki (özel ağ) adresler kabul edilir.
- Model seçince Usta modeli tanımak için yarım dakikaya kadar bekler ("Modeli tanıyorum" yazar), bu sırada başka bir şeye basma.
- Sonunda "Hazır!" yazar. Altındaki örneklerden birine bas ve dene.

## Usta seni tanısın

**Ayarlar → "Seni tanıyayım"** bölümünde sana ne diye hitap etmesini, nasıl anlatmasını ve bilmesini istediğin birkaç şeyi yazabilirsin (ör. "Sayfalarımda hep büyük yazı isterim"). Bunları yalnız sen yazarsın; Usta kendiliğinden eklemez. Yazdıkların her görevde yapay zekâya gönderilir (internet servisi seçtiysen o servise de), bu yüzden şifre ya da anahtar yazma. İstediğin zaman tek tek silebilir ya da "Hepsini sil"e basabilirsin. **Ayarlar → Görünüm**'den zemin rengini, vurgu rengini ve yazı boyutunu değiştirebilirsin.

## Usta'ya yeni bir iş öğret (beceriler)

Hep aynı şekilde yapmasını istediğin bir iş varsa (ör. "haftalık raporu şu düzende yaz"), Usta'ya öğretebilirsin.

1. **Ayarlar → Becerilerim → "Usta'ya yeni bir iş öğret"**'e bas, açılan kutuya işi yaz ve gönder.
2. Usta bir **öneri kartı** gösterir: becerinin adı ve tam metni. İyice oku.
3. Beğendiysen **Kaydet**'e bas. Beğenmediysen **Vazgeç**. Sen onaylamadan hiçbir şey kaydedilmez.
4. Kartta kırmızı bir uyarı varsa (bağlantı, komut, "onay gerekmez" gibi), "Uyarıları okudum"u işaretlemeden Kaydet açılmaz. Emin değilsen Vazgeç.
5. Kullanmak için **Ayarlar → Becerilerim → Kullan**'a bas ya da kutuya `/beceri-adı` yaz. Beceriler kendiliğinden çalışmaz.

## Evdeki bilgisayarlar aynı hafızayı kullansın

Evde birden çok bilgisayarda Usta kullanıyorsan, kendini her birinde yeniden tanıtmana gerek yok.

1. Hep açık duran (ya da en çok kullandığın) bilgisayarda **Ayarlar → Evdeki ortak hafıza → "Bu bilgisayar ortak hafızayı tutsun"** düğmesine bas. Sonra **"Yeni bilgisayar bağla: kod göster"**e bas: bir adres ve 6 haneli kod çıkar.
2. Öbür bilgisayarda aynı yere gir, adresi ve kodu yaz, **Bağlan**'a bas. Kod 5 dakika geçerlidir ve bir kez kullanılır.
3. Bundan sonra "Seni tanıyayım" bilgilerin ve ortak notlar her bilgisayarda aynıdır. Bilgilerini yalnız ev sahibi bilgisayardan değiştirirsin.
4. Öbür bilgisayardan eklediğin not, ev sahibi bilgisayarda **Onayla**'ya basana kadar yapay zekâya gitmez. Bunu güvenlik için yaptık.

Bu bağlantı yalnız evdeki ağda çalışır, imzalıdır ama **şifrelenmez**: yalnız güvendiğin ev Wi-Fi'ında kullan. Ortak hafızaya şifre ya da anahtar yazma. Ev sahibi bilgisayar kapalıysa diğerleri son bildiği kopyayı kullanır.

## Tabletten ya da telefondan kullanmak

Bilgisayar ve tablet **aynı Wi-Fi'a** bağlı olmalı.

1. Usta açıksa önce kapat (masaüstü simgesiyle açtıysan: **Ayarlar → "Usta'yı kapat"**; siyah pencerede açtıysan `/çık` yaz). Sonra siyah pencerede şunu yaz: `python -m usta --lan`
2. Windows "güvenlik duvarı" sorusu sorarsa **"Özel ağlar"** kutusunu işaretleyip **"Erişime izin ver"**e bas.
3. Siyah pencerede **adres** ve **giriş kodu** yazar. Tabletin tarayıcısına adresi yaz, kodu sorduğu kutuya gir.
4. Kodu kaybedersen bilgisayardaki Usta ekranında "Tablet" düğmesine bas, yeni kod verir.

Bu bağlantı şifrelenmez. Yalnız evindeki gibi güvendiğin bir Wi-Fi'da kullan.

## Bilmen gerekenler (dürüst notlar)

- **Docker yoksa komut çalıştırılamaz.** Usta, bilgisayarında bir komut çalıştırması gerektiğinde bunu güvenlik için Docker adlı programın içinde yapar. Docker kurulu değilse Usta dosya yazabilir ve okuyabilir ama komut çalıştıramaz (ör. yazdığı kodu deneyemez). Basit sayfa/metin işleri için gerekmez.
- **Windows'ta denendi, ama sınırlı.** Usta Linux'ta geliştirildi. 9 Kasım 2026'da gerçek bir Windows 10 bilgisayarda (Python 3.14) kurulum, açılış, ayarlar, dosya yazma ve Türkçe karakterler denendi ve buldukları düzeltildi. 10 Kasım'da masaüstü simgesi, arka planda çalışma ve tek tıkla kurulum dosyası (`Usta-Kur.bat`) da denendi. Docker'lı komut çalıştırma ve tablet bağlantısı Windows'ta denenmedi. Bir şey bozulursa **Ayarlar → "Yardım iste"** düğmesine bas ve çıkan yazıyı sana Usta'yı veren kişiye gönder (içinde yazdıkların, dosyaların ve anahtarın olmaz).
- **Verin nerede?** Usta'daki "Gizlilik" düğmesi, yazdıklarının nereye gittiğini ve bilgisayarında neleri sakladığını gösterir.

## Sorun olursa

| Gördüğün | Ne yap |
|---|---|
| `python bulunamadı` | Python'u yeniden kur ve "Add python.exe to PATH" kutusunu işaretle. |
| `usta bulunamadı` | Hep `python -m usta` yaz, `usta` yazma. |
| Tarayıcı açılmadı | Siyah pencereye `/portal link` yaz, bağlantıyı tarayıcıya yapıştır. |
| "Anahtar kabul edilmedi" | Anahtarı doğru kopyaladığından ve hesapta bakiye/kota olduğundan emin ol. |
| "Servise ulaşılamıyor" | İnternet bağlantını ya da (bilgisayarımda seçildiyse) Ollama'nın açık olduğunu kontrol et. |
| "Bugünkü ücretsiz hakkın doldu" | Yarın yeniden dene ya da kurulum ekranından başka bir servis seç. |
| Ne olduğunu anlamadın | Ayarlar → "Yardım iste" düğmesine bas, çıkan yazıyı sana Usta'yı veren kişiye gönder. |
| Tablet bağlanmıyor | Aynı Wi-Fi'da mısınız? Güvenlik duvarı sorusuna "izin ver" dedin mi? |
