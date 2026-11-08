# Orta zorlukta bench (mid-*): ilk ölçüm

Tarih: 2026-11-08. Amaç: önceki bench'in doygunluğunu (DeepSeek 18/18, 7B zor görevlerde 0) kırmak.
Görev sayısı: 9 (6 dev, 3 final). Final görevleri bu ölçümde AÇILMADI. Kullanılan: 6 dev görevi × 3 tekrar = 18 koşu/kol.

## Görevler nasıl üretildi ve doğrulandı
- Görevleri Usta (DeepSeek) yazdı; DeepSeek bakiyesi bitince yazım yarıda kaldı (11 görev tamamlanmıştı).
- Bağımsız doğrulama: her görevde başlangıç+gizli test BAŞARISIZ, başlangıç+referans çözüm+gizli test GEÇER. 1 görev bu koşulu sağlamadı (elendi).
- Adalet denetimi (Gemini 2.5 Pro, "her gizli beklenti istemden çıkarılabilir mi?"): 1 görevde istem-test çelişkisi bulundu, elle doğrulandı, elendi.

## Sonuç (18 koşu/kol, altyapı hatası 0)
| Model | B (temel) | C (doğrulama + bitirme kapısı) |
|---|---|---|
| Qwen2.5-Coder 7B (JSON) | 0/18 | 0/18 |
| Gemini 2.5 Flash | 7/18 (%39) | 14/18 (%78) |
| Gemini 2.5 Pro | 15/18 (%83) | 16/18 (%89) |

Eşleştirilmiş (aynı görev+tekrar): Flash C lehine 8'e 1 (yalnız-C 8, yalnız-B 1); Pro 3'e 2. İki durumda da %95 aralıklar örtüşüyor: fark KANITLANMADI, yön C lehine.
Flash B'de başarısızlıkların çoğu "kanıtsız bitti" (11/18 koşuda düzenleyip doğrulamadan bitirdi); C'de 0. Bitirme kapısının etkisi orta güçteki modelde görünür, güçlü modelde azalır, 7B'de görünmez (taban etkisi).

## Sınırlar
Küçük örneklem (6 görev); görevleri bir model yazdı ve başka bir model denetledi; Flash/Pro tek koşu kümesi; DeepSeek ve 12B+ yerel model bu ölçümde yok (DeepSeek bakiyesi yok).
Ölçüm hatası notu: çalışan betiği düzenlediğimde bash dosyayı kaymış okudu; gflash logları bozuldu, JSON raporları sağlam.
