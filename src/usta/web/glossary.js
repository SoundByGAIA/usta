// Usta sözlüğü: 5 yaşındaki bir çocuğun anlayacağı düzlükte açıklamalar (Feynman ilkesi).
// Veri yereldir; hiçbir şey dışarıdan yüklenmez. node ile test edilir.
(function (root) {
  "use strict";

  // say: tek bakışta anlatım (kısa ve gündelik); like: gündelik bir benzetme.
  const TERMS = [
    { term: "Yapay zekâ", aka: "ai yapay zeka", say: "Çok kitap okumuş, senin yazdığını anlayıp cevap veren bir bilgisayar yardımcısı.", like: "Her şeyi okumuş, hiç yorulmayan bir arkadaş gibi." },
    { term: "Model", aka: "llm dil modeli", say: "Yapay zekânın beyni. Farklı modeller var: bazıları küçük ve hızlı, bazıları büyük ve çok zeki.", like: "Okul gibi düşün: ilkokul öğrencisi de var, profesör de." },
    { term: "Usta", aka: "ajan agent", say: "Senin söylediğini yapan yardımcı. \"Bir hesap makinesi yap\" dersin, o yapar.", like: "Bir ustaya iş tarif edersin, o da yapar." },
    { term: "API anahtarı", aka: "api key anahtar şifre", say: "Bir internet servisini kullanmak için aldığın uzun gizli yazı. Servis, kapıyı sana açtığı için bunu ister.", like: "Evinin anahtarı gibi: kimseye verme." },
    { term: "API", aka: "arayüz", say: "İki programın birbiriyle konuştuğu kapı. Usta, API ile yapay zekâ servisine soru sorar.", like: "Lokantadaki garson: sen siparişi ona verirsin, o mutfağa iletir." },
    { term: "Servis", aka: "bulut internet servisi", say: "Başka bir yerdeki büyük bilgisayarlarda çalışan yapay zekâ. İnternetle ona bağlanırsın.", like: "Su gibi: evinde kuyu kazmak yerine şebekeden alırsın." },
    { term: "Bulut", aka: "cloud internet", say: "Senin değil, başkasının bilgisayarları. Yazdıkların internetle oraya gider.", like: "Eşyalarını komşunun deposuna koymak gibi." },
    { term: "Yerel", aka: "bilgisayarımda lokal local", say: "Her şey senin bilgisayarında kalır, internete çıkmaz.", like: "Defterine yazmak gibi: kimse görmez." },
    { term: "Ollama", aka: "ollama", say: "Yapay zekâyı kendi bilgisayarında çalıştıran ücretsiz program.", like: "Yapay zekâ için bir ev: modeli oraya indirirsin, orada yaşar." },
    { term: "Docker", aka: "konteyner kutu", say: "Programları kapalı, güvenli bir kutunun içinde çalıştıran program. Kutuda ne olursa olsun bilgisayarın zarar görmez.", like: "Deney yaparken cam fanus kullanmak gibi." },
    { term: "Yalıtım", aka: "sandbox izole güvenli kutu", say: "Bir şeyi çevresinden ayırıp kapalı kutuda çalıştırmak. Hata yapsa bile dışarı zarar veremez.", like: "Kumda oyun alanı: kum dışarı taşmaz." },
    { term: "JSON", aka: "json dosya veri", say: "Bilgileri düzenli bir liste gibi yazma yolu. Bilgisayarlar birbirine bilgiyi böyle verir.", like: "Bir form doldurmak gibi: ad, soyad, yaş alt alta yazılır." },
    { term: "Token", aka: "jeton belirteç", say: "Yapay zekânın okuduğu küçük yazı parçaları. Yaklaşık bir kelimenin yarısı kadar. Servisler parayı buna göre sayar.", like: "Bozuk para gibi: harcadıkça biter." },
    { term: "Bağlam penceresi", aka: "context ctx hafıza uzunluk", say: "Yapay zekânın bir anda aklında tutabildiği yazı miktarı. Dolunca eskileri unutur.", like: "Bir masanın büyüklüğü: ne kadar kâğıt sığarsa o kadarına bakabilir." },
    { term: "Düşünme", aka: "reasoning think düşünme ayarı", say: "Yapay zekânın cevap vermeden önce kafasında düşünmesi. Açık olursa daha iyi ama daha yavaş cevap verir.", like: "Soruyu hemen cevaplamak yerine önce kâğıtta hesap yapmak gibi." },
    { term: "İstem", aka: "prompt komut talimat", say: "Yapay zekâya yazdığın şey. Ne istediğini ne kadar açık yazarsan o kadar iyi olur.", like: "Bir tarif vermek gibi." },
    { term: "Çalışma alanı", aka: "workspace klasör proje", say: "Usta'nın dosyalarını koyduğu bir klasör. Usta yalnız bu klasörde çalışır, başka yere dokunmaz.", like: "Çocuğa verilen çizim masası: yalnız orada çizer." },
    { term: "Dosya", aka: "file", say: "Bilgisayarda saklanan bir şey: yazı, resim ya da program.", like: "Bir çekmecedeki kâğıt gibi." },
    { term: "Klasör", aka: "dizin dizin folder", say: "Dosyaları içine koyduğun kutu. Klasörün içinde klasör de olabilir.", like: "Dolap çekmecesi." },
    { term: "Onay", aka: "izin onay iste", say: "Usta önemli bir şey yapmadan önce sana sorar. Sen \"olur\" ya da \"hayır\" dersin.", like: "Annenden izin istemek gibi." },
    { term: "Geri alma", aka: "geri al undo", say: "Usta'nın yaptığı değişikliği önceki haline döndürmek.", like: "Silgiyle silmek gibi." },
    { term: "Hata", aka: "bug error", say: "Bir şeyin yanlış çalışması. Korkma, bilgisayar bozulmaz; Usta'ya \"düzelt\" dersin.", like: "Yanlış yazılmış bir harf." },
    { term: "Program", aka: "kod yazılım uygulama", say: "Bilgisayara ne yapacağını söyleyen talimatlar. Her uygulama bir programdır.", like: "Yemek tarifi: adım adım ne yapılacağı yazar." },
    { term: "Kod", aka: "yazılım code", say: "Bilgisayarın anlayacağı dilde yazılmış talimatlar.", like: "Bilgisayara yazılan mektup." },
    { term: "HTML", aka: "web sayfası site", say: "Web sayfasının iskeleti. Başlık, yazı ve resimler nerede dursun diye söyler.", like: "Evin duvarları." },
    { term: "CSS", aka: "stil renk görünüm", say: "Web sayfasının boyası ve süsü: renkler, yazı büyüklüğü, yerleşim.", like: "Evin boyası ve perdeleri." },
    { term: "JavaScript", aka: "js script", say: "Web sayfasını canlandıran dil: düğmeye basınca bir şey olması gibi.", like: "Evin elektriği: ışığı yakar." },
    { term: "Python", aka: "python", say: "Bilgisayara iş yaptırmak için kullanılan bir dil. Usta da Python ile yazıldı.", like: "Bilgisayarın anladığı Türkçe gibi bir dil." },
    { term: "Terminal", aka: "siyah pencere cmd komut satırı konsol", say: "Bilgisayara yazıyla komut verdiğin siyah pencere. Usta'yı kullanmak için ona gerek yok.", like: "Bilgisayarla yazışma ekranı." },
    { term: "Komut", aka: "command", say: "Bilgisayara yazıyla verilen emir. Mesela \"şu dosyayı aç\".", like: "\"Otur\" demek gibi." },
    { term: "Sunucu", aka: "server port localhost", say: "İsteklere cevap veren program. Usta'nın sayfası da senin bilgisayarında çalışan küçük bir sunucudur.", like: "Okul kantini: gelen sipariş alır, verir." },
    { term: "Adres", aka: "url link bağlantı http", say: "Bir web sayfasının yeri. Tarayıcının üstüne yazarsın.", like: "Evin adresi." },
    { term: "Tarayıcı", aka: "chrome edge firefox browser", say: "İnternet sayfalarını açtığın program. Usta da tarayıcıda açılır.", like: "İnternete bakmak için pencere." },
    { term: "Kurulum", aka: "install indir yükle", say: "Bir programı bilgisayarına yerleştirmek. Bir kere yapılır.", like: "Yeni eşyayı odana yerleştirmek." },
    { term: "Güncelleme", aka: "update sürüm yeni", say: "Programın yeni ve daha iyi hali. Hataları düzeltir, yeni şeyler ekler.", like: "Oyuncağa yeni parça eklemek." },
    { term: "Python'u PATH'e ekle", aka: "path yol", say: "Kurulumda işaretlediğin kutu. Bilgisayar Python'un nerede olduğunu bilsin diye gerekir.", like: "Bir yere gidebilmek için haritaya adresi yazmak." },
    { term: "MCP", aka: "araç eklenti mcp", say: "Usta'ya yeni beceri kazandıran küçük eklentiler. Gelişmiş bir şey, başlamak için gerekmez.", like: "Oyuncağa takılan yeni parça." },
    { term: "Gizlilik", aka: "veri güvenlik", say: "Senin bilgilerinin kimseyle paylaşılmaması. Usta senin yazdıklarını yalnız seçtiğin yapay zekâya gönderir.", like: "Günlüğün kilidi." },
    { term: "Geliştirici modu", aka: "gelişmiş mod ileri düzey", say: "Üstteki düğme. Açınca bilgisayar işi yapanların kullandığı ek araçlar görünür. Başlamak için kapalı kalsın.", like: "Arabanın motor kaputu: açmak zorunda değilsin." },
    { term: "Ordis", aka: "ordis", say: "Usta'yı yapan ekibin adı.", like: "Oyuncağı yapan atölye." },
  ];

  function norm(s) {
    return String(s || "").toLocaleLowerCase("tr").replace(/\s+/g, " ").trim();
  }

  // Arama: terim adı, takma adlar ve açıklama içinde geçenleri bulur; ad eşleşmesi önce gelir.
  function search(query, terms) {
    const list = terms || TERMS;
    const q = norm(query);
    const sorted = [...list].sort((a, b) => a.term.localeCompare(b.term, "tr"));
    if (!q) return sorted;
    const rank = (t) => {
      const name = norm(t.term);
      if (name === q) return 0;
      if (name.startsWith(q)) return 1;
      if (name.includes(q)) return 2;
      if (norm(t.aka).includes(q)) return 3;
      if (norm(t.say).includes(q) || norm(t.like).includes(q)) return 4;
      return 9;
    };
    return sorted.filter((t) => rank(t) < 9).sort((a, b) => rank(a) - rank(b));
  }

  /** Adı (ya da takma adı) tam tutan terim; yoksa null. Balonlar bununla açıklama bulur. */
  function find(name, terms) {
    const fold = (s) => norm(s).replace(/ı/g, "i");  // "API" küçülünce "apı" olur; "api" yazan da bulsun
    const q = fold(name);
    if (!q) return null;
    const list = terms || TERMS;
    return list.find((t) => fold(t.term) === q) || list.find((t) => fold(t.aka).split(/\s+/).includes(q)) || null;
  }

  const api = { TERMS, search, find };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.UstaGlossary = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
