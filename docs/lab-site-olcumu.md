# Kodsuz kullanıcı site istekleri: tek seferde mi, bölüm bölüm mü, en küçük parçalarla mı? (16–17 Kasım 2026)

## Soru

Kod bilmeyen bir kullanıcı küçük bir yerel modelden düz Türkçeyle site istiyor. Usta işi nasıl yaptırmalı?

- Tek seferde (`tek`): Usta'nın olağan ajan döngüsü. Söz–eylem denetimi açık, site bilgisi denetimi (`sitecheck.py`) açık.
- Bölüm bölüm (`l2`, `USTA_SITE_STEPS=1 USTA_SITE_LEVEL=2`): Model önce plan yazar, sonra her bölümü ayrı yazar. Usta her bölümü denetler ve parçaları birleştirir (`sitebuild.py`).
- En küçük parçalar (`l1`, `USTA_SITE_LEVEL=1`): Sayfanın iskeletini, kullanıcının bilgilerini ve sayacı Usta koyar. Model yalnız kısa bir tanıtım metni yazar.

## Düzen

- Modeller: Qwen3 4B instruct (`usta-q3-4b-16k`), Qwen2.5-Coder 7B (`usta-qc7b-16k`) ve DeepSeek-V4-Pro-Qwen3.5-9B (`ds-v4-qwen35-9b`, `--think off`). Hepsi Ollama'da, bağlam 16k, RTX 3050 4 GB.
- Görevler: Kodsuz kullanıcı gibi yazılmış üç istek:
  - Ayşe'nin tanıtım sitesi: ad, hobi, e-posta.
  - Pastane menüsü: üç ürün, fiyatları, adres.
  - Düğün davetiyesi: isimler, tarih, şehir ve gün sayacı.
- Tekrar: 3 model × 3 yöntem × 3 görev × 5 tekrar = 135 koşu. Tur tur koşuldu, kod sabit (`5158cc7`).
- Talimat dili: Talimatlar İngilizce ve olumlu, sitedeki metin Türkçe (aşağıdaki talimat dili bölümüne bakın).
- Başarı ölçütü: Bir sayfa yazıldı, kullanıcının verdiği bilgilerin hepsi sayfada (`sitecheck.missing`), ve kullanıcının vermediği hiçbir fiyat, saat, telefon ya da çok kelimeli yer adı yok.

## Sonuç

| Model | Yöntem | Başarı | Ort. süre |
|---|---|---|---|
| Qwen3 4B | tek | 6/15 | 119 sn |
| Qwen3 4B | l2 | 15/15 | 136 sn |
| Qwen3 4B | l1 | 15/15 | 12 sn |
| Qwen2.5-Coder 7B | tek | 1/15 | 87 sn |
| Qwen2.5-Coder 7B | l2 | 15/15 | 188 sn |
| Qwen2.5-Coder 7B | l1 | 15/15 | 20 sn |
| DS-V4-Qwen3.5 9B | tek | 3/15 | 258 sn |
| DS-V4-Qwen3.5 9B | l2 | 14/15 (1 zaman aşımı) | 365 sn |
| DS-V4-Qwen3.5 9B | l1 | 15/15 | 21 sn |

Tek seferde başarısızlığın nedeni neredeyse hep sayfanın hiç yazılmaması. Model ya "hangi dosyaya yazayım?" diye soruyor, ya "isteğinizi anlamadım" diyor, ya da kodu yanıta döküp bitiriyor. Söz–eylem hatırlatması bunların bir kısmını kurtarıyor ama hepsini değil.

Davetiye sayacı yalnız Usta'nın hazır parçasıyla doğru çıktı. Tek seferde yazılan tek davetiye "730 gün" gösterdi; doğrusu 209. Usta'nın hazır sayacı 30 sayfanın hepsinde doğru gösterdi.

## Otomatik ölçütün görmediği: Türkçe kalitesi

Örnek sayfalar elle okundu.

- 4B, l2: Doğru ama çok sade ("Adım Ayşe. Hobilerim: Resim yapma.").
- 7B, l2: Kontrollerden geçiyor ama içerik utandırıcı olabiliyor. Bir davetiyede "Cinayetli iki kişi, Ali ve Zeynep adları altında evleniyor" yazdı.
- 9B, l2: "Sütlaç: … klasik baklava içi" gibi yanlış açıklamalar yazdı.
- l1, üç model: Tek bir kısa tanıtım paragrafı var; çoğunlukla düzgün ya da zararsız garip ("Biz size hobi sayfanızı oluşturmayı seviyoruz").

Model ne kadar az serbest metin yazarsa sayfa o kadar güvenilir oluyor.

## Talimat dili ve yasak listesi (aynı gün, ayrı ölçüm)

Görev: "Tatlı Köşe, Nilüfer, Bursa için iki cümlelik tanıtım yaz." Qwen3 4B ile her biçimde 5 kez denendi.

| Talimat | Uydurmasız |
|---|---|
| Türkçe + yasak listesi ("saat, telefon, adres, ürün, fiyat ekleme") | 0/5 |
| Türkçe + olumlu ("yalnız bu bilgileri kullan") | 5/5 |
| İngilizce talimat + Türkçe metin | 5/5, en düzgün Türkçe |
| İngilizce yazdırıp sonra Türkçeye çevirtme | 5/5, ama çeviri yeni hata ekledi ("pide mağazası") |

Yasak listesinde, model listede adı geçenleri yazdı: telefon, saat ve adres uydurdu.

Qwen2.5-Coder 7B'de (3'er deneme) biçimler arasında belirgin fark çıkmadı. Bu modelin Türkçesi her biçimde zayıf.

Bu ölçümden sonra Usta'nın site talimatları İngilizce ve olumlu yazıldı. Yeniden yazdırma notu da artık bilgi türlerini saymıyor ("telefon, saat yazma" demiyor); yalnız modelin kendi uydurduğu parçaları adıyla anıyor. `tests/test_skillprobe.py` talimatlarda yasak listesi bulunmadığını denetler.

## Beceri sondası (`skillprobe.py`) kararlı değil

Her model için sonda 3 kez koşuldu:

| Model | Sonda sonucu |
|---|---|
| Qwen3 4B | iki kez seviye 2, bir kez seviye 1 |
| Qwen2.5-Coder 7B | üç kez seviye 2 (bir gün önce, Türkçe sorularla, seviye 1 vermişti) |
| DS-V4-Qwen3.5 9B | iki kez seviye 2, bir kez seviye 1 |

Tek bir sınav, seviye seçimini güvenilir biçimde yapamıyor. Yukarıdaki ölçüm de bunu gereksiz kılıyor: l1 üç modelde de en güvenilir ve en hızlı yöntem.

## Öneri

1. 12B altı yerel modellerde yeni site isteği varsayılan olarak l1 ile yapılsın. Usta iskeleti, bilgileri ve sayacı koyar; model kısa tanıtım metnini yazar. 45/45 başarılı, 12–21 saniye.
2. Sayfayı zenginleştirmek modele bırakılmasın, kullanıcıya sorulsun. Örneğin: "Çalışma saatlerini, telefonunu, bir fotoğraf eklemek ister misin?" Kullanıcının verdiği her yeni bilgi aynı yolla sayfaya girer.
3. l2 isteğe bağlı kalsın ("daha ayrıntılı yaz"). Bölüm başlığı, uydurma silme ve eksik bilgiyi Usta'nın ekleyebilmesi gibi güvenlik ağları onda da çalışıyor.
4. Beceri sondası kararlı hale gelene kadar seviye seçimine karar verdirilmesin. Tekrarlı sonda ya da görev sonuçlarından öğrenme düşünülebilir.

Bulut modeller (DeepSeek V4 Pro tek seferde 4/4) ve 12B üstü yerel modeller tek seferde kalır. Bu ölçümde 12B üstü yerel model yoktu; daha büyük bir makinede ayrıca ölçülmeli.

Ham veriler (sayfalar, kayıtlar, `scores.tsv`, `times.tsv`, `probe.jsonl`) depoda değil; isteyene gönderilebilir.
