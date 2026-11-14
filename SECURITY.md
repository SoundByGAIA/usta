# Güvenlik politikası

## Açık bildirme

Güvenlik açığını **herkese açık issue olarak açmayın.** GitHub'ın özel bildirim kanalını kullanın
(depoda *Security → Report a vulnerability*) ya da `Can@soundbygaia.com` adresine e-posta gönderin. Bildirimde etkilenen sürüm/commit, adım adım yeniden üretme ve etkiyi yazın.
Bildirimlere 7 gün içinde yanıt vermeyi, doğrulanan açıkları düzeltene kadar özel tutmayı hedefliyoruz.

Kapsam: sandbox kaçışı, çalışma alanı dışına erişim/yazma, izin motorunu atlatma, portal kimlik doğrulaması/oturum atlatma,
sır sızıntısı, önizleme ile portalı ele geçirme. Kapsam dışı: kendi makinenizde kendi verdiğiniz yetkiyle (ör. `--approve allow`,
oto onay modu, eklediğiniz MCP sunucusu) yapılan eylemler; model çıktısının yanlışlığı.

## Kırmayı deneyenler için rehber

Usta'yı kırmaya çalışmanızı istiyoruz. Bulduğunuz her açık, kodsuz bir kullanıcının başına gelmeden kapanır.

**Nerede deneyin.** Yalnız kendi kurulumunuzda: ayrı bir makine ya da sanal makine en iyisidir. Aynı makinede deneyecekseniz
ayrı bir ev dizini ve çalışma alanı verin (`USTA_HOME=/tmp/usta-deneme python -m usta -w /tmp/usta-ws`; Windows'ta önce
`set USTA_HOME=C:\usta-deneme`). Gerçek anahtarınızı değil, harcama sınırı düşük bir deneme anahtarı kullanın. Başkasının
bilgisayarı, hesabı ya da model servisi kapsam dışıdır.

**En değerli hedefler** (önem sırasıyla):

1. Sandbox'tan çıkmak: yalıtılmış komuttan ana makinede dosya yazmak, ağa çıkmak, süreç başlatmak.
2. Çalışma alanının dışını okumak ya da yazmak: `..`, simgesel bağ, Windows'ta dizin birleşimi (junction) ve UNC yolu, büyük/küçük harf ve
   Unicode oyunları, `.git` ve `.usta` içine yazmak.
3. İzin motorunu atlatmak: yasak (DENY) bir eylemi çalıştırmak, onay isteyen bir eylemi sormadan yaptırmak.
4. Portal: jetonsuz erişim, Host başlığı ve DNS rebinding, başka bir siteden istek attırmak (CSRF), önizlemedeki sayfadan portala
   ulaşmak, `--lan` giriş kodunu tahmin etmek ya da yeniden kullanmak, `/quit` ile başkasının Usta'sını kapatmak.
   Yeni (0.5.0): `POST /local/probe-host` ve `/local/scan-lan` ile internete ya da özel ağ dışına istek attırmak (adres, ad çözümü,
   IPv6/DNS hileleri, yönlendirme), `POST /system/install` ile listedeki programdan başkasını kurdurmak ya da komuta metin sokmak
   (`src/usta/localmodels.py`, `tests/test_localmodels.py`).
   Yeni (0.6.0), evdeki ortak hafıza (`src/usta/ortak.py`, `tests/test_ortak.py`): imzayı atlatmak ya da tekrar oynatmak, eşleşme kodunu
   tahmin etmek, çalınmış anahtarla modele giren bir not eklemek (onay kapısını aşmak), ev sahibi dinleyicisinden portal uçlarına
   ulaşmak, özel ağ dışından ya da tarayıcıdan (`Origin`) erişmek, bağlı bilgisayarda sahte cevapla enjeksiyon.
   Yeni (0.7.0), beceri tasarımcısı (`src/usta/skills.py`, `propose_skill` aracı, `tests/test_skill_design.py`): modelin kullanıcı onayı olmadan
   beceri kaydetmesi/silmesi, öneri kartında riskli metni gizlemek (uyarıları atlatmak), kayıtlı becerinin kendiliğinden devreye girmesi.
5. Sır sızıntısı: `apis.json` içindeki anahtarı API yanıtından, denetim günlüğünden, oturum kaydından ya da hata iletisinden çıkarmak.
6. Dolaylı komut enjeksiyonu: dosya, web sayfası ya da MCP çıktısına gizlenen talimatla ajana yasak bir iş yaptırmak (kaynak izi kapısını aşmak).
7. Kalıcı hafızayı zehirlemek: onaysız, sonraki görevleri yönlendiren bir not yazdırmak.
8. Windows'a özel: masaüstü simgesi, arka planda çalışma, `running.json`, `kurulum/Usta-Kur.bat`.

**Hazır araçlar.** `usta lab validate` ve `usta lab smoke` izin katmanını saldırılı senaryolarla ölçer
([docs/reliability-lab.md](docs/reliability-lab.md)); kendi senaryonuzu `src/usta/lab/scenarios/v1.jsonl` biçiminde ekleyebilirsiniz.
Daha önce kapatılan açıkların testleri `tests/test_hardening2.py`, `tests/test_hardening3.py`, `tests/test_policy.py`,
`tests/test_sandbox.py`, `tests/test_taint.py` ve `tests/test_portal.py` içindedir: nereye bakıldığını gösterir.

**Nasıl bildirin.** Sürüm (`python -m pip show usta`), işletim sistemi, Docker var mı, adım adım yeniden üretme, beklenen ve olan,
etkisi (ne okunuyor, ne yazılıyor, ne çalışıyor). Mümkünse en küçük örnek dosyayı ekleyin.

Aşağıdaki "bilinen sınırlar" tek başına bildirim sayılmaz; ama orada yazandan **daha kötü** bir etki gösterirseniz sayılır.

## Tehdit modeli ve bilinen sınırlar

Ayrıntı: [docs/design.md](docs/design.md) §5. Özet ve **bilinçli sınırlar**:

- **Docker erişimi kök yetkisine eşdeğerdir.** Docker'ı çalıştırabilen kullanıcı makineyi ele geçirebilir; Usta bunu değiştirmez.
  Sandbox: ağ kapalı, tüm yetenekler düşürülmüş, `no-new-privileges`, salt okunur kök dosya sistemi, kaynak sınırları, Docker soketi bağlanmaz,
  yalnız çalışma alanı bağlanır (`.git` ve `.usta` salt okunur). İmaj etiketle (`python:3.12-slim`) seçilir, özet (digest) ile sabitlenmemiştir;
  Usta imajı kendiliğinden çekmez.
- **Oto onay modu** onay isteyen eylemleri sormadan çalıştırır. Yasaklar (DENY) ve sandbox sınırları geçerlidir; izinli olmayan alan adlarına
  `fetch_url` oto modda da reddedilir. Eklediğiniz MCP araçları oto modda sorulmadan çağrılır: **güvenmediğiniz sunucu eklemeyin.**
- **MCP sunucuları varsayılan olarak yalıtılmış konteynerde çalışır (v0.2.0):** kök dosya sistemi salt okunur, root olmayan kullanıcı,
  `cap_drop=ALL`, `no-new-privileges`, CPU/RAM/PID sınırı, ağ kapalı (yalnız `--allow-host` ile allowlist proxy), ev dizini ve Docker soketi
  bağlanmaz, çalışma alanı yalnız istenirse bağlanır (`.git`/`.usta` yine salt okunur), sunucuya yalnız kendi tanımlı sırları verilir.
  Docker/imaj/sabitleme yoksa sunucu **başlamaz**; ana makineye sessizce düşülmez. `usta mcp prepare` paketleri bir kez, yalnız paket kayıtlarına açık
  bir ağda (kurulum betikleri kapalı) önbelleğe indirir ve imaj kimliğiyle önbellek özetini sabitler; sonra ağ kapalı çalışır, her başlatmada
  özet doğrulanır. Sınırlar: Docker erişimi kök yetkisi demektir; konteyner çekirdeği ana makineyle paylaşır (çekirdek/runtime açıkları kapsam dışıdır);
  izinli alan adlarına giden HTTPS içeriği opaktır; `--isolation host --i-understand-host-risk` açık bir uyumluluk modudur ve sunucuyu
  **ana makinede, sizin yetkilerinizle** çalıştırır (her başlatmada uyarı verilir). Oto onay modunda MCP araçları sorulmadan çağrılabilir:
  güvenmediğiniz sunucu eklemeyin.
- **Kalıcı hafıza zehirleme (v0.2.0):** `remember` ile yazılan her not kaynağını taşır (`[kaynak: model, görev …]`) ve bağlamda "doğrulanmamış"
  olarak görünür. Komut/bağlantı/gizli bilgi benzeri/onay iddiası/talimat geçersiz kılma içeren notlar kullanıcı onayı ister; oto onay modunda
  **reddedilir**. Zararsız ama tuhaf notlar (yanlış pozitif) ya da bu kalıplara uymayan ince zehirlemeler yine yazılabilir; notları `/hafıza` ile gözden geçirin.
- **Dış içerik işaretlemesi güvenlik sınırı DEĞİLDİR:** web/MCP/hafıza içeriği nonce'lu işaretlerle *veri* olarak verilir, ama bu bir modeli ikna edici
  bir enjeksiyondan korumaz. Asıl sınır izin motorudur (yasak yazma yolları, çalışma alanı dışı okuma, bilinmeyen araç, ağ allowlist'i). Çalışma
  alanı dosyaları (`read_file`) işaretlenmez. Çalışma alanı **içindeki** yazmaları (ör. bir test dosyasını boşaltmak) ve yanıt metnine sızdırmayı hiçbir kural engelleyemez;
  `usta lab` bunu ölçer ve açıkça raporlar.
- **Geri alma yalnız dosyaları kapsar:** devre kesici çalışma alanı dosyalarını geri sarar; komutların dış etkileri (ağ istekleri, paket kurulumu, sandbox dışına çıkan her şey) geri alınamaz.
- **Tedarik zinciri (v0.2.0):** Python bağımlılıkları hash'li, çok platformlu kilit dosyalarıyla (`requirements*.lock`) kurulur ve CI'da `pip-audit` kilidi tarar.
  Sandbox ve MCP imajları etiketle seçilir; `usta sandbox pin` / `usta mcp prepare` yerel imaj kimliğini sabitler ve her çalıştırmada doğrular
  (etiket başka içeriğe işaret ederse çalışmaz). Usta imajı kendiliğinden çekmez; ilk kez çekilen imajın güvenilirliği sizin kararınızdır.
- **Dolaylı komut enjeksiyonu (v0.2.1, kısmi savunma):** okunan dosya/sayfa/MCP çıktısındaki gizli talimatlar modeli yönlendirebilir. Kaynak izi
  kapısı (`taint.py`, varsayılan açık; `--no-taint-gate` ile kapanır) şunu yakalar: `write_file`/`edit_file` yolu ya da `run` komutundaki yol/adres
  parçası, güvenilmeyen kaynaklardan (dosya içeriği, `fetch_url`, `web_search`, MCP) gelen metinde geçiyor ve sizin isteminizde geçmiyorsa eylem
  onay ister (manuel modda gerekçeyle sorulur, oto modda reddedilir). **Sınırlar:** komut çıktısındaki talimatlar kapsam dışıdır (test izlerindeki
  meşru yollar sürekli işaretlenmesin diye); model enjekte metni yazdığı dosyanın *içeriğine* kopyalarsa yakalanmaz; sezgiseldir, kesin koruma
  değildir. Ölçüm: [docs/v0.2.1-raporu.md](docs/v0.2.1-raporu.md).
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

Bağımlılıklar `pyproject.toml`'da alt sınırla, `requirements*.lock` dosyalarında hash'li olarak sabitlenir. CI her itmede `pip-audit` ile kilit dosyasını tarar.
