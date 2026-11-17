// Ofis sahnesinin hareketli parçaları: animasyonlar, karakter, konuşma balonu, parçacıklar.
// Çalışma zamanı office.js'te; paylaşılan adlar globalThis.UstaOffice (U) üzerinden okunur.
(function () {
  "use strict";
  const U = (globalThis.UstaOffice = globalThis.UstaOffice || {});
  // --- ikincil animasyonlu parçalar ---
  function drawBooks(ctx, frame, active) {
    // kitaplıktan yukarı süzülen kitap: yalnız kitaplıkta çalışırken
    if (!active) return;
    const phase = (frame % 24) / 24;
    const bx = 34 + Math.round(Math.sin(phase * Math.PI * 2) * 8);
    const by = 50 - Math.round(phase * 10);
    U.rect(ctx, bx, by, 4, 5, U.PAL.c);
    U.rect(ctx, bx, by, 4, 1, "#cfe4f4");
  }

  function drawScreen(ctx, frame, testState) {
    // testState: "pass" → yeşil, "fail" → kırmızı, "run" → kayan yeşil satırlar
    let col = "#183a28";
    let lineCol = "#2f6b45";
    if (testState === "fail") {
      col = "#3a1a18";
      lineCol = U.PAL.r;
    } else if (testState === "pass") {
      col = frame % 2 ? "#245c3a" : "#1e4a30";
      lineCol = "#a6e8bf";
    } else if (testState === "run") {
      col = "#1a4030";
      lineCol = "#7fd39c";
    }
    U.rect(ctx, 188, 56, 30, 13, col);
    for (let y = 0; y < 5; y++) {
      const wl = 22 - ((y + (testState === "run" ? frame : 0)) % 3) * 6;
      U.rect(ctx, 190, 58 + y * 2, Math.max(4, wl), 1, lineCol);
    }
    if (testState === "fail") U.drawText(ctx, "!", 210, 57, U.PAL.w, 1);
    if (testState === "pass") U.drawText(ctx, "OK", 202, 57, "#dff3e6", 1);
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
      U.rect(ctx, 219, 122 - lift, 16, 5, U.PAL.w);
      U.rect(ctx, 226, 122 - lift, 1, 5, "#cfc8b8");
      U.rect(ctx, 225, 121 - lift, 4, 1, U.PAL.p);
    }
    if (inZone === "memory" && busy && !moving && !away) {
      const led = frame % 6 < 3;
      U.rect(ctx, 24, 129, 3, 2, led ? U.PAL.y : U.PAL.o);
    }
  }

  // Tahta yazısı: görev durumu (üst satır) + kısa sayaçlar (alt satır); her karede tazelenir
  function drawBoard(ctx, state) {
    if (!ctx || !state || !state.counts) return;
    const STATUS = { idle: "HAZIR", running: "ÇALIŞIYOR", awaiting: "ONAY BEKLİYOR", done: "BİTTİ", failed: "BAŞARISIZ", cancelled: "İPTAL" };
    // her iki satır ölçek 1, 5x7 font: 7 px yükseklik, aralarında 2 px boşluk → 8..16 ve 18..24 (iç alan 8..26)
    const maxW = U.BOARD_IN_W;
    // satır başına en çok 22 karakter (136 px / 6 px); sayaç satırı ≤19 olduğu için kesilmez
    const maxChars = 22;
    const line1 = U.fitLine(STATUS[state.status] || state.status || "", maxW, 1, maxChars);
    // sayaçlar kısa biçimde (A araç, D düzenleme, T test geçti/kaldı); sığmazsa kesilir, tahta dışına çizilmez
    const line2 = U.fitLine(String(U.Logic.shortCounters ? U.Logic.shortCounters(state) : ""), maxW, 1, maxChars);
    const y1 = U.BOARD_IN_Y + 1;
    const y2 = y1 + 7 + 2;
    const col = state.status === "failed" || state.status === "cancelled" ? "#8c2f24" : state.status === "done" ? "#1f5f3a" : "#23282e";
    const c1 = Math.max(U.BOARD_IN_X, U.BOARD_IN_X + Math.round((maxW - U.textWidth(line1, 1)) / 2));
    const c2 = Math.max(U.BOARD_IN_X, U.BOARD_IN_X + Math.round((maxW - U.textWidth(line2, 1)) / 2));
    U.drawText(ctx, line1, c1, y1, col, 1); // ortalı
    U.drawText(ctx, line2, c2, y2, "#3c4652", 1); // ortalı
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
    const canvas = U.SPRITES[`char-${legs}`];
    const zone = moving ? state.zone : state.target;
    // ayak gölgesi (yumuşak elips)
    ctx.fillStyle = "rgba(0,0,0,.34)";
    ctx.beginPath();
    ctx.ellipse(x + U.CHAR_W / 2, pos.y + U.CHAR_H, 8, 2.5, 0, 0, Math.PI * 2);
    ctx.fill();
    const up = armsUp(state) && !moving; // görev başarıyla bitti → kollar havada
    if (up) {
      // kollar havada: omuzdan yukarı (gövde y..y+22; yüz y+3..y+8 → eller başın iki yanında y+3..y+10)
      U.rect(ctx, x + 1, y + 10, 3, 5, U.PAL.o); // sol kol yukarı
      U.rect(ctx, x + 1, y + 7, 3, 3, U.PAL.s);
      U.rect(ctx, x + 12, y + 10, 3, 5, U.PAL.o); // sağ kol yukarı
      U.rect(ctx, x + 12, y + 7, 3, 3, U.PAL.s);
    } else if (state.hand) {
      // el kaldırma: başın yanında görünen kol + ten el
      U.rect(ctx, x + (pos.dx >= 0 ? 13 : 1), y + 9, 3, 6, U.PAL.o);
      U.rect(ctx, x + (pos.dx >= 0 ? 13 : 1), y + 6, 3, 3, U.PAL.s);
    } else if (zone === "workshop" && !moving && (state.status === "running" || state.status === "awaiting")) {
      const up = frame % 2 === 0;
      U.rect(ctx, x + 13, y + (up ? 8 : 13), 2, 6, U.PAL.j);
      U.rect(ctx, x + 12, y + (up ? 5 : 16), 4, 3, U.PAL.m);
    } else if (zone === "library" && !moving && state.status === "running") {
      U.rect(ctx, x - 3, y + 11, 4, 4, frame % 2 === 0 ? U.PAL.c : U.PAL.y);
    }
    if (moving) U.rect(ctx, x + 6, y + 22, 4, 2, U.PAL.k); // bacak ayrımı vurgusu
    ctx.drawImage(canvas, x, y);
    if (state.mood === "sad") {
      // üzgün: ağız aşağı, omuzlar çökük
      U.rect(ctx, x + 7, y + 8, 3, 1, U.PAL.S);
      U.rect(ctx, x + 5, y + 7, 1, 1, U.PAL.S);
      U.rect(ctx, x + 11, y + 7, 1, 1, U.PAL.S);
    } else if (state.mood === "happy") {
      U.rect(ctx, x + 7, y + 8, 3, 1, U.PAL.O);
    }
    if (up) {
      // kollar havada: iki yanda küçük "kutlama" çizgileri (ellerin üstünde, y+4..y+7)
      U.rect(ctx, x - 3, y + 4, 1, 3, U.PAL.y);
      U.rect(ctx, x + U.CHAR_W + 2, y + 4, 1, 3, U.PAL.y);
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
    const g = U.glyph(ch);
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
    const widest = Math.max.apply(null, lines.map((l) => U.textWidth(l, BUB_FONT)));
    const bw = widest + BUB_PAD * 2; // genişlik: metin + 2x3 px iç boşluk + 2 px kenarlık
    const bh = lines.length * BUB_LINE_H + BUB_PAD * 2;
    // balon karakterin hemen ÜSTÜNDE (alta inmez → masayı/tabelaları örtmez)
    let bx = Math.round(anchor.x + U.CHAR_W / 2 - bw / 2);
    let by = Math.min(head - 4 - bh, 30); // en fazla y=30'a kadar iner (sahne üst öğeleri korunur)
    bx = Math.max(2, Math.min(U.W - bw - 2, bx)); // sahne kenarından taşmaz
    by = Math.max(2, by);
    // kutu: yumuşak gölge + koyu çerçeve + krem zemin + tür renkli kenar
    U.rect(ctx, bx + 1, by + 1, bw, bh, "rgba(0,0,0,.32)");
    U.rect(ctx, bx, by, bw, bh, U.PAL.D);
    U.rect(ctx, bx + 1, by + 1, bw - 2, bh - 2, "#f4efe2");
    const edge = state.bubbleKind === "alarm" ? U.PAL.r : state.bubbleKind === "ask" ? U.PAL.o : U.PAL.k;
    U.rect(ctx, bx, by, 2, bh, edge);
    U.rect(ctx, bx + 2, by + 1, bw - 3, 1, "#fffdf6");
    const ink = state.bubbleKind === "alarm" ? "#8c2f24" : "#23282e";
    lines.forEach((l, i) => drawBigText(ctx, l, bx + 2 + BUB_PAD, by + 1 + BUB_PAD + i * BUB_LINE_H, ink));
    // kuyruk: karakterin başına yönelen küçük üçgen (balonun altından)
    const tx = Math.max(bx + 6, Math.min(bx + bw - 8, Math.round(anchor.x + U.CHAR_W / 2)));
    const bot = by + bh;
    U.rect(ctx, tx - 2, bot, 5, 1, U.PAL.D); // kuyruk tabanı
    U.rect(ctx, tx - 1, bot + 1, 3, 1, U.PAL.D);
    U.rect(ctx, tx, bot + 2, 1, 1, U.PAL.D); // küçük uç: başa doğru
    U.rect(ctx, tx - 1, bot, 3, 1, "#f4efe2");
  }

  function drawMarker(ctx, state, frame) {
    // hedefteki küçük turuncu ok (aktif bölgeyi işaret eder)
    const p = charPos(state, 1);
    if (frame % 2 === 0) {
      U.rect(ctx, p.x + 6, p.y - 7, 4, 1, U.PAL.o);
      U.rect(ctx, p.x + 7, p.y - 6, 2, 1, U.PAL.o);
      U.rect(ctx, p.x + 8, p.y - 5, 1, 1, U.PAL.y);
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
    const cols = [U.PAL.o, U.PAL.y, U.PAL.g, U.PAL.c, U.PAL.p];
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
      U.rect(ctx, Math.round(p.x), Math.round(p.y), p.s || 1, p.s || 1, p.col);
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
        col: i % 2 ? "#a6e8bf" : U.PAL.g,
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
    U.rect(ctx, x, y + 3, 1, 1, ink);
    U.rect(ctx, x + 1, y + 4, 1, 1, ink);
    U.rect(ctx, x + 2, y + 3, 1, 1, ink);
    U.rect(ctx, x + 3, y + 2, 1, 1, ink);
    U.rect(ctx, x + 4, y + 1, 1, 1, ink);
    U.rect(ctx, x + 5, y, 1, 1, ink);
  }

  // Test kalınca: başın üstünde minik ter damlası + kırmızı ünlem
  function drawFailMark(ctx, fx, pivot, now, frame) {
    const age = now - fx.testAt;
    if (!(age >= 0 && age < 1400)) return;
    const x = Math.round(pivot.x + 11), y = Math.round(pivot.y - 8 + (frame % 2));
    U.rect(ctx, x + 1, y, 1, 1, U.PAL.r); // ünlem
    U.rect(ctx, x + 1, y + 1, 1, 1, U.PAL.r);
    U.rect(ctx, x + 1, y + 2, 1, 1, U.PAL.r);
    U.rect(ctx, x + 1, y + 4, 1, 1, U.PAL.r);
    U.rect(ctx, x - 3, y + 1, 2, 2, "#9fd0ea"); // ter damlası
    U.rect(ctx, x - 3, y + 3, 1, 1, "#9fd0ea");
  }

  // Üzgün: tepede küçük gri bulut (yavaşça süzülür)
  function drawCloud(ctx, pivot, now) {
    const x = Math.round(pivot.x + 2), y = Math.round(pivot.y - 9 + ((now / 700) | 0) % 2);
    U.rect(ctx, x, y + 2, 13, 3, "#7d8796");
    U.rect(ctx, x + 3, y, 7, 2, "#8f99a8");
    U.rect(ctx, x + 1, y + 5, 3, 1, "#5a6472");
    U.rect(ctx, x + 7, y + 5, 3, 1, "#5a6472");
  }

  // Çay içme: fincan + yükselen buhar (yalnız cosmetic, yalnız bekleme durumunda)
  function drawCoffee(ctx, pivot, now, frame) {
    const x = Math.round(pivot.x + 13), y = Math.round(pivot.y + 11);
    U.rect(ctx, x, y, 6, 5, U.PAL.o); // fincan
    U.rect(ctx, x, y, 6, 1, "#f0b070");
    U.rect(ctx, x + 6, y + 1, 2, 2, U.PAL.o); // kulp
    U.rect(ctx, x + 1, y - 1, 4, 1, "#6b4a3a"); // çay yüzeyi
    for (let i = 0; i < 3; i++) {
      const ph = ((frame + i * 4) % 12) / 12;
      U.rect(ctx, x + 1 + i, Math.round(y - 2 - ph * 7), 1, 1, "rgba(230,240,255,.55)");
    }
  }

  // Uyuklama: z z z (soldan sağa yükselir)
  function drawZzz(ctx, pivot, now, frame) {
    const zs = ["z", "z", "z"];
    for (let i = 0; i < 3; i++) {
      const ph = ((frame + i * 5) % 15) / 15;
      const x = Math.round(pivot.x + 9 + i * 4 + ph * 3);
      const y = Math.round(pivot.y - 8 - i * 4 - ph * 5);
      U.drawText(ctx, zs[i], x, y, "rgba(220,230,245," + (0.8 - ph * 0.5).toFixed(2) + ")", 1);
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
        U.rect(ctx, 0, 0, U.W, U.H, "rgba(6,8,14,.42)"); // sahne hafif kararır (lamba söndü)
        U.drawLamp(ctx, "off");
      }
    }
  }

  // Kollarını kaldırma niyeti: yalnız başarılı bittiğinde
  function armsUp(state) {
    return !!state && state.fx && state.fx.end === "done" && state.status === "done";
  }

  Object.assign(U, { COFFEE_MS, CONF_TTL, FX_CAP, NAP_MS, armsUp, charPos, confettiBits, confettiParts, createFx, drawBoard, drawBubble, drawCharacter, drawCloud, drawCoffee, drawFailMark, drawMarker, drawOffice, drawParts, drawStageFx, drawSuccessMark, drawZzz, fxEvent, mix32, stageMode, successParts });
})();
