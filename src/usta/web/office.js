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
  // Beyaz tahtanın iç (yazı) alanı: drawScene'deki 128x27 çerçeve + 3 px kenar → 68,8 120x19 (iç sınır 187,26)
  const BOARD_IN_X = 68, BOARD_IN_Y = 8, BOARD_IN_W = 120, BOARD_IN_H = 19;

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

  function rect(ctx, x, y, w, h, col) {
    ctx.fillStyle = col;
    ctx.fillRect(x, y, w, h);
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

  function textWidth(s, scale) {
    return String(s).length * (6 * scale) - scale;
  }

  // Satırı maxW genişliğe sığdırır: sığmıyorsa sonuna "…" ekleyip karakter keser (tahta dışına asla çizilmez)
  function fitLine(s, maxW, scale) {
    const str = String(s || "");
    const maxChars = Math.max(1, Math.floor((maxW + scale) / (6 * scale)));
    if (str.length <= maxChars) return str;
    return str.slice(0, Math.max(1, maxChars - 1)).trimEnd() + "…";
  }

  function drawText(ctx, s, x, y, col, scale) {
    scale = scale || 1;
    ctx.fillStyle = col;
    const str = String(s);
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

  // --- sahne katmanı: bir kez çizilir, kare başına yeniden çizilmez ---
  function drawScene(ctx) {
    // duvar: koyu mavi-gri panel dokusu
    rect(ctx, 0, 0, W, 92, "#252e3b");
    for (let y = 0; y < 92; y += 8) {
      rect(ctx, 0, y, W, 1, "#202834");
      const off = (y / 8) % 2 ? 8 : 0;
      for (let x = off; x < W; x += 16) rect(ctx, x, y, 1, 8, "#222b37");
    }
    rect(ctx, 0, 58, W, 2, "#303a4a"); // lambri bandı
    rect(ctx, 0, 58, W, 1, "#3a4557");

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

    // gece pencereli duvar (sol üst)
    rect(ctx, 12, 18, 44, 32, "#161d28"); // çerçeve
    rect(ctx, 14, 20, 40, 28, "#12243d"); // gece göğü
    rect(ctx, 30, 22, 1, 26, "#3b4657"); // kanat ayırıcı
    rect(ctx, 14, 34, 40, 1, "#3b4657");
    // ay
    rect(ctx, 44, 24, 5, 5, "#f2e7c0");
    rect(ctx, 45, 23, 3, 7, "#f2e7c0");
    rect(ctx, 43, 25, 7, 3, "#f2e7c0");
    // yıldızlar
    [[18, 24], [25, 27], [36, 24], [20, 30], [40, 30], [48, 34], [34, 30]].forEach(([sx, sy], i) =>
      rect(ctx, sx, sy, i % 3 === 0 ? 2 : 1, i % 3 === 0 ? 1 : 2, "#cfd8e6"));
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
    rect(ctx, 116, 4, 12, 2, "#e7c65a");
    rect(ctx, 116, 4, 12, 1, "#f6e6a8");
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

    // üstte beyaz tahta (görev durumu + sayaçlar; yazı drawBoard ile her karede basılır)
    rect(ctx, 64, 4, 128, 27, "#5a6472");
    rect(ctx, 65, 5, 126, 25, "#2a2018");
    rect(ctx, 68, 8, 120, 19, "#e6e8df");
    rect(ctx, 68, 8, 120, 1, PAL.w);
    rect(ctx, 68, 26, 120, 1, "#b9b3a3");
    rect(ctx, 168, 22, 8, 3, PAL.o); // tahta kalemi

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

  function drawOffice(ctx, state, frame, moving) {
    const inZone = state.target || state.zone || "desk";
    const busy = state.status === "running" || state.status === "awaiting";
    drawBooks(ctx, frame, inZone === "library" && busy && !moving);
    let testState = "idle";
    if (inZone === "testbench" && busy) {
      testState = state.mood === "alert" && !state.hand ? "fail" : "run";
    }
    if (inZone === "testbench" && state.ended === "done") testState = "pass";
    drawScreen(ctx, frame, testState);
    if (inZone === "post" && !moving) {
      // mektup kutudan yukarı süzülür
      const lift = busy ? frame % 3 : state.ended === "done" ? 0 : 0;
      rect(ctx, 219, 122 - lift, 16, 5, PAL.w);
      rect(ctx, 226, 122 - lift, 1, 5, "#cfc8b8");
      rect(ctx, 225, 121 - lift, 4, 1, PAL.p);
    }
    if (inZone === "memory" && busy && !moving) {
      const led = frame % 6 < 3;
      rect(ctx, 24, 129, 3, 2, led ? PAL.y : PAL.o);
    }
  }

  // Tahta yazısı: görev durumu (üst satır) + sayaçlar (alt satır); her karede tazelenir
  function drawBoard(ctx, state) {
    if (!ctx || !state || !state.counts) return;
    const STATUS = { idle: "HAZIR", running: "ÇALIŞIYOR", awaiting: "ONAY BEKLİYOR", done: "BİTTİ", failed: "BAŞARISIZ", cancelled: "İPTAL" };
    const c = state.counts;
    // her iki satır ölçek 1: 7 px yükseklik, aralarında 2 px boşluk → 8..16 ve 18..24 (iç alan 8..26)
    const maxW = BOARD_IN_W;
    const line1 = fitLine(String(STATUS[state.status] || state.status || ""), maxW, 1);
    // sayaçlar yalnız gerçek olaylardan (Logic.counts); sığmazsa karakter kesilir, tahta dışına çizilmez
    const line2 = fitLine(`ARAÇ ${c.tool_calls} · DÜZ ${c.edits} · TEST ${c.tests_pass}/${c.tests_pass + c.tests_fail}`, maxW, 1);
    const y1 = BOARD_IN_Y + 1;
    const y2 = y1 + 7 + 2;
    const col = state.status === "failed" || state.status === "cancelled" ? "#8c2f24" : state.status === "done" ? "#1f5f3a" : "#23282e";
    drawText(ctx, line1, BOARD_IN_X + Math.round((maxW - textWidth(line1, 1)) / 2), y1, col, 1); // ortalı
    drawText(ctx, line2, BOARD_IN_X + Math.round((maxW - textWidth(line2, 1)) / 2), y2, "#3c4652", 1); // ortalı
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
    if (state.hand) {
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
  };

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
    const key = `${S.frame}|${S.state.bubble}|${S.state.zone}|${S.state.target}|${S.state.status}|${S.state.mood}|${S.state.hand}|${S.state.counts.tool_calls},${S.state.counts.edits},${S.state.counts.tests_pass},${S.state.counts.tests_fail}`;
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
    const now = ts || 0;
    const progress = Math.min(1, (now - S.walkStart) / WALK_MS);
    const moving = progress < 1 && !S.reduced;
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(S.scene, 0, 0);
    drawOffice(ctx, S.state, moving ? S.frame : Math.floor(S.frame / 2), moving);
    drawBoard(ctx, S.state);
    drawMarker(ctx, S.state, S.frame);
    const pos = charPos(S.state, progress);
    drawCharacter(ctx, S.state, S.frame, pos, moving);
    drawSigns(ctx, S.state); // tabelalar karakterden SONRA → karakter/masa tabelayı örtmez
    drawBubble(ctx, S.state);
    out.drawImage(S.buf, 0, 0, S.canvas.width, S.canvas.height);
  }

  function describe(state) {
    return Logic.describe(state);
  }

  function boardText(state) {
    const STATUS = { idle: "hazır", running: "çalışıyor", awaiting: "onay bekliyor", done: "bitti", failed: "başarısız", cancelled: "iptal" };
    return `Görev: ${STATUS[state.status] || state.status} · ${Logic.countersText(state)}`;
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

  function onEvent(type, data) {
    const prev = S.state;
    S.state = Logic.reduce(prev, type, data || {});
    if (S.state.target !== prev.target) S.walkStart = root.performance ? root.performance.now() : 0;
    if (prev.zone !== S.state.zone) S.prevZone = prev.zone;
    S.dirty = true;
    updateText();
    if (!S.running) drawOnce(false);
    else if (S.state.target !== prev.target) restartWalk();
  }

  function reset() {
    S.state = Logic.initial();
    S.prevZone = "desk";
    S.walkStart = 0;
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
    }
    sync();
  }

  function init() {
    S.canvas = root.document ? root.document.getElementById("office-canvas") : null;
    if (!S.canvas) return;
    S.live = root.document.getElementById("office-live");
    S.word = root.document.getElementById("office-status");
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

  root.Office = { init, onEvent, reset, setVisible, getState: () => S.state, describe };
})(typeof globalThis !== "undefined" ? globalThis : this);
