# Kabul edilebilir kullanım

Usta senin bilgisayarında, senin seçtiğin yapay zekâ modeliyle çalışan bir yardımcıdır. Onunla ne yaptığından sen
sorumlusun. Bu sayfa neyin yasak olduğunu, Usta'nın neyi engellediğini ve neyi engelleyemediğini anlatır.

## Usta ile yapılmaz

- Yetkin olmayan bir bilgisayara, siteye, ağa ya da hesaba girmek; onu yavaşlatmak, çökertmek ya da bozmak.
- Zararlı yazılım (virüs, fidye yazılımı, casus yazılım) ya da saldırı aracı yazmak, yaymak.
- Başkasının şifresini, kişisel bilgisini ya da yazışmasını izinsiz ele geçirmek.
- Çok sayıda insanın canına mal olabilecek silahlar için bilgi toplamak.
- Çocuk istismarı içeren her türlü içerik.
- Yaşadığın yerin yasalarına aykırı her iş.

Kendi sistemini denemek serbesttir: kendi sitene yük testi, kendi ağının güvenlik taraması, sahibinden yazılı izin
alınmış sızma testi. Usta neye iznin olduğunu bilemez; bunu sen bilirsin.

## Usta neyi engeller

Bu sınırlar modelden bağımsızdır; kurallara uymayan bir model de onları aşamaz:

- Komutlar ağı kapalı bir kutuda çalışır. Kutudan dışarı yalnız senin izin verdiğin alan adlarına çıkılır; IP adresleri,
  evdeki ağ ve bu bilgisayar hiç açılmaz.
- İzin verdiğin bir adrese de bağlantı sınırlıdır (aynı anda en çok 32, saniyede en çok 20 yeni bağlantı); bir komut
  en çok 60 saniye çalışır.
- Usta yalnız seçtiğin klasöre yazar; riskli adımlar için sana sorar.
- İstersen (`USTA_ANAYASA=1`, deneysel) model Usta'nın ilkelerini de okur: yukarıdaki yasakları ve nedenini bilir.
  Gemini ve Qwen3 4B zararlı istekleri ilkeler olmadan da reddetti ([ölçüm](olcumler/anayasa.md)); Qwen 3.8 27B ise
  bir site çökertme isteğine araç yazdı ([ölçüm](olcumler/talimat.md)). Model reddetmezse yalnız yukarıdaki sınırlar kalır.

## Usta neyi engelleyemez

- Usta açık kaynaktır. Kodu değiştirip bu sınırları kaldıran birini hiçbir yazılım durduramaz.
- Kurallara uymayan (sansürsüz) bir model yasak bir isteği reddetmeyebilir; o zaman yalnız yukarıdaki sınırlar kalır.
- Usta'nın yazdığı bir programı sen kutunun dışında çalıştırırsan, o program artık senin bilgisayarında senin
  yetkilerinle çalışır.

## Garanti yok

Usta [Apache-2.0](../LICENSE) lisansıyla "olduğu gibi" verilir; doğruluğu ya da bir işe uygunluğu için hiçbir garanti
verilmez ve kullanımından doğan zarardan emek verenler sorumlu tutulamaz (lisansın 7. ve 8. maddeleri). Güvenlik açığı
bulursan bize bildir: [SECURITY.md](../SECURITY.md).
