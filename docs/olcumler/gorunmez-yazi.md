# Görünmeyen yazı hatırlatması (19 Kasım 2026)

Soru: küçük bir model bir yazıyı zeminiyle aynı renge boyadığında (pembe şerit üstüne pembe dükkân adı) Usta'nın
hatırlatması modele bunu düzelttirebiliyor mu?

Kodsuz kullanıcı denemesinde Gemini 2.5 Flash bir kuaför sitesinin başlığını pembe zemine pembe yazdı; bilgiler sayfada
vardı ama dükkânın adı görünmüyordu. Önceki site ölçümünün ([site-istekleri.md](site-istekleri.md)) 95 sayfası
`sitecontrast.py` ile tarandı: 12'sinde başlık görünmüyordu, 12'si de deneysel bölüm bölüm kurmadan (`USTA_SITE_STEPS=1`)
çıkmıştı.

## Bölüm bölüm kurma

Bu yolda modele sorulmaz: modelin yazdığı renkler bir yazıyı gizliyorsa Usta kendi renklerine döner. O 12 sayfanın
renkleri Usta'nınkilerle değiştirilince 12'si de okunur oluyor. Model çağrısı yok, sonuç her seferinde aynı.

## Olağan yol: hatırlatma

| | |
|---|---|
| Modeller | Qwen3 4B instruct (`usta-q3-4b-16k`), Qwen2.5-Coder 7B (`usta-qc7b-16k`); Ollama, bağlam 16k, RTX 3050 4 GB |
| Başlangıç | yukarıdaki 12 sayfadan 4'ü (pastane, iki Ayşe sayfası, davetiye) çalışma klasöründe `index.html` |
| İstek | "Sayfanın en altına 'Bizi Instagram'da takip edin: @ornek' yazısı ekle." (renkten söz edilmez) |
| Kollar | hatırlatmasız (0.9.0, `57fa667`); v1 "yazı rengini ya da zemin rengini değiştir" (`6f52ebb`); v2 sorunlu kuralı, iki rengi ve okunur bir renk önerisini söyler (`ed8cac6`) |
| Tekrar | 2 model × 4 sayfa × 2 tekrar = kol başına 16 koşu |
| Ölçüt | koşu sonunda `sitecontrast.hidden_texts` boş mu; Instagram satırı sayfada mı |

| Model | Kol | Başlık görünür | Instagram eklendi | Hatırlatma geldi | Ort. süre |
|---|---|---|---|---|---|
| Qwen3 4B | hatırlatmasız | 0/8 | 5/8 | 0/8 | 291 sn |
| Qwen3 4B | v1 | 3/8 | 7/8 | 7/8 | 329 sn |
| Qwen3 4B | v2 | 3/8 | 8/8 | 8/8 | 310 sn |
| Qwen2.5-Coder 7B | hatırlatmasız | 0/8 | 0/8 | 0/8 | 46 sn |
| Qwen2.5-Coder 7B | v1 | 0/8 | 0/8 | 0/8 | 159 sn |
| Qwen2.5-Coder 7B | v2 | 1/8 | 2/8 | 1/8 | 128 sn |

## Sonuç

- Hatırlatma Qwen3 4B'de görünmeyen başlığı 0/8'den 3/8'e çıkarıyor; kullanıcının asıl isteği bozulmuyor.
- v2 v1'den ölçülebilir biçimde iyi değil (8 koşuda fark yok); varsayılan v2, çünkü modele düzenlemenin yerini söylüyor ve
  zarar görülmedi. v1'de model başlığın kuralını tahmin edip tek satırlık bir metinle değiştirmeye çalışıyor, kural dosyada
  çok satırlı olduğu için düzenleme tutmuyor ve aynı denemeyi adım sınırına kadar tekrarlıyordu.
- Qwen2.5-Coder 7B bu sayfalarda `edit_file`'ı boş `old` ile çağırıp sayfayı neredeyse hiç değiştiremiyor; sayfa
  değişmeyince hatırlatma da gelmiyor. Bu hatırlatmanın değil, modelin düzenleme aracını kullanmasının sorunu.
- Ölçek küçük (kol başına 8 koşu, tek senaryo türü); oranlar yön gösterir, kesin değildir.

Bu işin yan bulgusu: ilk ölçütte "istek yapıldı mı" için sayfada `@ornek` arandı; Ayşe sayfalarında zaten
`ayse@ornek.com` olduğu için değişmemiş sayfalar da yapılmış sayıldı. Tablo düzeltilmiş ölçütle ("Instagram") hesaplandı.
