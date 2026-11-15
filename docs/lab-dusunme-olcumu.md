# Düşünmeyi sınırlamak küçük modeli hızlandırır mı? (15 Kasım 2026)

Soru: küçük yerel model çok uzun konuşuyor (koşu başına ~1800 jeton, ~5 dakika). Düşünmeyi kısmak ya da çıktıyı
sınırlamak doğrudan cevap getirip görev başarısını korur mu?

| | |
|---|---|
| Model | `qwen3:1.7b` (Q4_K_M, yerel Ollama 0.30.6, `num_ctx 16384`), yerel protokol |
| Senaryolar | yerleşik küme, 32 senaryo × temiz/saldırılı × 1 tekrar |
| Harness | kaynak izi kapısı açık, söz–eylem denetimi açık, onaycı `deny` |

## Önce bir ölçüm hatası

Önceki Lab koşularında düşünme `{"think": false}` ile "kapatılıyordu". Ollama'nın OpenAI-uyumlu ucu bu alanı **yok
sayar**: model her adımda yüzlerce jetonluk (İngilizce) iç düşünce yazdı, görünen yanıtlar kısaydı. Düşünmeyi gerçekten
kapatan alan `reasoning_effort: "none"`; portalın "Düşünme: kapalı" ayarı zaten bunu gönderir (`thinking.py`), yani
kullanıcılar etkilenmedi. Söz–eylem ölçümünde (9B) A ve B aynı koşulda koşulduğu için o karşılaştırma geçerlidir.

## Sonuçlar

| | Düşünme açık | Çıktı sınırı 512 jeton | Düşünme gerçekten kapalı |
|---|---|---|---|
| Temiz görev başarısı | **13/32** | 3/32 | 5/32 |
| Saldırı altında görev başarısı | **9/26** | 6/28 | 3/28 |
| Saldırı başarısı | 1 | 0 | 0 |
| Hiç araç çağırmayan koşu | 2 | **20** | 0 |
| Ortalama çıktı | 1816 jeton | 1079 jeton | **149 jeton** |
| Ortalama süre | 293 sn | 172 sn | **21 sn** |

- **512 sınırı:** düşünce yarıda kesildi, araç çağrısına sıra gelmedi (boş yanıt). Eşleştirilmiş: 2 kazanç, 15 kayıp.
- **Düşünme kapalı:** 14 kat hızlı ama model okumadan yazıyor (ör. `lesson.txt` içine görev cümlesinin kendisini
  yazdı; `install.txt` içine dosya adını). Eşleştirilmiş: 0 kazanç, 14 kayıp.

## Karar

Küçük modelde düşünmeyi kısmak **varsayılan yapılmaz**: hız gelir ama işi doğru yapma yeteneği gider. Hız için doğru
yol kaliteyi değiştirmeyen hızlandırmadır: aynı model llama.cpp'nin MTP (çok jeton tahmini) kipiyle ~%30 hızlı
çalıştı (9B, RTX 3050 4 GB: saniyede 3,05 → ~4,0 jeton, `--spec-type draft-mtp --spec-draft-n-max 2`, tahmin tutma
%59–73). Usta'ya `--endpoint` ile bağlanır; kod değişikliği gerekmez.

## Dürüstlük notları

- Tek model, tek tekrar; 1.7B koşudan koşuya çok değişken (düşünme açık iki koşu arasında bile 10 kazanç / 6 kayıp).
  Buna rağmen 0 kazanç / 14 kayıp tesadüf değildir.
- Güçlü modellerde düşünmeyi kısmanın etkisi ölçülmedi.
- MTP hızı düz sorularla ölçüldü, Usta görevleriyle değil.
