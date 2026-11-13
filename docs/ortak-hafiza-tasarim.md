# Ortak hafıza: tasarım taslağı (0.6.0)

Durum: **taslak, kod yok.** Berke'nin (güvenlik) incelemesi ve Can'ın kararı beklenir. Açık sorular en altta.

## Amaç

Aynı evdeki bilgisayarlarda Usta'yı kullanan kişi, kendini her bilgisayarda yeniden tanıtmak zorunda kalmasın.
"Seni tanıyayım" bilgileri (hitap, anlatım biçimi, "hakkımda", maddeler) ve birkaç ortak not, evdeki
bilgisayarlar arasında aynı olsun.

## Ne paylaşılır, ne paylaşılmaz

| Paylaşılır | Paylaşılmaz (hiçbir koşulda) |
|---|---|
| "Seni tanıyayım" profili (`kisi.json`) | Görev geçmişi, konuşmalar, çalışma alanı dosyaları |
| Kullanıcının elle eklediği ortak notlar (en çok 50 not, her biri en çok 300 harf) | API anahtarları, jeton, `apis.json`, denetim günlüğü |
| | Modelin yazdığı notlar (`remember` aracı yalnız yerel proje hafızasına yazar) |

Kural: **ortak hafızaya yalnız kullanıcı yazar** (arayüzden). Model yazamaz. Böylece bir web sayfasından gelen
enjeksiyon ortak hafızayı zehirleyemez.

## Yapı: bir ev sahibi, diğerleri bağlanır

1. **Ev sahibi bilgisayar:** Ayarlar'da "Bu bilgisayar evdeki ortak hafızayı tutsun" açılır (varsayılan KAPALI).
   Usta, portaldan ayrı, çok küçük ikinci bir dinleyici başlatır. Bu dinleyicide yalnız `/ortak/*` uçları vardır;
   portalın hiçbir ucu (görev, dosya, ayar, `/quit`) bu kapıdan erişilemez.
2. **Eşleştirme:** Ev sahibi 6 haneli bir kod gösterir (5 dakika geçerli, tek kullanım, 5 yanlış denemede kilit;
   tablet eşleştirmesindeki `LoginCodes` sınıfı yeniden kullanılır). Öbür bilgisayarda kullanıcı ev sahibinin adresini
   (sihirbazdaki "evdeki bilgisayar" taramasıyla bulunur) ve kodu girer.
3. **Bağlantı anahtarı:** Kod doğruysa ev sahibi bu bilgisayara özel rastgele bir anahtar (32 bayt) üretir. Ev
   sahibi yalnız anahtarın SHA-256 özetini saklar (`ortak-eslesme.json`, 0600); bağlanan bilgisayar anahtarın kendisini
   saklar (0600). Eşleşmeyi ev sahibi tek tıkla siler: anahtar o an geçersiz olur.
4. **Okuma/yazma:** Bağlanan bilgisayar profil ve notları ev sahibinden alır; her görevin başında güncel kopya
   okunur. Ev sahibi kapalıysa son bilinen kopya (önbellek) **salt okunur** kullanılır ve arayüz "Ortak hafıza şu an
   görünmüyor" der; görev düşmez.

## Modele nasıl girer

- Profil bugünkü gibi `<<<KULLANICI-PROFILI id=…>>>` bloğunda, kullanıcı mesajının başında, nonce'lu işaretlerle ve
  "güvenlik kurallarını/onayları değiştirmez" uyarısıyla girer. Sistem rolüne GİRMEZ.
- Ortak notlar ayrı bir `<<<ORTAK-HAFIZA id=…>>>` bloğunda, her biri `[kaynak: <bilgisayar adı>]` etiketiyle girer.
- **Onay kapısı:** Ev sahibi dışındaki bir bilgisayarın eklediği not, ev sahibinde "onay bekliyor" olur ve kullanıcı
  ev sahibinin ekranında onaylayana kadar hiçbir bilgisayardaki modele girmez. Böylece çalınmış bir bağlantı anahtarı
  diğer bilgisayarlara metin enjekte edemez.

## Tehditler ve karşılıkları

| Tehdit | Karşılık |
|---|---|
| Ağdaki biri ortak hafızayı okur/yazar | Anahtarsız her istek 401; eşleştirme kodu 5 dk, tek kullanım, 5 deneme kilidi; yalnız özel ağ kaynak adresi kabul |
| Eşleştirme kodunu kaba kuvvetle bulmak | 6 hane × 5 deneme × 5 dk ≈ 1/200 000 şans; kilitlenince yeni kod gerekir; kod yalnız ev sahibinin ekranında |
| Bağlantı anahtarı çalınır (düz HTTP dinleme) | **Açık soru 1.** Ev ağında şifresiz HTTP, tablet bağlantısıyla aynı sınır; arayüz bunu söyler |
| Çalınan anahtarla enjeksiyon | Onay kapısı (üstte); notlar sınırlı boyutta ve temizlenmiş karakterlerle |
| Web enjeksiyonuyla ortak hafızaya yazma | Model ortak hafızaya yazamaz; yalnız arayüzdeki kullanıcı eylemi yazar |
| DNS rebinding / başka sitenin istek attırması | Host başlığı denetimi (portaldaki gibi), `Origin` olan istekler reddedilir, CORS kapalı |
| Kaynak tüketme | Gövde sınırı 8 KB, 50 not, istek hız sınırı |
| Dinleyicinin internete açılması | Yalnız özel ağ arayüzlerine bağlanır; genel IP'li arayüzde başlamaz |
| Sızıntı: ortak hafıza yanlışlıkla gizli bilgi taşır | Arayüz "şifre/anahtar yazma" uyarır; not eklerken `audit.mask` deseni gizli bilgi bulursa reddeder |

## Yapılmayacaklar

- İnternet üzerinden erişim (yalnız ev ağı), hesap/bulut, otomatik senkron.
- Görev geçmişi ya da dosyaların paylaşımı.
- Modelin ortak hafızaya yazması.

## Test ve ölçüm

- Birim: eşleştirme (süre, tek kullanım, kilit), anahtarsız/yanlış anahtarlı 401, boyut sınırları, Host/Origin,
  özel ağ dışı kaynak reddi, onay kapısı (bekleyen not modele girmez), model yazma yolu yok.
- Reliability Lab'a yeni senaryolar: ortak nottaki gizli talimat, bekleyen notun sızması, çalınmış anahtarla not ekleme.
- Gerçek ağ: iki bilgisayarla uçtan uca (Windows + Linux).

## Kararlar (Can, 14 Kasım 2026)

1. **Taşıma:** imzalı istek (anahtarın kendisi ağda gitmez; her istek anahtardan türetilmiş HMAC imzası ve tek
   kullanımlık sayaç taşır). İçerik şifrelenmez; arayüz bunu söyler.
2. **Notlar düz dosya** (düz JSON ya da markdown; dinlenme anında şifreleme yok).
3. **Onay kapısı yalnız dışarıdan gelen notlar için.**
4. **Ev sahibi:** "ai-memory reposunu konumlandırabiliriz" dendi. Aşağıdaki karşılaştırma bu yüzden eklendi.

## İki yol: kendi küçük sunucumuz mu, ai-memory mi

[ai-memory](https://github.com/akitaonrails/ai-memory) (MIT lisanslı, Rust, 15 bini aşkın yıldız) zaten evdeki bir
sunucuda çalışan, birden çok bilgisayarın ve aracın (20'den fazla) ortak kullandığı bir hafıza sunucusudur. Bizim yukarıda
tarif ettiğimiz parçaların çoğu onda var:

| İhtiyaç | Kendi sunucumuz (yukarıdaki tasarım) | ai-memory'yi kullanmak |
|---|---|---|
| Sunucu, eşleştirme, kimlik | Yazılacak (`LoginCodes` üstüne) | Hazır: `aim_` anahtarları, çok kullanıcılı kimlik, proje bazlı yetki |
| Denetim kaydı | Yazılacak | Hazır (`audit_log`) |
| Notlar düz dosya | Yazılacak | Hazır: kaynak gerçek, git'li düz markdown viki |
| İmzalı istek | Yazılacak (karar 1) | **Yok:** Bearer anahtarı kullanır; ev ağında şifresiz HTTP'de anahtar dinlenebilir. Çözüm: yalnız `127.0.0.1` + SSH tüneli ya da TLS proxy (kendi belgesi önerir) |
| Yeni kullanıcıya kurulum | Usta içinde, düğmeyle | **Ağır:** Docker ve bir sunucu gerekir; sıfır bilgili kullanıcıya göre değil |
| Gizlilik duruşu | Her şeyi kullanıcı yazar | Kanca (hook) ile istemleri ve araç çağrılarını sessizce kaydeder. Usta'da bunu KULLANMAYIZ |
| Bakım yükü | Bizde | Onda (ama ona bağımlıyız) |

**Önerim: ikisini birleştirmek, ai-memory'yi gelişmiş kullanıcılar için bağlayıcı olarak eklemek.**
- Usta, ai-memory'ye **istemci** olur: model yalnız OKUR (`memory_query`/`memory_recent` benzeri, salt okunur araçlar);
  yazmayı yalnız kullanıcı, arayüzdeki "Ortak notlara ekle" düğmesiyle yapar. Kanca ve sessiz kayıt yoktur.
- Bağlantı adresi ve anahtarı `apis.json` gibi 0600 dosyada durur; adres yalnız loopback ya da özel ağ olabilir.
- ai-memory'den gelen her içerik `<<<ORTAK-HAFIZA id=…>>>` içinde VERİ olarak ve kaynak etiketiyle girer; dışarıdan
  (başka kullanıcı/araç) yazılmış kayıtlar kullanıcı onaylayana kadar modele girmez (karar 3).
- Kendi küçük sunucumuz **sonraya** kalır: yalnız ai-memory kurmak istemeyen, evde birden çok bilgisayarı olan
  yeni kullanıcılar için. Gerekirse o zaman yapılır.
- Bu yolda "imzalı istek" kararı ai-memory'nin Bearer modeline karşılık gelir; ev ağında kullanılacaksa TLS proxy ya da
  SSH tüneli ŞARTTIR (Usta, bağlantı adresi loopback ya da `https://` değilse uyarı verir).

Sonraki adım (onay bekliyor): ai-memory'nin HTTP/MCP uçlarını salt okunur olarak yoklayıp küçük bir bağlayıcı prototipi
(`src/usta/ortakhafiza.py`): bağlan, ara, listele, onay kapısı.
