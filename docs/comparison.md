# Usta ve benzer projeler: dürüst karşılaştırma

Tarih: 2026-11-07. Kaynak: her projenin kendi GitHub deposu ve README'si. **Bu karşılaştırma bağımsız bir
ölçüm değildir:** aşağıda "belgesinde yazıyor" denen şeyleri çalıştırıp doğrulamadım; yalnız Usta için kendi
ölçümlerimiz var (bkz. `docs/v0.2.0-raporu.md`). Yıldız sayıları o günkü değerlerdir ve kalite göstergesi değildir.

## Büyüklük (GitHub, 2026-11-07)

| Proje | Lisans | Yıldız | Dil |
|---|---|---|---|
| opencode (anomalyco) | MIT | ~225 bin | TypeScript |
| Claude Code (anthropics) | belirtilmemiş | ~155 bin | TypeScript |
| Codex (openai) | Apache-2.0 | ~134 bin | Rust |
| OpenHands | MIT | ~93 bin | TypeScript |
| Cline | Apache-2.0 | ~71 bin | TypeScript |
| goose | Apache-2.0 | ~56 bin | Rust |
| Aider | Apache-2.0 | ~50 bin | Python |
| **Usta** | Apache-2.0 | **3** | Python |

Usta bu alanda çok küçük bir projedir. Özellik genişliği, IDE entegrasyonu, topluluk ve cilada bu projelerle
yarışmıyoruz ve yarışıyormuş gibi davranmıyoruz.

## Belgelerinde yazanlar (özet, doğrulanmadı)

| Proje | Belgede öne çıkan |
|---|---|
| Aider | Terminalde eşli programlama; Claude, DeepSeek, OpenAI ve yerel modellerle çalışır; kendisini kıyas ölçütü olarak anıyor |
| OpenHands | Yerelde, Docker'da ya da sanal makinelerde çalıştırma; Docker sandbox seçeneği |
| Cline | İnsan onaylı araç kullanımı; Ollama/LM Studio ile yerel model; MCP; çoklu ajan ekipleri |
| goose | 15+ sağlayıcı (Ollama dahil), MCP üzerinden 70+ eklenti |
| opencode | Bash komutlarından önce izin ister; alt ajanlar |
| Claude Code, Codex | Terminalde çalışan kod ajanları (README'lerinden güvenilir bir özellik özeti çıkaramadım; ayrıntıya girmiyoruz) |

## Usta'nın farklı olduğu yer (kendi ölçümlerimizle desteklenen)

1. **Ölçüm altyapısı ürünün parçası.** `usta bench` (ajanın göremediği gizli testler, başarısızlık sınıflandırması,
   iz kaydı ve tekrar oynatma, eşleştirilmiş kol karşılaştırması, güven aralıkları, altyapı hatası ayrımı) ve
   `usta lab` (24 saldırı/hata senaryosu, eşleştirilmiş temiz/saldırılı koşu, saldırı başarı oranı, yanlış ret).
   Rakiplerin benzer bir dahili güvenilirlik laboratuvarı olup olmadığını bilmiyoruz; yalnız README'lerini anahtar kelimeyle taradık ve böyle bir şeyin öne çıkarıldığını görmedik (bu bir yokluk kanıtı değildir).
2. **Dürüst sonuç ilkesi.** "Özellik ancak ölçümde fayda gösterirse varsayılan olur." 7B'de yeni özelliklerin başarıyı
   artırmadığını yayınladık (v0.2.0 raporu).
3. **Varsayılan yalıtım.** MCP sunucuları yalıtılmış Docker konteynerinde (salt okunur kök, `cap-drop ALL`, ağ yok ya da
   izinli proxy); ana makinede çalıştırma ancak açık bir uyumluluk modudur.
4. **Küçük, bağımlılığı az çekirdek.** Python, saf JS portal; yerel küçük modellerle çalışacak şekilde ölçülüp ayarlanıyor.

## Usta'nın zayıf olduğu yer

- 3 yıldız, tek geliştirici, kullanıcı geri bildirimi çok az.
- IDE eklentisi, masaüstü uygulaması, çoklu oturum/çoklu ajan orkestrasyonu yok.
- 7B yerel modelde bench başarısı düşük ve deneysel özelliklerin faydası kanıtlanmadı; büyük yerel modeller (12B+) ölçülmedi.
- Araç çıktısı/README enjeksiyonuna karşı 7B'de koruma tam değil (bkz. v0.2.0 raporu; `--taint-gate` deneysel).
- Sağlayıcı kapsamı sınırlı test edildi (yerel Ollama ve DeepSeek).

## Piksel ofis görselleştiricileri

Aynı fikrin başka uygulamaları: Claude-Office (MIT, izometrik, çok oturumlu, masaüstü uygulaması), agent-virtual-office
(MIT, çok ajanlı, sahne etkileşimleri), pixtuoid (terminal içi), agent-office (çok ajanlı, sohbet ve görev atama).
Usta'nın **Ofis** sekmesi bunlardan ilham aldı ama kodu/görseli kopyalamadı; bağımlılıksızdır, özgün sprite'lar kodla
çizilir. Farkları: tek ajan odaklıdır (sahte kalabalık yok), her sayaç ve efekt gerçek olaylara bağlıdır, onay doğrudan
ofisten verilebilir, geçmiş oturum zaman çubuğuyla gezilir. Eksikleri: çok oturum yok, ses yok, masaüstü uygulaması yok.

## Sonuç

Usta "daha çok özellik" yarışına girmiyor. İddiası dar: **küçük ve yerel modellerle çalışan, ölçülebilir ve
denetlenebilir bir harness.** Bu iddia ancak ölçümle yaşar; ölçüm gösterdiği sürece yazarız, göstermediğinde de yazarız.
