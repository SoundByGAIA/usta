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

- Tarayıcıda "Yapay zekâ nerede çalışsın?" ekranı çıkar. İki seçeneğin artıları ve eksileri yazılıdır, altında da senin bilgisayarına göre bir öneri vardır.
  - **İnternet servisiyle** (çoğu kişi için önerilir): Daha güçlü ve hızlıdır. Bir servisten **anahtar** almalısın (uzun bir şifre gibi bir yazı). Ekran, her servis için adımları ve anahtar sayfasının bağlantısını gösterir; yaklaşık 5-10 dakika sürer. **Ücretsiz seçenekler:** Google Gemini ve OpenRouter (ücretsiz katmanlarında günlük istek sınırı düşüktür ve yazdıkların servis tarafından ürün geliştirmede kullanılabilir). DeepSeek, OpenAI, Claude (Anthropic) ve OpenCode ücretlidir.
  - **Bilgisayarımda**: Ücretsizdir ve yazdıkların bilgisayarından çıkmaz. Ekran bilgisayarının belleğine bakıp sana bir model önerir ve adım adım yürütür: önce Ollama programını kurarsın, sonra "İndir" düğmesiyle modeli indirirsin (2-5 GB, ilerleme çubuğu görünür). Küçük modeller basit işlerde iyidir, zor işlerde başarısız olabilir.
- Model seçince Usta modeli tanımak için yarım dakikaya kadar bekler ("Modeli tanıyorum" yazar), bu sırada başka bir şeye basma.
- Sonunda "Hazır!" yazar. Altındaki örneklerden birine bas ve dene.

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
