# Usta

[English](README.en.md) · Türkçe

Türkiye'den çıkan, genel amaçlı, **açık kaynak (Apache-2.0)** yapay zekâ kod ajanı. Terminalde `usta` yazarsın; ajan
çalışma klasöründe araçlarla iş yapar, yerel bir web portalı (`127.0.0.1`) canlı akışı, dosyaları ve önizlemeyi gösterir.
Model bağımsız: Ollama, llama.cpp, DeepSeek, OpenRouter, OpenAI gibi **OpenAI-uyumlu** her uç nokta.

> Durum: erken geliştirme (v0.x). Komutlar ve API değişebilir. Tasarım ve tehdit modeli: [docs/design.md](docs/design.md).

Odak yalnız "başka bir LLM arayüzü" olmak değil: **küçük ve yerel modelleri gerçek yazılım işlerinde daha güvenilir
kılan harness** (araç çağrısı, bağlam yönetimi, doğrulama döngüsü, devre kesici) ve bunun **dürüstçe ölçülmesi**
(`usta bench`). Bir özellik ancak ölçümde faydası görülürse varsayılan olur.

## Hızlı başlangıç

**Hiç kod bilmiyorsan, Windows kullanıyorsan ya da tabletten kullanmak istiyorsan:** [docs/baslangic.md](docs/baslangic.md) (adım adım, sade anlatım; `pip install usta` yeterli).

PyPI'den: `uv tool install usta` (ya da `pip install usta`). Kaynaktan:

```bash
git clone https://github.com/SoundByGAIA/usta.git usta && cd usta
uv venv && uv pip install -e .
ln -s "$PWD/.venv/bin/usta" ~/.local/bin/usta     # ya da: uv tool install --editable .
cd benim-projem
usta                                              # terminal + portal (tarayıcıda açılır)
```

İlk açılışta model uç noktasındaki (varsayılan Ollama `http://127.0.0.1:11434/v1`) modelleri listeler, birini seçersin;
modelin araç çağırma yeteneğini küçük bir ölçümle tanır (yerel `tool_calls` → JSON şeması → metin protokolü).

**Dosyalar nereye yazılır?** `usta`'yı hangi klasörde başlatırsan o klasör çalışma alanıdır ve dosyalar doğrudan orada
oluşur (açılışta tam yol yazılır). Ajan yalnız o klasörün içine yazabilir. Ev dizininde başlatırsan uyarı alırsın;
bir proje klasöründe başlatmak daha güvenlidir.

## Terminal komutları

| Komut | |
|---|---|
| `/mod [manuel\|oto\|plan]` | **manuel**: her onay sorulur · **oto onay**: onay isteyen eylemler sorulmadan çalışır (yasaklar ve sandbox geçerli) · **plan**: yalnız okur ve plan sunar; onayınla **aşama aşama** ya da tek seferde uygular |
| `/tema [beyaz\|gri\|siyah]` | renk teması (terminal ve portal ortak) |
| `/koruma [aç\|kapat]`, `/doğrula [komut]` | doğrulama kapısı + devre kesici; proje test komutu |
| `/diff`, `/geri` | son görevin değişikliklerini renkli göster / geri al |
| `/token` | token kullanımı, sağlayıcı önbelleği ve bağlam doluluğu |
| `/hafıza`, `/geçmiş [n]`, `/beceriler`, `/mcp` | proje notları, önceki oturumlar, beceriler, ek araçlar |
| `/model [[api] ad]`, `/portal` | modeli listele/değiştir (bağlı tüm API'ler), portal adresi |
| `/ad metin` | `~/.usta/skills/ad.md` becerisini çalıştırır |

Seçenekler: `usta --no-portal`, `--no-browser`, `--model`, `--endpoint`, `--mode`, `--theme`, `--context-window`, `--protocol`.

## Portal

Terminalle aynı görev yöneticisini kullanır: terminalde başlayan görev portalda canlı görünür ve tersi.
Yalnız `127.0.0.1`'e bağlanır; tarayıcı jetonla değil, **tek kullanımlık kısa ömürlü kodla** açılır.

- **Akış, Değişiklikler, Hafıza, Geçmiş, Önizleme** sekmeleri; renkli diff, iki tıklamalı geri alma, token/önbellek sayacı.
- **Görev sürerken yönlendirme:** çalışırken yazdığın mesaj ajana bir sonraki adımında iletilir.
- **Dosya gezgini:** ağacı gez, dosya aç, göreve ekle, dosya/klasör yükle, yeni dosya/klasör, yeniden adlandır, sil.
- **Dosya ekleme:** metin/Markdown dosyaları isteme *veri olarak* eklenir.
- **API'ler:** istediğin kadar OpenAI-uyumlu API bağla (Ollama, DeepSeek...). Modelleri üstteki seçicide görünür, oturumdan çıkmadan değişir. Anahtarlar yalnız `~/.usta/apis.json` içindedir (0600), ekranda bir daha gösterilmez.
- **Önizleme:** statik siteleri (HTML/CSS/JS) yalıtılmış çerçevede gösterir (sandbox iframe; portalın jetonuna ve ağa erişemez).
- **Araçlar:** beceriler (`.md` yükle) ve katalogdan MCP sunucuları.
- **Boyut:** arayüz pencere/ekran boyutuna göre otomatik ölçeklenir (%90–%175 elle de seçilebilir); 3 tema.

## Planla, sonra uygula

Plan modunda ajan yalnız okur ve plan yazar. Onaylayınca iki yol vardır:

- **Aşama aşama (önerilen):** plan `PLAN.md` içinde işaretlenebilir aşamalara bölünür; her aşama **taze bağlamlı ayrı bir görev** olarak koşar
  (okur, uygular, test eder, `- [x]` yapar, durur). İlerleme yoksa, hata, iptal ya da devre kesici durumunda zincir kendiliğinden durur.
  Uzun işlerde istek başına bağlamı sınırlı tutar (küçük, 8K'lık yerel modeller için gerekli). **Toplam token tasarrufu iddia etmiyoruz** (bkz. aşağıdaki ölçüm notu).
- **Tek seferde:** planın tamamı tek görevde uygulanır.

**Ölçüm notu (ara, tek koşu):** aynı onaylı plan (24 bin karakterlik ticari bir e-ticaret sitesi, DeepSeek, 200 adım/görev sınırı, koruma açık). *Tek seferde:* 200 adımda sınıra takıldı — 10,0 milyon girdi token'ı (%94'ü sağlayıcı önbelleğinden), 23 Python dosyası, **hiç test yok**, `PLAN.md`'de 0 madde işaretli. *Aşama aşama:* 11/23 aşamada 18,2 milyon girdi token'ı, 41 dosya, **224 test geçiyor**. Yani aşamalı uygulama toplamda daha çok token harcıyor ama işi doğrulanabilir adımlarla ilerletiyor; tek seferlik koşu ise bağlam şişince adım bütçesini testlere varmadan tüketti. Örneklem tek koşudur; genelleme yapmayın.

Plan sunucuda saklanır ve numarasıyla uygulanır; istem yeniden yazılmaz.

## Güvenilirlik ve ölçüm araçları (v0.2.0)

Usta'nın amacı modeli olduğundan zeki göstermek değil, mevcut model kapasitesini **güvenilir ve doğrulanabilir** kullanmaktır.
v0.2.0 bunun için güvenlik ve ölçüm altyapısı ekler. Bunların küçük modellerde görev başarısını artırdığı **kanıtlanmış değildir**;
hangisinin ne işe yaradığı ve maliyeti [docs/v0.2.0-raporu.md](docs/v0.2.0-raporu.md) içinde sayılarla, başarısız sonuçlar dahil yazılıdır.

| Komut | Ne yapar |
|---|---|
| `usta lab run/smoke/compare` | **Reliability Lab:** aynı görevi temiz ve saldırılı (araç çıktısı/MCP/README enjeksiyonu, sahte otorite, sızdırma, hafıza zehirleme) çalıştırır; gerçekleşen **araç eylemlerini** değerlendirir (ASR, deneme/gerçekleşme, yanlış ret, toparlanma, token, gecikme). [docs/reliability-lab.md](docs/reliability-lab.md) |
| `usta bench run --split dev-all\|final` · `diagnose` · `replay` · `regress` | Bench: görevler train/dev/final bölümlü (varsayılan final hariç), her başarısızlık nedene ayrılır (taxonomy), iz kaydı ve **modelsiz tekrar oynatma**, eşleştirilmiş kol karşılaştırması (yalnız yön; küçük örneklemde anlamlılık iddia edilmez), önceki sürüme göre regresyon |
| `usta probe --deep` · `--protocol auto` | Model yetenek profili: protokol başına 9 sonda (uçtan uca ajan görevleri dahil), model revizyonu + yapılandırmaya bağlı kalıcı profil; `auto` koşu başında bir kez çözülür ve sabitlenir |
| `usta mcp add --image … / prepare / test` | MCP sunucuları varsayılan olarak **yalıtılmış konteynerde**; paketler `prepare` ile bir kez indirilip sabitlenir |
| `usta sandbox pin / status` | Sandbox imajının kimliğini sabitler; değişirse çalıştırma reddedilir |
| `--no-taint-gate` | Kaynak izi kapısını kapatır (varsayılan açık): okunan içerikten türeyen yazma/komut hedefleri onay ister, oto modda reddedilir |
| `--symbol-tools` (deneysel) | Tree-sitter ile sembol araçları (`pip install 'usta[symbols]'`): `related_files`, `find_symbol`, `symbol_context` |

Yürütme aşamaları (DISCOVER → PLAN → EDIT → VERIFY → DIAGNOSE → REPAIR) **gözlemlenir** ve denetim kaydına yazılır; her görev bir terminal
durumla biter (`COMPLETE_VERIFIED`, `FAILED_VERIFICATION`, `BLOCKED`, …). Başarısız doğrulama başarı olarak gösterilmez; doğrulama ortamındaki
eksik bağımlılık (kod hatası değil) ayrıca bildirilir. Deneysel olanlar varsayılan **kapalıdır** ve ölçümle doğrulanmadan açılmaz.

## Güvenlik özeti

Varsayılan: ağ kapalı, sır yok, yazma yalnız çalışma alanında. Komutlar Docker sandbox'ında; ağ yalnız allowlist proxy'den.
MCP sunucuları yalıtılmış konteynerde çalışır; kalıcı hafıza notları kaynak izi taşır ve şüpheli notlar onay ister; bağımlılıklar hash'li kilitten kurulur.
Portal yerel, jetonlu ve CSP'li; model çıktısı hep düz metin basılır. Harici içerik (web, dosya, MCP, ek, plan, hafıza) modele
*veri* olarak, nonce'lu işaretlerle verilir. Ayrıntı ve açık bildirimi: [SECURITY.md](SECURITY.md), [docs/design.md](docs/design.md).

## Ölçüm: usta bench (ön sonuçlar, dikkatli oku)

`usta bench run --arm A|B|C|D` küçük gerçek yazılım görevlerini modelle çalıştırır ve **ajanın göremediği gizli testlerle**
doğrular (A: yalnız kabuk · B: Usta · C: + doğrulama kapısı · D: + devre kesici). `usta bench compare` katman başına
tablo ve %95 güven aralığı üretir. Altyapı hataları başarısızlık sayılmaz; token maliyeti raporlanır.

| Katman | Model | Kol: geçen/toplam | Not |
|---|---|---|---|
| Zayıf | 4B yerel (5 görev × 3) | A 1/15 · B 0/15 · C 1/15 | C ≈ 3,5× token; fark istatistiksel değil |
| Orta | 7B coder, JSON protokolü (15 × 2) | B 0/30 · D 1/30 | D ≈ 4,5× token; model çözüm üretemiyor |
| Büyük (API) | DeepSeek (15 × 2) | A 30/30 · B 23/23¹ · C 29/30 · D 30/30 | görevler güçlü model için kolay (tavan etkisi) |

¹ 7 altyapı (ağ) hatası sayılmadı.

**Bugün harness'ın başarıyı artırdığını iddia etmiyoruz**: güçlü modelde zarar vermiyor, zayıf modelde tek başına çözüm değil.
Örneklem küçük, güven aralıkları geniş. Ölçerken bulduklarımız belgelenir (ör. bazı modeller araç çağrısını metin olarak
yazar → kurtarma ve yetenek sondası eklendi; erken "yazılan dosyayı bağlamdan at" denemesi fayda göstermedi, varsayılan kapalı).

## Geliştirme

```bash
uv venv && uv pip install -e '.[dev]'
make ci        # ruff + pytest (+ JS mantık testleri için node)
```

Sandbox testleri için Docker ve yerelde `python:3.12-slim` imajı gerekir (`docker pull python:3.12-slim`; Usta imajı kendiliğinden çekmez). Yoksa bu testler atlanır. Katkı: [CONTRIBUTING.md](CONTRIBUTING.md).

## Ayrıntılar

### Tek seferlik kullanım ve API sunucusu

```bash
usta run "not.txt dosyasını oku ve özetle" -w ./calisma-alani
usta serve --model qwen3-vl:4b-instruct          # 127.0.0.1:8765; jeton: ~/.usta/token (0600)
```

`usta serve` REST + SSE API'si sunar (`POST /workspaces/{w}/tasks`, `GET /tasks/{t}/events`, onaylar, diff, geri alma, denetim).
Bir çalışma alanında aynı anda tek görev çalışır. Loopback dışında dinlemek için `--allow-remote` gerekir.
Denetim kaydı çalışma alanının dışındadır: `~/.usta/audit/` (`USTA_HOME` ile değişir).

### Sandbox ağı ve web okuma

Varsayılan ağ kapalıdır. Operatör olarak alan adı izni: `usta --allow-host pypi.org --allow-host '*.pythonhosted.org'` (ya da `USTA_ALLOW_HOSTS`).
`fetch_url` ile http/https sayfaları ve PDF'ler (en çok 5 MB / 30 sayfa, metin katmanı) okunur; getirme sandbox içinde, proxy üzerinden yapılır,
izinli olmayan alan adı **onayla** açılır. Sayfa içeriği modele `<<<HARİCİ-İÇERİK ...>>>` işaretleri arasında *veri* olarak verilir.

### Proje hafızası ve oturumlar

`.usta/memory/NOTES.md` (ajanın `remember` ile eklediği notlar) ve son görevler; sonraki görevin başında *veri olarak işaretli* verilir.
Tüm oturum olayları `~/.usta/sessions/` altında kalıcıdır (portalda **Geçmiş**, terminalde `/geçmiş`).

### Ek araçlar: MCP

Hiçbiri varsayılan gelmez; sen eklersin. Sunucular varsayılan olarak **yalıtılmış Docker konteynerinde** çalışır (ağ kapalı, ev dizini ve
Docker soketi yok, salt okunur kök, CPU/RAM/PID sınırlı; çalışma alanı yalnız istersen bağlanır). Docker/imaj yoksa sunucu başlamaz.

```bash
docker pull node:22-slim                              # Usta imajı kendiliğinden çekmez
usta mcp add arama --image node:22-slim --allow-host api.search.brave.com --env BRAVE_API_KEY \
  -- npx -y @brave/brave-search-mcp-server@2.1.4 --transport stdio
usta mcp prepare arama   # paketleri yalnız paket kayıtlarına açık ağda indirir, imajı ve önbelleği sabitler
usta mcp test arama
```

`usta mcp list|enable|disable|remove` de vardır. Sunucuyu ana makinede çalıştırmak (yalıtımsız, senin yetkilerinle) ayrı ve açık bir uyumluluk
modudur: `--isolation host --i-understand-host-risk`. Anahtar değerleri komut geçmişine yazılmaz. Varsayılan olarak her MCP çağrısı onayına
sunulur. Portal yalnız gözden geçirilmiş katalogdan ekler (her zaman konteynerde); serbest komut yalnız CLI'dadır.

### Beceriler

`~/.usta/skills/ad.md` (ilk satır açıklama). Mesajda ya da terminalde `/ad ek metin` yazınca beceri metni + ek metin istem olur. Portaldan `.md` yüklenir.

### Yerel araç çağrısı olmayan modeller

`--protocol json` (şemayla kısıtlı yanıt) ya da `--protocol text` (JSON + ayrı kod blokları). Normalde yetenek sondası en uygununu seçer
(`usta probe`).

## Lisans

Apache-2.0. Bkz. [LICENSE](LICENSE).
