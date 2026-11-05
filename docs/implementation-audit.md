# v0.2.0 uygulama denetimi (Faz 0)

Bu belge, v0.2.0 geliştirmesine başlamadan önce `v0.1.0` (`7f8f7f2`) durumunun denetimidir. Amaç:
neyin zaten var olduğunu, neyin eksik olduğunu ve neye dokunulacağını kayda geçirmek. Aşağıdaki
sayılar o gün ölçülmüştür; sonraki fazlar bu belgeyi değiştirmez, kendi bölümlerini `CHANGELOG.md` ve
ilgili tasarım belgelerine yazar.

## 1. Baseline

| Ölçüt | Değer |
|---|---|
| Testler | 871 geçti, 0 başarısız (`pytest`, ≈105 sn) |
| Lint | `ruff check` temiz |
| Kaynak | 8,5 bin satır (`src/usta/`, 49 test dosyası) |
| Donanım (ölçümler için) | RTX 3050 Laptop, 4 GB VRAM, 30 GB RAM |
| Yerel modeller | `qwen2.5-coder:7b` (`usta-qc7b-8k`), `qwen3:4b` (`usta-q3-4b-8k`), 2B; 14B yok |
| Docker | `python:3.12-slim` yerelde; Node imajı yok |

Önceki bench sonuçları (README'deki tablo): 4B A 1/15 · B 0/15 · C 1/15; 7B B 0/30 · D 1/30; DeepSeek
A 30/30 · B 23/23 (7 altyapı) · C 29/30 · D 30/30. Bu sonuçlar harness'ın küçük modelde başarıyı
artırdığını göstermiyor; v0.2.0 de bunu iddia etmemelidir.

## 2. Mevcut yetenekler (yeniden yazılmayacak)

| Alan | Durum | Yer |
|---|---|---|
| Docker sandbox | var: `--network none`, `--read-only`, `--cap-drop ALL`, `no-new-privileges`, pid/bellek/cpu sınırı, `.git`/`.usta` salt okunur | `sandbox.py` |
| Allowlist proxy ağı | var: `--internal` ağ + proxy konteyneri, karar günlüğü | `sandbox.py`, `proxy.py` |
| İzin motoru | var: dosya araçları, `run`, `fetch_url`, `mcp__*` (sunucu başına `ask`/`allow`, bilinmeyen `deny`) | `policy.py` |
| Denetim kaydı | var, çalışma alanı dışında, sır maskeli | `audit.py` |
| Doğrulama kapısı | var (unittest tabanlı, sandbox'ta) | `verify.py` |
| Devre kesici | var (aynı hata imzası, A→B→A salınımı, aynı çağrı ×3; geri sarma) | `breaker.py` |
| Araç protokolleri | native / JSON / metin + yetenek sondası (3 sorgu) + önbellek | `jsonproto.py`, `textproto.py`, `profile.py` |
| Plan ve aşamalı uygulama | var | `tasks.py` |
| Bağlam yönetimi | var: araç çıktısı bütçesi, sıkıştırma, Python `ast` outline, `read_symbol`; diğer diller için regex | `context.py`, `outline.py` |
| MCP istemcisi | var (stdio), sonuç/ad/şema temizliği, nonce'lu işaretleme | `mcp.py`, `mcp_tools.py`, `mcpconfig.py` |
| Bench | var: 4 kol, gizli testler, Wilson aralığı, altyapı ayrımı, 15 görev | `bench.py`, `bench_tasks/` |
| CLI, REST+SSE, portal | var | `cli.py`, `api.py`, `web/` |

## 3. Boşluklar (v0.2.0 işi)

### 3.1 MCP yürütme izolasyonu (P0)

`McpClient.start()` sunucuyu `subprocess.Popen` ile **ana makinede, kullanıcının yetkileriyle** başlatır:

- Ortam: `BASE_ENV = PATH, HOME, LANG, LC_ALL, TMPDIR, USER` + sunucunun tanımlı `env` adları.
  `HOME` ana makineninkidir; sunucu `~/.ssh`, `~/.usta/token`, `~/.usta/apis.json` dosyalarını okuyabilir.
- Dosya sistemi, ağ, CPU/RAM/PID sınırı yok. Yalnız satır boyutu, sonuç boyutu ve zaman sınırı var.
- Süreç grubu kapanışta öldürülür (iyi), ancak sunucu kapsayıcıda olmadığı için kaçan alt süreçler tamamen
  kapsanamaz.
- Katalogdaki komut sürümü sabit (`@brave/brave-search-mcp-server@2.1.4`) ama `npx -y` her çalıştırmada
  paketi ve bağımlılıklarını indirir; kilit dosyası ve bütünlük (integrity) denetimi yok.
- Sandbox imajında (`python:3.12-slim`) Node yok, yani mevcut katalog sunucusu kapsayıcıda çalışamaz.

Korunan iyi yanlar: ad/açıklama/şema temizleme, sonucun nonce'lu veri işaretiyle sarılması, sunucu
isteklerinin (sampling vb.) reddi, izin motorunun merkezi otorite olması. Bunlar korunacak.

### 3.2 Reliability Lab (P0)

Yok. Hiçbir saldırı/enjeksiyon senaryosu, eşleştirilmiş temiz/saldırılı koşu, araç eylemi izi, deterministik
değerlendirici veya ASR/yetkisiz-yürütme metriği bulunmuyor. Güvenlik testleri birim testlerdir; ajan
döngüsü uçtan uca enjeksiyonla ölçülmüyor.

### 3.3 Bench teşhisi (P0)

`TaskResult` sonuç ve sayaçları tutar; **neden** başarısız olduğunu (araç argüman hatası, yanlış dosya,
tekrar eden yaklaşım, bağlam doluşu, model hatası, altyapı) ayırmaz. Eksikler: başarısızlık sınıflandırması,
adım bazlı olay izi, tekrar oynatma, eşleştirilmiş kol karşılaştırması, geliştirme/nihai görev ayrımı,
görev başına onarım denemesi sayısı. Altyapı hataları ayrı sayılıyor (iyi) ama toplam koşu içindeki oranı
raporlanmıyor.

### 3.4 Sembol/bağlam (P1)

Python için `ast`; diğer diller için tek satırlı regex özeti (iç içe sınıf/metot yok, kapanış satırı
tahmini). Çok dilli ayrıştırma, import/çağrı ilişkisi, sembol indeksi ve görev bazlı seçim yok.

### 3.5 Yetenek profili (P1)

Sonda üç sorgudur (read_file, run, write_file) ve tek bir protokol seçer. Çoklu araç çağrısı, bozuk JSON
toparlama, uzun bağlam ve hata sonrası toparlanma ölçülmüyor; profil model revizyonuna bağlı değil.

### 3.6 Yürütme aşamaları (P1)

DISCOVER/PLAN/EDIT/VERIFY/DIAGNOSE/REPAIR aşamaları açıkça modellenmiyor; olaylar (`tool_call`,
`verification`, `breaker`) var ama aşama etiketi ve aşama başına bütçe yok. Doğrulama ortamı eksikliği
(bağımlılık yok) ile kod hatası ayrımı yapılmıyor.

### 3.7 Tedarik zinciri ve sır sızıntısı (P1)

- Docker imajları etiketle (`python:3.12-slim`) çağrılıyor, digest ile sabitlenmiyor.
- Python bağımlılıkları `pyproject.toml` aralıklarıyla; kilitli ortam yok (CI'da `pip-audit` var).
- Hafıza kaydının kaynağı/görevi kayıtlı değil; hafıza zehirleme için uçtan uca test yok.
- Log/bench raporu/hata çıktısı/istem sızıntısı için merkezi bir test yok (parça parça maskeleme var).

### 3.8 Gözlemlenebilirlik (P1)

Run kaydı şeması, hata kategorisi, güvenlik denemesi sayacı ve sürümler arası regresyon raporu yok.

## 4. Dokunulacak modüller ve riskler

| Faz | Yeni | Değişen | Regresyon riski |
|---|---|---|---|
| 1 MCP | `mcp_runtime.py` | `mcp_tools.py`, `mcpconfig.py`, `cli.py` (mcp add/test), `tasks.py` | Mevcut host yürütmeli kullanıcıların akışı; varsayılan davranış bilinçli değişecek (izole varsayılan) |
| 2 Lab | `lab/` | `cli.py` (alt komut) | Ajan döngüsüne dokunulmaz (yalnız gözlem) |
| 3 Bench | `benchdiag.py` | `bench.py`, `cli.py` | Mevcut rapor biçimi geriye uyumlu kalmalı |
| 4 Profil/bağlam | `symbols.py` | `profile.py`, `outline.py`, `tools.py` | Yanlış bağlam seçimi; varsayılan kapalı |
| 5 Aşamalar | `phases.py` | `agent.py`, `verify.py`, `breaker.py` | Döngü davranışı; yalnız gözlem + flag |
| 6 Sürüm | — | belgeler | — |

Kurallar: her faz ayrı commit(ler); testler aynı fazda; deneysel şeyler flag arkasında; başarısız
sonuçlar raporlanır; model gerektirmeyen CI testleri ile model gerektiren ölçümler ayrıdır.
ORDIS ile entegrasyon yoktur.
