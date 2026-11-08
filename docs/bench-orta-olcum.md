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

## Kademeli yönlendirme (X-CASCADE, deneysel): sonuç = fayda kanıtlanmadı
Ucuz model başlar; bitirme kapısı başarısız sayarsa ya da devre kesici açılırsa konuşma güçlü modele devredilir (`src/usta/cascade.py`). Aynı 6 dev görevi × 3 tekrar:

| Yapılandırma | Geçen | Güçlüye devredilen | Güçlü modelin token'ı | Toplam token |
|---|---|---|---|---|
| Flash C (tek model) | 14/18 | - | 536 bin (hepsi) | 536 bin |
| Pro C (tek model) | 16/18 | - | 452 bin (hepsi) | 452 bin |
| Flash → Pro | 12/18 | 3 | 58 bin | 601 bin |
| 7B → Flash (yalnız kapı/kesici işareti) | 2/18 | 5 | 134 bin | 468 bin |
| 7B → Flash (+ "düzenlemeden bitirdi" işareti) | 14/18 | 17 | 496 bin | 733 bin |

- **Flash → Pro:** kapı yalnız 3 koşuda tetiklendi; kalan hatalar yanlış çözümle "bitti" idi (deponun testleri yakalamıyor). Fayda yok; 12/18 ile 14/18 arası gürültü.
- **7B → Flash:** yalnız kapı işaretiyle 2/18. İkinci işaret (7B hiç düzenleme yapmadan "bitti" derse yanıtı at, güçlüye sor) eklenince 14/18, ama 17 koşunun 17'si Flash'a devredildi: bu, Flash'ın işi yapması + 7B'nin boşa token yakması demek. Flash'ın harcadığı token (496 bin) tek başına Flash C'den (536 bin) yalnız ~%7 az: bulut token tasarrufu gürültü düzeyinde; toplam token ve süre daha yüksek.
- İkinci işaret dev sonuçlarına bakılarak eklendi (ayarlama); bu yüzden 14/18 kanıt sayılmaz, final görevlerinde doğrulanmadı.
- **Karar:** deneysel kalır, varsayılan değil. Gerçek token tasarrufu için ucuz modelin işin büyük kısmını kendisinin bitirebilmesi gerekir; 7B bu görevlerde bunu yapamıyor.
