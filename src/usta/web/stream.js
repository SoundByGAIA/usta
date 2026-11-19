// Görev akışı: olayların çizimi, onaylar, değişiklik görünümü, sekmeler, önizleme ve görevi başlatma/durdurma.
// Ortak yardımcılar ve durum app.js'te; paylaşılan adlar window.UstaApp (U) üzerinden çağrı anında okunur.
(function () {
  "use strict";
  const U = (window.UstaApp = window.UstaApp || {});
  const $ = (id) => document.getElementById(id);
  const L = window.UstaLogic;
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
    if (O && typeof O.setContextWindow === "function") O.setContextWindow(U.state.contextWindow || 0);
  }
  function renderEvent(type, data) {
    if (type === "usage") { officeEvent(type, data); showUsage(data, U.state.contextWindow); officeContextWindow(); return; } // usage sayaçları değiştirmez
    officeEvent(type, data);
    if (type === "tool_call" && data && data.tool === "propose_skill" && !U.state.replay) return addNode(U.skillProposalNode(data.args || {}));
    const s = L.summarize(type, data);
    if (type === "message" && !s.body) return;
    if (s.kind === "tool" || s.kind === "result") {
      const d = U.h("details", "msg " + s.kind);
      const simpleTitle = s.kind === "tool" && U.state.view !== "advanced" ? L.plainProgress(s.tool, s.args) : null;
      d.appendChild(U.h("summary", null, simpleTitle || (s.kind === "result" ? "↳ " : "") + s.title));
      if (s.body) d.appendChild(U.h("pre", null, s.body));
      return addNode(d);
    }
    if (s.kind === "approval" && !U.state.replay) return addNode(approvalNode(s));
    const box = U.h("div", "msg " + s.kind);
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
    if (msg === "ok") { U.setStatus("running"); text = decision === "allow" ? "İzin verildi" : "Reddedildi"; }
    else text = msg === "stale" ? "İstek artık geçerli değil" : msg;
    if (row) row.textContent = text; // Akış'taki onay arayüzü de karar Ofis'ten verilse bile güncellenir
    return text;
  }
  // Karar isteğini gönderir; ağ/sunucu sonucunu düz metne çevirir. Akış'taki onay düğmesi de
  // (decideApproval üzerinden) aynı yolu kullanır — kopya kod yok.
  async function decideSend(id, decision) {
    try {
      const res = await U.api(`/approvals/${encodeURIComponent(id)}`, { method: "POST", body: JSON.stringify({ decision }) });
      return res.ok ? "ok" : "stale";
    } catch (_) { return "Gönderilemedi"; }
  }
  function approvalNode(s) {
    const box = U.h("div", "msg approval");
    const plain = L.plainApproval(s.tool, s.args, s.reason);
    box.appendChild(U.h("p", "plain", plain.title));
    if (plain.warn) box.appendChild(U.h("p", "plain-warn", plain.warn));
    const det = U.h("details", null);
    det.appendChild(U.h("summary", null, "Ayrıntılar (teknik)"));
    det.appendChild(U.h("strong", null, s.title));
    if (s.body) det.appendChild(U.h("pre", null, s.body));
    box.appendChild(det);
    const row = U.h("div", "row");
    const allow = U.h("button", "primary", "İzin ver");
    const deny = U.h("button", null, "Reddet");
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
  const MAX_DIFF_LINES = 2000;
  function renderDiff(text) {
    const files = L.parseDiff(text);
    const root = $("diff-files");
    root.replaceChildren();
    $("diff-count").textContent = files.length ? `(${files.length})` : "";
    $("revert").disabled = files.length === 0;
    if (!files.length) { root.appendChild(U.h("p", "empty", "Değişiklik yok.")); return; }
    const TAG = { added: "yeni", deleted: "silindi", modified: "değişti", binary: "ikili" };
    for (const f of files) {
      const d = U.h("details", "file");
      d.open = true;
      const sum = U.h("summary");
      sum.append(U.h("span", null, f.name + " "), U.h("span", "tag", `[${TAG[f.status]}] `));
      if (f.status !== "binary") sum.append(U.h("span", "stat-add", `+${f.stats.add} `), U.h("span", "stat-del", `−${f.stats.del}`));
      d.appendChild(sum);
      const code = U.h("div", "code");
      f.lines.slice(0, MAX_DIFF_LINES).forEach((l) => {
        const sign = { add: "+", del: "-", ctx: " ", hunk: "", meta: "" }[l.kind];
        code.appendChild(U.h("div", l.kind, sign + l.text));
      });
      if (f.lines.length > MAX_DIFF_LINES) code.appendChild(U.h("div", "meta", `… ${f.lines.length - MAX_DIFF_LINES} satır daha (gösterilmiyor)`));
      d.appendChild(code);
      root.appendChild(d);
    }
  }
  function showTab(name) {
    U.state.tab = name;
    $("stream").hidden = name !== "stream";
    $("diff").hidden = name !== "diff";
    $("memory").hidden = name !== "memory";
    $("history").hidden = name !== "history";
    $("fileview").hidden = name !== "file";
    $("preview").hidden = name !== "preview";
    $("office").hidden = name !== "office";
    $("replay-bar").hidden = !(U.state.replay && name === "stream");
    $("tab-file").hidden = !U.state.openFile && name !== "file";
    for (const t of ["stream", "diff", "memory", "history", "file", "preview", "office"]) $(`tab-${t}`).setAttribute("aria-selected", String(t === name));
    if (window.Office && typeof window.Office.setVisible === "function") window.Office.setVisible(name === "office");
    $("result-card").hidden = !(U.state.resultOn && name === "stream");
    U.updateStarters();
    if (name === "memory") U.loadMemory();
    if (name === "history") U.loadHistory();
    if (name === "preview") loadPreview();
  }

  // --- önizleme: yalıtılmış (sandbox) çerçeve, statik dosyalar ---
  async function previewBase() {
    const res = await U.api(`/workspaces/${encodeURIComponent(U.state.ws)}/preview`);
    return res.ok ? (await res.json()).base : null;
  }
  async function loadPreview() {
    if (!U.state.ws) return;
    const base = await previewBase();
    if (!base) return;
    const rel = $("preview-path").value.trim().replace(/^\/+/, "") || "index.html";
    const url = `${base}${rel.split("/").map(encodeURIComponent).join("/")}`;
    $("preview-frame").src = `${url}${url.includes("?") ? "&" : "?"}t=${Date.now()}`;
    $("preview-open").href = url;
  }
  // --- görev akışı ---
  async function follow(taskId) {
    U.state.task = taskId;
    U.put("usta_task", `${U.state.ws}:${taskId}`);
    U.setActive(true);
    const ctl = new AbortController();
    U.state.abort = ctl;
    let last = null;
    let finished = false;
    let nextTask = null;  // aşamalı uygulamada sunucunun başlattığı sonraki görev
    let tries = 0;
    while (!finished && tries < 6 && U.state.task === taskId) {
      const att = new AbortController();  // bu bağlantı denemesi; takılırsa yeniden bağlanılır
      const onAbort = () => att.abort();
      ctl.signal.addEventListener("abort", onAbort);
      let lastByte = Date.now();
      const watchdog = setInterval(() => { if (Date.now() - lastByte > 40000) att.abort(); }, 5000);  // sunucu 15 sn'de bir canlılık yollar
      try {
        const headers = last != null ? { "Last-Event-ID": String(last) } : {};
        const res = await U.api(`/tasks/${encodeURIComponent(taskId)}/events`, { headers, signal: att.signal });
        if (res.status === 404) {
          U.put("usta_task", "");
          addNode(U.h("div", "msg error", "Görev bulunamadı (sunucu yeniden başlamış olabilir)."));
          break;
        }
        if (!res.ok) throw new Error(String(res.status));
        const dec = new TextDecoder();
        const parser = L.createSSEParser((ev) => {
          let data = {};
          try { data = JSON.parse(ev.data); } catch (_) { return; }
          if (ev.id != null) last = Number(ev.id);
          if (ev.event === "started") U.setStatus("running");
          if (ev.event === "approval_required") U.setStatus("awaiting_approval");
          if (ev.event === "done") { finished = true; U.setStatus(data.status); if (data.next) nextTask = data.next; }
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
      if (!finished) await U.sleep(1000);
    }
    if (!finished && tries >= 6) addNode(U.h("div", "msg error", "Bağlantı koptu."));
    if (nextTask && U.state.task === taskId) {
      try {
        const info = await (await U.api(`/tasks/${encodeURIComponent(nextTask)}`)).json();
        addNode(U.h("div", "msg user", info.prompt));
      } catch (_) { /* istem gösterilemese de akış sürer */ }
      return follow(nextTask);
    }
    await finish(taskId);
  }
  async function finish(taskId) {
    if (U.state.task !== taskId) return;
    try {
      const info = await (await U.api(`/tasks/${encodeURIComponent(taskId)}`)).json();
      U.setStatus(info.status);
      if (!L.isActive(info.status)) {
        const res = await U.api(`/tasks/${encodeURIComponent(taskId)}/diff`);
        if (res.ok) renderDiff(await res.text());
        U.setActive(false);
        U.refreshTree();
        if (!$("preview").hidden) loadPreview();
        if (info.mode === "plan" && info.status === "done" && info.answer) offerPlan(info);
        return;
      }
    } catch (_) { /* bağlantı yok */ }
    U.setActive(false);
  }

  function offerPlan(info) {
    const box = U.h("div", "msg approval");
    box.appendChild(U.h("strong", null, "Planı uygulayayım mı?"));
    const row = U.h("div", "row");
    const mk = (label, mode, primary, phased) => {
      const b = U.h("button", primary ? "primary" : null, label);
      b.type = "button";
      b.title = phased ? "Plan PLAN.md aşamalarına bölünür; her aşama taze bağlamla ayrı görev olarak koşar (bağlam şişmez; yerel küçük modeller için)" : "Planın tamamı tek görevde uygulanır";
      b.addEventListener("click", () => {
        row.textContent = phased ? "Aşamalara bölünüyor…" : "Uygulanıyor…";
        startTask(phased ? "Planı aşama aşama uygula" : "Planı uygula", mode, [], info.id, phased);  // plan sunucuda; istem yeniden yazılmaz
      });
      return b;
    };
    const no = U.h("button", null, "Hayır");
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
    if (!prompt || !U.state.ws) return;
    if (U.state.active) return steer(prompt);
    return startTask(prompt, $("mode").value, U.state.files);
  }
  async function steer(text) {
    if (!U.state.task) return;
    const res = await U.api(`/tasks/${encodeURIComponent(U.state.task)}/messages`, { method: "POST", body: JSON.stringify({ text }) });
    if (res.ok) { $("prompt").value = ""; return; }  // mesaj akışa "user_message" olayıyla düşer
    addNode(U.h("div", "msg error", await U.errorText(res)));
  }

  async function startTask(prompt, mode, files = [], planId = null, phased = false) {
    U.leaveReplay();
    const body = { prompt, mode, guard: $("guard").checked, files: files.map((f) => ({ name: f.name, content: f.content })) };
    if (planId) { body.apply_plan = planId; if (phased) body.phased = true; }
    if (U.state.designSkill && mode !== "plan") body.design_skill = true;
    const res = await U.api(`/workspaces/${encodeURIComponent(U.state.ws)}/tasks`, { method: "POST", body: JSON.stringify(body) });
    if (!res.ok) { addNode(U.h("div", "msg error", await U.errorText(res))); return; }
    const task = await res.json();
    U.setDesignSkill(false);  // tek seferlik: bir sonraki görev yine normal
    U.state.contextWindow = task.context_window || null;
    showUsage(null);
    officeContextWindow(); // modelin bağlam penceresi Ofis göstergelerine
    $("prompt").value = "";
    $("diff-files").replaceChildren();
    $("diff-count").textContent = "";
    $("revert").disabled = true;
    U.state.files = [];
    U.renderAttached();
    addNode(U.h("div", "msg user", files.length ? `${prompt}\n📎 ${files.map((f) => f.name).join(", ")}` : prompt));
    officeReset(); // yeni görev: ofis sahnesi sıfırdan başlar
    showTab("stream");
    follow(task.id);
  }

  async function stopTask() {
    if (!U.state.task) return;
    $("stop").disabled = true;
    try { await U.api(`/tasks/${encodeURIComponent(U.state.task)}/cancel`, { method: "POST" }); U.setStatus("cancelling"); } catch (_) { /* yoksay */ }
    $("stop").disabled = false;
  }

  let revertArmed = null;
  async function revertTask() {
    const btn = $("revert");
    if (!U.state.task || U.state.active) return;
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
    const res = await U.api(`/tasks/${encodeURIComponent(U.state.task)}/revert`, { method: "POST" });
    if (!res.ok) { addNode(U.h("div", "msg error", await U.errorText(res))); return false; }
    renderDiff("");
    renderEvent("reverted", {});
    showTab("stream");
    return true;
  }
  Object.assign(U, { addNode, decideApproval, doRevert, follow, loadPreview, officeReplay, officeReset, renderDiff, renderEvent, revertTask, sendPrompt, showTab, showUsage, stopTask });
})();
