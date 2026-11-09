# Usta'yı başlat (adım adım, sade anlatım)

Usta, ne istediğini yazdığında bunu senin için yapan bir yapay zekâ yardımcısıdır (ör. "bir hesap makinesi sayfası yap").
Önce bilgisayarına bir kez kurarsın, sonra tarayıcıdan kullanırsın. Aşağıdaki adımları sırayla yap.

## Windows'ta kurulum

**1. Python'u kur** (bir kerelik)
- Tarayıcıda `python.org` adresine git, sarı "Download Python" düğmesine bas, inen dosyayı aç.
- Açılan pencerenin **en altındaki** "Add python.exe to PATH" kutusunu **işaretle**. Bunu unutma, sonra çok işe yarar.
- "Install Now"a bas ve bitmesini bekle.

**2. Siyah pencereyi aç**
- Klavyede Windows tuşuna bas, `cmd` yaz, Enter'a bas. Siyah bir pencere açılır.

**3. Usta'yı indir**
- Siyah pencereye şunu yaz ve Enter'a bas: `python -m pip install usta`
- Yazılar akar, biraz bekle. Bitince imleç geri gelir.
- "WARNING ... is not on PATH" gibi sarı bir uyarı çıkarsa **yok say**, sorun değil.

**4. Usta'yı çalıştır**
- Şunu yaz ve Enter'a bas: `python -m usta`
- Tarayıcın kendiliğinden açılır. Açılmazsa siyah pencereye `/portal link` yaz ve çıkan bağlantıyı tarayıcıya yapıştır.

**5. Kurulum ekranı**
- Tarayıcıda "Hoş geldin" ekranı çıkar. İki seçenek vardır:
  - **İnternet servisiyle:** Hızlı ve güçlüdür. Bir servisten (ör. Google Gemini, DeepSeek) **anahtar** almalısın. Anahtar, uzun bir şifre gibi bir yazıdır; servisin sitesinde hesap açınca "API keys" yazan yerden alırsın. Ekrandaki kutuya yapıştır, "Dene"ye bas. Yazdıkların o servisin sunucusuna gider, kullandıkça ücret çıkabilir.
  - **Bilgisayarımda:** Ücretsizdir, yazdıkların bilgisayarından çıkmaz. Önce `ollama.com`dan Ollama programını kurup bir model indirmen gerekir. Küçük modeller basit işleri yapar, zor işlerde zayıf kalabilir.
- Sonunda "Hazır!" yazar. Altındaki örneklerden birine bas ve dene.

## Tabletten ya da telefondan kullanmak

Bilgisayar ve tablet **aynı Wi-Fi'a** bağlı olmalı.

1. Siyah pencerede Usta'yı kapat (`/çık` yaz, Enter) ve şöyle başlat: `python -m usta --lan`
2. Windows "güvenlik duvarı" sorusu sorarsa **"Özel ağlar"** kutusunu işaretleyip **"Erişime izin ver"**e bas.
3. Siyah pencerede **adres** ve **giriş kodu** yazar. Tabletin tarayıcısına adresi yaz, kodu sorduğu kutuya gir.
4. Kodu kaybedersen bilgisayardaki Usta ekranında "Tablet" düğmesine bas, yeni kod verir.

Bu bağlantı şifrelenmez. Yalnız evindeki gibi güvendiğin bir Wi-Fi'da kullan.

## Bilmen gerekenler (dürüst notlar)

- **Docker yoksa komut çalıştırılamaz.** Usta, bilgisayarında bir komut çalıştırması gerektiğinde bunu güvenlik için Docker adlı programın içinde yapar. Docker kurulu değilse Usta dosya yazabilir ve okuyabilir ama komut çalıştıramaz (ör. yazdığı kodu deneyemez). Basit sayfa/metin işleri için gerekmez.
- **Windows'ta denendi, ama sınırlı.** Usta Linux'ta geliştirildi. 9 Kasım 2026'da gerçek bir Windows 10 bilgisayarda (Python 3.14) kurulum, açılış, ayarlar, dosya yazma ve Türkçe karakterler denendi ve buldukları düzeltildi. Docker'lı komut çalıştırma ve tablet bağlantısı Windows'ta denenmedi. Bir şey bozulursa bize haber ver.
- **Verin nerede?** Usta'daki "Gizlilik" düğmesi, yazdıklarının nereye gittiğini ve bilgisayarında neleri sakladığını gösterir.

## Sorun olursa

| Gördüğün | Ne yap |
|---|---|
| `python bulunamadı` | Python'u yeniden kur ve "Add python.exe to PATH" kutusunu işaretle. |
| `usta bulunamadı` | Hep `python -m usta` yaz, `usta` yazma. |
| Tarayıcı açılmadı | Siyah pencereye `/portal link` yaz, bağlantıyı tarayıcıya yapıştır. |
| "Anahtar kabul edilmedi" | Anahtarı doğru kopyaladığından ve hesapta bakiye/kota olduğundan emin ol. |
| "Servise ulaşılamıyor" | İnternet bağlantını ya da (bilgisayarımda seçildiyse) Ollama'nın açık olduğunu kontrol et. |
| Tablet bağlanmıyor | Aynı Wi-Fi'da mısınız? Güvenlik duvarı sorusuna "izin ver" dedin mi? |
