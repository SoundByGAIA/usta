// Ofis sekmesinin DOM parçaları: göstergeler şeridi, "son eylemler" paneli, onay şeridi ve geçmiş oturum zaman çubuğu.
// Canvas'a çizmez; durum ve yardımcılar office.js'te, paylaşılan adlar window.UstaOffice (U) üzerinden çağrı anında okunur.
(function (root) {
  "use strict";
  const U = (globalThis.UstaOffice = globalThis.UstaOffice || {});
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
    U.S.metrics = {
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
    if (!run) return U.Logic.formatDuration(0); // bu görevde `started` görülmedi
    if (U.S.durSeq !== run) {
      // yeni görev (veya ilk `started`): süre burada başlar
      U.S.durSeq = run;
      U.S.durStart = nowMs();
      U.S.durEnd = 0;
    }
    const stopped = !!state.endSeq; // görev bitti → süre durur (sayaç ilerlemez)
    if (stopped && !U.S.durEnd) U.S.durEnd = nowMs();
    const end = U.S.durEnd || nowMs();
    return U.Logic.formatDuration((end - U.S.durStart) / 1000);
  }

  function paintMetrics(state) {
    const m = U.S.metrics;
    if (!m) return;
    const lines = U.Logic.metricLines(state.usage, U.S.contextWindow);
    for (const line of lines) {
      const node = m[line.key];
      if (node && node.textContent !== line.value) node.textContent = line.value;
    }
    const pct = U.Logic.contextPercent(state.usage && state.usage.context, U.S.contextWindow);
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
    if (!U.S.metrics) return;
    if (U.S.state.runSeq && !U.S.state.endSeq) {
      paintMetrics(U.S.state);
      if (!U.S.durTick) U.S.durTick = setIntervalFn(tickDuration, 1000);
    } else if (U.S.durTick) {
      clearIntervalFn(U.S.durTick);
      U.S.durTick = 0;
      paintMetrics(U.S.state);
    }
  }

  function paintPanel() {
    const p = U.S.panel;
    if (!p) return;
    const { lines, now } = U.Logic.actionLines(U.S.state);
    const sig = lines.join("\n") + "\n" + now;
    if (U.S.panelSig === sig) return;
    U.S.panelSig = sig;
    const items = lines.map((text) => {
      const li = el("li");
      li.textContent = text;
      return li;
    });
    p.list.replaceChildren(...items);
    p.now.textContent = now;
  }

  function setPanel(open) {
    U.S.panelOpen = !!open;
    const p = U.S.panel;
    if (!p) return;
    p.box.hidden = !U.S.panelOpen;
    p.toggle.setAttribute("aria-expanded", U.S.panelOpen ? "true" : "false");
    if (U.S.panelOpen) paintPanel();
  }

  function initPanel() {
    const toggle = $id("office-actions-toggle");
    const box = $id("office-actions-panel");
    const list = $id("office-actions-list");
    const now = $id("office-actions-now");
    if (!toggle || !box || !list || !now) return;
    U.S.panel = { toggle, box, list, now };
    setPanel(false);
    toggle.addEventListener("click", () => setPanel(!U.S.panelOpen));
    // ek kolaylık: canvas'a tıklamak da paneli açar (asıl yol düğme)
    if (U.S.canvas) U.S.canvas.addEventListener("click", () => setPanel(true)); // açıkken yalnız tazelenir, kapanmaz
  }

  function setContextWindow(n) {
    const v = Number(n);
    U.S.contextWindow = Number.isFinite(v) && v > 0 ? Math.round(v) : 0; // 0 = pencere bilinmiyor
    if (U.S.metrics) paintMetrics(U.S.state);
  }

  // --- onay şeridi: app.js'teki MEVCUT karar akışı Office.onDecide ile çağrılır (kopya kod yok) ---
  function initApproval() {
    if (U.S.approval) return; // ikinci U.init'te düğüm dinleyicileri yeniden bağlanmaz
    const box = $id("office-approval");
    const text = $id("office-approval-text");
    const allow = $id("office-approval-allow");
    const deny = $id("office-approval-deny");
    if (!box || !text || !allow || !deny) return;
    U.S.approval = { box, text, allow, deny };
    allow.type = deny.type = "button";
    box.hidden = true;
    allow.addEventListener("click", () => sendDecision("allow"));
    deny.addEventListener("click", () => sendDecision("deny"));
  }

  // Karar: köprü işlevi (app.js `Office.onDecide = (id, decision) => decideApproval(...)`).
  // Dönen metin şeritte gösterilir, sonra şerit kapanır; Akış'taki onay düğmeleri aynı akıştan güncellenir.
  function sendDecision(decision) {
    const id = U.S.approvalId;
    if (!id || U.S.approvalBusy) return;
    const fn = root.Office && root.Office.onDecide;
    if (typeof fn !== "function") return; // köprü bağlı değilse istek gönderilmez (uydurma yok)
    U.S.approvalBusy = true;
    if (U.S.approval) {
      U.S.approval.allow.disabled = true;
      U.S.approval.deny.disabled = true;
    }
    const settle = (msg) => {
      U.S.approvalBusy = false;
      U.S.approvalId = "";
      U.S.approvalDone = msg || "";
      paintApproval();
      if (!U.S.approvalDone) return;
      if (U.S.approvalDoneTick) clearTimeout(U.S.approvalDoneTick);
      // şerit kısa süre sonucu yazar, sonra gizlenir (yeni onay gelirse yeniden açılır)
      U.S.approvalDoneTick = setTimeout(() => {
        U.S.approvalDoneTick = 0;
        U.S.approvalDone = "";
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
    const a = U.S.approval;
    if (!a) return;
    if (!U.S.approvalDone && !U.S.approvalBusy) {
      a.allow.disabled = false;
      a.deny.disabled = false;
    }
    const id = U.S.approvalId;
    const replaying = !!(U.S.replay && U.S.replay.events);
    const show = replaying ? false : !!(U.S.approvalDone || id); // replay'de onay şeridi ÇIKMAZ
    a.box.hidden = !show;
    const text = U.S.approvalDone || U.Logic.approvalLine(U.S.state); // başlık gerçek onay olayından
    if (a.text.textContent !== text) a.text.textContent = text;
    a.allow.hidden = !!U.S.approvalDone;
    a.deny.hidden = !!U.S.approvalDone;
  }

  // Canlı akışta bekleyen onay kimliği değişince şerit bağlanır (replay kendi durumunu gösterir)
  function trackApproval(state) {
    if (U.S.replay && U.S.replay.events) return;
    if (state.pendingApprovalId) {
      if (state.pendingApprovalId !== U.S.approvalId) {
        U.S.approvalId = state.pendingApprovalId;
        U.S.approvalDone = "";
      }
    } else if (!U.S.approvalDone) {
      U.S.approvalId = ""; // akışta onay çözüldü (auto_approved/denied/done) → şerit kapanır
    }
    paintApproval();
  }

  // --- geçmiş oturum zaman çubuğu: durum saf U.Logic.replayState ile BAŞTAN hesaplanır ---
  const REPLAY_MS = 700; // olay başına oynatma süresi (hıza bölünür)

  function initReplay() {
    if (U.S.replay) return; // ikinci U.init'te düğüm dinleyicileri yeniden bağlanmaz
    const box = $id("office-replay");
    const play = $id("office-replay-play");
    const range = $id("office-replay-range");
    const text = $id("office-replay-text");
    const rate = $id("office-replay-speed");
    if (!box || !play || !range || !text || !rate) return;
    U.S.replay = { events: null, i: 0, playing: false, speed: 1, box, play, range, text, rate, tick: 0 };
    play.type = rate.type = "button";
    box.hidden = true;
    play.addEventListener("click", () => {
      const r = U.S.replay;
      if (!r || !r.events) return;
      // sonda oynat → baştan başlar (deterministik: aynı dizi, aynı durumlar)
      if (!r.playing && r.i >= r.events.length) seekReplay(0);
      startPlayback(!r.playing);
    });
    range.addEventListener("input", () => {
      if (!U.S.replay || !U.S.replay.events) return;
      const want = Math.round(Number(range.value) || 0); // önce oku: stopPlayback çubuğu r.i'ye geri boyar
      stopPlayback();
      seekReplay(want);
    });
    rate.addEventListener("click", () => {
      const r = U.S.replay;
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
    const r = U.S.replay;
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
    const r = U.S.replay;
    if (!r || !r.events) return;
    const n = r.events.length;
    const raw = Math.floor(Number(i));
    r.i = !Number.isFinite(raw) ? 0 : Math.min(n, Math.max(0, raw));
    U.applyState(U.Logic.replayState(r.events, r.i));
    replayPaint();
  }

  function startPlayback(on) {
    const r = U.S.replay;
    if (!r) return;
    if (!on) return stopPlayback();
    if (U.S.reduced) {
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
    const r = U.S.replay;
    if (!r || !r.playing) return;
    if (r.i >= r.events.length) return stopPlayback(); // sonda durur
    seekReplay(r.i + 1);
    if (r.i >= r.events.length) stopPlayback();
  }

  function stopPlayback() {
    const r = U.S.replay;
    if (!r) return;
    r.playing = false;
    if (r.tick) clearIntervalFn(r.tick);
    r.tick = 0;
    replayPaint();
  }

  function loadReplay(events) {
    const r = U.S.replay;
    if (!r) return;
    const list = Array.isArray(events) ? events.slice() : []; // app.js'in dizisi paylaşılmaz
    r.events = list;
    r.i = 0;
    stopPlayback();
    r.box.hidden = false; // yalnız replay modunda görünür
    U.S.approvalId = ""; // geçmiş kararı değiştirilemez → onay şeridi ÇIKMAZ
    U.S.approvalDone = "";
    paintApproval();
    U.applyState(U.Logic.replayState(list, 0));
    replayPaint();
    startPlayback(true); // otomatik oynatma; reduced-motion'da başlamaz
  }

  function leaveReplay() {
    const r = U.S.replay;
    if (!r) return;
    stopPlayback();
    r.events = null;
    r.i = 0;
    r.box.hidden = true; // canlı mod aynen döner
    U.S.approvalId = "";
    U.S.approvalDone = "";
    paintApproval();
  }
  Object.assign(U, { initApproval, initMetrics, initPanel, initReplay, leaveReplay, loadReplay, paintApproval, paintMetrics, paintPanel, sendDecision, setContextWindow, tickDuration, trackApproval });
})(typeof globalThis !== "undefined" ? globalThis : this);
