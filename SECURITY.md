# Güvenlik politikası

## Açık bildirme

Güvenlik açığını **herkese açık issue olarak açmayın.** Depo yayınlandığında GitHub'ın özel bildirim kanalını kullanın
(depoda *Security → Report a vulnerability*) ya da `Can@soundbygaia.com` adresine e-posta gönderin. Bildirimde etkilenen sürüm/commit, adım adım yeniden üretme ve etkiyi yazın.
Bildirimlere 7 gün içinde yanıt vermeyi, doğrulanan açıkları düzeltene kadar özel tutmayı hedefliyoruz.

Kapsam: sandbox kaçışı, çalışma alanı dışına erişim/yazma, izin motorunu atlatma, portal kimlik doğrulaması/oturum atlatma,
sır sızıntısı, önizleme ile portalı ele geçirme. Kapsam dışı: kendi makinenizde kendi verdiğiniz yetkiyle (ör. `--approve allow`,
oto onay modu, eklediğiniz MCP sunucusu) yapılan eylemler; model çıktısının yanlışlığı.

## Tehdit modeli ve bilinen sınırlar

Ayrıntı: [docs/design.md](docs/design.md) §5. Özet ve **bilinçli sınırlar**:

- **Docker erişimi kök yetkisine eşdeğerdir.** Docker'ı çalıştırabilen kullanıcı makineyi ele geçirebilir; Usta bunu değiştirmez.
  Sandbox: ağ kapalı, tüm yetenekler düşürülmüş, `no-new-privileges`, salt okunur kök dosya sistemi, kaynak sınırları, Docker soketi bağlanmaz,
  yalnız çalışma alanı bağlanır (`.git` ve `.usta` salt okunur). İmaj etiketle (`python:3.12-slim`) seçilir, özet (digest) ile sabitlenmemiştir;
  Usta imajı kendiliğinden çekmez.
- **Oto onay modu** onay isteyen eylemleri sormadan çalıştırır. Yasaklar (DENY) ve sandbox sınırları geçerlidir; izinli olmayan alan adlarına
  `fetch_url` oto modda da reddedilir. Eklediğiniz MCP araçları oto modda sorulmadan çağrılır: **güvenmediğiniz sunucu eklemeyin.**
- **MCP sunucuları sandbox'ta değildir:** bilgisayarınızda sizin yetkilerinizle çalışır. Katalogdaki paket sürümü sabittir (`npx -y paket@sürüm`),
  ama alt bağımlılıklar npm tarafından çözülür; kilit dosyası/bütünlük denetimi yoktur.
- **Sızdırma kanalları** (belgeli): izinli alan adlarına HTTPS; model uç noktanız (istemler ve açılan dosya içerikleri o API'ye gider);
  önizlemede ajanın yazdığı sayfanın kendi kendine başka adrese yönlenmesi (iframe sandbox'ı bunu engelleyemez; `connect-src`, `form-action` ve
  `allow-top-navigation` kapalıdır).
- **Portal yereldir** (`127.0.0.1`): jetonla korunur, Host başlığı denetlenir (DNS rebinding), giriş kodu tek kullanımlıktır ve komut satırında görünmez.
  Aynı makinedeki *aynı kullanıcı* olarak çalışan başka bir süreç, `~/.usta/token` dosyasını okuyabilir; bu bir savunma sınırı değildir.
  Çok kullanıcılı makinelerde ev dizininizin izinlerini kısıtlı tutun (Usta kendi dizinini `0700` yapar).
- **Sırlar:** model API anahtarları yalnız `~/.usta/apis.json` ve `~/.usta/mcp-secrets.json` içindedir (`0600`); API'den geri verilmez;
  denetim günlüğü ve oturum kayıtlarındaki bilinen sır desenleri maskelenir (kapsamlı değildir: model/komut çıktısında tanınmayan biçimde sır olabilir).
- **Ev dizini ya da kök çalışma alanı olamaz**; ajan `.git` ve `.usta` klasörlerine dosya araçlarıyla yazamaz. Görev başında var olan her `.git`
  (iç içe olanlar ve çıplak depolar dahil) sandbox'ta salt okunur bağlanır; görev sırasında yeni oluşturulan `.git`/`.usta`/çıplak depo girdileri
  görev sonunda `~/.usta/quarantine/<görev>/` altına taşınır ve uyarı verilir. Sınırlar: `node_modules`/`.venv` içinde yalnız 3 seviye taranır;
  Docker kapalıyken sandbox yoktur. Ek önlem olarak `git config --global safe.bareRepository explicit` önerilir.
- Anlık görüntü (geri alma) bellekte tutulur: çalışma alanı başına son 5 görev, görev başına en çok 200 MB; çok sayıda çalışma alanında toplam bellek artar.
- Sır maskeleme bilinen desenlerle çalışır (özel anahtar blokları, `sk-…`, JWT, `Bearer …` vb.); tanınmayan biçimler maskelenmez.

## Bağımlılıklar

`pip-audit` ile yayın öncesi taranır (şu an bilinen açık yok). Bağımlılıklar alt sınırla belirtilir; kilit dosyası yoktur.
