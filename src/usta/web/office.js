// Usta "Ofis" sekmesi: canvas 2D piksel-sanat sahnesi. Bağımlılık yok, harici görsel/font yok.
// Tüm çizim kodla yapılır (dizge-palet sprite'lar, tam sayı ölçek). Olaylar Office.onEvent ile gelir.
(function (root) {
  "use strict";
  const U = (globalThis.UstaOffice = globalThis.UstaOffice || {});
  Object.assign(U, {  });
  const Logic = root.OfficeLogic;
  Object.assign(U, { Logic });
  const W = 256, H = 160; // mantıksal piksel tuvali
  Object.assign(U, { W, H });
  const MAX_FPS = 30;
  const WALK_MS = 750;
  const MIN_SCALE = 3; // küçük ekranda bile en az 3x (CSS max-width taşmayı engeller)
  const MAX_SCALE = 6; // geniş ekranda dev sahne yerine ölçülü büyütme
  // Beyaz tahtanın iç (yazı) alanı: drawScene'deki 144x27 çerçeve + 3 px kenar → 62,8 136x19 (iç sınır 197,26)
  // Genişlik 5x7 fontta 22 karaktere yeter: "ONAY BEKLİYOR" (13) ve kısa sayaçlar (≤19, Logic.shortCounters) taşmaz.
  const BOARD_IN_X = 62, BOARD_IN_Y = 8, BOARD_IN_W = 136, BOARD_IN_H = 19;
  Object.assign(U, { BOARD_IN_X, BOARD_IN_Y, BOARD_IN_W });

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
    fx: U.createFx(), // efekt/çay/uyku durumu (yalnız gerçek tetikleyicilerle ilerler)
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
    if (!cache[phase]) cache[phase] = U.makeCanvas(W, H, (c) => U.drawScene(c, phase));
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
      S.phase = U.dayPhase(typeof hooks.hour === "function" ? hooks.hour() : localHour());
      S.phaseAt = now;
    }
    U.fxEvent(S.fx, S.state, now);
    const mode = U.stageMode(S.state, S.fx, now, hooks.seed == null ? 42 : hooks.seed);
    const progress = Math.min(1, (now - S.walkStart) / WALK_MS);
    const moving = progress < 1 && !S.reduced;
    const asleep = mode === "sleep";
    const f = asleep ? Math.floor(S.frame / 4) : S.frame; // uyurken hareket yavaşlar
    const anim = S.reduced ? 0 : f; // prefers-reduced-motion: animasyon yok (tek kare sabit)
    const pos = U.charPos(S.state, progress);
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(sceneFor(S.phase, now), 0, 0); // duvar/pencere tonu saate göre
    U.drawOffice(ctx, S.state, moving ? S.frame : Math.floor(S.frame / 2), moving, mode);
    U.drawBoard(ctx, S.state);
    U.drawMarker(ctx, S.state, S.frame);
    U.drawCharacter(ctx, S.state, S.frame, pos, moving);
    U.drawSigns(ctx, S.state); // tabelalar karakterden SONRA → karakter/masa tabelayı örtmez
    if (S.reduced) U.drawBubble(ctx, S.state); // reduce: efekt katmanı yok, balon her zaman görünür
    // --- efekt katmanı (yalnız gerçek olay tetikleyicileri) ---
    if (mode === "coffee") U.drawCoffee(ctx, pos, now, anim);
    if (asleep) U.drawZzz(ctx, pos, now, anim);
    U.drawSuccessMark(ctx, S.fx, pos, now);
    U.drawFailMark(ctx, S.fx, pos, now, anim);
    if (S.state.mood === "sad" && !U.armsUp(S.state)) U.drawCloud(ctx, pos, now);
    if (!S.reduced) {
      // reduce: parçacık/parlama/kararma yok (animasyon yok kuralı) — tek sabit kare
      U.drawParts(ctx, U.successParts(S.fx, pos, now));
      U.drawParts(ctx, U.confettiParts(S.fx, now));
      U.drawStageFx(ctx, S.state, S.fx, now, anim);
      U.drawBubble(ctx, S.state);
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
    U.fxEvent(S.fx, next, frameNow(0)); // efekt zamanı olay anından başlar
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
    S.fx = U.createFx(); // efektler ve boş zaman davranışı da sıfırlanır
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
    S.scene = U.makeCanvas(W, H, U.drawScene);
    S.buf = U.makeCanvas(W, H, () => {});
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
    dayPhase: U.dayPhase,
    skyPalette: U.skyPalette,
    drawScene: U.drawScene,
    drawBoard: U.drawBoard,
    drawOffice: U.drawOffice,
    drawCharacter: U.drawCharacter,
    drawWindowSky: U.drawWindowSky,
    stageMode: U.stageMode,
    confettiBits: U.confettiBits,
    confettiParts: U.confettiParts,
    replay: () => S.replay, // testte zaman çubuğu durumu (DOM düğümleri yoksa null)
    sendDecision, // testte onay şeridi kararı (köprü Office.onDecide çağrılır)
    mix32: U.mix32,
    createFx: U.createFx,
    fxEvent: U.fxEvent,
    fakeCtx,
    FX_CAP: U.FX_CAP,
    CONF_TTL: U.CONF_TTL,
    NAP_MS: U.NAP_MS,
    COFFEE_MS: U.COFFEE_MS,
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
