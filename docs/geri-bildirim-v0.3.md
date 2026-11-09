# Kullanıcı geri bildirimi ve v0.3 planı

Tarih: 2026-11-09. Kaynak: yaklaşık 20 kişiden toplanan geri bildirimin ortak özeti (Can aktardı). Bunlar filtrelenmiş notlar: Can gereksiz konuşmaları ayıkladı. Zaten var olan şeyleri isteyen notlar (ör. Docker yalıtımı: v0.2.0'da var) madde sayılmadı. Kişi başına
ayrıntı ve hangi maddeyi kaç kişinin söylediği kayıtlı değil; sıralama sayıya değil, ihtiyacın tekrarına ve
maliyete dayanır. Mobil kullanımın (hareket halindeki kullanıcı) önerisi ayrıca geldi.

## Maddeler, durum ve karar

| # | Geri bildirim | Durum | Karar |
|---|---|---|---|
| 1 | Model düşünmesi açılıp kapatılabilmeli | **Yapıldı** (portal seçicisi, `reasoning_effort`) | Tanımayan uç noktada alan bırakılır, bir kez yeniden denenir. DeepSeek'in kendi anahtarı henüz bağlı değil. |
| 2 | Bağlam (ctx) ayarı | **Yapıldı**: seçici Usta'nın kısaltma eşiğini değiştirir; "Bilgisayarımdaki model" kartı Ollama'da gerçek `num_ctx`'li varyant oluşturur | Ollama `/v1` istekteki `num_ctx`'i yok sayar; varyant `/api/create` ile üst veri katmanı olarak eklenir (gerçek Ollama'da doğrulandı). |
| 3 | Basit ama görsel arayüz | Bekliyor | Madde 8'in sihirbazıyla birlikte. |
| 4 | Zamanla kullanıcıyı tanıma (kişiye özel skill/MCP, otomasyon) | Bekliyor, **önce tasarım** | İlke aşağıda. |
| 5 | Dışarıya veri sızdırmama | **Yapıldı**: portalda "Gizlilik" ekranı, gerçek duruma göre hesaplanır | Telemetri yok; `tests/test_privacy.py` ağ kullanan modülleri izin listesine bağlar, yeni ağ modülü gerekçesiz eklenemez. İstemler seçilen model API'sine gider (ekranda yazar). |
| 6 | Yerel modeli port veya klasörle tanıtma | **Port yapıldı** (yalnız 127.0.0.1; "Bul" ve elle port) | Klasör (GGUF) Ollama'ya eklemeyi gerektirir, ayrı ve büyük; sonraya. |
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

1. v0.3 "herkes için": 1, 2, 6 (port) yapıldı; 5 (gizlilik ekranı) yapıldı; sırada 8 (sihirbaz), üst çubuğu ayarlar sayfasına toplama.
2. Ofis ve profil (7, 4): ayrı sürüm; profil için önce tasarım belgesi, Can onayı.
3. Telefon: dar ekran, PWA, ardından barındırma kararı.

İlke değişmez: bir özellik ancak ölçümde ya da kullanıcı denemesinde faydası görülürse varsayılan olur.
