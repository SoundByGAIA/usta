// Usta "Ofis" sekmesi: canvas 2D piksel-sanat sahnesi. Bağımlılık yok, harici görsel/font yok.
// Tüm çizim kodla yapılır (dizge-palet sprite'lar, tam sayı ölçek). Olaylar Office.onEvent ile gelir.
(function (root) {
  "use strict";
  const Logic = root.OfficeLogic;
  const W = 256, H = 160; // mantıksal piksel tuvali
  const MAX_FPS = 30;
  const WALK_MS = 750;
  const MIN_SCALE = 3; // küçük ekranda bile en az 3x (CSS max-width taşmayı engeller)
  const MAX_SCALE = 6; // geniş ekranda dev sahne yerine ölçülü büyütme
  // Beyaz tahtanın iç (yazı) alanı: drawScene'deki 144x27 çerçeve + 3 px kenar → 62,8 136x19 (iç sınır 197,26)
  // Genişlik 5x7 fontta 22 karaktere yeter: "ONAY BEKLİYOR" (13) ve kısa sayaçlar (≤19, Logic.shortCounters) taşmaz.
  const BOARD_IN_X = 62, BOARD_IN_Y = 8, BOARD_IN_W = 136, BOARD_IN_H = 19;

  const PAL = {
    ".": null,
    b: "#c9a074", // ahşap orta
    B: "#a67c52", // ahşap koyu
    j: "#8a6136", // ahşap çizgi
    d: "#2b3442", // koyu mavi-gri
    D: "#1c232e", // daha koyu
    n: "#222b36", // zemin
    w: "#e8e4d8", // beyaz/kâğıt
    W: "#b9b3a3", // gölgeli beyaz
    o: "#e08a3c", // sıcak turuncu
    O: "#b4531a", // koyu turuncu
    s: "#f2c69a", // ten
    S: "#d29b6c", // ten gölge
    k: "#2a2018", // saç/çizgi koyu
    g: "#4a8f5e", // yeşil (kitap/ekran)
    G: "#2f6b45", // koyu yeşil
    r: "#cf5a4a", // kırmızı
    y: "#e7c65a", // sarı
    m: "#7d8796", // gri metal
    M: "#5a6472", // koyu gri metal
    p: "#8a6fb0", // mor (mektup/dolap)
    c: "#8fb7d6", // açık mavi
  };

  // Usta: 16x22 gövde (+2 satır bacak → 24) — turuncu önlük, koyu saç, ten yüz.
  const SPRITE = [
    "................",
    ".....kkkkkk.....",
    "....kkkkkkkk....",
    "....kssssssk....",
    "....kssssssk....",
    "....kskssksk....",
    "....kssssssk....",
    "....kssSSssk....",
    ".....kssssk.....",
    "......kssk......",
    "....oooooooo....",
    "...oooooooooo...",
    "...soowwwwOos...",
    "...soowwwwOos...",
    "...soowwwwOos...",
    "...soowwwwOos...",
    "...soowwwwOos...",
    "...soowwwwOos...",
    "...soobbbboos...",
    "...soObbbbOos...",
    "....oOOOOOOo....",
    ".....o....o.....",
  ];
  const LEGS = {
    0: ["....kk....kk....", "....kk....kk...."],
    1: ["...kkk....kkk...", "...kk......kk..."],
    2: ["....kk....kk....", "...kkk.....kkk.."],
    3: ["....kk....kk....", "....kkk..kkk...."],
  };
  const CHAR_H = SPRITE.length + 2; // 24
  const CHAR_W = 16;

  function makeCanvas(w, h, draw) {
    const c = document.createElement("canvas");
    c.width = w;
    c.height = h;
    const ctx = c.getContext("2d");
    if (ctx) draw(ctx);
    return c;
  }

  const SPRITES = (function () {
    const out = {};
    for (const key of Object.keys(LEGS)) {
      out[`char-${key}`] = rasterSprite(SPRITE.concat(LEGS[key]));
    }
    return out;
  })();

  // Dikdörtgen: ctx.ops varsa (testte sahte bağlam) çizim kaydı da tutulur — ağ/PATH yok
  function rect(ctx, x, y, w, h, col) {
    ctx.fillStyle = col;
    ctx.fillRect(x, y, w, h);
    const ops = ctx.ops;
    if (ops) ops.push({ k: "r", x, y, w, h, c: col });
  }

  // Piksel fontu (5x7, kodla tanımlı; harici font yok). Yazı mantıksal ölçekte net durur.
  const FONT = {
    A: [14, 17, 17, 31, 17, 17, 17], B: [30, 17, 17, 30, 17, 17, 30], C: [14, 17, 16, 16, 16, 17, 14],
    D: [28, 18, 17, 17, 17, 18, 28], E: [31, 16, 16, 30, 16, 16, 31], F: [31, 16, 16, 30, 16, 16, 16],
    G: [14, 17, 16, 23, 17, 17, 14], H: [17, 17, 17, 31, 17, 17, 17], I: [14, 4, 4, 4, 4, 4, 14],
    J: [7, 2, 2, 2, 2, 18, 12], K: [17, 18, 20, 24, 20, 18, 17], L: [16, 16, 16, 16, 16, 16, 31],
    M: [17, 27, 21, 21, 17, 17, 17], N: [17, 25, 21, 19, 17, 17, 17], O: [14, 17, 17, 17, 17, 17, 14],
    P: [30, 17, 17, 30, 16, 16, 16], Q: [14, 17, 17, 17, 21, 18, 13], R: [30, 17, 17, 30, 20, 18, 17],
    S: [15, 16, 16, 14, 1, 1, 30], T: [31, 4, 4, 4, 4, 4, 4], U: [17, 17, 17, 17, 17, 17, 14],
    V: [17, 17, 17, 17, 17, 10, 4], W: [17, 17, 17, 21, 21, 21, 10], X: [17, 17, 10, 4, 10, 17, 17],
    Y: [17, 17, 10, 4, 4, 4, 4], Z: [31, 1, 2, 4, 8, 16, 31],
    0: [14, 17, 19, 21, 25, 17, 14], 1: [4, 12, 4, 4, 4, 4, 14], 2: [14, 17, 1, 2, 4, 8, 31],
    3: [31, 2, 4, 2, 1, 17, 14], 4: [2, 6, 10, 18, 31, 2, 2], 5: [31, 16, 30, 1, 1, 17, 14],
    6: [6, 8, 16, 30, 17, 17, 14], 7: [31, 1, 2, 4, 8, 8, 8], 8: [14, 17, 17, 14, 17, 17, 14],
    9: [14, 17, 17, 15, 1, 2, 12],
    " ": [0, 0, 0, 0, 0, 0, 0], ".": [0, 0, 0, 0, 0, 12, 12], ",": [0, 0, 0, 0, 0, 6, 4],
    ":": [0, 12, 12, 0, 12, 12, 0], "-": [0, 0, 0, 31, 0, 0, 0], "!": [4, 4, 4, 4, 4, 0, 4],
    "?": [14, 17, 1, 2, 4, 0, 4], "·": [0, 0, 12, 12, 0, 0, 0], "/": [1, 1, 2, 4, 8, 16, 16],
    "…": [0, 0, 0, 0, 0, 0, 21], "(": [2, 4, 8, 8, 8, 4, 2], ")": [8, 4, 2, 2, 2, 4, 8],
    "'": [4, 4, 0, 0, 0, 0, 0],
    // Türkçe: I (noktasız) / İ (noktalı) net ayrılır; Ç Ğ İ Ö Ş Ü + küçükleri işaretleriyle
    "İ": [4, 0, 14, 4, 4, 4, 14], "ı": [4, 0, 12, 4, 4, 4, 14],
    "Ş": [14, 17, 16, 14, 1, 14, 4], "ş": [7, 8, 6, 1, 14, 4, 10],
    "Ç": [14, 17, 16, 16, 17, 14, 4], "ç": [14, 16, 16, 17, 14, 4, 8],
    "Ö": [10, 0, 14, 17, 17, 17, 14], "ö": [10, 0, 14, 17, 17, 17, 14],
    "Ü": [10, 0, 17, 17, 17, 17, 14], "ü": [10, 0, 17, 17, 17, 17, 14],
    "Ğ": [10, 0, 14, 16, 23, 17, 14], "ğ": [10, 0, 14, 18, 18, 14, 12],
    "â": [10, 4, 12, 18, 18, 12, 0], "Â": [10, 4, 14, 17, 17, 17, 14],
  };
  // Fontta olmayan karakter: "?" yerine ASCII karşılığına düş (Türkçe-ASCII eşleme + aksan soyma)
  const ASCII_FALLBACK = { "Ğ": "G", "ğ": "G", "Ş": "S", "ş": "S", "Ç": "C", "ç": "C", "Ö": "O", "ö": "O", "Ü": "U", "ü": "U", "İ": "I", "ı": "I" };
  const FONT_UP = { "ç": "Ç", "ş": "Ş", "ö": "Ö", "ü": "Ü", "ğ": "Ğ", "ı": "I", "â": "Â" };

  function glyph(ch) {
    const c = String(ch);
    let g = FONT[c] || FONT[c.toUpperCase()];
    if (g) return g;
    const ascii = ASCII_FALLBACK[c] || ASCII_FALLBACK[c.toUpperCase()] || c.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
    const up = ASCII_FALLBACK[ascii] || String(ascii).toUpperCase();
    return FONT[ascii] || FONT[up] || FONT["?"];
  }

  // Gerçek piksel genişliği: her glif 5 px + 1 px aralık, son aralık düşülür (n karakter → 6n-1 px)
  function textWidth(s, scale) {
    const n = String(s).length;
    return n ? n * 6 * scale - scale : 0;
  }

  // Satırı maxW genişliğe sığdırır: sığmıyorsa sonuna "…" ekleyip karakter keser (tahta dışına asla çizilmez)
  function fitLine(s, maxW, scale, maxChars0) {
    const str = String(s || "");
    const cap = maxChars0 == null ? Math.floor((maxW + scale) / (6 * scale)) : maxChars0; // ölçek 1: 136 px → 22 karakter
    const maxChars = Math.max(1, cap);
    if (str.length <= maxChars && textWidth(str, scale) <= maxW) return str;
    const keep = Math.max(1, Math.min(str.length, maxChars - 1));
    return str.slice(0, keep).trimEnd() + "…";
  }

  function drawText(ctx, s, x, y, col, scale) {
    scale = scale || 1;
    ctx.fillStyle = col;
    const str = String(s);
    const ops = ctx.ops;
    // testte tek kayıt yeter: glifleri tek tek yazmak yerine metnin sınırları
    if (ops) ops.push({ k: "t", s: str, x, y, w: textWidth(str, scale), h: 7 * scale, c: col });
    for (let i = 0; i < str.length; i++) {
      const g = glyph(str[i]);
      const gx = x + i * 6 * scale;
      for (let row = 0; row < 7; row++) {
        const bits = g[row];
        for (let b = 0; b < 5; b++) {
          if (bits & (1 << (4 - b))) ctx.fillRect(gx + b * scale, y + row * scale, scale, scale);
        }
      }
    }
  }

  // Dizge-palet sprite tanımını piksel piksel tuvale basar (harici görsel yok).
  function rasterSprite(rows) {
    return makeCanvas(rows[0].length, rows.length, (ctx) => {
      rows.forEach((row, y) => {
        for (let x = 0; x < row.length; x++) {
          const col = PAL[row[x]];
          if (col) rect(ctx, x, y, 1, 1, col);
        }
      });
    });
  }

  // Bölge tabelaları: sabit, kim olduğunu yazar (renk tek başına anlam taşımaz)
  // Tabelalar yere paralel: karakterin (y 76..130 + bacak) ve masaların/objelerin ALTINDA kalır.
  const ZONES = [
    { key: "library", label: "KITAPLIK", x: 30, y: 149 },
    { key: "workshop", label: "ATOLYE", x: 101, y: 149 },
    { key: "testbench", label: "TEST", x: 150, y: 149 },
    { key: "post", label: "POSTANE", x: 189, y: 149 },
    { key: "memory", label: "HAFIZA", x: 235, y: 149 },
  ];

  function drawSign(ctx, zone, active) {
    const tw = textWidth(zone.label, 1);
    const w = tw + 6, x = zone.x - Math.round(w / 2), y = zone.y;
    rect(ctx, x + 1, y + 1, w, 10, "rgba(0,0,0,.30)"); // gölge
    rect(ctx, x, y, w, 10, active ? PAL.o : "#3b4658");
    rect(ctx, x, y, w, 1, active ? "#f0b070" : "#4d5a6e");
    rect(ctx, x, y + 9, w, 1, PAL.D);
    drawText(ctx, zone.label, x + 3, y + 2, active ? PAL.D : "#d8d2c4", 1);
  }

  // Tabela katmanı: drawCharacter'dan SONRA çağrılır (tabela hiçbir zaman karakter/masa altında kalmaz)
  function drawSigns(ctx, state) {
    const inZone = state.target || state.zone || "desk";
    ZONES.forEach((z) => drawSign(ctx, z, z.key === inZone));
  }

  // --- gündüz / gün batımı / gece: yerel saate göre ton ve gökyüzü (saf fonksiyon, test edilebilir) ---
  function dayPhase(hour) {
    const h = Number(hour);
    const v = h >= 0 && h < 24 ? Math.floor(h) : 12; // geçersiz saat → gündüz varsayılanı
    if (v >= 6 && v < 18) return "day";
    if (v >= 18 && v < 20) return "sunset";
    return "night";
  }

  // Saat dilimine göre duvar ve pencere renkleri (06-18 gündüz, 18-20 gün batımı, gerisi gece)
  function skyPalette(phase) {
    if (phase === "day") {
      return {
        wall: ["#2a3546", "#253041", "#28344a"], // ana, doku çizgisi, dikey çizgi
        strip: ["#38465c", "#42526b"],
        sky: ["#5ba7dd", "#7cc0ea", "#dcf0ff"],
        dir: "day",
      };
    }
    if (phase === "sunset") {
      return {
        wall: ["#332e3d", "#2d2937", "#312c3f"],
        strip: ["#463c4c", "#57475a"],
        sky: ["#d97b3a", "#f0a85a", "#6b4a6e"],
        dir: "sunset",
      };
    }
    return { wall: ["#252e3b", "#202834", "#222b37"], strip: ["#303a4a", "#3a4557"], sky: ["#12243d"], dir: "night" };
  }

  // Pencere içi: gündüz mavi gökyüzü + güneş/bulut, gün batımı turuncu + alçak güneş, gece ay + yıldız
  function drawWindowSky(ctx, dir, sky) {
    rect(ctx, 14, 20, 40, 28, sky[0]);
    if (dir === "day") {
      rect(ctx, 14, 20, 40, 10, sky[1]);
      rect(ctx, 14, 20, 40, 4, sky[2]);
      // güneş (sağ üst köşe) + hafif hale
      rect(ctx, 44, 23, 7, 7, "#f6e07a");
      rect(ctx, 45, 22, 5, 9, "#f6e07a");
      rect(ctx, 43, 24, 9, 5, "#f6e07a");
      ctx.fillStyle = "rgba(246,224,122,.16)";
      ctx.beginPath();
      ctx.ellipse(47, 26, 9, 7, 0, 0, Math.PI * 2);
      ctx.fill();
      // iki küçük bulut
      [[20, 27, 10], [30, 33, 8]].forEach(([cx, cy, cw]) => {
        rect(ctx, cx, cy, cw, 3, "#ffffff");
        rect(ctx, cx + 2, cy - 1, cw - 4, 1, "#ffffff");
        rect(ctx, cx, cy + 3, cw, 1, "#cfe3f2");
      });
    } else if (dir === "sunset") {
      rect(ctx, 14, 20, 40, 12, sky[1]);
      rect(ctx, 14, 20, 40, 5, sky[2]);
      // ufka yakın güneş (turuncu-kızıl disk)
      rect(ctx, 36, 36, 9, 6, "#fbd07a");
      rect(ctx, 37, 35, 7, 8, "#fbd07a");
      rect(ctx, 44, 32, 1, 1, "#ffe3a8");
      rect(ctx, 23, 30, 1, 1, "#ffe3a8");
    } else {
      rect(ctx, 44, 24, 5, 5, "#f2e7c0"); // ay
      rect(ctx, 45, 23, 3, 7, "#f2e7c0");
      rect(ctx, 43, 25, 7, 3, "#f2e7c0");
      [[18, 24], [25, 27], [36, 24], [20, 30], [40, 30], [48, 34], [34, 30]].forEach(([sx, sy], i) =>
        rect(ctx, sx, sy, i % 3 === 0 ? 2 : 1, i % 3 === 0 ? 1 : 2, "#cfd8e6"));
    }
    rect(ctx, 30, 22, 1, 26, "#3b4657"); // kanat ayırıcı
    rect(ctx, 14, 34, 40, 1, "#3b4657");
  }

  // Tavan lambası: "on" → sarı ampul + iki yumuşak hale; "off" → sönük ampul (sahne kararır)
  function drawLamp(ctx, mode) {
    const on = mode !== "off";
    rect(ctx, 116, 4, 12, 2, on ? "#e7c65a" : "#4a4a44");
    rect(ctx, 116, 4, 12, 1, on ? "#f6e6a8" : "#5a5a50");
    if (!on) return;
    ctx.fillStyle = "rgba(231,198,90,.10)";
    ctx.beginPath();
    ctx.moveTo(114, 6);
    ctx.lineTo(130, 6);
    ctx.lineTo(186, 92);
    ctx.lineTo(58, 92);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = "rgba(231,198,90,.08)";
    ctx.beginPath();
    ctx.ellipse(122, 94, 54, 7, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "rgba(231,198,90,.06)";
    ctx.beginPath();
    ctx.ellipse(122, 58, 60, 38, 0, 0, Math.PI * 2);
    ctx.fill();
  }

  // --- sahne katmanı: saat dilimi başına bir kez çizilir, kare başına yeniden çizilmez ---
  function drawScene(ctx, phase) {
    const pal = skyPalette(dayPhase(phase));
    // duvar: saat dilimine göre tonlu panel dokusu
    rect(ctx, 0, 0, W, 92, pal.wall[0]);
    for (let y = 0; y < 92; y += 8) {
      rect(ctx, 0, y, W, 1, pal.wall[1]);
      const off = (y / 8) % 2 ? 8 : 0;
      for (let x = off; x < W; x += 16) rect(ctx, x, y, 1, 8, pal.wall[2]);
    }
    rect(ctx, 0, 58, W, 2, pal.strip[0]); // lambri bandı
    rect(ctx, 0, 58, W, 1, pal.strip[1]);

    // zemin: parke döşeme (ızgara + dama deseni), üstte süpürgelik
    rect(ctx, 0, 92, W, H - 92, "#2f3a49");
    rect(ctx, 0, 92, W, 1, "#8a6136");
    rect(ctx, 0, 93, W, 1, "#1c232e");
    for (let y = 96; y < H; y += 8) {
      rect(ctx, 0, y, W, 1, "#28323f");
      const off = ((y - 96) / 8) % 2 ? 8 : 0;
      for (let x = off; x < W; x += 16) rect(ctx, x, y - 7, 1, 7, "#28323f");
    }
    for (let y = 96; y < H; y += 8) {
      for (let x = 0; x < W; x += 16) {
        if ((x / 16 + y / 8) % 2 === 0) rect(ctx, x, y, 16, 8, "#323e4e");
      }
    }
    // halı (karakterin masası çevresi): sıcak tonlu, desenli
    rect(ctx, 100, 98, 96, 11, "#4a3a34");
    rect(ctx, 102, 100, 92, 7, "#6b4a3a");
    for (let i = 0; i < 11; i++) rect(ctx, 105 + i * 8, 103, 4, 1, "#c98a4e");

    // pencereli duvar (sol üst): gökyüzü saat dilimine göre çizilir
    rect(ctx, 12, 18, 44, 32, "#161d28"); // çerçeve
    drawWindowSky(ctx, pal.dir, pal.sky);
    // şehir silueti + ışıklı pencereler
    rect(ctx, 14, 41, 40, 7, "#0b1420");
    [[16, 43, 6], [24, 39, 7], [33, 44, 5], [40, 41, 7], [48, 46, 6]].forEach(([tx, ty, tw], i) => {
      rect(ctx, tx, ty, tw, 48 - ty, "#16233a");
      for (let k = 0; k < 3; k++) rect(ctx, tx + 1 + ((i + k) % 2), ty + 1 + (k % 2) * 2, 1, 1, k % 2 ? "#e7c65a" : "#8fb7d6");
    });
    // denizlik
    rect(ctx, 10, 48, 48, 3, "#5a6472");
    rect(ctx, 10, 48, 48, 1, "#7d8796");

    // tavan lambası (üst orta) + yumuşak ışık halesi
    rect(ctx, 121, 0, 2, 2, "#3b4657");
    rect(ctx, 114, 2, 16, 2, PAL.D);
    drawLamp(ctx, "on");

    // üstte beyaz tahta (görev durumu + sayaçlar; yazı drawBoard ile her karede basılır)
    rect(ctx, 58, 4, 144, 27, "#5a6472");
    rect(ctx, 59, 5, 142, 25, "#2a2018");
    rect(ctx, 62, 8, 136, 19, "#e6e8df");
    rect(ctx, 62, 8, 136, 1, PAL.w);
    rect(ctx, 62, 26, 136, 1, "#b9b3a3");
    rect(ctx, 190, 22, 8, 3, PAL.o); // tahta kalemi

    // sol: kitaplık
    rect(ctx, 4, 54, 54, 40, PAL.B);
    rect(ctx, 4, 54, 54, 2, "#c9a074");
    rect(ctx, 4, 54, 1, 40, PAL.j);
    for (let shelf = 0; shelf < 2; shelf++) {
      const y = 57 + shelf * 18;
      rect(ctx, 6, y, 50, 16, "#3a2c1f");
      const books = [PAL.r, PAL.g, PAL.c, PAL.y, PAL.p, PAL.o];
      for (let i = 0; i < 9; i++) {
        const bh = 9 + ((i * 5 + shelf) % 4);
        rect(ctx, 7 + i * 5 + (i > 7 ? 1 : 0), y + 15 - bh, 4, bh, books[(i + shelf) % books.length]);
        rect(ctx, 7 + i * 5 + (i > 7 ? 1 : 0), y + 15 - bh, 4, 1, "rgba(255,255,255,.25)");
      }
      rect(ctx, 6, y + 15, 50, 1, "#d8b48a");
    }

    // orta: atölye tezgâhı
    rect(ctx, 76, 74, 66, 5, PAL.b);
    rect(ctx, 76, 74, 66, 1, "#d8b48a");
    rect(ctx, 78, 79, 3, 20, PAL.B);
    rect(ctx, 137, 79, 3, 20, PAL.B);
    rect(ctx, 80, 84, 58, 2, PAL.j);
    rect(ctx, 82, 68, 20, 6, PAL.m); // alet kutusu
    rect(ctx, 82, 67, 20, 1, PAL.M);
    rect(ctx, 84, 70, 12, 1, PAL.o);
    rect(ctx, 128, 71, 10, 2, PAL.W); // kâğıt
    rect(ctx, 88, 88, 8, 5, PAL.d);
    rect(ctx, 102, 89, 14, 4, PAL.g);
    rect(ctx, 102, 89, 14, 1, "#7dbd8f");
    rect(ctx, 120, 71, 6, 2, PAL.c); // cetvel

    // sağ: test tezgâhı + monitör
    rect(ctx, 176, 74, 58, 4, PAL.b);
    rect(ctx, 176, 74, 58, 1, "#d8b48a");
    rect(ctx, 178, 78, 3, 21, PAL.B);
    rect(ctx, 229, 78, 3, 21, PAL.B);
    rect(ctx, 186, 54, 34, 17, PAL.D); // ekran çerçevesi
    rect(ctx, 188, 56, 30, 13, "#16221d");
    rect(ctx, 196, 71, 14, 2, PAL.M); // ayak
    rect(ctx, 192, 47, 22, 6, "#3b4658"); // monitör arkası
    rect(ctx, 192, 47, 22, 1, PAL.M);

    // orta sağ: postane kutusu
    rect(ctx, 210, 128, 34, 20, "#6b4f3a");
    rect(ctx, 210, 128, 34, 2, "#8a6a4f");
    rect(ctx, 212, 132, 14, 14, "#5a3f2d");
    rect(ctx, 228, 132, 14, 14, "#5a3f2d");
    rect(ctx, 216, 136, 6, 1, PAL.y);
    rect(ctx, 232, 136, 6, 1, PAL.y);
    rect(ctx, 219, 122, 16, 5, PAL.w); // mektup
    rect(ctx, 225, 121, 4, 1, PAL.p);
    rect(ctx, 226, 122, 1, 5, "#cfc8b8");

    // sol alt: hafıza dolabı
    rect(ctx, 6, 112, 34, 36, PAL.M);
    rect(ctx, 6, 112, 34, 1, "#8f9aaa");
    rect(ctx, 8, 115, 30, 9, "#6f7a88");
    rect(ctx, 8, 126, 30, 9, "#6f7a88");
    rect(ctx, 8, 137, 30, 9, "#6f7a88");
    rect(ctx, 24, 118, 3, 2, PAL.o);
    rect(ctx, 24, 129, 3, 2, PAL.o);
    rect(ctx, 24, 140, 3, 2, PAL.o);

    // orta: masası (karakterin evi)
    rect(ctx, 114, 100, 32, 5, PAL.b);
    rect(ctx, 114, 100, 32, 1, "#d8b48a");
    rect(ctx, 116, 105, 3, 13, PAL.B);
    rect(ctx, 141, 105, 3, 13, PAL.B);
    rect(ctx, 119, 96, 10, 4, PAL.w); // defter
    rect(ctx, 121, 97, 6, 1, PAL.c);
    rect(ctx, 133, 93, 4, 7, PAL.o); // fincan
    rect(ctx, 134, 92, 2, 1, "#f2c69a");

    // sağ alt: saksı bitkisi
    rect(ctx, 236, 136, 12, 11, "#8a5a3c");
    rect(ctx, 235, 134, 14, 3, "#a06a48");
    rect(ctx, 238, 135, 10, 1, "#5a3a24");
    rect(ctx, 241, 128, 1, 8, "#2f6b45");
    [[239, 130, PAL.g], [244, 131, PAL.G], [236, 127, PAL.g], [246, 125, PAL.g], [241, 122, PAL.G]].forEach(([lx, ly, lc]) =>
      rect(ctx, lx, ly, 4, 4, lc));

    // gölgeler
    ctx.fillStyle = "rgba(0,0,0,.35)";
    ctx.beginPath();
    ctx.ellipse(138, 127, 9, 3, 0, 0, Math.PI * 2);
    ctx.fill();
  }

  // --- ikincil animasyonlu parçalar ---
  function drawBooks(ctx, frame, active) {
    // kitaplıktan yukarı süzülen kitap: yalnız kitaplıkta çalışırken
    if (!active) return;
    const phase = (frame % 24) / 24;
    const bx = 34 + Math.round(Math.sin(phase * Math.PI * 2) * 8);
    const by = 50 - Math.round(phase * 10);
    rect(ctx, bx, by, 4, 5, PAL.c);
    rect(ctx, bx, by, 4, 1, "#cfe4f4");
  }

  function drawScreen(ctx, frame, testState) {
    // testState: "pass" → yeşil, "fail" → kırmızı, "run" → kayan yeşil satırlar
    let col = "#183a28";
    let lineCol = "#2f6b45";
    if (testState === "fail") {
      col = "#3a1a18";
      lineCol = PAL.r;
    } else if (testState === "pass") {
      col = frame % 2 ? "#245c3a" : "#1e4a30";
      lineCol = "#a6e8bf";
    } else if (testState === "run") {
      col = "#1a4030";
      lineCol = "#7fd39c";
    }
    rect(ctx, 188, 56, 30, 13, col);
    for (let y = 0; y < 5; y++) {
      const wl = 22 - ((y + (testState === "run" ? frame : 0)) % 3) * 6;
      rect(ctx, 190, 58 + y * 2, Math.max(4, wl), 1, lineCol);
    }
    if (testState === "fail") drawText(ctx, "!", 210, 57, PAL.w, 1);
    if (testState === "pass") drawText(ctx, "OK", 202, 57, "#dff3e6", 1);
  }

  // mode: "work" | "coffee" | "sleep" | "lamp" (yalnız cosmetic; drawOffice'e enjekte edilir)
  function drawOffice(ctx, state, frame, moving, mode) {
    const inZone = state.target || state.zone || "desk";
    const busy = state.status === "running" || state.status === "awaiting";
    const away = mode === "sleep" || mode === "coffee";
    drawBooks(ctx, frame, inZone === "library" && busy && !moving && !away);
    let testState = "idle";
    if (inZone === "testbench" && busy) {
      testState = state.mood === "alert" && !state.hand ? "fail" : "run";
    }
    if (inZone === "testbench" && state.ended === "done") testState = "pass";
    drawScreen(ctx, frame, testState);
    if (inZone === "post" && !moving && !away) {
      // mektup kutudan yukarı süzülür
      const lift = busy ? frame % 3 : state.ended === "done" ? 0 : 0;
      rect(ctx, 219, 122 - lift, 16, 5, PAL.w);
      rect(ctx, 226, 122 - lift, 1, 5, "#cfc8b8");
      rect(ctx, 225, 121 - lift, 4, 1, PAL.p);
    }
    if (inZone === "memory" && busy && !moving && !away) {
      const led = frame % 6 < 3;
      rect(ctx, 24, 129, 3, 2, led ? PAL.y : PAL.o);
    }
  }

  // Tahta yazısı: görev durumu (üst satır) + kısa sayaçlar (alt satır); her karede tazelenir
  function drawBoard(ctx, state) {
    if (!ctx || !state || !state.counts) return;
    const STATUS = { idle: "HAZIR", running: "ÇALIŞIYOR", awaiting: "ONAY BEKLİYOR", done: "BİTTİ", failed: "BAŞARISIZ", cancelled: "İPTAL" };
    // her iki satır ölçek 1, 5x7 font: 7 px yükseklik, aralarında 2 px boşluk → 8..16 ve 18..24 (iç alan 8..26)
    const maxW = BOARD_IN_W;
    // satır başına en çok 22 karakter (136 px / 6 px); sayaç satırı ≤19 olduğu için kesilmez
    const maxChars = 22;
    const line1 = fitLine(STATUS[state.status] || state.status || "", maxW, 1, maxChars);
    // sayaçlar kısa biçimde (A araç, D düzenleme, T test geçti/kaldı); sığmazsa kesilir, tahta dışına çizilmez
    const line2 = fitLine(String(Logic.shortCounters ? Logic.shortCounters(state) : ""), maxW, 1, maxChars);
    const y1 = BOARD_IN_Y + 1;
    const y2 = y1 + 7 + 2;
    const col = state.status === "failed" || state.status === "cancelled" ? "#8c2f24" : state.status === "done" ? "#1f5f3a" : "#23282e";
    const c1 = Math.max(BOARD_IN_X, BOARD_IN_X + Math.round((maxW - textWidth(line1, 1)) / 2));
    const c2 = Math.max(BOARD_IN_X, BOARD_IN_X + Math.round((maxW - textWidth(line2, 1)) / 2));
    drawText(ctx, line1, c1, y1, col, 1); // ortalı
    drawText(ctx, line2, c2, y2, "#3c4652", 1); // ortalı
  }

  // --- karakter ---
  function charPos(state, progress) {
    const spots = {
      // y = sprite'ın üst kenarı (24 px boy → ayaklar y + 24)
      desk: { x: 122, y: 104 },
      library: { x: 62, y: 106 },
      workshop: { x: 101, y: 76 },
      testbench: { x: 198, y: 76 },
      post: { x: 202, y: 108 },
      memory: { x: 42, y: 106 },
    };
    const to = spots[state.target] || spots.desk;
    const from = spots[state.zone] || to;
    return {
      x: Math.round(from.x + (to.x - from.x) * progress),
      y: Math.round(from.y + (to.y - from.y) * progress),
      dx: to.x - from.x,
      dy: to.y - from.y,
    };
  }

  function drawCharacter(ctx, state, frame, pos, moving) {
    const bouncing = state.status === "done" && state.mood === "happy" && !state.hand && frame % 2 === 0;
    const breathe = moving ? 0 : frame % 2 === 0 ? 0 : 1; // bekleyince 1 px nefes
    // 0: duruyor, 1-3: dört karelik yürüyüş döngüsü
    const legs = moving ? 1 + (frame % 4) % 3 : 0;
    const x = pos.x, y = pos.y - (bouncing ? 2 : 0) + breathe;
    const canvas = SPRITES[`char-${legs}`];
    const zone = moving ? state.zone : state.target;
    // ayak gölgesi (yumuşak elips)
    ctx.fillStyle = "rgba(0,0,0,.34)";
    ctx.beginPath();
    ctx.ellipse(x + CHAR_W / 2, pos.y + CHAR_H, 8, 2.5, 0, 0, Math.PI * 2);
    ctx.fill();
    const up = armsUp(state) && !moving; // görev başarıyla bitti → kollar havada
    if (up) {
      // kollar havada: omuzdan yukarı (gövde y..y+22; yüz y+3..y+8 → eller başın iki yanında y+3..y+10)
      rect(ctx, x + 1, y + 10, 3, 5, PAL.o); // sol kol yukarı
      rect(ctx, x + 1, y + 7, 3, 3, PAL.s);
      rect(ctx, x + 12, y + 10, 3, 5, PAL.o); // sağ kol yukarı
      rect(ctx, x + 12, y + 7, 3, 3, PAL.s);
    } else if (state.hand) {
      // el kaldırma: başın yanında görünen kol + ten el
      rect(ctx, x + (pos.dx >= 0 ? 13 : 1), y + 9, 3, 6, PAL.o);
      rect(ctx, x + (pos.dx >= 0 ? 13 : 1), y + 6, 3, 3, PAL.s);
    } else if (zone === "workshop" && !moving && (state.status === "running" || state.status === "awaiting")) {
      const up = frame % 2 === 0;
      rect(ctx, x + 13, y + (up ? 8 : 13), 2, 6, PAL.j);
      rect(ctx, x + 12, y + (up ? 5 : 16), 4, 3, PAL.m);
    } else if (zone === "library" && !moving && state.status === "running") {
      rect(ctx, x - 3, y + 11, 4, 4, frame % 2 === 0 ? PAL.c : PAL.y);
    }
    if (moving) rect(ctx, x + 6, y + 22, 4, 2, PAL.k); // bacak ayrımı vurgusu
    ctx.drawImage(canvas, x, y);
    if (state.mood === "sad") {
      // üzgün: ağız aşağı, omuzlar çökük
      rect(ctx, x + 7, y + 8, 3, 1, PAL.S);
      rect(ctx, x + 5, y + 7, 1, 1, PAL.S);
      rect(ctx, x + 11, y + 7, 1, 1, PAL.S);
    } else if (state.mood === "happy") {
      rect(ctx, x + 7, y + 8, 3, 1, PAL.O);
    }
    if (up) {
      // kollar havada: iki yanda küçük "kutlama" çizgileri (ellerin üstünde, y+4..y+7)
      rect(ctx, x - 3, y + 4, 1, 3, PAL.y);
      rect(ctx, x + CHAR_W + 2, y + 4, 1, 3, PAL.y);
    }
  }

  // --- balon: metin her zaman yazıyla (renk tek başına anlam taşımaz) ---
  function wrap(text, max) {
    const words = String(text || "").split(" ");
    const lines = [];
    let cur = "";
    for (const w of words) {
      const next = cur ? cur + " " + w : w;
      if (next.length > max && cur) {
        lines.push(cur);
        cur = w.slice(0, max);
      } else cur = next;
    }
    if (cur) lines.push(cur);
    return lines;
  }

  const BUB_MAX_W = 156; // mantıksal px (balon kutusu üst sınırı)
  const BUB_FONT = 1; // piksel font 5x7 → 1x: küçük balon, sahneyi örtmez
  const BUB_MAX_CHARS = 28; // satır başına en çok karakter
  const BUB_MAX_LINES = 2; // en çok iki satır; uzunsa "…" ile kesilir
  const BUB_LINE_H = 7 * BUB_FONT + 2; // satır yüksekliği
  const BUB_PAD = 3; // iç boşluk

  // Metni en çok max satıra böler; taşan kısmı "…" ile keser
  function bubbleLines(text, max, maxLines) {
    const clean = String(text || "").replace(/\s+/g, " ").trim();
    if (!clean) return [];
    const all = wrap(clean, max, maxLines + 1);
    const lines = all.slice(0, maxLines);
    const truncated = all.length > maxLines;
    if (truncated && lines.length) {
      // taşan kısım varsa son satırı "…" ile kes
      lines[lines.length - 1] = lines[lines.length - 1].slice(0, Math.max(1, max - 1)).trimEnd() + "…";
    }
    return lines;
  }

  function drawChar(ctx, ch, x, y, s, layer) {
    // yumuşak gölge katmanı: her bit 1 px sağa/aşağıya kaydırılarak yarı saydam basılır
    const g = glyph(ch);
    ctx.fillStyle = layer;
    const gx = x + (layer === "shadow" ? 1 : 0);
    const gy = y + (layer === "shadow" ? 1 : 0);
    for (let row = 0; row < 7; row++) {
      const bits = g[row];
      for (let b = 0; b < 5; b++) {
        if (bits & (1 << (4 - b))) ctx.fillRect(gx + b * s, gy + row * s, s, s);
      }
    }
    return true;
  }

  // Metni TEK KEZ basar (gölge/çift katman yok); balon metni bulanık görünmesin
  function drawBigText(ctx, s, x, y, ink) {
    ctx.fillStyle = ink;
    for (let i = 0; i < s.length; i++) drawChar(ctx, s[i], x + i * 6 * BUB_FONT, y, BUB_FONT, "ink");
  }

  function drawBubble(ctx, state) {
    const text = state.bubble;
    if (!text) return;
    const lines = bubbleLines(text, BUB_MAX_CHARS, BUB_MAX_LINES);
    if (!lines.length) return;
    const anchor = charPos(state, 1);
    const head = anchor.y - 1; // başın hemen üstü (karakterin üst kenarı)
    const widest = Math.max.apply(null, lines.map((l) => textWidth(l, BUB_FONT)));
    const bw = widest + BUB_PAD * 2; // genişlik: metin + 2x3 px iç boşluk + 2 px kenarlık
    const bh = lines.length * BUB_LINE_H + BUB_PAD * 2;
    // balon karakterin hemen ÜSTÜNDE (alta inmez → masayı/tabelaları örtmez)
    let bx = Math.round(anchor.x + CHAR_W / 2 - bw / 2);
    let by = Math.min(head - 4 - bh, 30); // en fazla y=30'a kadar iner (sahne üst öğeleri korunur)
    bx = Math.max(2, Math.min(W - bw - 2, bx)); // sahne kenarından taşmaz
    by = Math.max(2, by);
    // kutu: yumuşak gölge + koyu çerçeve + krem zemin + tür renkli kenar
    rect(ctx, bx + 1, by + 1, bw, bh, "rgba(0,0,0,.32)");
    rect(ctx, bx, by, bw, bh, PAL.D);
    rect(ctx, bx + 1, by + 1, bw - 2, bh - 2, "#f4efe2");
    const edge = state.bubbleKind === "alarm" ? PAL.r : state.bubbleKind === "ask" ? PAL.o : PAL.k;
    rect(ctx, bx, by, 2, bh, edge);
    rect(ctx, bx + 2, by + 1, bw - 3, 1, "#fffdf6");
    const ink = state.bubbleKind === "alarm" ? "#8c2f24" : "#23282e";
    lines.forEach((l, i) => drawBigText(ctx, l, bx + 2 + BUB_PAD, by + 1 + BUB_PAD + i * BUB_LINE_H, ink));
    // kuyruk: karakterin başına yönelen küçük üçgen (balonun altından)
    const tx = Math.max(bx + 6, Math.min(bx + bw - 8, Math.round(anchor.x + CHAR_W / 2)));
    const bot = by + bh;
    rect(ctx, tx - 2, bot, 5, 1, PAL.D); // kuyruk tabanı
    rect(ctx, tx - 1, bot + 1, 3, 1, PAL.D);
    rect(ctx, tx, bot + 2, 1, 1, PAL.D); // küçük uç: başa doğru
    rect(ctx, tx - 1, bot, 3, 1, "#f4efe2");
  }

  function drawMarker(ctx, state, frame) {
    // hedefteki küçük turuncu ok (aktif bölgeyi işaret eder)
    const p = charPos(state, 1);
    if (frame % 2 === 0) {
      rect(ctx, p.x + 6, p.y - 7, 4, 1, PAL.o);
      rect(ctx, p.x + 7, p.y - 6, 2, 1, PAL.o);
      rect(ctx, p.x + 8, p.y - 5, 1, 1, PAL.y);
    }
  }


  // --- parçacık sistemi: tek küçük yardımcı, kütüphane yok, kare başına en çok 40 parçacık ---
  const FX_CAP = 40; // aynı karede en çok 40 parçacık çizilir
  const CONF_TTL = 1500; // konfeti: 1,5 sn sonra durur
  const COFFEE_MS = 4200; // çay içme süresi
  const ZZZ_MS = 3200; // uyuklama süresi
  const NAP_MS = 20000; // bekleme eşiği: bu kadar sessizlikten sonra uyuklar
  const NAP_GAP_MS = 24000; // uyandıktan sonra tekrar uyuma arası

  // Çay içme anları (tohum ± jitter, hepsi sabit): 6,5 / 15 / 19,3 sn — "ara sıra"
  function coffeeTimes(seed) {
    const j = seed == null ? 0 : mix32(seed) % 5;
    return [6500 + j * 100, 15000 - j * 100, 19300 + j * 50];
  }

  // Deterministik sözde-rastgele: tohum (42) sabit → testte ve tek karede aynı çıktı
  function mix32(seed) {
    let x = (Number(seed) | 0) + 0x6d2b79f5;
    x = Math.imul(x ^ (x >>> 15), x | 1);
    x ^= x + Math.imul(x ^ (x >>> 7), x | 61);
    return (x ^ (x >>> 14)) >>> 0;
  }

  // Konfeti parçacıklarını üretir: az sayıda (12), aynı çağrıda hep aynı (tohum enjekte edilebilir)
  function confettiBits(seed, n) {
    const out = [];
    const cols = [PAL.o, PAL.y, PAL.g, PAL.c, PAL.p];
    const count = Math.max(0, Math.min(FX_CAP, n == null ? 12 : n));
    for (let i = 0; i < count; i++) {
      const r = mix32((seed || 0) * 31 + i * 7 + 3);
      out.push({
        x: 110 + (r % 52),
        vx: ((r >>> 5) % 17) - 8,
        vy: -12 - ((r >>> 9) % 8),
        col: cols[(r >>> 13) % cols.length],
      });
    }
    return out;
  }

  // Sahne efektleri yalnız GERÇEK olaylardan gelen tetikleyicilere (state.fx) tepki verir.
  // Zaman kaynağı enjekte edilir (now) → testte sabit, uydurma zaman yok.
  function createFx() {
    return { seenTest: 0, testAt: -1e9, testKind: "", seenEnd: 0, endAt: -1e9, endKind: "", confetti: [], coffeeAt: -1e9, coffeeSlot: -1, napAt: -1e9, idleAt: -1e9 };
  }

  function fxEvent(fx, state, now) {
    const f = state && state.fx;
    if (!f) return;
    if (f.testSeq && f.testSeq !== fx.seenTest) {
      fx.seenTest = f.testSeq; // yalnız yeni tetikleyici (aynı seq tekrar efekt üretmez)
      fx.testAt = now;
      fx.testKind = f.test;
    }
    if (f.endSeq && f.endSeq !== fx.seenEnd) {
      fx.seenEnd = f.endSeq;
      fx.endAt = now;
      fx.endKind = f.end;
      fx.confetti = f.end === "done" ? confettiBits(f.endSeq, 12) : [];
      if (f.end === "cancelled") fx.coffeeAt = -1e9; // lambayı söndürdü: çay/uyku da durur
    }
  }

  // Cosmetic boş zaman durumu: yalnız `state.idle` iken (görev yok/bitmiş) ve masadayken.
  // Çay "ara sıra" (sabit anlarda), uzun bekleyişte (20 sn+) uyku. Çalışırken hiçbiri.
  function stageMode(state, fx, now, seed) {
    if (state && state.fx && fx.seenEnd && state.fx.endSeq === fx.seenEnd && fx.endKind === "cancelled" && now - fx.endAt >= 0 && now - fx.endAt < 1500) {
      return "lamp"; // iptal: lamba söner gibi kısa kararma
    }
    const idle = !!(state && state.idle) && (state.target || "desk") === "desk";
    if (!idle) {
      fx.idleAt = -1e9; // görev sürüyor: boş zaman sayacı (ve çay anı) sıfırlanır
      fx.napAt = -1e9; // sonraki boş zamanda uyku eşiği baştan sayılır
      fx.coffeeSlot = -1;
      return "work";
    }
    if (fx.idleAt < 0) fx.idleAt = now; // boş zaman başladı (ilk kare)
    const sinceIdle = now - fx.idleAt;
    if (now - fx.coffeeAt >= 0 && now - fx.coffeeAt < COFFEE_MS && fx.coffeeAt >= fx.napAt) return "coffee";
    // uyku yalnız NAP_MS sessizlikten SONRA başlar: eşiğe kadar work/coffee, sonra ZZZ_MS boyunca sleep
    if (sinceIdle >= NAP_MS && now - fx.idleAt < NAP_MS + ZZZ_MS) {
      fx.napAt = fx.idleAt + NAP_MS;
      return "sleep";
    }
    if (sinceIdle >= NAP_MS) {
      const lastNap = fx.napAt > 0 ? fx.napAt : fx.idleAt;
      if (now - lastNap >= NAP_GAP_MS) {
        fx.napAt = now; // uzun bekleme → tekrar uyuklar
        return "sleep";
      }
      return "work";
    }
    const slots = coffeeTimes(seed == null ? 42 : seed);
    for (let i = 0; i < slots.length; i++) {
      // yalnız "yeni" içtiğimiz an: geçen son an, son çaydan ilerideyse bir kez
      if (sinceIdle >= slots[i] && (fx.coffeeSlot < 0 || slots[i] > slots[fx.coffeeSlot])) {
        fx.coffeeSlot = i;
        fx.coffeeAt = now;
        return "coffee";
      }
    }
    return "work";
  }

  // Dikdörtgen parçacık: en fazla FX_CAP tanesi çizilir (sahne boğulmaz)
  function drawParts(ctx, parts) {
    const n = Math.min(parts.length, FX_CAP);
    for (let i = 0; i < n; i++) {
      const p = parts[i];
      rect(ctx, Math.round(p.x), Math.round(p.y), p.s || 1, p.s || 1, p.col);
    }
  }

  // Konfeti: görev başarıyla bittiğinde 1,5 sn yağar, sonra durur
  function confettiParts(fx, now) {
    const age = now - fx.endAt;
    if (fx.endKind !== "done" || !(age >= 0 && age < CONF_TTL)) return [];
    const pieces = [];
    for (const b of fx.confetti) {
      const t = age / 1000;
      const y = 44 + b.vy * t + 46 * t * t;
      if (y > 130) continue; // yere düşen parçacık kaybolur
      pieces.push({ x: b.x + b.vx * t, y, col: b.col, s: age > CONF_TTL - 400 ? 1 : 2 });
    }
    return pieces;
  }

  // Karakterin başı üstündeki küçük efektler: test sonucu ✓/ünlem, bitti konfeti başlangıcı
  function successParts(fx, pivot, now) {
    const age = now - fx.testAt;
    if (fx.testKind !== "pass" || !(age >= 0 && age < 900)) return [];
    const pieces = [];
    const head = { x: pivot.x + 8, y: pivot.y - 4 };
    for (let i = 0; i < 6; i++) {
      const r = mix32(fx.seenTest * 17 + i * 5);
      const a = ((r % 360) * Math.PI) / 180;
      const d = 3 + ((r >>> 7) % 9) * (age / 900);
      pieces.push({
        x: head.x + Math.cos(a) * d,
        y: head.y + Math.sin(a) * d - age / 220,
        col: i % 2 ? "#a6e8bf" : PAL.g,
        s: 1,
      });
    }
    return pieces;
  }

  function drawSuccessMark(ctx, fx, pivot, now) {
    const age = now - fx.testAt;
    if (!(age >= 0 && age < 1300)) return;
    // küçük yeşil "✓" (5x5 glif, kodla)
    const x = Math.round(pivot.x + 11), y = Math.round(pivot.y - 6);
    const ink = "#7fe0a3";
    rect(ctx, x, y + 3, 1, 1, ink);
    rect(ctx, x + 1, y + 4, 1, 1, ink);
    rect(ctx, x + 2, y + 3, 1, 1, ink);
    rect(ctx, x + 3, y + 2, 1, 1, ink);
    rect(ctx, x + 4, y + 1, 1, 1, ink);
    rect(ctx, x + 5, y, 1, 1, ink);
  }

  // Test kalınca: başın üstünde minik ter damlası + kırmızı ünlem
  function drawFailMark(ctx, fx, pivot, now, frame) {
    const age = now - fx.testAt;
    if (!(age >= 0 && age < 1400)) return;
    const x = Math.round(pivot.x + 11), y = Math.round(pivot.y - 8 + (frame % 2));
    rect(ctx, x + 1, y, 1, 1, PAL.r); // ünlem
    rect(ctx, x + 1, y + 1, 1, 1, PAL.r);
    rect(ctx, x + 1, y + 2, 1, 1, PAL.r);
    rect(ctx, x + 1, y + 4, 1, 1, PAL.r);
    rect(ctx, x - 3, y + 1, 2, 2, "#9fd0ea"); // ter damlası
    rect(ctx, x - 3, y + 3, 1, 1, "#9fd0ea");
  }

  // Üzgün: tepede küçük gri bulut (yavaşça süzülür)
  function drawCloud(ctx, pivot, now) {
    const x = Math.round(pivot.x + 2), y = Math.round(pivot.y - 9 + ((now / 700) | 0) % 2);
    rect(ctx, x, y + 2, 13, 3, "#7d8796");
    rect(ctx, x + 3, y, 7, 2, "#8f99a8");
    rect(ctx, x + 1, y + 5, 3, 1, "#5a6472");
    rect(ctx, x + 7, y + 5, 3, 1, "#5a6472");
  }

  // Çay içme: fincan + yükselen buhar (yalnız cosmetic, yalnız bekleme durumunda)
  function drawCoffee(ctx, pivot, now, frame) {
    const x = Math.round(pivot.x + 13), y = Math.round(pivot.y + 11);
    rect(ctx, x, y, 6, 5, PAL.o); // fincan
    rect(ctx, x, y, 6, 1, "#f0b070");
    rect(ctx, x + 6, y + 1, 2, 2, PAL.o); // kulp
    rect(ctx, x + 1, y - 1, 4, 1, "#6b4a3a"); // çay yüzeyi
    for (let i = 0; i < 3; i++) {
      const ph = ((frame + i * 4) % 12) / 12;
      rect(ctx, x + 1 + i, Math.round(y - 2 - ph * 7), 1, 1, "rgba(230,240,255,.55)");
    }
  }

  // Uyuklama: z z z (soldan sağa yükselir)
  function drawZzz(ctx, pivot, now, frame) {
    const zs = ["z", "z", "z"];
    for (let i = 0; i < 3; i++) {
      const ph = ((frame + i * 5) % 15) / 15;
      const x = Math.round(pivot.x + 9 + i * 4 + ph * 3);
      const y = Math.round(pivot.y - 8 - i * 4 - ph * 5);
      drawText(ctx, zs[i], x, y, "rgba(220,230,245," + (0.8 - ph * 0.5).toFixed(2) + ")", 1);
    }
  }

  // Sahne geneli ekler: ekran parlaması (test geçti/kaldı) ve iptal kararması
  function drawStageFx(ctx, state, fx, now, frame) {
    const sig = !!fx.seenTest; // yalnız gerçek bir test sonucu geldiyse parlama var
    const age = now - fx.testAt;
    if (sig && age >= 0 && age < 900) {
      // test tezgâhı ekranı: geçti → yeşil parlar, kaldı → kırmızı yanıp söner
      const on = fx.testKind === "pass" || frame % 2 === 0;
      if (on) {
        ctx.fillStyle = fx.testKind === "pass" ? "rgba(127,224,163,.30)" : "rgba(207,90,74,.34)";
        ctx.beginPath();
        ctx.moveTo(186, 52);
        ctx.lineTo(222, 52);
        ctx.lineTo(232, 74);
        ctx.lineTo(178, 74);
        ctx.closePath();
        ctx.fill();
      }
    }
    if (state && state.fx && state.fx.endSeq === fx.seenEnd && fx.endKind === "cancelled" && state.fx.end === "cancelled") {
      const cage = now - fx.endAt;
      if (cage >= 0 && cage < 1200) {
        rect(ctx, 0, 0, W, H, "rgba(6,8,14,.42)"); // sahne hafif kararır (lamba söndü)
        drawLamp(ctx, "off");
      }
    }
  }

  // Kollarını kaldırma niyeti: yalnız başarılı bittiğinde
  function armsUp(state) {
    return !!state && state.fx && state.fx.end === "done" && state.status === "done";
  }

  // --- çalışma zamanı ---
  const S = {
    canvas: null,
    ctx: null,
    word: null, // tahta yazısı (aria ve görünür metin)
    live: null,
    scene: null, // statik katman (256x160)
    buf: null, // kare tamponu (256x160)
    state: Logic.initial(),
    raf: 0,
    last: 0,
    frame: 0,
    walkStart: 0,
    prevZone: "desk",
    running: false,
    reduced: false,
    visibleTab: false,
    dirty: true,
    lastDrawn: null,
    fx: createFx(), // efekt/çay/uyku durumu (yalnız gerçek tetikleyicilerle ilerler)
    phase: "", // çizili sahne katmanının saat dilimi
    phaseAt: 0, // saat diliminin son kontrol zamanı (60 sn'de bir yeniden bakılır)
    scenes: {}, // saat dilimi başına statik katman önbelleği
    // --- göstergeler (yalnız DOM; canvas'a çizilmez) ---
    metrics: null, // { token, context, duration, requests, bar, barFill } DÜĞÜMLERİ
    contextWindow: 0, // modelin bağlam penceresi (app.js köprüsü; 0 = bilinmiyor)
    durStart: 0, // görevin başladığı istemci saati (ms)
    durEnd: 0, // görevin bittiği istemci saati (0 = sürüyor)
    durSeq: 0, // süreyi kuran runSeq (reset'te 0 → yeni görevde yeniden başlar)
    durTick: 0, // saniyelik süre çizicisi (yalnız görev sürerken çalışır)
    // --- "Usta'nın son eylemleri" paneli ---
    panel: null, // { toggle, box, list, now } DÜĞÜMLERİ
    panelOpen: false,
    panelSig: "", // son çizilen içerik imzası (gereksiz DOM yazımı yok)
    // --- onay şeridi (yalnız canlı modda ve bekleyen onay kimliği varken) ---
    approval: null, // { box, text, allow, deny } DÜĞÜMLERİ
    approvalId: "", // şeridin bağlı olduğu onay kimliği
    approvalDone: "", // karar sonrası şerit yazısı ("İzin verildi"/"Reddedildi")
    approvalBusy: false,
    approvalDoneTick: 0, // karar sonrası şeridin görünme sayacı
    // --- geçmiş oturum zaman çubuğu ---
    // { events, i, playing, speed, box, play, range, text, rate, tick } DURUMU
    // (ad `replay`; loadReplay/leaveReplay işlevleriyle çakışma yok — ikisi de farklı ad alanında)
    replay: null,
  };

  // Çizici saati parametre olarak alır: yerel saat yalnız burada okunur, mantık saf kalır.
  function localHour(d) {
    try {
      const t = d || new Date();
      const h = t.getHours();
      return typeof h === "number" && h >= 0 && h < 24 ? h : 12;
    } catch (_) {
      return 12;
    }
  }

  function sceneFor(phase, now) {
    const cache = S.scenes || (S.scenes = {});
    if (!cache[phase]) cache[phase] = makeCanvas(W, H, (c) => drawScene(c, phase));
    return cache[phase];
  }

  // Kare zamanı: testte sabit (hooks), tarayıcıda performance.now
  function frameNow(fallback) {
    const hooks = S.hooks;
    if (hooks && typeof hooks.now === "function") return hooks.now();
    if (fallback) return fallback;
    return root.performance && root.performance.now ? root.performance.now() : 0;
  }

  function reduceMotion() {
    try {
      return !!(root.matchMedia && root.matchMedia("(prefers-reduced-motion: reduce)").matches);
    } catch (_) {
      return false;
    }
  }

  function shouldRun() {
    if (!S.canvas || !S.ctx) return false;
    if (S.reduced) return false;
    try {
      if (root.document && root.document.hidden) return false;
    } catch (_) {
      return false;
    }
    return S.visibleTab;
  }

  function sync() {
    const want = shouldRun();
    if (want && !S.running) {
      S.running = true;
      S.last = 0;
      S.raf = root.requestAnimationFrame(loop);
    } else if (!want && S.running) {
      S.running = false;
      if (S.raf) root.cancelAnimationFrame(S.raf);
      S.raf = 0;
    }
    if (!want) drawOnce(true);
  }

  function loop(ts) {
    if (!S.running) return;
    S.raf = root.requestAnimationFrame(loop);
    const interval = 1000 / MAX_FPS;
    if (S.last && ts - S.last < interval - 1) return;
    S.last = ts;
    S.frame = (S.frame + 1) % 1000;
    render(ts);
  }

  function drawOnce(force) {
    const f = S.state.fx || {};
    const key = `${S.frame}|${S.state.bubble}|${S.state.zone}|${S.state.target}|${S.state.status}|${S.state.mood}|${S.state.hand}|${S.state.idle}|${f.seq},${f.testSeq},${f.endSeq}|${S.state.counts.tool_calls},${S.state.counts.edits},${S.state.counts.tests_pass},${S.state.counts.tests_fail}`;
    if (!force && !S.dirty && S.lastDrawn === key) return;
    S.dirty = false;
    S.lastDrawn = key;
    render(0);
  }

  // Mantıksal kare önce 256x160 tampona çizilir; sonra tek seferde tam sayı ölçekle tuvale basılır.
  // Böylece sahne ölçekten bağımsız olarak tuvalin TAMAMINI doldurur.
  function render(ts) {
    const out = S.ctx;
    const ctx = S.buf && S.buf.getContext("2d");
    if (!out || !ctx) return;
    out.imageSmoothingEnabled = false;
    const now = frameNow(ts || 0);
    const hooks = S.hooks || {};
    // saat enjekte edilebilir: testte sabit saat dilimi, tarayıcıda yerel saat (60 sn'de bir bakılır)
    if (!S.phase || now - S.phaseAt > 60000) {
      S.phase = dayPhase(typeof hooks.hour === "function" ? hooks.hour() : localHour());
      S.phaseAt = now;
    }
    fxEvent(S.fx, S.state, now);
    const mode = stageMode(S.state, S.fx, now, hooks.seed == null ? 42 : hooks.seed);
    const progress = Math.min(1, (now - S.walkStart) / WALK_MS);
    const moving = progress < 1 && !S.reduced;
    const asleep = mode === "sleep";
    const f = asleep ? Math.floor(S.frame / 4) : S.frame; // uyurken hareket yavaşlar
    const anim = S.reduced ? 0 : f; // prefers-reduced-motion: animasyon yok (tek kare sabit)
    const pos = charPos(S.state, progress);
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(sceneFor(S.phase, now), 0, 0); // duvar/pencere tonu saate göre
    drawOffice(ctx, S.state, moving ? S.frame : Math.floor(S.frame / 2), moving, mode);
    drawBoard(ctx, S.state);
    drawMarker(ctx, S.state, S.frame);
    drawCharacter(ctx, S.state, S.frame, pos, moving);
    drawSigns(ctx, S.state); // tabelalar karakterden SONRA → karakter/masa tabelayı örtmez
    if (S.reduced) drawBubble(ctx, S.state); // reduce: efekt katmanı yok, balon her zaman görünür
    // --- efekt katmanı (yalnız gerçek olay tetikleyicileri) ---
    if (mode === "coffee") drawCoffee(ctx, pos, now, anim);
    if (asleep) drawZzz(ctx, pos, now, anim);
    drawSuccessMark(ctx, S.fx, pos, now);
    drawFailMark(ctx, S.fx, pos, now, anim);
    if (S.state.mood === "sad" && !armsUp(S.state)) drawCloud(ctx, pos, now);
    if (!S.reduced) {
      // reduce: parçacık/parlama/kararma yok (animasyon yok kuralı) — tek sabit kare
      drawParts(ctx, successParts(S.fx, pos, now));
      drawParts(ctx, confettiParts(S.fx, now));
      drawStageFx(ctx, S.state, S.fx, now, anim);
      drawBubble(ctx, S.state);
    }
    out.drawImage(S.buf, 0, 0, S.canvas.width, S.canvas.height);
  }

  function describe(state) {
    return Logic.describe(state);
  }

  function boardText(state) {
    const STATUS = { idle: "hazır", running: "çalışıyor", awaiting: "onay bekliyor", done: "bitti", failed: "başarısız", cancelled: "iptal" };
    return `Görev: ${STATUS[state.status] || state.status} · ${Logic.countersText(state)}`;
  }

  // --- göstergeler şeridi + eylem paneli (canvas DIŞI, saf DOM: textContent/createElement) ---
  const $id = (id) => (root.document && root.document.getElementById ? root.document.getElementById(id) : null);
  const el = (tag, cls) => {
    const n = root.document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  };
  const nowMs = () => (root.performance && root.performance.now ? root.performance.now() : Date.now());
  const clearIntervalFn = (h) => {
    if (root.clearInterval) root.clearInterval(h);
    else clearTimeout(h);
  };
  const setIntervalFn = (fn, ms) => (root.setInterval ? root.setInterval(fn, ms) : setTimeout(fn, ms));

  function initMetrics() {
    const token = $id("office-metric-token");
    const context = $id("office-metric-context");
    const duration = $id("office-metric-duration");
    const requests = $id("office-metric-requests");
    if (!token || !context || !duration || !requests) return;
    S.metrics = {
      token,
      context,
      duration,
      requests,
      bar: $id("office-bar-context"),
      barFill: $id("office-bar-context-fill"),
    };
  }

  // Süre: görev başından beri geçen saniye; istemci saati burada okunur (mantık saf kalır).
  // Başlangıç/bitiş işaretleri reduce'un runSeq/endSeq alanlarından gelir.
  function durationText(state) {
    const run = state.runSeq || 0;
    if (!run) return Logic.formatDuration(0); // bu görevde `started` görülmedi
    if (S.durSeq !== run) {
      // yeni görev (veya ilk `started`): süre burada başlar
      S.durSeq = run;
      S.durStart = nowMs();
      S.durEnd = 0;
    }
    const stopped = !!state.endSeq; // görev bitti → süre durur (sayaç ilerlemez)
    if (stopped && !S.durEnd) S.durEnd = nowMs();
    const end = S.durEnd || nowMs();
    return Logic.formatDuration((end - S.durStart) / 1000);
  }

  function paintMetrics(state) {
    const m = S.metrics;
    if (!m) return;
    const lines = Logic.metricLines(state.usage, S.contextWindow);
    for (const line of lines) {
      const node = m[line.key];
      if (node && node.textContent !== line.value) node.textContent = line.value;
    }
    const pct = Logic.contextPercent(state.usage && state.usage.context, S.contextWindow);
    if (m.bar && m.barFill) {
      const show = pct != null;
      if (m.bar.hidden === show) m.bar.hidden = !show; // pencere yoksa çubuk gizli, yalnız sayı kalır
      const w = show ? `${pct}%` : "0%";
      if (m.barFill.style.width !== w) m.barFill.style.width = w;
      const level = pct == null ? "" : pct >= 90 ? "high" : pct >= 70 ? "mid" : "";
      if (m.barFill.dataset.level !== level) m.barFill.dataset.level = level;
    }
    const dur = durationText(state);
    if (m.duration.textContent !== dur) m.duration.textContent = dur;
  }

  // Görev sürerken saniyede bir süreyi tazeler (bitince durur; sekme gizliyse de durur).
  function tickDuration() {
    if (!S.metrics) return;
    if (S.state.runSeq && !S.state.endSeq) {
      paintMetrics(S.state);
      if (!S.durTick) S.durTick = setIntervalFn(tickDuration, 1000);
    } else if (S.durTick) {
      clearIntervalFn(S.durTick);
      S.durTick = 0;
      paintMetrics(S.state);
    }
  }

  function paintPanel() {
    const p = S.panel;
    if (!p) return;
    const { lines, now } = Logic.actionLines(S.state);
    const sig = lines.join("\n") + "\n" + now;
    if (S.panelSig === sig) return;
    S.panelSig = sig;
    const items = lines.map((text) => {
      const li = el("li");
      li.textContent = text;
      return li;
    });
    p.list.replaceChildren(...items);
    p.now.textContent = now;
  }

  function setPanel(open) {
    S.panelOpen = !!open;
    const p = S.panel;
    if (!p) return;
    p.box.hidden = !S.panelOpen;
    p.toggle.setAttribute("aria-expanded", S.panelOpen ? "true" : "false");
    if (S.panelOpen) paintPanel();
  }

  function initPanel() {
    const toggle = $id("office-actions-toggle");
    const box = $id("office-actions-panel");
    const list = $id("office-actions-list");
    const now = $id("office-actions-now");
    if (!toggle || !box || !list || !now) return;
    S.panel = { toggle, box, list, now };
    setPanel(false);
    toggle.addEventListener("click", () => setPanel(!S.panelOpen));
    // ek kolaylık: canvas'a tıklamak da paneli açar (asıl yol düğme)
    if (S.canvas) S.canvas.addEventListener("click", () => setPanel(true)); // açıkken yalnız tazelenir, kapanmaz
  }

  function setContextWindow(n) {
    const v = Number(n);
    S.contextWindow = Number.isFinite(v) && v > 0 ? Math.round(v) : 0; // 0 = pencere bilinmiyor
    if (S.metrics) paintMetrics(S.state);
  }

  // --- onay şeridi: app.js'teki MEVCUT karar akışı Office.onDecide ile çağrılır (kopya kod yok) ---
  function initApproval() {
    if (S.approval) return; // ikinci init'te düğüm dinleyicileri yeniden bağlanmaz
    const box = $id("office-approval");
    const text = $id("office-approval-text");
    const allow = $id("office-approval-allow");
    const deny = $id("office-approval-deny");
    if (!box || !text || !allow || !deny) return;
    S.approval = { box, text, allow, deny };
    allow.type = deny.type = "button";
    box.hidden = true;
    allow.addEventListener("click", () => sendDecision("allow"));
    deny.addEventListener("click", () => sendDecision("deny"));
  }

  // Karar: köprü işlevi (app.js `Office.onDecide = (id, decision) => decideApproval(...)`).
  // Dönen metin şeritte gösterilir, sonra şerit kapanır; Akış'taki onay düğmeleri aynı akıştan güncellenir.
  function sendDecision(decision) {
    const id = S.approvalId;
    if (!id || S.approvalBusy) return;
    const fn = root.Office && root.Office.onDecide;
    if (typeof fn !== "function") return; // köprü bağlı değilse istek gönderilmez (uydurma yok)
    S.approvalBusy = true;
    if (S.approval) {
      S.approval.allow.disabled = true;
      S.approval.deny.disabled = true;
    }
    const settle = (msg) => {
      S.approvalBusy = false;
      S.approvalId = "";
      S.approvalDone = msg || "";
      paintApproval();
      if (!S.approvalDone) return;
      if (S.approvalDoneTick) clearTimeout(S.approvalDoneTick);
      // şerit kısa süre sonucu yazar, sonra gizlenir (yeni onay gelirse yeniden açılır)
      S.approvalDoneTick = setTimeout(() => {
        S.approvalDoneTick = 0;
        S.approvalDone = "";
        paintApproval();
      }, 2500);
    };
    let out;
    try {
      out = fn(id, decision);
    } catch (_) {
      settle("Gönderilemedi");
      return;
    }
    if (out && typeof out.then === "function") out.then(settle, () => settle("Gönderilemedi"));
    else settle(decision === "allow" ? "İzin verildi" : "Reddedildi");
  }

  // Şerit yalnız CANLI modda, onay bekleyen kimlik varken (veya karar sonucu kısa süre) görünür.
  function paintApproval() {
    const a = S.approval;
    if (!a) return;
    if (!S.approvalDone && !S.approvalBusy) {
      a.allow.disabled = false;
      a.deny.disabled = false;
    }
    const id = S.approvalId;
    const replaying = !!(S.replay && S.replay.events);
    const show = replaying ? false : !!(S.approvalDone || id); // replay'de onay şeridi ÇIKMAZ
    a.box.hidden = !show;
    const text = S.approvalDone || Logic.approvalLine(S.state); // başlık gerçek onay olayından
    if (a.text.textContent !== text) a.text.textContent = text;
    a.allow.hidden = !!S.approvalDone;
    a.deny.hidden = !!S.approvalDone;
  }

  // Canlı akışta bekleyen onay kimliği değişince şerit bağlanır (replay kendi durumunu gösterir)
  function trackApproval(state) {
    if (S.replay && S.replay.events) return;
    if (state.pendingApprovalId) {
      if (state.pendingApprovalId !== S.approvalId) {
        S.approvalId = state.pendingApprovalId;
        S.approvalDone = "";
      }
    } else if (!S.approvalDone) {
      S.approvalId = ""; // akışta onay çözüldü (auto_approved/denied/done) → şerit kapanır
    }
    paintApproval();
  }

  // --- geçmiş oturum zaman çubuğu: durum saf Logic.replayState ile BAŞTAN hesaplanır ---
  const REPLAY_MS = 700; // olay başına oynatma süresi (hıza bölünür)

  function initReplay() {
    if (S.replay) return; // ikinci init'te düğüm dinleyicileri yeniden bağlanmaz
    const box = $id("office-replay");
    const play = $id("office-replay-play");
    const range = $id("office-replay-range");
    const text = $id("office-replay-text");
    const rate = $id("office-replay-speed");
    if (!box || !play || !range || !text || !rate) return;
    S.replay = { events: null, i: 0, playing: false, speed: 1, box, play, range, text, rate, tick: 0 };
    play.type = rate.type = "button";
    box.hidden = true;
    play.addEventListener("click", () => {
      const r = S.replay;
      if (!r || !r.events) return;
      // sonda oynat → baştan başlar (deterministik: aynı dizi, aynı durumlar)
      if (!r.playing && r.i >= r.events.length) seekReplay(0);
      startPlayback(!r.playing);
    });
    range.addEventListener("input", () => {
      if (!S.replay || !S.replay.events) return;
      const want = Math.round(Number(range.value) || 0); // önce oku: stopPlayback çubuğu r.i'ye geri boyar
      stopPlayback();
      seekReplay(want);
    });
    rate.addEventListener("click", () => {
      const r = S.replay;
      if (!r) return;
      r.speed = r.speed === 1 ? 2 : r.speed === 2 ? 4 : 1;
      rate.textContent = `${r.speed}x`;
      rate.setAttribute("aria-label", `Oynatma hızı: ${r.speed}x (değiştir)`);
      if (r.playing) startPlayback(true); // yeni hızla yeniden zamanlanır
    });
    rate.textContent = "1x";
    rate.setAttribute("aria-label", "Oynatma hızı: 1x (değiştir)");
  }

  function replayPaint() {
    const r = S.replay;
    if (!r || !r.events) return;
    const n = r.events.length;
    if (r.range.max !== String(n)) r.range.max = String(n);
    if (r.range.value !== String(r.i)) r.range.value = String(r.i);
    const label = `Olay ${r.i} / ${n}`;
    if (r.text.textContent !== label) r.text.textContent = label;
    const playText = r.playing ? "⏸ Duraklat" : "▶ Oynat";
    if (r.play.textContent !== playText) r.play.textContent = playText;
    r.play.setAttribute("aria-pressed", r.playing ? "true" : "false");
    r.play.setAttribute("aria-label", r.playing ? "Oynatmayı duraklat" : "Oynatmayı başlat");
  }

  // Çubuğu i. olaya sar: durum olay dizisine BAŞTAN uygulanarak hesaplanır (saf, tekrarlanabilir)
  function seekReplay(i) {
    const r = S.replay;
    if (!r || !r.events) return;
    const n = r.events.length;
    const raw = Math.floor(Number(i));
    r.i = !Number.isFinite(raw) ? 0 : Math.min(n, Math.max(0, raw));
    applyState(Logic.replayState(r.events, r.i));
    replayPaint();
  }

  function startPlayback(on) {
    const r = S.replay;
    if (!r) return;
    if (!on) return stopPlayback();
    if (S.reduced) {
      // prefers-reduced-motion: otomatik oynatma YOK (yalnız çubukla gezinme)
      r.playing = false;
      replayPaint();
      return;
    }
    r.playing = true;
    if (r.tick) clearIntervalFn(r.tick);
    r.tick = setIntervalFn(replayStep, Math.max(50, Math.round(REPLAY_MS / r.speed)));
    replayPaint();
  }

  function replayStep() {
    const r = S.replay;
    if (!r || !r.playing) return;
    if (r.i >= r.events.length) return stopPlayback(); // sonda durur
    seekReplay(r.i + 1);
    if (r.i >= r.events.length) stopPlayback();
  }

  function stopPlayback() {
    const r = S.replay;
    if (!r) return;
    r.playing = false;
    if (r.tick) clearIntervalFn(r.tick);
    r.tick = 0;
    replayPaint();
  }

  function loadReplay(events) {
    const r = S.replay;
    if (!r) return;
    const list = Array.isArray(events) ? events.slice() : []; // app.js'in dizisi paylaşılmaz
    r.events = list;
    r.i = 0;
    stopPlayback();
    r.box.hidden = false; // yalnız replay modunda görünür
    S.approvalId = ""; // geçmiş kararı değiştirilemez → onay şeridi ÇIKMAZ
    S.approvalDone = "";
    paintApproval();
    applyState(Logic.replayState(list, 0));
    replayPaint();
    startPlayback(true); // otomatik oynatma; reduced-motion'da başlamaz
  }

  function leaveReplay() {
    const r = S.replay;
    if (!r) return;
    stopPlayback();
    r.events = null;
    r.i = 0;
    r.box.hidden = true; // canlı mod aynen döner
    S.approvalId = "";
    S.approvalDone = "";
    paintApproval();
  }

  function updateText() {
    const line = describe(S.state);
    if (S.live && S.live.textContent !== line) S.live.textContent = line;
    const board = boardText(S.state);
    if (S.word && S.word.textContent !== board) S.word.textContent = board;
    if (S.canvas) {
      const label = `Usta ofis animasyonu. ${line}. ${board}`;
      if (S.canvas.getAttribute("aria-label") !== label) S.canvas.setAttribute("aria-label", label);
    }
    paintMetrics(S.state); // göstergeler yalnız olayla değişir (token/bağlam/istek)
    tickDuration(); // süre çizicisi yalnız görev sürerken ayakta kalır
    if (S.panelOpen) paintPanel(); // panel kapalıyken DOM'a yazılmaz (gürültü yok)
    paintApproval(); // onay şeridi başlığı güncel durumdan gelir
  }

  function fit() {
    if (!S.canvas) return;
    const stage = (root.document && root.document.getElementById("office-stage")) || S.canvas.parentElement;
    const box = S.canvas.parentElement || stage;
    const pad = 2;
    const stageW = (stage && stage.clientWidth ? stage.clientWidth : 0) - pad * 2;
    const cssW = Math.max(W, stageW > 0 ? stageW : box && box.clientWidth ? box.clientWidth : W * MIN_SCALE);
    // görünür yük: sekme panelinin geri kalanı (canlı satır + tahta + not) düşülür
    let avail = box && box.clientHeight ? box.clientHeight : 0;
    const panel = root.document && root.document.getElementById ? root.document.getElementById("office") : null;
    if (panel && panel.clientHeight) avail = Math.max(avail, panel.clientHeight - 110);
    const scaleW = Math.floor(cssW / W);
    const scaleH = avail > 0 ? Math.floor((avail - pad * 2) / H) : scaleW;
    let scale = Math.min(scaleW, scaleH > 0 ? scaleH : scaleW);
    if (!(scale >= 1)) scale = 1;
    scale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, scale)); // en az 3x; dar ekranda CSS max-width taşmayı önler
    const w = W * scale, h = H * scale;
    if (S.canvas.width !== w || S.canvas.height !== h) {
      S.canvas.width = w;
      S.canvas.height = h;
    }
    S.canvas.style.width = `${w}px`;
    S.canvas.style.height = `${h}px`;
    S.canvas.style.maxWidth = "100%"; // dar kapsayıcıda (mobil) taşmaz
    S.ctx = S.canvas.getContext("2d");
    S.dirty = true;
    drawOnce(true);
  }

  // Yeni durumu sahneye uygular: canlı olay (reduce) ve replay (replayState) aynı yoldan geçer.
  function applyState(next) {
    const prev = S.state;
    S.state = next;
    fxEvent(S.fx, next, frameNow(0)); // efekt zamanı olay anından başlar
    if (next.target !== prev.target) S.walkStart = root.performance ? root.performance.now() : 0;
    if (prev.zone !== next.zone) S.prevZone = prev.zone;
    S.dirty = true;
    updateText();
    if (!S.running) drawOnce(false);
    else if (next.target !== prev.target) restartWalk();
  }

  function onEvent(type, data) {
    const prev = S.state;
    applyState(Logic.reduce(prev, type, data || {}));
    trackApproval(S.state); // onay şeridi yalnız bekleyen gerçek kimlikle açılır
  }

  function reset() {
    leaveReplay(); // yeni görev: replay modu ve zaman çubuğu kapanır, canlı mod döner
    S.approvalId = "";
    S.approvalDone = "";
    S.approvalBusy = false;
    paintApproval();
    const prev = S.state;
    S.state = Logic.initial();
    S.fx = createFx(); // efektler ve boş zaman davranışı da sıfırlanır
    S.prevZone = prev.zone || "desk"; // karakter masaya yürür (bölge değişimi animasyonu)
    S.walkStart = 0;
    // göstergeler: yeni görev → süre sıfırdan; yeni görevde ilk `started` süreyi yeniden kurar
    S.durStart = 0;
    S.durEnd = 0;
    S.durSeq = 0;
    S.panelSig = "";
    S.dirty = true;
    updateText();
    if (!S.running) drawOnce(true);
    else restartWalk();
  }

  function restartWalk() {
    S.walkStart = root.performance ? root.performance.now() : 0;
  }

  function setVisible(on) {
    S.visibleTab = !!on;
    if (on) {
      S.dirty = true;
      fit();
      paintMetrics(S.state); // sekme açılınca göstergeler güncel duruma tazelenir
      tickDuration();
    }
    sync();
  }

  function init() {
    S.canvas = root.document ? root.document.getElementById("office-canvas") : null;
    if (!S.canvas) return;
    S.hooks = root.OfficeTestHooks || null; // test: saat/tohum enjeksiyonu (tarayıcıda yok)
    S.live = root.document.getElementById("office-live");
    S.word = root.document.getElementById("office-status");
    initMetrics();
    initPanel();
    initApproval();
    initReplay();
    S.reduced = reduceMotion();
    S.scene = makeCanvas(W, H, drawScene);
    S.buf = makeCanvas(W, H, () => {});
    if (S.buf.getContext) {
      // tahta yazısı statik değil: tampon başlangıçta boş, render her karede üzerine çizer
      const bctx = S.buf.getContext("2d");
      if (bctx) bctx.imageSmoothingEnabled = false;
    }
    S.ctx = S.canvas.getContext("2d");
    fit();
    updateText();
    drawOnce(true);
    try {
      root.document.addEventListener("visibilitychange", sync);
      const mq = root.matchMedia ? root.matchMedia("(prefers-reduced-motion: reduce)") : null;
      if (mq && mq.addEventListener) mq.addEventListener("change", () => {
        S.reduced = reduceMotion();
        sync();
      });
      if (root.ResizeObserver && S.canvas.parentElement) {
        let t = 0;
        const target = root.document.getElementById("office-stage") || S.canvas.parentElement;
        const ro = new root.ResizeObserver(() => {
          clearTimeout(t);
          t = setTimeout(fit, 80);
        });
        ro.observe(target);
        const panel = root.document.getElementById("office");
        if (panel && panel !== target) ro.observe(panel);
      } else {
        root.addEventListener("resize", () => setTimeout(fit, 80));
      }
    } catch (_) {
      /* ortam sınırlı: çizim yine tek kare olarak çalışır */
    }
    sync();
  }

  // Sahte kayıt bağlamı: çizim fonksiyonlarını testte DOM'suz çağırmayı sağlar (yalnız testten)
  function fakeCtx() {
    const ops = [];
    const ctx = {
      ops,
      fillStyle: "",
      imageSmoothingEnabled: false,
      fillRect() {},
      drawImage() {
        ops.push({ k: "img" });
      },
      beginPath() {},
      moveTo() {},
      lineTo() {},
      closePath() {},
      ellipse() {},
      fill() {},
      clearRect() {},
    };
    return ctx;
  }

  // Testte kullanılan iç API: çizim fonksiyonları DOM/gerçek tuval istemez (sahte bağlam yeter).
  const drawApi = {
    dayPhase,
    skyPalette,
    drawScene,
    drawBoard,
    drawOffice,
    drawCharacter,
    drawWindowSky,
    stageMode,
    confettiBits,
    confettiParts,
    replay: () => S.replay, // testte zaman çubuğu durumu (DOM düğümleri yoksa null)
    sendDecision, // testte onay şeridi kararı (köprü Office.onDecide çağrılır)
    mix32,
    createFx,
    fxEvent,
    fakeCtx,
    FX_CAP,
    CONF_TTL,
    NAP_MS,
    COFFEE_MS,
  };

  root.Office = {
    init,
    onEvent,
    reset,
    setVisible,
    setContextWindow, // app.js köprüsü: modelin bağlam penceresi (state.contextWindow)
    loadReplay, // app.js köprüsü: geçmiş oturum olayları [{type,data}] → zaman çubuğu
    leaveReplay, // replay modundan çık (yeni görev / reset ile de kapanır)
    onDecide: null, // app.js köprüsü: onay kararı akışı (decideApproval)
    getState: () => S.state,
    describe,
  };
  root.OfficeDraw = drawApi;
})(typeof globalThis !== "undefined" ? globalThis : this);
