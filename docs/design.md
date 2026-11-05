# Usta — Tasarım Taslağı (v0.1, 26 Eki 2026)

Genel amaçlı, açık kaynak (Apache-2.0) bir yapay zekâ ajanı: sohbet + görev, proje çalışma alanı, yalıtılmış sandbox, model bağımsız.

## 1. İlkeler
- **YAGNI:** önce tek kullanıcılı, tek makine; çoklu kullanıcı/rol iskeleti var ama sade.
- **Varsayılan güvenli:** ağ kapalı, sır yok, yazma yalnız çalışma alanında.
- **Model bağımsız:** yalnız "OpenAI-uyumlu chat/completions + tool calling" arayüzü.
- **ORDIS'ten bağımsız:** ORDIS ileride yalnızca dar API'li bir istemci olur (şimdi yok).

## 2. Mimari
```
 CLI (usta) ─┐                       ┌─ Model uç noktası (OpenAI-uyumlu)
 Web UI (SSE)┼─► API (FastAPI) ─► Ajan döngüsü ─┤
             │        │                └─ Araç kaydı ─► Sandbox (Docker, çalışma alanı başına)
             │        ├─ İzin motoru + denetim kaydı
             │        └─ Depo: SQLite (oturum, görev, hafıza, denetim)
```
Bileşenler:
- **API (FastAPI):** REST + SSE akışı. Görevler arka planda asyncio görevi olarak koşar; durdurma = iptal + konteyner komutunu öldürme.
- **Ajan döngüsü:** mesajlar → model → araç çağrıları → izin kontrolü → sandbox → sonuç → tekrar. Adım ve token bütçesi sınırlı.
- **Araçlar (v0):** `read_file`, `write_file`, `edit_file`, `list_dir`, `run` (komut/kod), `web_search`, `fetch_url` (link/PDF→metin). Ek araçlar: MCP istemcisi ve Python eklenti arayüzü (v0.3).
- **Çalışma alanı:** `~/.usta/workspaces/<id>/` dizini + bir konteyner. Proje hafızası (`NOTES.md` + SQLite görev geçmişi) çalışma alanında durur.
- **Depo:** SQLite (tek dosya, bağımlılık yok).
- **İstemciler:** CLI (tek bağımlılık: `httpx`/`rich` isteğe bağlı), web arayüzü (düz HTML/JS, derleme adımı yok).

## 3. Sandbox yaklaşımı
- Çalışma alanı başına bir Docker konteyneri; çalışma dizini bind-mount (yalnız o alan).
- `--network none` varsayılan. Alan adı izni verilirse (`--allow-host`, operatör kararı) sandbox `--internal` bir ağa girer; dışarı yalnız ağdaki **allowlist proxy** konteyneri çıkar (`src/usta/proxy.py`, stdlib). Çıkış için başka yol yoktur (doğrudan IP bağlantısı çalışmaz).
  - Proxy: HTTPS için `CONNECT`, düz HTTP için yalnız GET/HEAD/OPTIONS; yalnız izinli portlar (80/443); IP literal hedefler ve özel/yerel/link-local adreslere çözülen alan adları reddedilir; bağlantı çözülen IP'ye yapılır (DNS rebinding'e karşı). Karar günlüğü yalnız {yöntem, host, port, karar} tutar; yol/sorgu/gövde kaydedilmez.
  - Sınırlar (bilinçli): HTTPS içeriği opaktır; izinli bir alan adına HTTPS ile veri gönderilebilir (sızdırma kanalı = izin listesine güvenilen alan adları). Bu yüzden liste kısa tutulur ve operatör seçer; model/ajan listeyi değiştiremez. Joker (`*.alan.adı`) kök alanı kapsamaz.
  - Komut başına geçici ağ+proxy açılır ve çıkışta silinir; çökme artıkları `usta serve` başlangıcında (sahibi ölmüş `usta.managed` kaynaklar) temizlenir. İmajlar asla otomatik çekilmez (`--pull never`).
- `--read-only` kök, `--cap-drop ALL`, `no-new-privileges`, root olmayan kullanıcı, CPU/bellek/pids/süre sınırları, seccomp varsayılan profil.
- Ortama sır geçirilmez; model anahtarı yalnız API sürecinde kalır, konteynere girmez.
- Sonraki aşama: gVisor/Firecracker seçeneği (v1+).

## 4. İzin sistemi ve denetim
| Eylem | Politika |
|---|---|
| Çalışma alanında okuma | serbest |
| Çalışma alanında yazma/komut (sandbox içi) | serbest, denetim kaydı |
| Çalışma alanı dışı yol | reddedilir (yol normalizasyonu + symlink çözümü) |
| Ağ (izinli alan adı) | serbest; diğerleri **onay ister** |
| Dış dünyaya yazma (POST, e-posta, push vb.) | her seferinde onay |
- Değişiklikler **diff/yama** olarak sunulur; uygula/geri al (çalışma alanı git deposu).
- Denetim kaydı: eklemeli JSONL + SQLite (kim, ne, hangi argüman, karar, sonuç özeti). Sır desenleri maskelenir.
- Onay akışı: API `approval_required` olayı yollar; istemci `POST /approvals/{id}`.

## 5. Tehdit modeli (özet)
| Tehdit | Önlem |
|---|---|
| Prompt injection (web/PDF/dosya içeriği) | Dış içerik "veri" etiketiyle verilir (nonce'lu işaretler); dış dünya eylemleri onaylı; sandbox ağı kapalı. **Kalan sızdırma kanalları (bilinçli, belgeli):** izinli alan adlarına HTTPS; kullanıcının eklediği MCP araçları (oto onayda sorulmaz); önizlemede ajanın yazdığı sayfanın kendi kendine yönlenmesi (CSP bunu engelleyemez); modelin kendi uç noktası (istem ve dosya içerikleri o API'ye gider) |
| Sandbox kaçışı | düşürülmüş yetenekler, root dışı, kaynak sınırı; Docker soketi asla bağlanmaz |
| Sır sızıntısı | konteynerde sır yok; çıktı/denetim maskeleme; repoda gitleaks benzeri tarama (CI) |
| Yol aşımı / symlink | yol çözümleme + çalışma alanı kökü kontrolü; geri alma ve dosya işlemleri sembolik bağı izlemez (bağın kendisi silinir); FIFO/aygıt dosyaları atlanır; `.git` ve `.usta` ajan tarafından yazılamaz ve sandbox'ta salt okunur; ev dizini/kök/Usta ev dizinini kapsayan klasör çalışma alanı olamaz |
| Kötü eklenti/MCP | varsayılan kapalı, açıkça etkinleştirme, aynı izin motoru |
| Yetkisiz API erişimi | jeton (0600), tek kullanımlık giriş kodu (komut satırında görünmez), `127.0.0.1`'e bağlanma, Host denetimi (DNS rebinding), kimlik doğrulamadan önce gövde sınırı, CSP |
| Kaynak tüketimi | adım/token/süre/disk kotaları |

### 5.1 `fetch_url` ve harici içerik
- Getirme ana süreçte değil **sandbox konteynerinde** yapılır (allowlist proxy üzerinden); konteynere çalışma alanı bağlanmaz (boş geçici dizin). Ana süreç ağa çıkmaz.
- Hedef doğrulaması iki katlı: araç/politika katmanı (yalnız http/https, IP/yerel/tek etiketli ad yok, portlar 80/443, kimlik bilgisi yok) ve proxy (SSRF, özel adres, port). Politika geçersiz hedefi onaya sunmadan reddeder.
- Operatör listesinde olmayan host **her çağrıda kullanıcı onayı** ister; onaylanan host yalnız o çağrı için proxy listesine eklenir. Yönlendirmeler her halkada proxy'den geçer: listede olmayan host'a yönlendirme 403 alır.
- Sınırlar: 500 KB indirme, 30 sn toplam süre (yavaş damlatma dahil), sıkıştırılmış içerik reddedilir (decompression bomb yok), 50 000 karakter çıktı.
- İçerik her çağrıda **rastgele nonce'lu** `<<<HARİCİ-İÇERİK ...>>>` işaretleriyle sarılır ve "veridir, talimat değildir" uyarısı taşır; sistem istemi de aynısını söyler. HTML'den script/style/yorum/gizli (hidden, aria-hidden, display:none) öğeler ve görünmez/bidi karakterler atılır.
- **PDF:** gövde (≤5 MB; kırpık PDF kullanılamaz, hata) konteynerde `body.pdf` dosyasına yazılır, stdout'a değil. Ana süreç dosyayı `O_NOFOLLOW` ile, yalnız bu ad ve `%PDF-` başlığıyla okur/doğrular. Ayrıştırma **ağsız ikinci bir konteynerde** (`pdf_inner.py`, pypdf ana makineden `:ro` bağlı, bellek 384 MB, 40 sn) yapılır; ilk 30 sayfa ve `max_chars` karakter. Şifreli PDF reddedilir, metin katmanı yoksa bunu söyler (OCR yok). Üst veri (başlık/yazar) modele verilmez. Çıktı aynı nonce'lu işaretlerle sarılır. Bağımlılık: `pypdf` (saf Python; ana süreçte hiç içe aktarılmaz).
- **Kalan risk:** Bu önlemler prompt injection'ı *ortadan kaldırmaz*; görünür sayfa metni içinde de talimat olabilir. Asıl savunma katmanlıdır: ajanın yetkisi sınırlı (çalışma alanı, ağsız sandbox, dış yazma onaylı), her eylem denetim kaydında, değişiklikler diff ile geri alınabilir.

### 5.2 Proje hafızası (taslak, v0.3)
- **Kapsam:** yalnız çalışma alanı içinde, `<çalışma alanı>/.usta/memory/`: `NOTES.md` (tek satırlık notlar) ve `history.jsonl` (görev başına tek kayıt: zaman, görev kimliği, durum, kısaltılmış istem ve yanıt). Genel/ortak hafıza yok; başka çalışma alanına sızmaz. Anlık görüntü/diff `.usta/` dizinini görmez.
- **Yazma:** `remember(text)` aracı (≤500 karakter, tek satır, toplam ≤32 KB) ve `TaskManager` görev bitince geçmiş kaydı ekler (son 200 tutulur). Not metninden denetim/bidi karakterleri atılır.
- **Okuma:** görev başında son 8000 karakter not + son 5 görev, nonce'lu `<<<PROJE-HAFIZASI ...>>>` işaretleriyle **kullanıcı mesajına** eklenir (sistem rolüne değil): veridir, talimat değildir.
- **Tehdit:** (1) ajan web içeriğinden etkilenip kalıcı bir yanlış/kötü niyetli not yazabilir (kalıcı prompt injection); (2) sandbox'taki `run` bu dosyaları doğrudan değiştirebilir. Bu yüzden içerik her okunduğunda güvenilmeyen veri sayılır, boyutu sınırlıdır ve karakterleri yeniden temizlenir; `.usta` veya `memory` sembolik bağ/dosya ise hafıza devre dışı kalır (hata görevi durdurmaz). Notlar düz metindir, kullanıcı `NOTES.md`'yi elle okuyup temizleyebilir. Henüz yok: notları API/arayüzde gösterme, silme, arama; görev geçmişinin SQLite'a taşınması.

### 5.3 MCP istemcisi ve MCP Runtime (v0.3; izolasyon v0.2.0)
Amaç: arama, takvim, veritabanı gibi araçları Usta'ya sonradan, kod yazmadan eklemek. Kullanıcı kolaylığı ve güvenlik birlikte tasarlanır.

**Kullanıcı deneyimi (hiç bilmeyen kullanıcı için):**
- `usta mcp add <ad> -- <komut ...>` ile ekleme; `usta mcp list|remove|test <ad>`. `test` sunucuyu başlatıp araç listesini gösterir. Web arayüzünde "Araçlar" bölümü sonraki adım.
- Ekleme sırasında ne çalışacağı açıkça gösterilir ve onay istenir ("bu komut bilgisayarında senin yetkilerinle çalışır"). Anahtar gerekiyorsa `--env ANAHTAR` ile adı verilir, değeri ekranda gizli sorulur (komut geçmişine ve yapılandırma dosyasına yazılmaz).
- Hata mesajları ne yapılacağını söyler (komut bulunamadı, sunucu yanıt vermedi, ...).

**Güvenlik:**
- Varsayılan kapalı: yalnız kullanıcının `usta mcp add` ile eklediği sunucular başlar; yapılandırma `~/.usta/mcp.json` (0600) çalışma alanının dışındadır, ajan değiştiremez.
- Taşıma: stdio. **MCP Runtime (`mcp_runtime.py`):** sunucu varsayılan olarak `docker run -i` ile yalıtılmış konteynerde başlar (salt okunur kök, root olmayan kullanıcı, `cap_drop=ALL`, `no-new-privileges`, `--init`, CPU/RAM/PID sınırı, `tmpfs`, ağ kapalı; ev dizini/Docker soketi/ana makine ortamı yok; çalışma alanı yalnız `none|ro|rw` ile açıkça). Ağ gereken sunucuda mevcut allowlist proxy (`ProxyNetwork`) yeniden kullanılır; engellenen/izinli ağ kararları denetim kaydına `mcp_network` olarak girer. Sırlar komut satırına değil, docker istemci ortamına yazılır (`-e ADI`). İzolasyon kurulamazsa (Docker yok, imaj yok, sabitleme tutmuyor) sunucu başlamaz ve `mcp_blocked` kaydı düşer; ana makineye geri düşülmez. `--isolation host --i-understand-host-risk` ayrı, açık bir uyumluluk modudur (her başlatmada uyarı).
- Paket sabitleme: `usta mcp prepare` komutu ağ allowlist'i (yalnız npm/PyPI kayıtları, kurulum betikleri kapalı) altında bir kez çalıştırıp paketleri `~/.usta/mcp-cache/<ad>/` önbelleğine indirir; çalışma anında önbellek `:ro` bağlanır, ağ kapalıdır. Yerel imaj kimliği ve önbellek içerik özeti `mcp.json`'a yazılır ve her başlatmada doğrulanır (tutmuyorsa başlatma reddedilir).
- Her MCP aracı politikada varsayılan **ASK** (her çağrıda onay); kullanıcı sunucu bazında `--approve allow` diyebilir. Bilinmeyen `mcp__` aracı DENY.
- Araç adı `mcp__<sunucu>__<araç>` (yerel araçlarla çakışamaz); açıklama ve şema sunucudan geldiği için **güvenilmez**: açıklama kısaltılır ve temizlenir, aşırı büyük şema genel bir şemayla değiştirilir.
- Sonuç her zaman nonce'lu `<<<HARİCİ-İÇERİK ...>>>` içinde VERİ olarak verilir; boyut ve süre sınırlıdır.
- Sunucu istemciden istek yapamaz (sampling/roots/elicitation reddedilir); stderr sınırlı tutulur, yanıtsız sunucu zaman aşımıyla sonlandırılır, görev bitince süreç kapatılır.
- Kalan risk: Docker erişimi kök yetkisi demektir; konteyner çekirdeği paylaşır; izinli alan adlarına HTTPS içeriği opaktır; host uyumluluk modu yalıtımsızdır. Plan modunda MCP sunucuları hiç başlatılmaz. Olumsuz testler `tests/test_mcp_runtime.py` (canary dosyalar, sahte sırlar, ağ, salt okunur kök, zaman aşımı/artık süreç temizliği, kapalı başarısızlık).

### 5.4 Terminal deneyimi, kalıcı oturumlar ve alt ajanlar (taslak, v0.3-0.4)
**Referanslar (fikir olarak; kaynaklar ikinci el, resmi depolar doğrudan incelenmedi, kod alınmaz):** Hermes Agent (Nous Research, MIT) ve DeepSeek-TUI (MIT): Plan/Agent/YOLO modları, SQLite+FTS5 oturum araması, beceriler → `/komut`, sınırlı sayıda izole alt ajan, yürütme ortamının ajan döngüsünden ayrılması.

- **Tek yönetici:** terminal (`usta`) ve portal aynı `TaskManager`'ı kullanır. Terminalde başlayan görev portalda canlı izlenir; onay, diff, geri alma ve meşgul kilidi ortaktır.
- **Modlar:** `manual` (her ASK sorulur), `auto` (ASK otomatik onaylanır ve kaydedilir; DENY ve sandbox kuralları aynen geçerli), `plan` (yalnız okuma araçları, plan sunar; onaylanınca `manual`/`auto` ile uygulanır).
- **Kalıcı oturumlar:** `~/.usta/usta.db` (SQLite, çalışma alanı DIŞINDA; sandbox'taki komutlar değiştiremez): oturum, görev, olay; FTS5 ile arama; `/geçmiş`, `/devam`. Eski konuşmalar yalnız veri olarak gösterilir/modele özet olarak verilir (güvenilmeyen).
- **Alt ajanlar + ortak hafıza:** araçlar `spawn_agent`, `list_agents`, `agent_result`, `send_message`. Kurallar: derinlik 1 (alt ajan alt ajan başlatamaz), en çok 3 eşzamanlı, token/adım bütçesi üstten miras; alt ajan üst ajandan GENİŞ yetki alamaz (aynı politika, onaylar kullanıcıya iletilir); paralel çalışanlar salt okunur (plan modu), yazan alt ajan üstün işini bekleterek tek başına çalışır. Ortak hafıza: çalışma alanı notları + `.usta/memory/board.jsonl` (ajanların bulgu bıraktığı pano); hepsi güvenilmeyen veri olarak işaretli okunur.
- **Beceriler:** `~/.usta/skills/<ad>.md` (kullanıcı yazar) → `/ad` komutu. Serbest kod çalıştırmaz, yalnız istem şablonudur.

### 5.5 Küçük modelleri güvenilir kılma: dört sütun (topluluk geri bildirimi + ölçümler)
Zekâyı modelden alıp deterministik kurallara harness'a yıkma ilkesi. Her madde ancak `usta bench` ile faydası görülünce varsayılan olur.

| # | Sütun | Durum | Ölçüm/gerekçe |
|---|---|---|---|
| 1 | **Cimri bağlam:** ham dosya yerine AST/sembol özeti, satır aralığı okuma, araç çıktısı bütçesi, pencere dolarken sıkıştırma | **var:** `outline`, `read_symbol`, `read_file` satır aralığı, pencereye göre çıktı bütçesi ve eski sonuçları/yazma içeriklerini özetleyen sıkıştırma (`context.py`). Python için `ast`, diğer diller için genel (satır tabanlı) özet; Tree-sitter/LSP yok | 8K bağlamlı yerel modellerde bağlam hızla doluyordu |
| 2 | **Kısıtlı araç çağrısı:** şema/GBNF ile çıktı kilidi; modele göre otomatik seçim | **var:** `json` protokolü (`response_format` json_schema: kod/tırnak kaçışı sunucuda garanti), içerikte JSON kurtarma, metin protokolü; sonda native→json→text seçer. GBNF ve diff biçimi yok | qwen2.5-coder:7b: native 3/3 (hepsi kurtarılarak), json 3/3, text 1/3 |
| 3 | **Deterministik doğrulama:** her değişiklik sandbox'ta test/derleyiciden; yalnız `exit 0` ilerletir; kırpılmış hata geri beslenir | **kısmen var:** sözdizimi geri bildirimi + bitirme kapısı; projeye özel komut/imaj (`usta verify`, çalışma alanı dışında saklanır). Linter ve çok dilli otomatik keşif yok (sandbox imajında yalnız Python) | 4B'de başarıyı artırmadı, ≈3,5x maliyet; orta bantta ölçülüyor |
| 4 | **Durum makinesi + devre kesici:** aynı hata/yaklaşım tekrarında kes, temiz duruma dön, farklı yaklaşım zorla ya da kullanıcıya bırak | **var:** `breaker.py` (aynı hata, A→B→A salınımı, aynı çağrı), kontrol noktasına geri sarma, "denenenler" listesi, `max_trips` sonrası kullanıcıya devir. Açık DAG/durum makinesi yok (akış hâlâ model güdümlü) | birim ve bütünleşik testli; bench D kolu |

Koruma (doğrulama kapısı + devre kesici) varsayılan **kapalı**; `/koruma aç`, `--guard` ya da portaldaki kutu ile açılır. Ölçümle faydası görülünce varsayılan olur.

Kalan işler: Tree-sitter ile çok dilli `outline`; GBNF ve diff/arama-değiştir biçimleri; linter ve dil algılamalı doğrulayıcı (özel sandbox imajı ile); keşfet→düzenle→doğrula durum makinesi.

## 6. API taslağı (v0)
```
POST /workspaces                      {name}                 → workspace
POST /workspaces/{w}/tasks            {prompt, model?}       → task
GET  /tasks/{t}/events                (SSE: token, tool_call, tool_result, approval_required, done)
POST /tasks/{t}/cancel
POST /approvals/{id}                  {decision: allow|deny}
GET  /workspaces/{w}/files?path=      GET/PUT dosya (yalnız çalışma alanı içi)
GET  /tasks/{t}/diff
GET  /audit?workspace=
```
Kimlik: `Authorization: Bearer <jeton>`; jeton = rol (`admin|user|readonly`) + kapsam (çalışma alanı). İlk yönetici jetonu kurulumda yerel dosyaya yazılır (0600), repoya girmez.

## 7. Model katmanı
`ModelClient` arayüzü: `chat(messages, tools, stream) → olaylar`. Tek uygulama: OpenAI-uyumlu HTTP (Ollama, llama.cpp, vLLM, bulut). Uç nokta/model adı yapılandırmadan gelir. Araç çağrısı desteklemeyen küçük modeller için JSON-metin yedek protokolü (v0.2).
**Açık soru (Can):** geliştirme modeli hangisi? (4 GB GPU: ~3–4B yerel, ya da ağdan uç nokta.)

## 8. Depo yapısı
```
usta/ (src/usta/{api,agent,tools,sandbox,policy,store,models,cli}), web/, tests/, docs/, docker/
LICENSE (Apache-2.0), README.md, CONTRIBUTING.md, SECURITY.md, pyproject.toml
```
Bağımlılıklar: fastapi, uvicorn, httpx, pydantic; test: pytest. Yerel CI = `make ci` (ruff + pytest + gizli tarama).

## 9. Yol haritası
- **v0.0 İskelet:** yapı, lisans, README, yerel CI, sandbox prototipi (tek komut, ağsız, çıktı), testler.
- **v0.1:** ajan döngüsü + dosya/komut araçları + izin motoru + denetim + CLI.
- **v0.2 (tamam):** API + SSE + web arayüzü, arka plan görevleri/durdurma, diff/yama, JSON-metin yedek protokolü, allowlist proxy.
- **v0.3:** `fetch_url` (tamam), PDF okuma (tamam), `web_search`, proje hafızası (taslak tamam: notlar + görev geçmişi, bkz. §5.2), MCP istemcisi (stdio tamam: `usta mcp ...`, bkz. §5.3; web arayüzünde yönetim ve uzak/HTTP taşıma sonra), eklenti araçları.
- **v0.4:** roller/kapsamlı jetonlar, ORDIS için dar istemci API'si (Can istediğinde).
- **v1.0:** sertleştirme, belgeler, açık kaynak yayını (Can onayıyla).

## 10. Ad kontrolü (26 Eki 2026)
- PyPI `usta`: **boş** (404). `atolye`, `usta-agent`: boş.
- npm `usta`: dolu (2022'den kalma, ilgisiz Node küme aracı, 0.0.4). `atolye`, `usta-agent` boş.
- GitHub `usta` kullanıcısı dolu (2009, kişisel hesap) → `github.com/usta/usta` olmaz. `usta-ai`, `usta-agent`, `usta-dev` kullanıcı/org adları boş.
- GitHub'da "usta agent" adlı belirgin bir rakip proje yok (arama: ilgisiz, 0 yıldız).
- Öneri: PyPI paketi `usta`, GitHub org `usta-ai` (alınmadan önce Can'a sorulur; hesap/org açmak onay ister).


## v0.2.0 eklemeleri (güvenilirlik ve ölçüm)

Ayrıntılı denetim ve boşluk analizi: [implementation-audit.md](implementation-audit.md). Sonuçlar ve maliyetler: [v0.2.0-raporu.md](v0.2.0-raporu.md).

- **MCP Runtime** (`mcp_runtime.py`, §5.3): MCP sunucuları varsayılan olarak yalıtılmış konteynerde; `prepare` ile paket/imaj sabitleme.
- **Reliability Lab** (`lab/`, [reliability-lab.md](reliability-lab.md)): eşleştirilmiş temiz/saldırılı koşular, araç eylemi izi, deterministik değerlendirici, metrik motoru.
- **Bench teşhisi** (`taxonomy.py`, `bench.py`): başarısızlık sınıflandırması, adım izi, modelsiz tekrar oynatma, eşleştirilmiş kol karşılaştırması, train/dev/final bölümleri.
- **Yetenek profili** (`capability.py`): protokol başına sondalar (uçtan uca ajan görevleri dahil); uç nokta + model revizyonu + yapılandırma ile anahtarlı.
- **Sembol araçları** (`symbols.py`, deneysel): Tree-sitter ile çok dilli semboller, stat tabanlı güncel indeks, bütçeli bağlam; yoksa regex/AST'ye düşer.
- **Yürütme aşamaları** (`phases.py`): durum makinesi gözlemcisi ve terminal durumlar; ajan döngüsünü değiştirmez (onarım bütçesi `enforce` deneysel).
- **Doğrulama ortamı ayrımı** (`verify.env_problem`): eksik bağımlılık kod hatası sayılmaz; kapı onarım turu yakmaz, bench'te altyapı hatası sayılır.
- **Hafıza zehirleme azaltımı** (`memory.suspicious`, `policy.py`): kaynak izi + şüpheli not onayı.
- **Tedarik zinciri**: hash'li kilit dosyaları, sandbox imaj sabitleme.

İlke: yeni yetenekler varsayılan kapalıdır ya da yalnız gözlem yapar; varsayılan olması için `usta bench`/`usta lab` ile fayda ve maliyetin birlikte gösterilmesi gerekir.
