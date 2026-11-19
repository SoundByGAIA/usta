# NVIDIA NIM ücretsiz modelleriyle bench (18–19 Kasım 2026)

Soru: ücretsiz NIM uç noktasındaki modeller Usta'nın bench görevlerinde nasıl çalışıyor, bitirme kapısı (kol C) fark yaratıyor mu?

| | |
|---|---|
| Uç nokta | `https://integrate.api.nvidia.com/v1` (OpenAI uyumlu, `USTA_API_KEY` ile) |
| Görevler | `dev` bölümü, 20 görev × 1 tekrar; `final` açılmadı |
| Kollar | B (temel Usta), C (doğrulama + bitirme kapısı) |
| Protokol | native araç çağrısı, model zaman aşımı 180 sn, görev başına 600 sn |

## Sonuç

| Model | B | C |
|---|---|---|
| nemotron-3.5-lightning-30b-a3b | 17/20 (%85) | 16/19 (%84) |
| minimax-m3.1-flash | 16/16 (%100) | 8/10 (%80), ölçüm yarıda kesildi |
| glm-5.3-flash | ölçülemedi | ölçülemedi |

Altyapı hatası olan koşular başarı oranına sayılmadı: Nemotron C'de 1, MiniMax B'de 4 ve C'de 2 koşu; GLM'de 40 koşunun hepsi.

| Model, kol | adım | süre (sn) | token/görev | çözülen başına token | kanıtsız bildirim | "bitti" deyip kalan |
|---|---|---|---|---|---|---|
| Nemotron B | 10,95 | 28,9 | 40 518 | 47 668 | 3 | 3 |
| Nemotron C | 8,95 | 49,4 | 28 991 | 34 426 | 0 | 3 |
| MiniMax B | 5,38 | 167,1 | 15 752 | 15 752 | 0 | 0 |
| MiniMax C | 6,5 | 359,5 | 22 146 | 27 683 | 0 | 0 |

Hiçbir koşuda test dosyası değiştirilmedi.

## Yorum

- Nemotron'da B zaten %85'te; C başarı oranını değiştirmedi ama kanıtsız bildirimi 3'ten 0'a ve görev başına tokenı yaklaşık %28 düşürdü. Üç koşuda "bitti" deyip kalma sürdü.
- MiniMax B'de geçerli 16 koşunun hepsini çözdü. Koşular sunucu tarafında Nemotron'dan çok daha yavaş (167 sn'ye karşı 29 sn) ve 6 koşu 429 (hız sınırı) ya da zaman aşımıyla düştü.
- GLM bu uç noktada 180 sn içinde hiç yanıt vermedi, bu yüzden ölçülemedi.

## Sınırlar

Tek tekrar, 20 görev; aralıklar geniş, kollar arasındaki fark kanıtlanmış sayılmaz. Ücretsiz uç noktanın hız ve zaman aşımı davranışı saate göre değişiyor, süreler bu yüzden karşılaştırılamaz. Mistral Large, Kimi ve Nemotron Ultra ölçülmedi.
