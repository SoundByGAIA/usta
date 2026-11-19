// Usta web arayüzü. Güvenilmeyen içerik (model çıktısı, dosyalar) yalnız textContent ile basılır.
(function () {
  "use strict";
  const U = (window.UstaApp = window.UstaApp || {});
  Object.assign(U, { api, errorText, fillPrompt, h, loadModels, put, setActive, updateStarters });
  const L = window.UstaLogic;
  const $ = (id) => document.getElementById(id);
  const state = { token: "", ws: null, task: null, active: false, abort: null, approvals: {}, contextWindow: null, files: [], replay: false, openFile: null, openDirs: new Set(), selDir: "", defaultWs: null, zoom: "auto", fsMode: null, tab: "stream", resultOn: false, panelStack: [], designSkill: false };
  Object.assign(U, { state });
  const STATUS = {
    running: "çalışıyor", awaiting_approval: "onay bekliyor", cancelling: "durduruluyor",
    done: "bitti", cancelled: "durduruldu", failed: "başarısız",
  };
  Object.assign(U, { STATUS, setStatus });

  function put(k, v) {
    try { if (v == null || v === "") sessionStorage.removeItem(k); else sessionStorage.setItem(k, v); } catch (_) { /* gizli mod */ }
  }
  function get(k) {
    try { return sessionStorage.getItem(k) || ""; } catch (_) { return ""; }
  }
  // Açılış animasyonu tarayıcı oturumu başına bir kez; sonra öğe kaldırılır (tıklamaları hiç engellemez)
  const acilis = $("acilis");
  if (acilis) {
    if (get("usta_acilis")) acilis.remove();
    else { put("usta_acilis", "1"); setTimeout(() => acilis.remove(), 1600); }
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
  const ACCENTS = ["cini", "turkuaz", "nar", "zeytin", "mor"];
  function applyAccent(name) {
    const a = ACCENTS.includes(name) ? name : "cini";
    document.documentElement.dataset.accent = a;
    for (const b of document.querySelectorAll("#accent .swatch")) b.setAttribute("aria-pressed", String(b.dataset.accent === a));
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
    applyAccent(s.accent);
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
  Object.assign(U, { sleep });

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
    const show = !!state.ws && !state.active && !state.replay && state.tab === "stream" && $("stream").children.length === 0 && !state.resultOn;
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
  function hideResult() { state.resultOn = false; $("result-card").hidden = true; }
  async function showResult() {
    if (!state.ws || state.replay) return;
    const card = $("result-card");
    state.resultOn = true;
    card.hidden = state.tab !== "stream";  // başka sekmedeyken görünmez; Konuşma'ya dönünce yeniden görünür
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
    if (info.model) updateWhere();
    else $("where").hidden = true;  // model seçilmeden "nerede çalışıyor" söylenemez
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
  const PANELS = ["tools", "apis", "privacy", "wizard", "tablet", "settings", "glossary"];
  Object.assign(U, { PANELS });
  const openPanel = () => PANELS.find((p) => !$(p).hidden) || null;
  Object.assign(U, { openPanel });
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
    U.officeReset();
    state.files = [];
    U.renderAttached();
    $("replay-bar").hidden = true;
    put("usta_ws", id);
    $("ws-title").textContent = id;
    $("stream").replaceChildren();
    U.showUsage(null);
    U.renderDiff("");
    $("diff-count").textContent = "";
    $("revert").disabled = true;
    setStatus("");
    setActive(false);
    $("memory-count").textContent = "";
    state.openFile = null;
    state.openDirs = new Set();
    state.selDir = "";
    $("fs-form").hidden = true;
    U.refreshTree();
    if (!$("memory").hidden || !$("history").hidden || !$("fileview").hidden || !$("preview").hidden) U.showTab("stream");
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
    U.showUsage(info.usage, state.contextWindow);
    U.officeReset();
    U.addNode(h("div", "msg user", info.prompt));
    U.follow(taskId);
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
    if (modelInfo && !modelInfo.model) U.openWizard();  // model seçilmemiş: sihirbaz açılır
    const [ids] = await Promise.all([loadWorkspaces(), loadSettings()]);
    const saved = get("usta_ws");
    // kayıtlı alan yoksa terminalin açtığı alan, o da yoksa tek/ilk alan seçilir (yazı alanı kilitli kalmasın)
    const pick = saved && ids.includes(saved) ? saved : state.defaultWs && ids.includes(state.defaultWs) ? state.defaultWs : ids[0];
    if (pick) await selectWorkspace(pick);
    else { put("usta_ws", ""); put("usta_task", ""); $("prompt").placeholder = "Önce soldan bir çalışma alanı oluştur"; }
  }

  $("token-form").addEventListener("submit", connect);
  $("ws-form").addEventListener("submit", createWorkspace);
  $("composer").addEventListener("submit", (ev) => { ev.preventDefault(); U.sendPrompt(); });
  $("prompt").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); U.sendPrompt(); }
  });
  $("stop").addEventListener("click", U.stopTask);
  $("model-select").addEventListener("change", switchModel);
  $("revert").addEventListener("click", U.revertTask);
  $("tab-stream").addEventListener("click", () => U.showTab("stream"));
  $("tab-diff").addEventListener("click", () => U.showTab("diff"));
  $("tab-memory").addEventListener("click", () => U.showTab("memory"));
  $("tab-history").addEventListener("click", () => U.showTab("history"));
  $("replay-close").addEventListener("click", () => { U.leaveReplay(); U.showTab("stream"); });
  $("attach").addEventListener("click", () => $("file-input").click());
  $("file-input").addEventListener("change", async () => { await U.addFiles($("file-input").files); $("file-input").value = ""; });
  const comp = $("composer");
  comp.addEventListener("dragover", (ev) => { if (state.ws && !state.active) { ev.preventDefault(); comp.classList.add("drop"); } });
  comp.addEventListener("dragleave", () => comp.classList.remove("drop"));
  comp.addEventListener("drop", (ev) => {
    ev.preventDefault();
    comp.classList.remove("drop");
    if (state.ws && !state.active && ev.dataTransfer) U.addFiles(ev.dataTransfer.files);
  });
  $("tools-btn").addEventListener("click", () => U.togglePanel("tools"));
  $("apis-btn").addEventListener("click", () => U.togglePanel("apis"));
  $("privacy-btn").addEventListener("click", () => U.togglePanel("privacy"));
  $("api-form").addEventListener("submit", U.addApi);
  $("tools-reg-form").addEventListener("submit", (ev) => U.searchRegistry(ev));
  $("local-scan").addEventListener("click", U.scanLocal);
  $("wizard-btn").addEventListener("click", () => U.togglePanel("wizard"));
  $("tablet-btn").addEventListener("click", () => U.togglePanel("tablet"));
  $("glossary-btn").addEventListener("click", () => U.togglePanel("glossary"));
  $("gloss-q").addEventListener("input", U.renderGlossary);
  $("settings-btn").addEventListener("click", () => U.togglePanel("settings"));
  $("tablet-renew").addEventListener("click", U.loadTablet);
  $("wiz-local").addEventListener("click", U.wizLocal);
  $("wiz-cloud").addEventListener("click", U.wizCloud);
  $("wiz-lan").addEventListener("click", U.wizLan);
  $("wiz-lan-back").addEventListener("click", () => U.wizShow("wiz-start"));
  $("wiz-lan-rescan").addEventListener("click", U.wizLan);
  $("wiz-lan-form").addEventListener("submit", U.wizLanTry);
  $("wiz-local-back").addEventListener("click", () => U.wizShow("wiz-start"));
  $("wiz-local-rescan").addEventListener("click", U.wizLocal);
  $("wiz-cloud-back").addEventListener("click", () => U.wizShow("wiz-start"));
  $("wiz-test-back").addEventListener("click", () => U.wizShow("wiz-start"));
  $("wiz-cloud-form").addEventListener("submit", U.wizTryKey);
  $("skill-upload").addEventListener("click", () => $("skill-input").click());
  $("skill-input").addEventListener("change", async () => { await U.uploadSkills($("skill-input").files); $("skill-input").value = ""; });
  $("tab-file").addEventListener("click", () => U.showTab("file"));
  $("tab-preview").addEventListener("click", () => U.showTab("preview"));
  $("tab-office").addEventListener("click", () => U.showTab("office"));
  $("preview-go").addEventListener("click", U.loadPreview);
  $("preview-reload").addEventListener("click", U.loadPreview);
  $("preview-path").addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); U.loadPreview(); } });
  $("kisi-save").addEventListener("click", U.saveProfile);
  $("skill-design").addEventListener("click", U.startSkillDesign);
  $("design-off").addEventListener("click", () => { U.setDesignSkill(false); $("prompt").value = ""; });
  $("ortak-ac").addEventListener("click", async () => { U.ortakMsg("Açıyorum…"); if (await U.ortakCall("/ortak/ev-sahibi", "POST", { acik: true })) { U.ortakMsg("Açıldı. Şimdi \"kod göster\"e basıp öbür bilgisayardan bağlanabilirsin.", "ok"); U.loadOrtak(); } });
  $("ortak-kapat").addEventListener("click", async () => { if (await U.ortakCall("/ortak/ev-sahibi", "POST", { acik: false })) { U.ortakMsg("Kapattım. Bağlı bilgisayarlar artık ulaşamaz.", "ok"); U.loadOrtak(); } });
  $("ortak-kod-al").addEventListener("click", async () => {
    const d = await U.ortakCall("/ortak/kod");
    if (!d) return;
    $("ortak-kod-kutu").textContent = d.kod; $("ortak-kod-kutu").hidden = false;
    $("ortak-kod-not").textContent = `Öbür bilgisayarda "Evdeki ortak hafıza" bölümüne şu adresi ve bu kodu yaz: ${d.adres}. Kod 5 dakika geçerli ve bir kez kullanılır.`;
    $("ortak-kod-not").hidden = false; U.ortakMsg("");
  });
  $("ortak-baglan-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    U.ortakMsg("Bağlanıyorum…");
    const d = await U.ortakCall("/ortak/baglan", "POST", { adres: $("ortak-adres").value.trim(), kod: $("ortak-kod").value.trim() });
    if (d) { $("ortak-baglan-form").reset(); U.ortakMsg(`Bağlandım: ${d.ad}.`, "ok"); await U.loadProfile(); U.loadOrtak(); }
  });
  $("ortak-ayril").addEventListener("click", async () => { if (await U.ortakCall("/ortak/ayril")) { U.ortakMsg("Bağlantıyı kestim. Bilgilerin yine bu bilgisayarın kendi bilgileri.", "ok"); await U.loadProfile(); U.loadOrtak(); } });
  $("ortak-not-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const v = $("ortak-not").value.trim();
    if (!v) return;
    const d = await U.ortakCall("/ortak/notlar", "POST", { text: v });
    if (d) { $("ortak-not").value = ""; U.ortakMsg(d.durum === "bekliyor" ? "Notu ev sahibine gönderdim. O onaylayana kadar yapay zekâya gitmez." : "Not eklendi.", "ok"); U.loadOrtak(); }
  });
  $("kisi-clear").addEventListener("click", async () => {
    const r = await api("/profile", { method: "DELETE" });
    if (!r.ok) { U.kisiMsg(await errorText(r), "error"); return; }
    await U.loadProfile(); U.kisiMsg("Hepsini sildim.", "ok");
  });
  $("accent").addEventListener("click", (ev) => {
    const b = ev.target.closest && ev.target.closest(".swatch");
    if (!b) return;
    applyAccent(b.dataset.accent);
    saveSetting({ accent: b.dataset.accent });
  });
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
  $("set-wizard").addEventListener("click", () => { if ($("wizard").hidden) U.togglePanel("wizard"); else U.wizShow("wiz-start"); });
  $("set-tablet").addEventListener("click", () => U.togglePanel("tablet"));
  // Yardım raporu: sunucu hazırlar, kullanıcı görür ve kendisi gönderir (kendiliğinden hiçbir yere gitmez).
  let helpReport = null;
  $("set-help").addEventListener("click", async () => {
    const res = await api("/support/report");
    $("help-box").hidden = false;
    if (!res.ok) { helpReport = null; $("help-text").textContent = ""; $("help-msg").textContent = "Rapor hazırlanamadı. Usta'yı kapatıp yeniden aç ve tekrar dene."; return; }
    helpReport = await res.json();
    $("help-text").textContent = helpReport.text;
    $("help-msg").textContent = "Rapor hazır. İndir ya da kopyala, sonra sana Usta'yı veren kişiye gönder.";
  });
  $("help-save").addEventListener("click", () => {
    if (!helpReport) return;
    const url = URL.createObjectURL(new Blob([helpReport.text], { type: "text/plain;charset=utf-8" }));
    const a = h("a"); a.href = url; a.download = helpReport.filename;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    $("help-msg").textContent = `"${helpReport.filename}" dosyası İndirilenler klasörüne indi. Bu dosyayı sana Usta'yı veren kişiye gönder.`;
  });
  $("help-copy").addEventListener("click", async () => {
    if (!helpReport) return;
    try { await navigator.clipboard.writeText(helpReport.text); $("help-msg").textContent = "Kopyalandı. Mesajına yapıştırıp gönderebilirsin."; }
    catch { $("help-msg").textContent = "Kopyalanamadı. Yazıyı elle seçip kopyala ya da dosya olarak indir."; }
  });
  let quitArmed = null;
  $("set-quit").addEventListener("click", async () => {
    const b = $("set-quit");
    if (!quitArmed) { b.textContent = "Emin misin? Tekrar bas"; quitArmed = setTimeout(() => { quitArmed = null; b.textContent = "Usta'yı kapat"; }, 4000); return; }
    clearTimeout(quitArmed); quitArmed = null;
    const r = await api("/quit", { method: "POST" });
    if (!r.ok) { b.textContent = "Usta'yı kapat"; U.wizMsg(await errorText(r), "error"); return; }
    document.body.replaceChildren(h("p", "wiz-note", "Usta kapandı. Tekrar açmak için masaüstündeki Usta simgesine çift tıkla. Bu sekmeyi kapatabilirsin."));
    document.body.style.padding = "32px";
  });
  $("result-open").addEventListener("click", () => U.showTab("preview"));
  $("result-folder").addEventListener("click", async () => {
    const r = await api(`/workspaces/${encodeURIComponent(state.ws)}/reveal`, { method: "POST" });
    if (!r.ok) U.addNode(h("div", "msg error", "Klasör açılamadı. Dosyalar sol taraftaki \"Dosyalarım\" listesinde de görünür."));
  });
  let undoArmed = null;
  $("result-undo").addEventListener("click", async () => {
    const b = $("result-undo");
    if (!undoArmed) { b.textContent = "Emin misin? Tekrar bas"; undoArmed = setTimeout(() => { undoArmed = null; b.textContent = "Yaptığı değişikliği geri al"; }, 4000); return; }
    clearTimeout(undoArmed); undoArmed = null; b.textContent = "Yaptığı değişikliği geri al";
    if (await U.doRevert()) { hideResult(); updateStarters(); }
  });
  $("ctx").addEventListener("change", () => saveSetting({ context_window: Number($("ctx").value) }));
  applyZoom();
  if (window.Office && typeof window.Office.init === "function") window.Office.init();
  // Ofis onay şeridi → mevcut karar akışı (tek yol: U.decideApproval)
  if (window.Office) window.Office.onDecide = (id, decision) => U.decideApproval(id, decision);
  $("theme").addEventListener("change", () => { applyTheme($("theme").value); saveSetting({ theme: $("theme").value }); });
  $("guard").addEventListener("change", () => saveSetting({ guard: $("guard").checked }));
  $("mode").addEventListener("change", () => { applyMode($("mode").value); saveSetting({ mode: $("mode").value }); });
  $("clear-history").addEventListener("click", U.clearHistory);

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
