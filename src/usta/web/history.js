// Geçmiş oturumlar, göreve eklenen dosyalar ve proje hafızası.
// Ortak yardımcılar ve durum app.js'te; paylaşılan adlar window.UstaApp (U) üzerinden çağrı anında okunur.
(function () {
  "use strict";
  const U = (window.UstaApp = window.UstaApp || {});
  const $ = (id) => document.getElementById(id);
  // --- geçmiş oturumlar ---
  const fmtTs = (ts) => (ts ? new Date(ts * 1000).toLocaleString("tr-TR", { dateStyle: "short", timeStyle: "short" }) : "");
  const HIST_STATUS = Object.assign({ interrupted: "kesildi" }, U.STATUS);
  async function loadHistory() {
    const list = $("history-list");
    list.replaceChildren();
    $("history-msg").textContent = "";
    if (!U.state.ws) return;
    const ws = U.state.ws;
    const res = await U.api(`/workspaces/${encodeURIComponent(ws)}/sessions`);
    if (!res.ok || U.state.ws !== ws) { $("history-msg").textContent = await U.errorText(res); return; }
    const all = await res.json();
    if (!all.length) list.appendChild(U.h("li", "empty", "Henüz oturum yok."));
    for (const s of all) {
      const li = U.h("li");
      const b = U.h("button", null);
      b.type = "button";
      const st = U.h("span", "h-st", HIST_STATUS[s.status] || s.status);
      st.dataset.s = s.status;
      b.append(U.h("span", "h-ts", fmtTs(s.ts)), st, U.h("span", "h-prompt", s.prompt));
      b.addEventListener("click", () => openSession(s.id));
      li.appendChild(b);
      list.appendChild(li);
    }
  }
  async function openSession(id) {
    if (U.state.active || !U.state.ws) return;
    const ws = U.state.ws;
    const res = await U.api(`/workspaces/${encodeURIComponent(ws)}/sessions/${encodeURIComponent(id)}`);
    if (!res.ok || U.state.ws !== ws) { $("history-msg").textContent = await U.errorText(res); return; }
    const s = await res.json();
    U.state.task = null;
    U.state.replay = true;
    $("stream").replaceChildren();
    U.showUsage(null);
    U.officeReset(); // geçmiş oturum: sahne baştan aynı olaylarla yeniden oynar
    const m = s.meta || {};
    const names = (m.files || []).length ? `\n📎 ${m.files.join(", ")}` : "";
    U.addNode(U.h("div", "msg user", (m.prompt || "") + names));
    for (const e of s.events) {
      if (e.type === "done") U.setStatus(e.data.status);
      U.renderEvent(e.type, e.data);
    }
    // Ofis sekmesi: olaylar tek tek değil toplu verilir → sahne zaman çubuğuyla gezilebilir
    U.officeReplay(s.events.map((e) => ({ type: e.type, data: e.data })));
    if (s.status === "interrupted") U.addNode(U.h("div", "msg warn", "Bu görev yarıda kesilmiş (sunucu kapanmış olabilir)."));
    $("replay-text").textContent = `Geçmiş oturum · ${fmtTs(m.ts)} · ${HIST_STATUS[s.status] || s.status} (salt okunur)`;
    U.showTab("stream");
    $("stream").scrollTop = 0;
  }
  function leaveReplay() {
    if (!U.state.replay) return;
    U.state.replay = false;
    $("stream").replaceChildren();
    U.showUsage(null);
    U.setStatus("");
    $("replay-bar").hidden = true;
    U.officeReset();
  }

  // --- ekler (metin / Markdown) ---
  const MAX_ATT = 5, MAX_ATT_BYTES = 100000;
  Object.assign(U, { MAX_ATT, MAX_ATT_BYTES, renderAttached });
  function renderAttached() {
    const box = $("attached");
    box.replaceChildren();
    box.hidden = U.state.files.length === 0;
    U.state.files.forEach((f, i) => {
      const chip = U.h("span", "att", `${f.name} · ${Math.max(1, Math.round(f.size / 1000))} KB`);
      const x = U.h("button", null, "×");
      x.type = "button";
      x.setAttribute("aria-label", `${f.name} ekini kaldır`);
      x.addEventListener("click", () => { U.state.files.splice(i, 1); renderAttached(); });
      chip.appendChild(x);
      box.appendChild(chip);
    });
  }
  async function addFiles(list) {
    for (const file of Array.from(list)) {
      if (U.state.files.length >= MAX_ATT) { U.addNode(U.h("div", "msg warn", `En çok ${MAX_ATT} dosya eklenebilir.`)); break; }
      if (file.size > MAX_ATT_BYTES) { U.addNode(U.h("div", "msg warn", `${file.name}: çok büyük (en çok 100 KB).`)); continue; }
      let content;
      try { content = await file.text(); } catch (_) { U.addNode(U.h("div", "msg warn", `${file.name}: okunamadı.`)); continue; }
      if (content.includes("\u0000")) { U.addNode(U.h("div", "msg warn", `${file.name}: ikili dosya, yalnız metin eklenebilir.`)); continue; }
      U.state.files.push({ name: file.name, content, size: file.size });
    }
    renderAttached();
  }

  // --- proje hafızası ---
  async function loadMemory() {
    const notes = $("memory-notes"), hist = $("memory-history");
    notes.replaceChildren();
    hist.replaceChildren();
    $("memory-msg").textContent = "";
    if (!U.state.ws) return;
    const ws = U.state.ws;
    const res = await U.api(`/workspaces/${encodeURIComponent(ws)}/memory`);
    if (!res.ok || U.state.ws !== ws) { $("memory-msg").textContent = await U.errorText(res); return; }
    const mem = await res.json();
    $("memory-count").textContent = mem.notes.length ? `(${mem.notes.length})` : "";
    $("clear-history").disabled = mem.history.length === 0;
    if (!mem.notes.length) notes.appendChild(U.h("li", "empty", "Not yok."));
    mem.notes.forEach((text, i) => {
      const li = U.h("li", "mem-row");
      const del = U.h("button", null, "Sil");
      del.type = "button";
      del.addEventListener("click", () => deleteNote(i));
      li.append(U.h("span", "mem-text", text), del);
      notes.appendChild(li);
    });
    if (!mem.history.length) hist.appendChild(U.h("li", "empty", "Geçmiş yok."));
    for (const r of mem.history.slice().reverse()) {
      hist.appendChild(U.h("li", "mem-row", `[${r.ts}] ${U.STATUS[r.status] || r.status}: ${r.prompt}${r.answer ? " → " + r.answer : ""}`));
    }
  }
  async function memoryAction(path, opts) {
    const res = await U.api(`/workspaces/${encodeURIComponent(U.state.ws)}/memory${path}`, opts);
    if (!res.ok) $("memory-msg").textContent = await U.errorText(res);
    else await loadMemory();
  }
  const deleteNote = (i) => U.state.ws && memoryAction(`/notes/${i}`, { method: "DELETE" });
  const clearHistory = () => U.state.ws && memoryAction("/history", { method: "DELETE" });
  Object.assign(U, { addFiles, clearHistory, leaveReplay, loadHistory, loadMemory, renderAttached });
})();
