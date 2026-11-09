# Kullanıcı geri bildirimi ve v0.3 planı

Tarih: 2026-11-09. Kaynak: yaklaşık 20 kişiden toplanan geri bildirimin ortak özeti (Can aktardı). Kişi başına
ayrıntı ve hangi maddeyi kaç kişinin söylediği kayıtlı değil; sıralama sayıya değil, ihtiyacın tekrarına ve
maliyete dayanır. Mobil kullanımın (hareket halindeki kullanıcı) önerisi ayrıca geldi.

## Maddeler, durum ve karar

| # | Geri bildirim | Durum | Karar |
|---|---|---|---|
| 1 | Model düşünmesi açılıp kapatılabilmeli | **Yapıldı** (portal seçicisi, `reasoning_effort`) | Tanımayan uç noktada alan bırakılır, bir kez yeniden denenir. DeepSeek'in kendi anahtarı henüz bağlı değil. |
| 2 | Bağlam (ctx) ayarı | **Kısmen**: seçici var, Usta'nın kısaltma eşiğini değiştirir | Ollama `/v1` istekteki `num_ctx`'i yok sayar; gerçek pencere için model varyantı (`/api/create`) gerekir, madde 6 ile yapılacak. Arayüz bunu açıkça söylemeli. |
| 3 | Basit ama görsel arayüz | Bekliyor | Madde 8'in sihirbazıyla birlikte. |
| 4 | Zamanla kullanıcıyı tanıma (kişiye özel skill/MCP, otomasyon) | Bekliyor, **önce tasarım** | İlke aşağıda. |
| 5 | Dışarıya veri sızdırmama | Telemetri kodu yok; istemler seçilen model API'sine gider | "Veri nereye gider" ekranı; yerel modelde dışarı hiçbir şey çıkmadığı belgelenir. |
| 6 | Yerel modeli port veya klasörle tanıtma | Bekliyor | Port önce. Klasör (GGUF) Ollama'ya eklemeyi gerektirir, ayrı ve büyük. |
| 7 | Ofis ortamı çok beğenildi, geliştirilmeli | Bekliyor | Çok ajan ve paralel görev görünümü. Sahte kalabalık yok: her şey gerçek olaya bağlı kalır. |
| 8 | Hiç kod bilmeyen biri kullanabilmeli | Bekliyor | İlk açılış sihirbazı, sade Türkçe, tek komutla kurulum. En çok tekrar eden ihtiyaç olarak ele alınır. |
| – | Telefon / tablet | Bekliyor | Bulut/API yolu. Önce dar ekran düzeltmesi ve PWA; barındırma kararı ayrı. |

## Kişiselleştirme ilkesi (madde 4, Can ile kararlaştırıldı)

Hedef: Hermes gibi zamanla kullanıcıya özel skill, MCP ve otomasyon üretmek, ama **veri cihazda kalır**.

- Profil yalnız kullanıcının cihazında, düz dosyada tutulur; kullanıcı okuyabilir, düzenleyebilir, siler.
- **Varsayılan kapalı.** Kullanıcı açar. Sessizce öğrenme yok.
- Üretilen skill ve MCP'ler de yerel dosyadır; yürütme mevcut izin ve yalıtım kurallarına tabidir.
- Profil hiçbir koşulda model API'sine ham olarak gönderilmez; gönderilen şey kullanıcının görebildiği istemdir.

## Sıra

1. v0.3 "herkes için": 1, 2 (kalanı), 6 (port), 5 (ekran), 8 (sihirbaz).
2. Ofis ve profil (7, 4): ayrı sürüm; profil için önce tasarım belgesi, Can onayı.
3. Telefon: dar ekran, PWA, ardından barındırma kararı.

İlke değişmez: bir özellik ancak ölçümde ya da kullanıcı denemesinde faydası görülürse varsayılan olur.
