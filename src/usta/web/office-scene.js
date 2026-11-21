// Ofis sahnesinin çizimi: renkler, karakter ve yazı tipleri, gökyüzü ve saat dilimi, sabit sahne katmanı.
// Çalışma zamanı office.js'te; paylaşılan adlar globalThis.UstaOffice (U) üzerinden okunur.
(function () {
  "use strict";
  const U = (globalThis.UstaOffice = globalThis.UstaOffice || {});
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
    { key: "memory", label: "DOLAP", x: 235, y: 149 },
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
    rect(ctx, 0, 0, U.W, 92, pal.wall[0]);
    for (let y = 0; y < 92; y += 8) {
      rect(ctx, 0, y, U.W, 1, pal.wall[1]);
      const off = (y / 8) % 2 ? 8 : 0;
      for (let x = off; x < U.W; x += 16) rect(ctx, x, y, 1, 8, pal.wall[2]);
    }
    rect(ctx, 0, 58, U.W, 2, pal.strip[0]); // lambri bandı
    rect(ctx, 0, 58, U.W, 1, pal.strip[1]);

    // zemin: parke döşeme (ızgara + dama deseni), üstte süpürgelik
    rect(ctx, 0, 92, U.W, U.H - 92, "#2f3a49");
    rect(ctx, 0, 92, U.W, 1, "#8a6136");
    rect(ctx, 0, 93, U.W, 1, "#1c232e");
    for (let y = 96; y < U.H; y += 8) {
      rect(ctx, 0, y, U.W, 1, "#28323f");
      const off = ((y - 96) / 8) % 2 ? 8 : 0;
      for (let x = off; x < U.W; x += 16) rect(ctx, x, y - 7, 1, 7, "#28323f");
    }
    for (let y = 96; y < U.H; y += 8) {
      for (let x = 0; x < U.W; x += 16) {
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

  Object.assign(U, { CHAR_H, CHAR_W, PAL, SPRITES, dayPhase, drawLamp, drawScene, drawSigns, drawText, drawWindowSky, fitLine, glyph, makeCanvas, rect, skyPalette, textWidth });
})();
