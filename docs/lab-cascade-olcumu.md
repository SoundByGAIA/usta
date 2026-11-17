# Kademeli yönlendirme (cascade) Lab ölçümü (15–16 Kasım 2026)

Soru: yerel model işe başlasın, takılınca konuşma güçlü modele geçsin. Görev başarısı artar mı, kaç koşu buluta
gider, güçlü model saldırı metni içeren konuşmayı devralınca kanar mı?

| | |
|---|---|
| Ucuz model | `ds-v4-qwen35-9b` (DeepSeek-V4-Pro-Qwen3.5-9B Q4_K_M, yerel Ollama, RTX 3050 4 GB) |
| Güçlü model | `deepseek-v4-pro` (DeepSeek API) |
| Takılma işareti | söz–eylem hatırlatması (`finishcheck.py`): model hedef dosyayı yazmadan bitirmek ya da niyet söyleyip durmak istedi. Lab'da bitirme kapısı yok; "boş el" işareti kapalı (yanıtı okuyarak veren görevlerde doğru yanıtı atardı) |
| Senaryolar | yerleşik küme, 32 senaryo × temiz/saldırılı × 1 (`usta lab run --strong-model …`) |
| Harness | kaynak izi kapısı ve söz–eylem denetimi açık, onaycı `deny` |

## Sonuçlar

| | 9B tek başına (14–15 Kas, 29 senaryo) | 9B → DeepSeek | DeepSeek tek başına |
|---|---|---|---|
| Temiz görev başarısı | 19/25 (%76) | 27/31 (%87) | 32/32 |
| Saldırı altında görev başarısı | 21/25 (%84) | 26/28 (%93) | 28/28 |
| Saldırı başarısı | 1/25 | 0/28 | 0/28 |
| Yetkisiz eylem denemesi | 1/25 | 2/28 (ikisi de gizli dosya kapısında durdu) | 0 |
| Yanlış ret | 0 | 0 | 0 |
| Buluta giden koşu | 0 | 10/59 | 60/60 |
| Güçlü modelin jetonu | - | 75 bin | 436 bin |
| Ortalama süre | 166 sn | 109 sn | 6 sn |

- Devredilen 10 koşunun 10'u başarılı. Güçlü model saldırılı konuşmayı 4 kez devraldı, hiçbirinde kanmadı.
- Koşuların %83'ü bilgisayardan hiç çıkmadan bitti (49/59). DeepSeek'in harcadığı jeton tek başına çalışmasının ~%17'si.
- Eşleştirilmiş (önceki 9B tek başına koşusuyla ortak 53 koşu): 7 kazanç, 3 kayıp. İki ölçüm farklı günlerde koşuldu
  (ikisinde de düşünme modelin kendi ayarındaydı, bkz. `lab-dusunme-olcumu.md`); kayıplar değişkenlikten.
- Maliyet: iki ölçüm (DeepSeek tek başına 60 koşu + kademeli 10 devir) toplam ~8 sent.

## Okuma

Para tasarrufu burada asıl kazanç değildir: DeepSeek bu kümeyi tek başına ~4 sente ve 6 saniyede kusursuz geçiyor.
Kademeli yönlendirmenin değeri gizlilik + güvenilirlik: işlerin çoğu yerelde kalır, yerel modelin takıldığı yerde
görev yine biter. Takılma işareti ucuz (kural, model çağrısı yok) ve bu kümede yanlış alarm vermedi.

## Ölçümün sınırları

- Tek tekrar; Lab görevleri güçlü model için kolay (DeepSeek tavanda). Zor görevlerde devrin etkisi ölçülmedi.
- Bench'teki önceki ölçüm (Flash→Pro, 7B→Flash; `bench-orta-olcum.md`) fayda göstermemişti; orada işaret bitirme
  kapısıydı ve ucuz model işin çoğunu bitiremiyordu. Burada 9B işin çoğunu bitirebiliyor.
- Devredilince konuşma geçmişi (okunan içerikler dahil) buluta gider. Gizli dosya kapısı ve kaynak izi kapısı devirden
  önce de sonra da çalışır, ama yerel dosyalardan okunan içerik buluttaki modele ulaşır: bu, portalda açıkça
  söylenmeden varsayılan yapılmamalı.

## Karar

Deneysel kalır (`usta lab run --strong-model`, `usta bench --arm X-CASCADE`). Portalda bir seçenek olarak sunulması
("yerel model takılırsa buluttaki modele sor") için önce kullanıcıya devrin ne göndereceğini gösteren onay tasarımı gerekir.
