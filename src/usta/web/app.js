// Usta web arayüzü. Güvenilmeyen içerik (model çıktısı, dosyalar) yalnız textContent ile basılır.
(function () {
  "use strict";
  const L = window.UstaLogic;
  const $ = (id) => document.getElementById(id);
  const state = { token: "", ws: null, task: null, active: false, abort: null, approvals: {}, contextWindow: null, files: [], replay: false, openFile: null, openDirs: new Set(), selDir: "", defaultWs: null, zoom: "auto", fsMode: null };
  const STATUS = {
    running: "çalışıyor", awaiting_approval: "onay bekliyor", cancelling: "durduruluyor",
    done: "bitti", cancelled: "durduruldu", failed: "başarısız",
  };
  const MAX_DIFF_LINES = 2000;

  function put(k, v) {
    try { if (v == null || v === "") sessionStorage.removeItem(k); else sessionStorage.setItem(k, v); } catch (_) { /* gizli mod */ }
  }
  function get(k) {
    try { return sessionStorage.getItem(k) || ""; } catch (_) { return ""; }
  }
  function h(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  // --- tema ve mod (terminalle ortak: ~/.usta/config.json) ---
  // Arayüz boyutu: "auto" pencere boyutuna göre ölçeklenir; seçim bu tarayıcıda hatırlanır
  function applyZoom() {
    const choice = state.zoom;
    const z = choice === "auto" ? L.autoScale(window.innerWidth, window.innerHeight) : Number(choice) || 1;
    document.documentElement.style.zoom = z === 1 ? "" : String(z);
    $("zoom").value = choice;
  }
  let zoomTimer = null;
  window.addEventListener("resize", () => { clearTimeout(zoomTimer); zoomTimer = setTimeout(applyZoom, 150); });
  function applyTheme(name) {
    document.documentElement.dataset.theme = ["beyaz", "gri", "siyah"].includes(name) ? name : "";
    $("theme").value = ["beyaz", "gri", "siyah"].includes(name) ? name : "siyah";
  }
  function applyMode(mode) {
    $("mode").value = ["manual", "auto", "plan"].includes(mode) ? mode : "manual";
    $("mode-warn").hidden = $("mode").value !== "auto";
  }
  function applyView(view) {
    state.view = view === "advanced" ? "advanced" : "simple";
    document.body.classList.toggle("simple", state.view === "simple");
    $("view").value = state.view;
    const on = state.view === "advanced";
    $("dev-btn").textContent = `Geliştirici modu: ${on ? "Açık" : "Kapalı"}`;
    $("dev-btn").setAttribute("aria-pressed", String(on));
  }
  async function updateWhere() {
    const el = $("where");
    try {
      const r = await api("/privacy");
      if (!r.ok) { el.hidden = true; return; }
      const m = (await r.json()).model;
      if (!m) { el.hidden = true; return; }
      el.hidden = false;
      el.className = "where " + (m.where === "bu-bilgisayar" ? "local" : m.where === "yerel-ağ" ? "lan" : "cloud");
      el.textContent = m.where === "bu-bilgisayar" ? "Bu bilgisayarda" : m.where === "yerel-ağ" ? "Yerel ağda" : `Bulutta (${m.name})`;
      el.title = m.where === "bu-bilgisayar" ? "Yazdıkların bu bilgisayardan çıkmaz." : "Yazdıkların bu servisin sunucusuna gider. Ayrıntı için Gizlilik düğmesine bas.";
    } catch (_) { el.hidden = true; }
  }
  async function loadSettings() {
    const res = await api("/settings");
    if (!res.ok) return;
    const s = await res.json();
    applyTheme(s.theme);
    applyMode(s.mode);
    $("guard").checked = !!s.guard;
    state.defaultWs = s.workspace || null;
    state.zoom = s.zoom || "auto";
    applyZoom();
    applyView(s.view);
    $("set-quit-row").hidden = !s.background;
    $("think").value = s.think || "auto";
    const ctx = String(s.context_window || 0);
    if (![...$("ctx").options].some((o) => o.value === ctx)) {  // terminalden gelen özel değer
      const o = document.createElement("option");
      o.value = ctx; o.textContent = ctx + " token";
      $("ctx").appendChild(o);
    }
    $("ctx").value = ctx;
  }
  async function saveSetting(change) {
    try { await api("/settings", { method: "PUT", body: JSON.stringify(change) }); } catch (_) { /* yoksay */ }
  }
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  async function api(path, opts) {
    opts = opts || {};
    const headers = Object.assign({}, L.authHeaders(state.token), opts.body ? { "Content-Type": "application/json" } : {}, opts.headers || {});
    const res = await fetch(path, Object.assign({}, opts, { headers }));
    if (res.status === 401) { $("token-form").hidden = false; setConn("Jeton geçersiz", "bad"); throw new Error("401"); }
    return res;
  }
  async function errorText(res) {
    try {
      const j = await res.json();
      if (typeof j.detail === "string") return j.detail;
    } catch (_) { /* gövde yok */ }
    return `hata ${res.status}`;
  }

  const USTA_KAPALI = "Usta kapalı görünüyor. Siyah pencereyi kapattıysan Usta'yı yeniden başlat (python -m usta).";
  function setConn(text, cls) {
    const c = $("conn");
    c.textContent = text;
    c.className = cls || "";
  }
  function setStatus(s) {
    const chip = $("status");
    chip.textContent = s ? STATUS[s] || s : "";
    chip.dataset.s = s || "";
    if (s === "running") { hideResult(); updateStarters(); }
    else if (s === "done" && !state.replay) showResult();
  }

  // --- yeni başlayanlar: başlangıç işleri, sonuç kartı, devam önerileri ---
  const STARTERS = [
    ["Tanıtım sayfası", "Kendi işim için bir tanıtım web sayfası yap: başlık, kısa açıklama ve iletişim bölümü olsun."],
    ["Hesap makinesi", "Bir hesap makinesi web sayfası yap."],
    ["Alışveriş listesi", "Alışveriş listesi tutabileceğim basit bir web sayfası yap; madde ekleyip silebileyim."],
    ["Bugünün tarihi", "Bugünün tarihini büyük yazıyla gösteren basit bir sayfa yap."],
    ["Yılan oyunu", "Basit bir yılan oyunu web sayfası yap."],
    ["Dosyalarımı anlat", "Bu klasördeki dosyaları incele ve ne işe yaradıklarını kısaca anlat."],
  ];
  const FOLLOWUPS = ["Daha güzel görünmesini sağla", "Renklerini değiştir", "Yazıları büyüt", "Bir hata var, düzelt", "Türkçe karakterleri kontrol et"];
  function fillPrompt(text) { const p = $("prompt"); p.value = text; p.focus(); p.setSelectionRange(text.length, text.length); }
  function updateStarters() {
    const box = $("starters");
    const show = !!state.ws && !state.active && !state.replay && $("stream").children.length === 0 && $("result-card").hidden;
    box.hidden = !show;
    if (!show || box.dataset.ready) return;
    box.dataset.ready = "1";
    const grid = h("div", "starter-grid");
    for (const [title, text] of STARTERS) {
      const b = h("button");
      b.type = "button";
      b.append(h("strong", null, title), h("span", null, text));
      b.addEventListener("click", () => fillPrompt(text));
      grid.appendChild(b);
    }
    box.replaceChildren(h("h3", null, "Ne yapmamı istersin?"), h("p", "tip", "Bir örneğe bas ya da aşağıya kendi cümlelerinle yaz. Ne kadar ayrıntı verirsen sonuç o kadar iyi olur."), grid);
  }
  function hideResult() { $("result-card").hidden = true; }
  async function showResult() {
    if (!state.ws || state.replay) return;
    const card = $("result-card");
    card.hidden = false;
    $("starters").hidden = true;
    let hasIndex = false;
    try {
      const r = await api(`/workspaces/${encodeURIComponent(state.ws)}/tree?path=`);
      if (r.ok) hasIndex = ((await r.json()).entries || []).some((e) => !e.dir && e.name === "index.html");
    } catch (_) { /* yoksay */ }
    $("result-open").hidden = !hasIndex;
    $("result-title").textContent = hasIndex ? "Usta işi bitirdi. Sonucu görmek için \"Sonucu aç\"a bas." : "Usta işi bitirdi.";
    const fu = $("followups");
    fu.replaceChildren(...FOLLOWUPS.map((t) => { const b = h("button", null, t); b.type = "button"; b.addEventListener("click", () => fillPrompt(t)); return b; }));
  }
  function setActive(active) {
    state.active = active;
    $("send").disabled = !state.ws;
    $("send").textContent = active ? "Yönlendir" : "Gönder";
    $("send").title = active ? "Görev sürerken mesaj gönder: ajan bir sonraki adımında görür" : "";
    $("prompt").placeholder = !state.ws ? "Önce soldan bir çalışma alanı seç" : active ? "Görev sürerken de yazabilirsin; mesajın ajana iletilir (Ctrl+Enter)" : "Ne yapmamı istersin? (Ctrl+Enter gönderir)";
    $("prompt").disabled = !state.ws;
    $("model-select").disabled = active;
    $("attach").disabled = active || !state.ws;
    $("stop").hidden = !active;
    document.querySelectorAll("#ws-list button").forEach((b) => { b.disabled = active; });
    $("f-up-files").disabled = $("f-up-dir").disabled = $("f-new-file").disabled = $("f-new-dir").disabled = active || !state.ws;
  }

  // --- akış çizimi ---
  function addNode(node) {
    const box = $("stream");
    const near = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
    box.appendChild(node);
    if (near) box.scrollTop = box.scrollHeight;
  }
  function showUsage(u, windowSize) {
    const t = $("tokens");
    const info = L.usageText(u, windowSize);
    t.hidden = !info;
    if (!info) return;
    t.textContent = info.context ? `${info.text} · ${info.context}` : info.text;
    t.dataset.level = info.pct == null ? "" : info.pct >= 90 ? "high" : info.pct >= 70 ? "mid" : "";
  }
  // Ofis sekmesi: her olayı sahneye iletir; yeni görev/geçmiş oturum sıfırlar (Office.onEvent(type, data))
  function officeEvent(type, data) {
    const O = window.Office;
    // Ofis.onEvent(type, data)
    if (O && typeof O.onEvent === "function") O.onEvent(type, data);
  }
  function officeReset() {
    const O = window.Office;
    if (O && typeof O.reset === "function") O.reset();
    officeContextWindow(); // sıfırlanan sahneye penceresi bilgisi yeniden verilir
  }
  // Ofis'teki onay şeridi: karar MEVCUT akışa (decideApproval) iletilir; dönen metni şerit yazar.
  // Köprü tek satır: `Office.onDecide = (id, decision) => decideApproval(id, decision)` (init içinde).
  // Geçmiş oturum: olaylar tek tek değil toplu verilir (replay durumu saf reduce ile hesaplanır)
  function officeReplay(events) {
    const O = window.Office;
    if (O && typeof O.loadReplay === "function") O.loadReplay(events);
  }
  // Ofis köprüsü: modelin bağlam penceresi göstergelere aktarılır (0/null = bilinmiyor)
  function officeContextWindow() {
    const O = window.Office;
    if (O && typeof O.setContextWindow === "function") O.setContextWindow(state.contextWindow || 0);
  }
  function renderEvent(type, data) {
    if (type === "usage") { officeEvent(type, data); showUsage(data, state.contextWindow); officeContextWindow(); return; } // usage sayaçları değiştirmez
    officeEvent(type, data);
    const s = L.summarize(type, data);
    if (type === "message" && !s.body) return;
    if (s.kind === "tool" || s.kind === "result") {
      const d = h("details", "msg " + s.kind);
      const simpleTitle = s.kind === "tool" && state.view !== "advanced" ? L.plainProgress(s.tool, s.args) : null;
      d.appendChild(h("summary", null, simpleTitle || (s.kind === "result" ? "↳ " : "") + s.title));
      if (s.body) d.appendChild(h("pre", null, s.body));
      return addNode(d);
    }
    if (s.kind === "approval" && !state.replay) return addNode(approvalNode(s));
    const box = h("div", "msg " + s.kind);
    box.textContent = s.title && s.body ? `${s.title}\n${s.body}` : s.title || s.body;
    addNode(box);
  }
  // Onay kararı: tek akış (onay uç noktasına POST + durum "running"). Akış'taki onay düğmeleri ve
  // Ofis'teki onay şeridi aynı işlevi çağırır (kopya kod yok). Çözüm metni çağırana döner.
  const approvalRows = new Map(); // onay kimliği -> Akış'taki düğme satırı (karar iki yerden de verilebilir)
  async function decideApproval(approvalId, decision) {
    const row = approvalRows.get(approvalId);
    if (row) for (const b of row.querySelectorAll("button")) b.disabled = true; // çift gönderim yok
    const msg = await decideSend(approvalId, decision);
    let text;
    if (msg === "ok") { setStatus("running"); text = decision === "allow" ? "İzin verildi" : "Reddedildi"; }
    else text = msg === "stale" ? "İstek artık geçerli değil" : msg;
    if (row) row.textContent = text; // Akış'taki onay arayüzü de karar Ofis'ten verilse bile güncellenir
    return text;
  }
  // Karar isteğini gönderir; ağ/sunucu sonucunu düz metne çevirir. Akış'taki onay düğmesi de
  // (decideApproval üzerinden) aynı yolu kullanır — kopya kod yok.
  async function decideSend(id, decision) {
    try {
      const res = await api(`/approvals/${encodeURIComponent(id)}`, { method: "POST", body: JSON.stringify({ decision }) });
      return res.ok ? "ok" : "stale";
    } catch (_) { return "Gönderilemedi"; }
  }
  function approvalNode(s) {
    const box = h("div", "msg approval");
    const plain = L.plainApproval(s.tool, s.args, s.reason);
    box.appendChild(h("p", "plain", plain.title));
    if (plain.warn) box.appendChild(h("p", "plain-warn", plain.warn));
    const det = h("details", null);
    det.appendChild(h("summary", null, "Ayrıntılar (teknik)"));
    det.appendChild(h("strong", null, s.title));
    if (s.body) det.appendChild(h("pre", null, s.body));
    box.appendChild(det);
    const row = h("div", "row");
    const allow = h("button", "primary", "İzin ver");
    const deny = h("button", null, "Reddet");
    allow.type = deny.type = "button";
    if (s.approvalId != null) approvalRows.set(s.approvalId, row);
    const decide = (decision) => decideApproval(s.approvalId, decision);
    allow.addEventListener("click", () => decide("allow"));
    deny.addEventListener("click", () => decide("deny"));
    row.append(allow, deny);
    box.appendChild(row);
    return box;
  }

  // --- diff çizimi ---
  function renderDiff(text) {
    const files = L.parseDiff(text);
    const root = $("diff-files");
    root.replaceChildren();
    $("diff-count").textContent = files.length ? `(${files.length})` : "";
    $("revert").disabled = files.length === 0;
    if (!files.length) { root.appendChild(h("p", "empty", "Değişiklik yok.")); return; }
    const TAG = { added: "yeni", deleted: "silindi", modified: "değişti", binary: "ikili" };
    for (const f of files) {
      const d = h("details", "file");
      d.open = true;
      const sum = h("summary");
      sum.append(h("span", null, f.name + " "), h("span", "tag", `[${TAG[f.status]}] `));
      if (f.status !== "binary") sum.append(h("span", "stat-add", `+${f.stats.add} `), h("span", "stat-del", `−${f.stats.del}`));
      d.appendChild(sum);
      const code = h("div", "code");
      f.lines.slice(0, MAX_DIFF_LINES).forEach((l) => {
        const sign = { add: "+", del: "-", ctx: " ", hunk: "", meta: "" }[l.kind];
        code.appendChild(h("div", l.kind, sign + l.text));
      });
      if (f.lines.length > MAX_DIFF_LINES) code.appendChild(h("div", "meta", `… ${f.lines.length - MAX_DIFF_LINES} satır daha (gösterilmiyor)`));
      d.appendChild(code);
      root.appendChild(d);
    }
  }
  function showTab(name) {
    $("stream").hidden = name !== "stream";
    $("diff").hidden = name !== "diff";
    $("memory").hidden = name !== "memory";
    $("history").hidden = name !== "history";
    $("fileview").hidden = name !== "file";
    $("preview").hidden = name !== "preview";
    $("office").hidden = name !== "office";
    $("replay-bar").hidden = !(state.replay && name === "stream");
    $("tab-file").hidden = !state.openFile && name !== "file";
    for (const t of ["stream", "diff", "memory", "history", "file", "preview", "office"]) $(`tab-${t}`).setAttribute("aria-selected", String(t === name));
    if (window.Office && typeof window.Office.setVisible === "function") window.Office.setVisible(name === "office");
    if (name === "memory") loadMemory();
    if (name === "history") loadHistory();
    if (name === "preview") loadPreview();
  }

  // --- önizleme: yalıtılmış (sandbox) çerçeve, statik dosyalar ---
  async function previewBase() {
    const res = await api(`/workspaces/${encodeURIComponent(state.ws)}/preview`);
    return res.ok ? (await res.json()).base : null;
  }
  async function loadPreview() {
    if (!state.ws) return;
    const base = await previewBase();
    if (!base) return;
    const rel = $("preview-path").value.trim().replace(/^\/+/, "") || "index.html";
    const url = `${base}${rel.split("/").map(encodeURIComponent).join("/")}`;
    $("preview-frame").src = `${url}${url.includes("?") ? "&" : "?"}t=${Date.now()}`;
    $("preview-open").href = url;
  }
  // --- geçmiş oturumlar ---
  const fmtTs = (ts) => (ts ? new Date(ts * 1000).toLocaleString("tr-TR", { dateStyle: "short", timeStyle: "short" }) : "");
  const HIST_STATUS = Object.assign({ interrupted: "kesildi" }, STATUS);
  async function loadHistory() {
    const list = $("history-list");
    list.replaceChildren();
    $("history-msg").textContent = "";
    if (!state.ws) return;
    const ws = state.ws;
    const res = await api(`/workspaces/${encodeURIComponent(ws)}/sessions`);
    if (!res.ok || state.ws !== ws) { $("history-msg").textContent = await errorText(res); return; }
    const all = await res.json();
    if (!all.length) list.appendChild(h("li", "empty", "Henüz oturum yok."));
    for (const s of all) {
      const li = h("li");
      const b = h("button", null);
      b.type = "button";
      const st = h("span", "h-st", HIST_STATUS[s.status] || s.status);
      st.dataset.s = s.status;
      b.append(h("span", "h-ts", fmtTs(s.ts)), st, h("span", "h-prompt", s.prompt));
      b.addEventListener("click", () => openSession(s.id));
      li.appendChild(b);
      list.appendChild(li);
    }
  }
  async function openSession(id) {
    if (state.active || !state.ws) return;
    const ws = state.ws;
    const res = await api(`/workspaces/${encodeURIComponent(ws)}/sessions/${encodeURIComponent(id)}`);
    if (!res.ok || state.ws !== ws) { $("history-msg").textContent = await errorText(res); return; }
    const s = await res.json();
    state.task = null;
    state.replay = true;
    $("stream").replaceChildren();
    showUsage(null);
    officeReset(); // geçmiş oturum: sahne baştan aynı olaylarla yeniden oynar
    const m = s.meta || {};
    const names = (m.files || []).length ? `\n📎 ${m.files.join(", ")}` : "";
    addNode(h("div", "msg user", (m.prompt || "") + names));
    for (const e of s.events) {
      if (e.type === "done") setStatus(e.data.status);
      renderEvent(e.type, e.data);
    }
    // Ofis sekmesi: olaylar tek tek değil toplu verilir → sahne zaman çubuğuyla gezilebilir
    officeReplay(s.events.map((e) => ({ type: e.type, data: e.data })));
    if (s.status === "interrupted") addNode(h("div", "msg warn", "Bu görev yarıda kesilmiş (sunucu kapanmış olabilir)."));
    $("replay-text").textContent = `Geçmiş oturum · ${fmtTs(m.ts)} · ${HIST_STATUS[s.status] || s.status} (salt okunur)`;
    showTab("stream");
    $("stream").scrollTop = 0;
  }
  function leaveReplay() {
    if (!state.replay) return;
    state.replay = false;
    $("stream").replaceChildren();
    showUsage(null);
    setStatus("");
    $("replay-bar").hidden = true;
    officeReset();
  }

  // --- ekler (metin / Markdown) ---
  const MAX_ATT = 5, MAX_ATT_BYTES = 100000;
  function renderAttached() {
    const box = $("attached");
    box.replaceChildren();
    box.hidden = state.files.length === 0;
    state.files.forEach((f, i) => {
      const chip = h("span", "att", `${f.name} · ${Math.max(1, Math.round(f.size / 1000))} KB`);
      const x = h("button", null, "×");
      x.type = "button";
      x.setAttribute("aria-label", `${f.name} ekini kaldır`);
      x.addEventListener("click", () => { state.files.splice(i, 1); renderAttached(); });
      chip.appendChild(x);
      box.appendChild(chip);
    });
  }
  async function addFiles(list) {
    for (const file of Array.from(list)) {
      if (state.files.length >= MAX_ATT) { addNode(h("div", "msg warn", `En çok ${MAX_ATT} dosya eklenebilir.`)); break; }
      if (file.size > MAX_ATT_BYTES) { addNode(h("div", "msg warn", `${file.name}: çok büyük (en çok 100 KB).`)); continue; }
      let content;
      try { content = await file.text(); } catch (_) { addNode(h("div", "msg warn", `${file.name}: okunamadı.`)); continue; }
      if (content.includes("\u0000")) { addNode(h("div", "msg warn", `${file.name}: ikili dosya, yalnız metin eklenebilir.`)); continue; }
      state.files.push({ name: file.name, content, size: file.size });
    }
    renderAttached();
  }

  // --- proje hafızası ---
  async function loadMemory() {
    const notes = $("memory-notes"), hist = $("memory-history");
    notes.replaceChildren();
    hist.replaceChildren();
    $("memory-msg").textContent = "";
    if (!state.ws) return;
    const ws = state.ws;
    const res = await api(`/workspaces/${encodeURIComponent(ws)}/memory`);
    if (!res.ok || state.ws !== ws) { $("memory-msg").textContent = await errorText(res); return; }
    const mem = await res.json();
    $("memory-count").textContent = mem.notes.length ? `(${mem.notes.length})` : "";
    $("clear-history").disabled = mem.history.length === 0;
    if (!mem.notes.length) notes.appendChild(h("li", "empty", "Not yok."));
    mem.notes.forEach((text, i) => {
      const li = h("li", "mem-row");
      const del = h("button", null, "Sil");
      del.type = "button";
      del.addEventListener("click", () => deleteNote(i));
      li.append(h("span", "mem-text", text), del);
      notes.appendChild(li);
    });
    if (!mem.history.length) hist.appendChild(h("li", "empty", "Geçmiş yok."));
    for (const r of mem.history.slice().reverse()) {
      hist.appendChild(h("li", "mem-row", `[${r.ts}] ${STATUS[r.status] || r.status}: ${r.prompt}${r.answer ? " → " + r.answer : ""}`));
    }
  }
  async function memoryAction(path, opts) {
    const res = await api(`/workspaces/${encodeURIComponent(state.ws)}/memory${path}`, opts);
    if (!res.ok) $("memory-msg").textContent = await errorText(res);
    else await loadMemory();
  }
  const deleteNote = (i) => state.ws && memoryAction(`/notes/${i}`, { method: "DELETE" });
  const clearHistory = () => state.ws && memoryAction("/history", { method: "DELETE" });

  // --- görev akışı ---
  async function follow(taskId) {
    state.task = taskId;
    put("usta_task", `${state.ws}:${taskId}`);
    setActive(true);
    const ctl = new AbortController();
    state.abort = ctl;
    let last = null;
    let finished = false;
    let nextTask = null;  // aşamalı uygulamada sunucunun başlattığı sonraki görev
    let tries = 0;
    while (!finished && tries < 6 && state.task === taskId) {
      const att = new AbortController();  // bu bağlantı denemesi; takılırsa yeniden bağlanılır
      const onAbort = () => att.abort();
      ctl.signal.addEventListener("abort", onAbort);
      let lastByte = Date.now();
      const watchdog = setInterval(() => { if (Date.now() - lastByte > 40000) att.abort(); }, 5000);  // sunucu 15 sn'de bir canlılık yollar
      try {
        const headers = last != null ? { "Last-Event-ID": String(last) } : {};
        const res = await api(`/tasks/${encodeURIComponent(taskId)}/events`, { headers, signal: att.signal });
        if (res.status === 404) {
          put("usta_task", "");
          addNode(h("div", "msg error", "Görev bulunamadı (sunucu yeniden başlamış olabilir)."));
          break;
        }
        if (!res.ok) throw new Error(String(res.status));
        const dec = new TextDecoder();
        const parser = L.createSSEParser((ev) => {
          let data = {};
          try { data = JSON.parse(ev.data); } catch (_) { return; }
          if (ev.id != null) last = Number(ev.id);
          if (ev.event === "started") setStatus("running");
          if (ev.event === "approval_required") setStatus("awaiting_approval");
          if (ev.event === "done") { finished = true; setStatus(data.status); if (data.next) nextTask = data.next; }
          try { renderEvent(ev.event, data); } catch (_) { /* tek olay çizilemese de akış sürsün */ }
        });
        const reader = res.body.getReader();
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          lastByte = Date.now();
          tries = 0;
          parser.feed(dec.decode(value, { stream: true }));
        }
      } catch (e) {
        if (ctl.signal.aborted || String(e.message) === "401") break;
        tries++;
      } finally {
        clearInterval(watchdog);
        ctl.signal.removeEventListener("abort", onAbort);
      }
      if (!finished) await sleep(1000);
    }
    if (!finished && tries >= 6) addNode(h("div", "msg error", "Bağlantı koptu."));
    if (nextTask && state.task === taskId) {
      try {
        const info = await (await api(`/tasks/${encodeURIComponent(nextTask)}`)).json();
        addNode(h("div", "msg user", info.prompt));
      } catch (_) { /* istem gösterilemese de akış sürer */ }
      return follow(nextTask);
    }
    await finish(taskId);
  }
  async function finish(taskId) {
    if (state.task !== taskId) return;
    try {
      const info = await (await api(`/tasks/${encodeURIComponent(taskId)}`)).json();
      setStatus(info.status);
      if (!L.isActive(info.status)) {
        const res = await api(`/tasks/${encodeURIComponent(taskId)}/diff`);
        if (res.ok) renderDiff(await res.text());
        setActive(false);
        refreshTree();
        if (!$("preview").hidden) loadPreview();
        if (info.mode === "plan" && info.status === "done" && info.answer) offerPlan(info);
        return;
      }
    } catch (_) { /* bağlantı yok */ }
    setActive(false);
  }

  function offerPlan(info) {
    const box = h("div", "msg approval");
    box.appendChild(h("strong", null, "Planı uygulayayım mı?"));
    const row = h("div", "row");
    const mk = (label, mode, primary, phased) => {
      const b = h("button", primary ? "primary" : null, label);
      b.type = "button";
      b.title = phased ? "Plan PLAN.md aşamalarına bölünür; her aşama taze bağlamla ayrı görev olarak koşar (bağlam şişmez; yerel küçük modeller için)" : "Planın tamamı tek görevde uygulanır";
      b.addEventListener("click", () => {
        row.textContent = phased ? "Aşamalara bölünüyor…" : "Uygulanıyor…";
        startTask(phased ? "Planı aşama aşama uygula" : "Planı uygula", mode, [], info.id, phased);  // plan sunucuda; istem yeniden yazılmaz
      });
      return b;
    };
    const no = h("button", null, "Hayır");
    no.type = "button";
    no.addEventListener("click", () => { row.textContent = "Plan uygulanmadı"; });
    row.append(
      mk("Aşama aşama · oto onay (önerilen)", "auto", true, true), mk("Aşama aşama · manuel", "manual", false, true),
      mk("Tek seferde · manuel", "manual", false, false), mk("Tek seferde · oto onay", "auto", false, false), no);
    box.appendChild(row);
    addNode(box);
  }

  async function sendPrompt() {
    const prompt = $("prompt").value.trim();
    if (!prompt || !state.ws) return;
    if (state.active) return steer(prompt);
    return startTask(prompt, $("mode").value, state.files);
  }
  async function steer(text) {
    if (!state.task) return;
    const res = await api(`/tasks/${encodeURIComponent(state.task)}/messages`, { method: "POST", body: JSON.stringify({ text }) });
    if (res.ok) { $("prompt").value = ""; return; }  // mesaj akışa "user_message" olayıyla düşer
    addNode(h("div", "msg error", await errorText(res)));
  }

  // --- model seçimi ---
  async function loadModels() {
    const sel = $("model-select");
    let info = null;
    try {
      const res = await api("/model");
      if (res.ok) info = await res.json();
    } catch (_) { /* yok */ }
    sel.hidden = !info || !info.model;  // kurulum sırasında boş liste gösterilmez
    if (!info) return null;
    sel.replaceChildren();
    const groups = info.apis || [{ api: info.api || "", models: info.models || [] }];
    for (const g of groups) {
      const parent = groups.length > 1 ? sel.appendChild(h("optgroup")) : sel;
      if (parent !== sel) parent.label = g.error && !g.models.length ? `${g.api} (ulaşılamadı)` : g.api;
      for (const m of g.models) {
        const o = h("option", null, m);
        o.value = `${g.api}|${m}`;
        parent.appendChild(o);
      }
    }
    sel.value = `${info.api}|${info.model}`;
    sel.dataset.cur = sel.value;
    updateWhere();
    return info;
  }
  async function switchModel() {
    const sel = $("model-select");
    const want = sel.value;
    const cut = want.indexOf("|");
    sel.disabled = true;
    setConn(`Model hazırlanıyor: ${want.slice(cut + 1)}…`, "");
    try {
      const res = await api("/model", { method: "PUT", body: JSON.stringify({ api: want.slice(0, cut), model: want.slice(cut + 1) }) });
      if (res.ok) { sel.dataset.cur = want; setConn("Bağlı", "ok"); }
      else { sel.value = sel.dataset.cur; setConn(await errorText(res), "bad"); }
    } catch (_) { sel.value = sel.dataset.cur; setConn("Model değiştirilemedi", "bad"); }
    sel.disabled = state.active;
  }
  async function startTask(prompt, mode, files = [], planId = null, phased = false) {
    leaveReplay();
    const body = { prompt, mode, guard: $("guard").checked, files: files.map((f) => ({ name: f.name, content: f.content })) };
    if (planId) { body.apply_plan = planId; if (phased) body.phased = true; }
    const res = await api(`/workspaces/${encodeURIComponent(state.ws)}/tasks`, { method: "POST", body: JSON.stringify(body) });
    if (!res.ok) { addNode(h("div", "msg error", await errorText(res))); return; }
    const task = await res.json();
    state.contextWindow = task.context_window || null;
    showUsage(null);
    officeContextWindow(); // modelin bağlam penceresi Ofis göstergelerine
    $("prompt").value = "";
    $("diff-files").replaceChildren();
    $("diff-count").textContent = "";
    $("revert").disabled = true;
    state.files = [];
    renderAttached();
    addNode(h("div", "msg user", files.length ? `${prompt}\n📎 ${files.map((f) => f.name).join(", ")}` : prompt));
    officeReset(); // yeni görev: ofis sahnesi sıfırdan başlar
    showTab("stream");
    follow(task.id);
  }

  async function stopTask() {
    if (!state.task) return;
    $("stop").disabled = true;
    try { await api(`/tasks/${encodeURIComponent(state.task)}/cancel`, { method: "POST" }); setStatus("cancelling"); } catch (_) { /* yoksay */ }
    $("stop").disabled = false;
  }

  let revertArmed = null;
  async function revertTask() {
    const btn = $("revert");
    if (!state.task || state.active) return;
    if (!revertArmed) {
      btn.textContent = "Emin misin? Tekrar tıkla";
      revertArmed = setTimeout(() => { revertArmed = null; btn.textContent = "Değişiklikleri geri al"; }, 4000);
      return;
    }
    clearTimeout(revertArmed);
    revertArmed = null;
    btn.textContent = "Değişiklikleri geri al";
    await doRevert();
  }
  async function doRevert() {
    const res = await api(`/tasks/${encodeURIComponent(state.task)}/revert`, { method: "POST" });
    if (!res.ok) { addNode(h("div", "msg error", await errorText(res))); return false; }
    renderDiff("");
    renderEvent("reverted", {});
    showTab("stream");
    return true;
  }

  // --- ek araçlar (MCP): yalnız katalogdan ekleme, serbest komut yok ---
  function toolsMsg(text, cls) {
    const m = $("tools-msg");
    m.textContent = text || "";
    m.className = cls || "empty";
  }
  async function toolsCall(path, method, body) {
    const res = await api(`/mcp${path}`, { method, body: body ? JSON.stringify(body) : undefined });
    if (!res.ok) { toolsMsg(await errorText(res), "error"); return null; }
    return res.json();
  }
  async function loadTools() {
    const res = await api("/mcp");
    if (!res.ok) { toolsMsg(await errorText(res), "error"); return; }
    const data = await res.json();
    const inst = $("tools-installed"), cat = $("tools-catalog");
    inst.replaceChildren();
    cat.replaceChildren();
    if (!data.servers.length) inst.appendChild(h("p", "empty", "Henüz araç eklenmedi."));
    for (const s of data.servers) inst.appendChild(serverCard(s));
    const avail = data.catalog.filter((c) => !c.added);
    if (!avail.length) cat.appendChild(h("p", "empty", "Eklenebilecek başka araç yok."));
    for (const c of avail) cat.appendChild(catalogCard(c));
  }
  function catalogCard(c) {
    const card = h("div", "card");
    card.append(h("strong", null, c.title), h("p", null, c.description), h("code", "cmd", c.command.join(" ")));
    card.appendChild(h("p", "empty", `Yalıtılmış konteynerde çalışır (imaj: ${c.image}; ağ: ${c.allow_hosts.length ? c.allow_hosts.join(", ") : "kapalı"}). İmaj yerelde olmalı: docker pull ${c.image}`));
    if (c.homepage.startsWith("https://")) {
      const a = h("a", null, c.homepage);
      a.href = c.homepage;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      card.appendChild(h("p", "empty")).appendChild(a);
    }
    const add = h("button", "primary", "Ekle");
    add.type = "button";
    add.addEventListener("click", async () => {
      add.disabled = true;
      if (await toolsCall(`/catalog/${encodeURIComponent(c.id)}`, "POST")) { toolsMsg("Eklendi. Önce Hazırla (paketleri indirip sabitler), anahtarı gir, sonra Test et.", "ok"); await loadTools(); }
      else add.disabled = false;
    });
    card.appendChild(add);
    return card;
  }
  function serverCard(s) {
    const card = h("div", "card");
    const title = h("strong", null, s.name);
    const host = s.isolation === "host";
    card.append(title, h("span", "chip", s.enabled ? "açık" : "kapalı"), h("span", "chip", host ? "ANA MAKİNE (yalıtımsız)" : "yalıtılmış konteyner"));
    if (!host) card.appendChild(h("span", "chip", s.pinned ? "sabitlendi" : "sabitlenmedi"));
    card.append(h("p", "empty", `onay: ${s.approve === "allow" ? "sormadan çalışır" : "her çağrıda sorulur"}${host ? "" : ` · imaj: ${s.image || "YOK"} · ağ: ${s.allow_hosts.length ? s.allow_hosts.join(", ") : "kapalı"}`}`), h("code", "cmd", s.command.join(" ")));
    for (const e of s.env) {
      const row = h("div", "key-row");
      const input = h("input");
      input.type = "password";
      input.autocomplete = "off";
      input.spellcheck = false;
      input.placeholder = e.set ? `${e.name} tanımlı (değiştirmek için yaz)` : `${e.name} değerini gir`;
      input.setAttribute("aria-label", e.name);
      const save = h("button", null, "Kaydet");
      save.type = "button";
      save.addEventListener("click", async () => {
        const v = input.value.trim();
        if (!v) return;
        if (await toolsCall(`/${encodeURIComponent(s.name)}/secrets/${encodeURIComponent(e.name)}`, "PUT", { value: v })) {
          input.value = "";
          toolsMsg(`${e.name} kaydedildi.`, "ok");
          await loadTools();
        }
      });
      row.append(input, save);
      card.appendChild(row);
    }
    const actions = h("div", "row");
    const test = h("button", null, "Test et");
    test.type = "button";
    test.addEventListener("click", async () => {
      test.disabled = true;
      toolsMsg("Konteyner başlatılıyor...");
      const r = await toolsCall(`/${encodeURIComponent(s.name)}/test`, "POST");
      test.disabled = false;
      if (r) toolsMsg(`${r.tools.length} araç bulundu: ${r.tools.map((t) => t.name).join(", ")}`.slice(0, 600), "ok");
    });
    const prepare = h("button", null, s.pinned ? "Yeniden hazırla" : "Hazırla");
    prepare.type = "button";
    prepare.hidden = host;
    prepare.addEventListener("click", async () => {
      prepare.disabled = true;
      toolsMsg("Hazırlanıyor: paketler yalnız paket kayıtlarına açık ağda indirilir, kurulum betikleri çalışmaz (birkaç dakika sürebilir)...");
      const r = await toolsCall(`/${encodeURIComponent(s.name)}/prepare`, "POST");
      prepare.disabled = false;
      if (r) { toolsMsg("Hazır: imaj ve paketler sabitlendi.", "ok"); await loadTools(); }
    });
    const toggle = h("button", null, s.enabled ? "Kapat" : "Aç");
    toggle.type = "button";
    toggle.addEventListener("click", async () => {
      if (await toolsCall(`/${encodeURIComponent(s.name)}/enabled`, "POST", { enabled: !s.enabled })) await loadTools();
    });
    const remove = h("button", null, "Kaldır");
    remove.type = "button";
    let armed = null;
    remove.addEventListener("click", async () => {
      if (!armed) {
        remove.textContent = "Emin misin? Tekrar tıkla";
        armed = setTimeout(() => { armed = null; remove.textContent = "Kaldır"; }, 4000);
        return;
      }
      clearTimeout(armed);
      if (await toolsCall(`/${encodeURIComponent(s.name)}`, "DELETE")) await loadTools();
    });
    actions.append(prepare, test, toggle, remove);
    card.appendChild(actions);
    return card;
  }
  function togglePanel(name) {
    const open = $(name).hidden;
    for (const p of ["tools", "apis", "privacy", "wizard", "tablet", "settings"]) {
      $(p).hidden = !(open && p === name);
      $(`${p}-btn`).setAttribute("aria-pressed", String(open && p === name));
    }
    document.querySelector("main").hidden = open;
    if (!open) return;
    if (name === "tools") { toolsMsg(""); loadTools(); loadSkills(); }
    else if (name === "privacy") loadPrivacy();
    else if (name === "wizard") wizShow("wiz-start");
    else if (name === "tablet") loadTablet();
    else { apisMsg(""); loadApis(); }
  }
  const fmtBytes = (n) => (n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`);
  async function loadTablet() {
    const res = await api("/pair", { method: "POST" });
    $("tablet-off").hidden = res.ok;
    $("tablet-on").hidden = !res.ok;
    $("tablet-msg").textContent = "";
    if (!res.ok) { if (res.status !== 404) $("tablet-msg").textContent = await errorText(res); return; }
    const d = await res.json();
    $("tablet-pin").textContent = d.pin;
    $("tablet-ttl").textContent = `Bu kod ${Math.round(d.ttl / 60)} dakika geçerli.`;
    $("tablet-urls").replaceChildren(...(d.urls.length ? d.urls.map((u) => h("code", "cmd", u)) : [h("p", "empty", "Yerel ağ adresi bulunamadı. Bilgisayarın Wi-Fi'a bağlı mı?")]));
  }
  async function loadPrivacy() {
    const res = await api("/privacy");
    if (!res.ok) { $("privacy-sends").replaceChildren(h("p", "error", await errorText(res))); return; }
    const d = await res.json();
    const where = { "bu-bilgisayar": "bu bilgisayar", "yerel-ağ": "yerel ağ", internet: "internet" };
    $("privacy-sends").replaceChildren(...d.sends.map((t) => h("p", null, t)));
    const list = h("div", "models");
    for (const a of d.apis) list.appendChild(h("span", d.model && d.model.name === a.name ? "cur" : null, `${a.name}: ${where[a.where]}`));
    $("privacy-sends").appendChild(list);
    $("privacy-other").replaceChildren(...d.other.map((t) => h("li", null, t)));
    $("privacy-home").textContent = `Klasör: ${d.home}`;
    $("privacy-stored").replaceChildren(...d.stored.map((f) => {
      const card = h("div", "card");
      card.append(h("strong", null, f.name), h("span", "chip", fmtBytes(f.bytes)), h("p", "empty", f.what));
      return card;
    }));
  }
  const toggleTools = () => togglePanel("tools");

  // --- beceriler: klasörü göster, yükle, sil ---
  function skillsMsg(text, cls) { const m = $("skills-msg"); m.textContent = text || ""; m.className = cls || "empty"; }
  async function loadSkills() {
    const box = $("skills-list");
    box.replaceChildren();
    const res = await api("/skills");
    if (!res.ok) { skillsMsg(await errorText(res), "error"); return; }
    const list = await res.json();
    if (!list.length) box.appendChild(h("p", "empty", "Henüz beceri yok."));
    for (const s of list) {
      const row = h("div", "skill-row");
      row.append(h("span", null, `/${s.name}  ${s.description}`));
      const del = h("button", null, "Sil");
      del.type = "button";
      del.addEventListener("click", async () => {
        const r = await api(`/skills/${encodeURIComponent(s.name)}`, { method: "DELETE" });
        if (r.ok) loadSkills(); else skillsMsg(await errorText(r), "error");
      });
      row.appendChild(del);
      box.appendChild(row);
    }
  }
  async function uploadSkills(files) {
    for (const f of Array.from(files)) {
      const name = f.name.replace(/\.md$/i, "").toLowerCase().replace(/[^a-z0-9çğıöşü_-]+/g, "-").replace(/^-+/, "").slice(0, 30);
      if (!name || f.size > 20000) { skillsMsg(`${f.name}: ad geçersiz ya da 20 KB'tan büyük`, "error"); continue; }
      const res = await api(`/skills/${encodeURIComponent(name)}`, { method: "PUT", body: JSON.stringify({ content: await f.text() }) });
      skillsMsg(res.ok ? `/${name} yüklendi.` : `${f.name}: ${await errorText(res)}`, res.ok ? "ok" : "error");
    }
    loadSkills();
  }

  // --- API'ler ---
  function apisMsg(text, cls) { const m = $("apis-msg"); m.textContent = text || ""; m.className = cls || "empty"; }
  async function loadApis() {
    const box = $("apis-list");
    box.replaceChildren();
    const [res, info] = await Promise.all([api("/apis"), api("/model").then((r) => (r.ok ? r.json() : null)).catch(() => null)]);
    if (!res.ok) { apisMsg(await errorText(res), "error"); return; }
    const byApi = {};
    for (const g of (info && info.apis) || []) byApi[g.api] = g;
    for (const a of await res.json()) {
      const card = h("div", "card");
      const g = byApi[a.name];
      card.append(h("strong", null, a.name), h("span", "chip", a.has_key ? "anahtar var" : "anahtarsız"), h("code", "cmd", a.endpoint));
      const models = h("div", "models");
      if (g && g.models.length) for (const m of g.models) models.appendChild(h("span", info && info.api === a.name && info.model === m ? "cur" : null, m));
      else models.appendChild(h("span", null, g && g.error ? g.error : "model yok"));
      card.appendChild(models);
      if (a.builtin) { card.appendChild(h("p", "empty", "Terminalden açılan varsayılan uç nokta.")); box.appendChild(card); continue; }
      const row = h("div", "key-row");
      const input = h("input");
      input.type = "password"; input.autocomplete = "off"; input.spellcheck = false;
      input.placeholder = a.has_key ? "yeni anahtar (değiştirmek için yaz)" : "anahtar gir";
      input.setAttribute("aria-label", `${a.name} anahtarı`);
      const save = h("button", null, "Kaydet");
      save.type = "button";
      save.addEventListener("click", async () => {
        const v = input.value.trim();
        if (!v) return;
        const r = await api(`/apis/${encodeURIComponent(a.name)}/key`, { method: "PUT", body: JSON.stringify({ key: v }) });
        if (r.ok) { apisMsg("Anahtar kaydedildi.", "ok"); loadApis(); loadModels(); } else apisMsg(await errorText(r), "error");
      });
      row.append(input, save);
      const remove = h("button", null, "Kaldır");
      remove.type = "button";
      let armed = null;
      remove.addEventListener("click", async () => {
        if (!armed) { remove.textContent = "Emin misin? Tekrar tıkla"; armed = setTimeout(() => { armed = null; remove.textContent = "Kaldır"; }, 4000); return; }
        clearTimeout(armed);
        const r = await api(`/apis/${encodeURIComponent(a.name)}`, { method: "DELETE" });
        if (r.ok) { loadApis(); loadModels(); } else apisMsg(await errorText(r), "error");
      });
      const actions = h("div", "row");
      actions.appendChild(remove);
      card.append(row, actions);
      box.appendChild(card);
    }
  }
  async function addApi(ev) {
    ev.preventDefault();
    const body = { name: $("api-name").value.trim(), endpoint: $("api-endpoint").value.trim() };
    const key = $("api-key").value.trim();
    if (key) body.key = key;
    const res = await api("/apis", { method: "POST", body: JSON.stringify(body) });
    if (!res.ok) { apisMsg(await errorText(res), "error"); return; }
    $("api-form").reset();
    apisMsg("API eklendi; modelleri model listesinde görünür.", "ok");
    loadApis(); loadModels();
  }

  // --- bilgisayarımdaki model ---
  const LOCAL_SLUG = { 11434: "ollama", 1234: "lm-studio", 8080: "llama-cpp", 8000: "vllm" };
  const CTX_CHOICES = [4096, 8192, 16384, 32768, 65536, 131072];
  async function scanLocal() {
    const box = $("local-found");
    box.replaceChildren();
    const raw = $("local-port").value.trim();
    const body = raw ? { port: Number(raw) } : {};
    const res = await api("/local/scan", { method: "POST", body: JSON.stringify(body) });
    if (!res.ok) { apisMsg(await errorText(res), "error"); return; }
    const found = await res.json();
    if (!found.length) { box.appendChild(h("p", "empty", "Bu portlarda çalışan bir model sunucusu bulamadım. Program açık mı?")); return; }
    for (const f of found) {
      const card = h("div", "card");
      card.append(h("strong", null, `${f.name} (port ${f.port})`), h("code", "cmd", f.endpoint));
      const models = h("div", "models");
      for (const m of f.models) models.appendChild(h("span", null, m));
      if (!f.models.length) models.appendChild(h("span", null, "model yok"));
      card.appendChild(models);
      const add = h("button", "primary", "Ekle");
      add.type = "button";
      add.addEventListener("click", async () => {
        const name = LOCAL_SLUG[f.port] || `yerel-${f.port}`;
        const r = await api("/apis", { method: "POST", body: JSON.stringify({ name, endpoint: f.endpoint }) });
        if (r.ok) { apisMsg(`Eklendi (${name}); modeller model listesinde görünür.`, "ok"); loadApis(); loadModels(); }
        else apisMsg(await errorText(r), "error");
      });
      const actions = h("div", "row");
      actions.appendChild(add);
      card.appendChild(actions);
      if (f.port === 11434 && f.models.length) {
        const row = h("div", "key-row");
        const msel = h("select");
        msel.setAttribute("aria-label", "Model");
        for (const m of f.models) { const o = h("option", null, m); o.value = m; msel.appendChild(o); }
        const csel = h("select");
        csel.setAttribute("aria-label", "Bağlam");
        for (const c of CTX_CHOICES) { const o = h("option", null, `${c / 1024}K`); o.value = String(c); csel.appendChild(o); }
        csel.value = "16384";
        const go = h("button", null, "Bağlamı uygula");
        go.type = "button";
        go.title = "Ollama'da bu bağlamla yeni bir model kopyası oluşturur (ağırlıklar kopyalanmaz)";
        go.addEventListener("click", async () => {
          go.disabled = true;
          const r = await api("/local/context", { method: "POST", body: JSON.stringify({ port: f.port, model: msel.value, num_ctx: Number(csel.value) }) });
          go.disabled = false;
          if (r.ok) { const d = await r.json(); apisMsg(`Oluşturuldu: ${d.model}. Model listesinden seçebilirsin.`, "ok"); scanLocal(); loadApis(); loadModels(); }
          else apisMsg(await errorText(r), "error");
        });
        row.append(msel, csel, go);
        card.appendChild(row);
      }
      box.appendChild(card);
    }
  }


  // --- kurulum sihirbazı (kodsuz kullanıcı için: "API/endpoint/token" yok) ---
  // Servis bilgileri resmî sayfalardan doğrulandı (2026-11-09). Ücretsiz katman iddiası yalnız doğrulananlar için.
  const WIZ_SERVICES = [
    { id: "gemini", label: "Google Gemini", free: true, endpoint: "https://generativelanguage.googleapis.com/v1beta/openai",
      url: "https://aistudio.google.com/apikey", linkText: "Google AI Studio anahtar sayfasını aç",
      steps: ["Sayfa açılınca Google hesabınla giriş yap.", "\"Create API key\" (anahtar oluştur) düğmesine bas.", "Çıkan uzun yazıyı kopyala ve aşağıdaki kutuya yapıştır."],
      note: "Ücretsiz kotası var, ama günlük istek sınırı düşüktür ve Google bunu değiştirebilir. Ücretsiz katmanda yazdıkların Google'ın ürünlerini geliştirmek için kullanılabilir (Google'ın koşullarına bak).",
      prefer: "gemini-2.5-flash" },
    { id: "openrouter", label: "OpenRouter", free: true, endpoint: "https://openrouter.ai/api/v1",
      url: "https://openrouter.ai/keys", linkText: "OpenRouter anahtar sayfasını aç",
      steps: ["Sayfa açılınca hesap aç (e-posta ya da Google ile) ve giriş yap.", "Anahtar oluştur düğmesine bas ve bir ad ver.", "Çıkan uzun yazıyı kopyala ve aşağıdaki kutuya yapıştır."],
      note: "Ücretsiz kalmak için \"openrouter/free\" modelini seç (sihirbaz onu önerir). \"openrouter/auto\" ücretli modellere yönlendirir. Ücretsiz modellerin günlük istek sınırı düşüktür; bazı ücretsiz modellerde sağlayıcı yazdıklarını kaydedebilir.",
      prefer: "openrouter/free" },
    { id: "deepseek", label: "DeepSeek", free: false, endpoint: "https://api.deepseek.com/v1",
      url: "https://platform.deepseek.com/api_keys", linkText: "DeepSeek anahtar sayfasını aç",
      steps: ["Sayfa açılınca hesap aç ve giriş yap.", "Hesabına bakiye yükle (bakiye yoksa anahtar çalışmaz).", "\"API keys\" sayfasında anahtar oluştur ve kopyala."],
      note: "Ücretlidir: kullandıkça bakiyeden düşer.", prefer: "deepseek-chat" },
    { id: "anthropic", label: "Claude (Anthropic)", free: false, endpoint: "https://api.anthropic.com/v1",
      url: "https://platform.claude.com/settings/keys", linkText: "Claude anahtar sayfasını aç",
      steps: ["Sayfa açılınca hesap aç ve giriş yap.", "Kullanmak için kredi yükle (ücretli servis).", "Anahtar oluştur ve çıkan yazıyı kopyala."],
      note: "Ücretlidir. Anthropic bu bağlantı yolunu \"deneme ve karşılaştırma amaçlı\" diye etiketlemiştir; bir şey çalışmazsa bize haber ver.",
      prefer: "claude-sonnet-5-5" },
    { id: "opencode", label: "OpenCode (çok modelli ağ geçidi)", free: false, endpoint: "https://opencode.ai/inference/openai/v1",
      url: "https://opencode.ai/console", linkText: "OpenCode konsolunu aç",
      steps: ["Sayfa açılınca giriş yap.", "Faturalandırma bilgilerini ve kredi ekle (anahtardan önce gerekir).", "Anahtarı kopyala ve aşağıdaki kutuya yapıştır."],
      note: "Ücretlidir, kullandıkça kredi düşer. OpenCode'un ücretsiz modelleri yalnız OpenCode uygulamasında çalışır; burada yalnız ücretli modeller görünür. GPT ve Claude modelleri bu ağ geçidinde farklı bir yolla çalıştığı için listede yoktur; onlar için doğrudan OpenAI ve Claude seçeneklerini kullan.",
      prefer: "deepseek-v4-pro" },
    { id: "openai", label: "OpenAI (GPT)", free: false, endpoint: "https://api.openai.com/v1",
      url: "https://platform.openai.com/api-keys", linkText: "OpenAI anahtar sayfasını aç",
      steps: ["Sayfa açılınca hesap aç ve giriş yap.", "Kullanmak için ödeme bilgisi ekle ya da kredi yükle.", "\"API keys\" sayfasında anahtar oluştur ve kopyala."],
      note: "Ücretlidir.", prefer: "" },
  ];
  const WIZ_STEPS = ["wiz-start", "wiz-local-step", "wiz-cloud-step", "wiz-test-step"];
  const WIZ_EXAMPLES = ["Bir hesap makinesi web sayfası yap.", "Bu klasördeki dosyaları incele ve ne işe yaradıklarını kısaca anlat.", "Bugünün tarihini büyük yazıyla gösteren basit bir sayfa yap."];
  const wizMsg = (t, c) => { const m = $("wiz-msg"); m.textContent = t || ""; m.className = c || "empty"; };
  function wizBusy(on, text) { $("wizard").classList.toggle("wiz-busy", !!on); wizMsg(on ? text : "", on ? "ok" : "empty"); }
  function wizShow(id) {
    for (const s of WIZ_STEPS) $(s).hidden = s !== id;
    wizMsg("");
    if (id === "wiz-start") wizReco();
  }
  function openWizard() { if ($("wizard").hidden) togglePanel("wizard"); else wizShow("wiz-start"); }
  const trimSlash = (u) => String(u || "").replace(/\/+$/, "");
  function wizLink(url, text) {
    const a = h("a", "wiz-link", text);
    a.href = url; a.target = "_blank"; a.rel = "noopener noreferrer";
    return a;
  }

  async function wizReco() {
    const el = $("wiz-reco-text");
    el.textContent = "Bilgisayarına bakıyorum…";
    let d = null;
    try { const r = await api("/system/info"); if (r.ok) d = await r.json(); } catch (_) { /* yoksay */ }
    const ram = d && d.ram_gb ? `${d.ram_gb} GB` : null;
    if (d && d.recommend && !d.recommend.model) {
      el.textContent = `Bilgisayarının belleği az (${ram}). İnternet servisiyle başla; ücretsiz seçenek olarak Google Gemini'yi deneyebilirsin.`;
    } else {
      el.textContent = "Yeni başlıyorsan ve anahtar almaktan çekinmiyorsan: İnternet servisiyle başla, ücretsiz seçenek olarak Google Gemini'yi dene. "
        + `Yazdıklarının bilgisayarından çıkmaması senin için çok önemliyse: Bilgisayarımda${ram ? ` (belleğin ${ram}, bu iş için uygun)` : ""}, ama zor işlerde zayıf kalabileceğini bil.`;
    }
  }

  async function wizUse(apiName, model) {
    wizBusy(true, "Modeli tanıyorum, bu yarım dakika sürebilir. Lütfen bekle…");
    let r;
    try { r = await api("/model", { method: "PUT", body: JSON.stringify({ model, api: apiName }) }); }
    finally { wizBusy(false); }
    if (!r.ok) { wizMsg(await errorText(r), "error"); return; }
    await loadModels();
    wizTest();
  }
  async function wizEnsureLocalApi() {
    const endpoint = "http://127.0.0.1:11434/v1";
    const rows = await (await api("/apis")).json();
    const row = rows.find((a) => trimSlash(a.endpoint) === endpoint);
    if (row) return row.name;
    const r = await api("/apis", { method: "POST", body: JSON.stringify({ name: "ollama", endpoint }) });
    if (!r.ok) throw new Error(await errorText(r));
    return "ollama";
  }
  const fmtGb = (n) => `${(n / 1073741824).toFixed(1)} GB`;
  let wizPullTimer = null;
  function wizStopPull() { clearTimeout(wizPullTimer); wizPullTimer = null; }

  async function wizLocal() {
    wizStopPull();
    wizShow("wiz-local-step");
    const body = $("wiz-local-body");
    body.replaceChildren(h("p", null, "Bilgisayarına bakıyorum…"));
    const res = await api("/system/info");
    if (!res.ok) { body.replaceChildren(h("p", "error", await errorText(res))); return; }
    const d = await res.json();
    const rec = d.recommend || {};
    const out = [h("p", null, d.ram_gb ? `Bilgisayarının belleği: ${d.ram_gb} GB.` : "Bilgisayarının belleğini öğrenemedim.")];
    if (!rec.model) {
      out.push(h("p", null, rec.reason || ""));
      const go = h("button", "primary", "İnternet servisine geç");
      go.type = "button"; go.addEventListener("click", wizCloud);
      body.replaceChildren(...out, go);
      return;
    }
    out.push(h("p", null, rec.reason));
    if (!d.ollama_running) {
      const card = h("div", "card");
      card.append(h("strong", null, "1. Ollama programını kur"),
        h("p", null, "Ollama, yapay zekâ modellerini bilgisayarında çalıştıran ücretsiz bir programdır."),
        wizLink("https://ollama.com/download", "Ollama indirme sayfasını aç"));
      const ol = h("ol", "wiz-steps");
      for (const t of ["İndirdiğin dosyayı aç ve kur.", "Kurulum bitince Ollama'yı bir kez aç (Başlat menüsünde \"Ollama\").", "Bu pencereye dön ve aşağıdaki \"Tekrar ara\" düğmesine bas."]) ol.appendChild(h("li", null, t));
      card.appendChild(ol);
      body.replaceChildren(...out, card);
      return;
    }
    const have = (d.installed || []).includes(rec.model);
    const card = h("div", "card");
    if (!have) {
      card.append(h("strong", null, `2. Modeli indir: ${rec.model}`),
        h("p", null, `Yaklaşık ${rec.size_gb} GB indirir. Hızlı internetle birkaç dakika sürer, yavaşta daha uzun. İndirirken bu pencereyi kapatma.`));
      const dl = h("button", "primary", `İndir (≈ ${rec.size_gb} GB)`);
      dl.type = "button";
      dl.addEventListener("click", () => wizPull(rec.model, card));
      card.appendChild(dl);
    } else {
      card.append(h("strong", null, `Önerilen model zaten kurulu: ${rec.model}`));
      const use = h("button", "primary", "Bunu kullan");
      use.type = "button";
      use.addEventListener("click", async () => { try { wizUse(await wizEnsureLocalApi(), rec.model); } catch (e) { wizMsg(String(e.message || e), "error"); } });
      card.appendChild(use);
    }
    body.replaceChildren(...out, card);
    const others = (d.installed || []).filter((m) => m !== rec.model);
    if (others.length) {
      body.appendChild(h("p", "wiz-group", "Bilgisayarında kurulu diğer modeller:"));
      for (const m of others) {
        const b = h("button", "card wiz-choice");
        b.type = "button"; b.append(h("strong", null, m));
        b.addEventListener("click", async () => { try { wizUse(await wizEnsureLocalApi(), m); } catch (e) { wizMsg(String(e.message || e), "error"); } });
        body.appendChild(b);
      }
    }
  }
  async function wizPull(model, card) {
    const r = await api("/local/pull", { method: "POST", body: JSON.stringify({ model }) });
    if (!r.ok && r.status !== 409) { wizMsg(await errorText(r), "error"); return; }
    const bar = h("progress", "wiz-progress"); bar.max = 100; bar.value = 0;
    const label = h("p", "note", "İndirme başlıyor…");
    card.replaceChildren(h("strong", null, `İndiriliyor: ${model}`), bar, label);
    const poll = async () => {
      if ($("wiz-local-step").hidden) return;  // kullanıcı başka adıma geçti
      let s = null;
      try { const p = await api("/local/pull"); if (p.ok) s = await p.json(); } catch (_) { /* tekrar dene */ }
      if (s && s.error) {
        card.replaceChildren(h("p", "error", s.error));
        const again = h("button", null, "Tekrar dene"); again.type = "button"; again.addEventListener("click", wizLocal);
        card.appendChild(again);
        return;
      }
      if (s && s.done) { wizLocal(); return; }
      if (s && s.total) {
        const pct = Math.min(100, Math.round((s.completed / s.total) * 100));
        bar.value = pct;
        label.textContent = `%${pct} (${fmtGb(s.completed)} / ${fmtGb(s.total)})`;
      }
      wizPullTimer = setTimeout(poll, 1000);
    };
    poll();
  }

  let wizService = null;
  function wizCloud() {
    wizStopPull();
    wizShow("wiz-cloud-step");
    wizService = null;
    $("wiz-service-help").hidden = true;
    $("wiz-cloud-form").hidden = true;
    $("wiz-models").hidden = true;
    const box = $("wiz-services");
    box.replaceChildren();
    const groups = [["Ücretsiz seçenekler", true], ["Ücretli servisler (bakiye ya da kredi gerekir)", false]];
    for (const [title, free] of groups) {
      box.appendChild(h("p", "wiz-group", title));
      const row = h("div", "wiz-choices");
      for (const svc of WIZ_SERVICES.filter((x) => x.free === free)) {
        const b = h("button", "card wiz-choice");
        b.type = "button";
        const name = h("strong", null, svc.label);
        name.appendChild(h("span", free ? "wiz-tag" : "wiz-tag paid", free ? "ücretsiz katmanı var" : "ücretli"));
        b.append(name);
        b.addEventListener("click", () => wizPickService(svc));
        row.appendChild(b);
      }
      box.appendChild(row);
    }
  }
  function wizPickService(svc) {
    wizService = svc;
    const help = $("wiz-service-help");
    const ol = h("ol", "wiz-steps");
    for (const t of svc.steps) ol.appendChild(h("li", null, t));
    help.replaceChildren(h("strong", null, `${svc.label}: anahtarı nasıl alırım?`), wizLink(svc.url, svc.linkText), ol, h("p", "wiz-note", svc.note));
    help.hidden = false;
    $("wiz-cloud-form").hidden = false;
    $("wiz-models").hidden = true;
    wizMsg("");
    help.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  async function wizTryKey(ev) {
    ev.preventDefault();
    const svc = wizService;
    const key = $("wiz-key").value.trim();
    if (!svc || !key) return;
    wizBusy(true, "Anahtarı deniyorum…");
    try {
      let r = await api("/apis", { method: "POST", body: JSON.stringify({ name: svc.id, endpoint: svc.endpoint, key }) });
      if (r.status === 409) r = await api(`/apis/${svc.id}/key`, { method: "PUT", body: JSON.stringify({ key }) });
      if (!r.ok) { wizBusy(false); wizMsg(await errorText(r), "error"); return; }
      $("wiz-key").value = "";
      const info = await (await api("/model")).json();
      const g = (info.apis || []).find((x) => x.api === svc.id);
      wizBusy(false);
      if (!g || !g.models.length) { wizMsg("Anahtar kabul edilmedi ya da servise ulaşılamadı. Doğru kopyaladığından emin ol (başında/sonunda boşluk olmasın) ve tekrar dene.", "error"); return; }
      const sel = $("wiz-model");
      const list = L.chatModels(g.models, svc.prefer);
      sel.replaceChildren(...list.map((m) => { const o = h("option", null, m.replace(/^models\//, "")); o.value = m; return o; }));
      sel.value = list[0];
      $("wiz-models").hidden = false;
    } catch (e) {
      wizBusy(false);
      wizMsg("Bir şey ters gitti, tekrar dene.", "error");
    }
  }
  async function wizTest() {
    wizShow("wiz-test-step");
    $("wiz-test-title").textContent = "Deniyorum…";
    $("wiz-test-text").textContent = "Modele kısa bir merhaba gönderiyorum.";
    $("wiz-examples").hidden = true;
    $("wiz-test-back").hidden = true;
    const res = await api("/setup/ping", { method: "POST" });
    const d = res.ok ? await res.json() : { ok: false, error: await errorText(res) };
    if (!d.ok) {
      $("wiz-test-title").textContent = "Olmadı";
      $("wiz-test-text").textContent = d.error;
      $("wiz-test-back").hidden = false;
      return;
    }
    $("wiz-test-title").textContent = "Hazır!";
    $("wiz-test-text").textContent = `Model cevap verdi (${d.seconds} sn): "${d.reply}". Şimdi bir şey dene:`;
    const box = $("wiz-examples");
    box.replaceChildren(...WIZ_EXAMPLES.map((t) => {
      const b = h("button", "card wiz-choice");
      b.type = "button";
      b.append(h("strong", null, t));
      b.addEventListener("click", () => { togglePanel("wizard"); $("prompt").value = t; $("prompt").focus(); });
      return b;
    }));
    box.hidden = false;
  }

  // --- dosya gezgini ---
  const filesMsg = (t) => { $("files-msg").textContent = t || ""; };
  const joinPath = (dir, name) => (dir ? `${dir}/${name}` : name);
  async function fillDir(dir, ul) {
    const res = await api(`/workspaces/${encodeURIComponent(state.ws)}/tree?path=${encodeURIComponent(dir)}`);
    if (!res.ok) { filesMsg(await errorText(res)); return; }
    ul.replaceChildren();
    const { entries } = await res.json();
    if (!entries.length && !dir) ul.appendChild(h("li", "empty", "Boş. Dosya ya da klasör yükleyebilirsin."));
    for (const e of entries) {
      const path = joinPath(dir, e.name);
      const li = h("li", (e.dir ? "dir" : "file") + (e.link ? " link" : "") + (e.dir && state.selDir === path ? " sel" : ""));
      const b = h("button", null, (e.dir ? (state.openDirs.has(path) ? "▾ " : "▸ ") : "  ") + e.name);
      b.type = "button";
      b.title = path;
      const line = h("div", "line");
      line.appendChild(b);
      line.appendChild(rowActions(path, e));
      li.appendChild(line);
      if (e.dir && !e.link) {
        const sub = h("ul");
        sub.hidden = !state.openDirs.has(path);
        li.appendChild(sub);
        if (state.openDirs.has(path)) fillDir(path, sub);
        b.addEventListener("click", () => {
          document.querySelectorAll("#file-tree li.sel").forEach((x) => x.classList.remove("sel"));
          li.classList.add("sel");
          state.selDir = path;
          const open = !state.openDirs.has(path);
          if (open) state.openDirs.add(path); else state.openDirs.delete(path);
          b.textContent = (open ? "▾ " : "▸ ") + e.name;
          sub.hidden = !open;
          if (open) fillDir(path, sub);
        });
      } else if (!e.dir) {
        b.addEventListener("click", () => openFile(path));
      }
      ul.appendChild(li);
    }
  }
  // --- dosya işlemleri: yeni dosya/klasör, yeniden adlandır, sil ---
  async function fsCall(body) {
    const res = await api(`/workspaces/${encodeURIComponent(state.ws)}/fs`, { method: "POST", body: JSON.stringify(body) });
    if (!res.ok) { filesMsg(await errorText(res)); return false; }
    return true;
  }
  function rowActions(path, e) {
    const acts = h("span", "acts");
    const ren = h("button", null, "✎");
    ren.type = "button"; ren.title = "Yeniden adlandır"; ren.setAttribute("aria-label", `${path} yeniden adlandır`);
    ren.addEventListener("click", () => startFs("rename", path));
    const del = h("button", null, "🗑");
    del.type = "button"; del.title = "Sil"; del.setAttribute("aria-label", `${path} sil`);
    let armed = null;
    del.addEventListener("click", async () => {
      if (!armed) {
        del.textContent = e.dir ? "Klasörü sil?" : "Sil?";
        del.classList.add("armed");
        armed = setTimeout(() => { armed = null; del.textContent = "🗑"; del.classList.remove("armed"); }, 4000);
        return;
      }
      clearTimeout(armed);
      if (await fsCall({ op: "delete", path })) {
        if (state.openFile && (state.openFile.path === path || state.openFile.path.startsWith(`${path}/`))) { state.openFile = null; showTab("stream"); }
        state.openDirs.delete(path);
        if (state.selDir === path) state.selDir = "";
        refreshTree();
        filesMsg(`${path} silindi.`);
      }
    });
    acts.append(ren, del);
    return acts;
  }
  function startFs(mode, path) {
    state.fsMode = { mode, path };
    const label = { create_file: "Yeni dosya adı", create_dir: "Yeni klasör adı", rename: `Yeni ad: ${path}` }[mode];
    $("fs-label").textContent = mode === "rename" ? label : `${label}${state.selDir ? ` (${state.selDir}/ içine)` : ""}`;
    $("fs-input").value = mode === "rename" ? path.split("/").pop() : "";
    $("fs-form").hidden = false;
    $("fs-input").focus();
  }
  async function submitFs(ev) {
    ev.preventDefault();
    const f = state.fsMode;
    const name = $("fs-input").value.trim();
    if (!f || !name || name.includes("\\")) return;
    const base = f.mode === "rename" ? f.path.split("/").slice(0, -1).join("/") : state.selDir;
    const target = joinPath(base, name);
    const ok = await fsCall(f.mode === "rename" ? { op: "rename", path: f.path, to: target } : { op: f.mode, path: target });
    if (!ok) return;
    $("fs-form").hidden = true;
    state.fsMode = null;
    if (f.mode === "rename" && state.openFile && state.openFile.path === f.path) { state.openFile = null; showTab("stream"); }
    refreshTree(true);
    filesMsg(f.mode === "rename" ? `${f.path} → ${target}` : `${target} oluşturuldu.`);
  }
  async function refreshTree(keepMsg) {
    if (keepMsg !== true) filesMsg("");
    const ul = $("file-tree");
    ul.replaceChildren();
    const up = !state.ws || state.active;
    $("f-up-files").disabled = $("f-up-dir").disabled = $("f-new-file").disabled = $("f-new-dir").disabled = up;
    if (state.ws) await fillDir("", ul);
  }
  async function openFile(path) {
    const res = await api(`/workspaces/${encodeURIComponent(state.ws)}/files?path=${encodeURIComponent(path)}`);
    if (!res.ok) { filesMsg(`${path}: ${await errorText(res)}`); return; }
    const f = await res.json();
    state.openFile = { path, content: f.content };
    $("fileview-path").textContent = path;
    $("fileview-body").textContent = f.content.length > 200000 ? `${f.content.slice(0, 200000)}\n… [kırpıldı]` : f.content;
    showTab("file");
  }
  function attachOpenFile() {
    const f = state.openFile;
    if (!f) return;
    if (state.files.some((x) => x.name === f.path)) { filesMsg("Zaten ekli."); return; }
    if (f.content.length > MAX_ATT_BYTES) { filesMsg("Dosya 100 KB'tan büyük, göreve eklenemez; ajan zaten read_file ile okuyabilir."); return; }
    if (state.files.length >= MAX_ATT) { filesMsg(`En çok ${MAX_ATT} dosya eklenebilir.`); return; }
    state.files.push({ name: f.path, content: f.content, size: f.content.length });
    renderAttached();
    filesMsg(`${f.path} göreve eklendi.`);
    showTab("stream");
  }
  const SKIP_UPLOAD = new Set([".git", "node_modules", ".venv", "__pycache__", ".usta"]);
  async function toB64(file) {
    const buf = new Uint8Array(await file.arrayBuffer());
    let s = "";
    for (let i = 0; i < buf.length; i += 0x8000) s += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
    return btoa(s);
  }
  async function uploadFiles(list) {
    if (!state.ws || state.active) return;
    const files = Array.from(list).filter((f) => !(f.webkitRelativePath || f.name).split("/").some((p) => SKIP_UPLOAD.has(p)));
    if (!files.length) { filesMsg("Yüklenecek dosya yok."); return; }
    let written = 0, skipped = 0, batch = [], size = 0;
    const flush = async () => {
      if (!batch.length) return true;
      const res = await api(`/workspaces/${encodeURIComponent(state.ws)}/import`, { method: "POST", body: JSON.stringify({ files: batch }) });
      batch = []; size = 0;
      if (!res.ok) { filesMsg(await errorText(res)); return false; }
      const r = await res.json();
      written += r.written.length; skipped += r.skipped.length;
      return true;
    };
    filesMsg(`Yükleniyor (${files.length} dosya)…`);
    for (const f of files) {
      if (f.size > 5000000) { filesMsg(`${f.name}: 5 MB'tan büyük, atlandı.`); continue; }
      batch.push({ path: f.webkitRelativePath || f.name, b64: await toB64(f) });
      size += f.size;
      if (batch.length >= 100 || size > 6000000) { if (!(await flush())) return; }
    }
    if (!(await flush())) return;
    filesMsg(`${written} dosya yüklendi${skipped ? `, ${skipped} dosya zaten vardı (atlandı)` : ""}.`);
    refreshTree(true);
  }

  // --- çalışma alanları ---
  async function loadWorkspaces() {
    const res = await api("/workspaces");
    if (!res.ok) return [];
    const list = $("ws-list");
    list.replaceChildren();
    const all = await res.json();
    for (const w of all) {
      const li = h("li");
      const b = h("button", null, w.id);
      b.type = "button";
      b.setAttribute("aria-current", String(w.id === state.ws));
      b.addEventListener("click", () => selectWorkspace(w.id));
      li.appendChild(b);
      list.appendChild(li);
    }
    return all.map((w) => w.id);
  }
  async function selectWorkspace(id) {
    if (state.active) return;
    state.ws = id;
    state.task = null;
    state.replay = false;
    officeReset();
    state.files = [];
    renderAttached();
    $("replay-bar").hidden = true;
    put("usta_ws", id);
    $("ws-title").textContent = id;
    $("stream").replaceChildren();
    showUsage(null);
    renderDiff("");
    $("diff-count").textContent = "";
    $("revert").disabled = true;
    setStatus("");
    setActive(false);
    $("memory-count").textContent = "";
    state.openFile = null;
    state.openDirs = new Set();
    state.selDir = "";
    $("fs-form").hidden = true;
    refreshTree();
    if (!$("memory").hidden || !$("history").hidden || !$("fileview").hidden || !$("preview").hidden) showTab("stream");
    await loadWorkspaces();
    const saved = get("usta_task");
    if (saved.startsWith(id + ":")) await resume(saved.slice(id.length + 1));
    hideResult();
    updateStarters();
  }
  async function resume(taskId) {
    const res = await api(`/tasks/${encodeURIComponent(taskId)}`);
    if (!res.ok) { put("usta_task", ""); return; }
    const info = await res.json();
    state.contextWindow = info.context_window || null;
    showUsage(info.usage, state.contextWindow);
    officeReset();
    addNode(h("div", "msg user", info.prompt));
    follow(taskId);
  }
  async function createWorkspace(ev) {
    ev.preventDefault();
    const input = $("ws-name");
    const res = await api("/workspaces", { method: "POST", body: JSON.stringify({ name: input.value.trim() }) });
    if (!res.ok) { setConn(await errorText(res), "bad"); return; }
    const w = await res.json();
    input.value = "";
    await selectWorkspace(w.id);
  }

  async function connect(ev) {
    if (ev) ev.preventDefault();
    const typed = $("token").value.trim();
    if (/^\d{6}$/.test(typed)) { $("token").value = ""; await exchangeCode(typed); return; }  // tablet eşleştirme kodu
    state.token = typed || state.token;
    if (!state.token) { setConn("Jeton ya da 6 haneli kod gerekli", "bad"); return; }
    try {
      const res = await api("/workspaces");
      if (!res.ok) { setConn(await errorText(res), "bad"); return; }
    } catch (e) {
      if (String(e.message) !== "401") setConn(USTA_KAPALI, "bad");
      return;
    }
    put("usta_token", state.token);
    $("token").value = "";
    $("token-form").hidden = true;
    setConn("Bağlı", "ok");
    const modelInfo = await loadModels();
    if (modelInfo && !modelInfo.model) openWizard();  // model seçilmemiş: sihirbaz açılır
    const [ids] = await Promise.all([loadWorkspaces(), loadSettings()]);
    const saved = get("usta_ws");
    // kayıtlı alan yoksa terminalin açtığı alan, o da yoksa tek/ilk alan seçilir (yazı alanı kilitli kalmasın)
    const pick = saved && ids.includes(saved) ? saved : state.defaultWs && ids.includes(state.defaultWs) ? state.defaultWs : ids[0];
    if (pick) await selectWorkspace(pick);
    else { put("usta_ws", ""); put("usta_task", ""); $("prompt").placeholder = "Önce soldan bir çalışma alanı oluştur"; }
  }

  $("token-form").addEventListener("submit", connect);
  $("ws-form").addEventListener("submit", createWorkspace);
  $("composer").addEventListener("submit", (ev) => { ev.preventDefault(); sendPrompt(); });
  $("prompt").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); sendPrompt(); }
  });
  $("stop").addEventListener("click", stopTask);
  $("model-select").addEventListener("change", switchModel);
  $("revert").addEventListener("click", revertTask);
  $("tab-stream").addEventListener("click", () => showTab("stream"));
  $("tab-diff").addEventListener("click", () => showTab("diff"));
  $("tab-memory").addEventListener("click", () => showTab("memory"));
  $("tab-history").addEventListener("click", () => showTab("history"));
  $("replay-close").addEventListener("click", () => { leaveReplay(); showTab("stream"); });
  $("attach").addEventListener("click", () => $("file-input").click());
  $("file-input").addEventListener("change", async () => { await addFiles($("file-input").files); $("file-input").value = ""; });
  const comp = $("composer");
  comp.addEventListener("dragover", (ev) => { if (state.ws && !state.active) { ev.preventDefault(); comp.classList.add("drop"); } });
  comp.addEventListener("dragleave", () => comp.classList.remove("drop"));
  comp.addEventListener("drop", (ev) => {
    ev.preventDefault();
    comp.classList.remove("drop");
    if (state.ws && !state.active && ev.dataTransfer) addFiles(ev.dataTransfer.files);
  });
  $("tools-btn").addEventListener("click", () => togglePanel("tools"));
  $("apis-btn").addEventListener("click", () => togglePanel("apis"));
  $("privacy-btn").addEventListener("click", () => togglePanel("privacy"));
  $("api-form").addEventListener("submit", addApi);
  $("local-scan").addEventListener("click", scanLocal);
  $("wizard-btn").addEventListener("click", () => togglePanel("wizard"));
  $("tablet-btn").addEventListener("click", () => togglePanel("tablet"));
  $("settings-btn").addEventListener("click", () => togglePanel("settings"));
  $("tablet-renew").addEventListener("click", loadTablet);
  $("wiz-local").addEventListener("click", wizLocal);
  $("wiz-cloud").addEventListener("click", wizCloud);
  $("wiz-local-back").addEventListener("click", () => wizShow("wiz-start"));
  $("wiz-local-rescan").addEventListener("click", wizLocal);
  $("wiz-cloud-back").addEventListener("click", () => wizShow("wiz-start"));
  $("wiz-test-back").addEventListener("click", () => wizShow("wiz-start"));
  $("wiz-cloud-form").addEventListener("submit", wizTryKey);
  $("wiz-model-go").addEventListener("click", () => wizUse(wizService.id, $("wiz-model").value));
  $("skill-upload").addEventListener("click", () => $("skill-input").click());
  $("skill-input").addEventListener("change", async () => { await uploadSkills($("skill-input").files); $("skill-input").value = ""; });
  $("f-refresh").addEventListener("click", () => refreshTree());
  $("f-new-file").addEventListener("click", () => startFs("create_file"));
  $("f-new-dir").addEventListener("click", () => startFs("create_dir"));
  $("fs-form").addEventListener("submit", submitFs);
  $("fs-cancel").addEventListener("click", () => { $("fs-form").hidden = true; state.fsMode = null; });
  $("f-up-files").addEventListener("click", () => $("f-input").click());
  $("f-up-dir").addEventListener("click", () => $("f-dir-input").click());
  $("f-input").addEventListener("change", async () => { await uploadFiles($("f-input").files); $("f-input").value = ""; });
  $("f-dir-input").addEventListener("change", async () => { await uploadFiles($("f-dir-input").files); $("f-dir-input").value = ""; });
  $("fileview-attach").addEventListener("click", attachOpenFile);
  $("tab-file").addEventListener("click", () => showTab("file"));
  $("tab-preview").addEventListener("click", () => showTab("preview"));
  $("tab-office").addEventListener("click", () => showTab("office"));
  $("preview-go").addEventListener("click", loadPreview);
  $("preview-reload").addEventListener("click", loadPreview);
  $("preview-path").addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); loadPreview(); } });
  $("zoom").addEventListener("change", () => {
    state.zoom = $("zoom").value;
    saveSetting({ zoom: state.zoom });
    applyZoom();
  });
  $("think").addEventListener("change", () => saveSetting({ think: $("think").value }));
  $("dev-btn").addEventListener("click", () => {
    const next = state.view === "advanced" ? "simple" : "advanced";
    applyView(next);
    saveSetting({ view: next });
  });
  $("view").addEventListener("change", () => { applyView($("view").value); saveSetting({ view: $("view").value }); });
  $("set-wizard").addEventListener("click", () => { if ($("wizard").hidden) togglePanel("wizard"); else wizShow("wiz-start"); });
  $("set-tablet").addEventListener("click", () => togglePanel("tablet"));
  let quitArmed = null;
  $("set-quit").addEventListener("click", async () => {
    const b = $("set-quit");
    if (!quitArmed) { b.textContent = "Emin misin? Tekrar bas"; quitArmed = setTimeout(() => { quitArmed = null; b.textContent = "Usta'yı kapat"; }, 4000); return; }
    clearTimeout(quitArmed); quitArmed = null;
    const r = await api("/quit", { method: "POST" });
    if (!r.ok) { b.textContent = "Usta'yı kapat"; wizMsg(await errorText(r), "error"); return; }
    document.body.replaceChildren(h("p", "wiz-note", "Usta kapandı. Tekrar açmak için masaüstündeki Usta simgesine çift tıkla. Bu sekmeyi kapatabilirsin."));
    document.body.style.padding = "32px";
  });
  $("result-open").addEventListener("click", () => showTab("preview"));
  $("result-folder").addEventListener("click", async () => {
    const r = await api(`/workspaces/${encodeURIComponent(state.ws)}/reveal`, { method: "POST" });
    if (!r.ok) addNode(h("div", "msg error", "Klasör açılamadı. Dosyalar sol taraftaki \"Dosyalarım\" listesinde de görünür."));
  });
  let undoArmed = null;
  $("result-undo").addEventListener("click", async () => {
    const b = $("result-undo");
    if (!undoArmed) { b.textContent = "Emin misin? Tekrar bas"; undoArmed = setTimeout(() => { undoArmed = null; b.textContent = "Yaptığı değişikliği geri al"; }, 4000); return; }
    clearTimeout(undoArmed); undoArmed = null; b.textContent = "Yaptığı değişikliği geri al";
    if (await doRevert()) { hideResult(); updateStarters(); }
  });
  $("ctx").addEventListener("change", () => saveSetting({ context_window: Number($("ctx").value) }));
  applyZoom();
  if (window.Office && typeof window.Office.init === "function") window.Office.init();
  // Ofis onay şeridi → mevcut karar akışı (tek yol: decideApproval)
  if (window.Office) window.Office.onDecide = (id, decision) => decideApproval(id, decision);
  $("theme").addEventListener("change", () => { applyTheme($("theme").value); saveSetting({ theme: $("theme").value }); });
  $("guard").addEventListener("change", () => saveSetting({ guard: $("guard").checked }));
  $("mode").addEventListener("change", () => { applyMode($("mode").value); saveSetting({ mode: $("mode").value }); });
  $("clear-history").addEventListener("click", clearHistory);

  // Terminal portalı `?code=` ile açar: tek kullanımlık kod jetonla takas edilir, URL hemen temizlenir.
  async function exchangeCode(code) {
    try {
      const res = await fetch("/auth/exchange", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code }) });
      if (!res.ok) { setConn("Kod geçersiz ya da süresi dolmuş. Bilgisayarda \"Tablet\" düğmesinden yeni kod al", "bad"); return; }
      state.token = (await res.json()).token;
      connect();
    } catch (_) { setConn(USTA_KAPALI, "bad"); }
  }
  const loginCode = new URLSearchParams(location.search).get("code");
  if (loginCode) {
    history.replaceState(null, "", location.pathname);
    exchangeCode(loginCode);
  } else {
    state.token = get("usta_token");
    if (state.token) connect();
  }
})();
