// Dosya gezgini: çalışma alanındaki dosyaları listeleme, açma, yükleme, yeni dosya/klasör, yeniden adlandırma, silme.
// Ortak yardımcılar ve durum app.js'te; paylaşılan adlar window.UstaApp (U) üzerinden çağrı anında okunur.
(function () {
  "use strict";
  const U = (window.UstaApp = window.UstaApp || {});
  const $ = (id) => document.getElementById(id);
  // --- dosya gezgini ---
  const filesMsg = (t) => { $("files-msg").textContent = t || ""; };
  const joinPath = (dir, name) => (dir ? `${dir}/${name}` : name);
  async function fillDir(dir, ul) {
    const res = await U.api(`/workspaces/${encodeURIComponent(U.state.ws)}/tree?path=${encodeURIComponent(dir)}`);
    if (!res.ok) { filesMsg(await U.errorText(res)); return; }
    ul.replaceChildren();
    const { entries } = await res.json();
    if (!entries.length && !dir) ul.appendChild(U.h("li", "empty", "Boş. Dosya ya da klasör yükleyebilirsin."));
    for (const e of entries) {
      const path = joinPath(dir, e.name);
      const li = U.h("li", (e.dir ? "dir" : "file") + (e.link ? " link" : "") + (e.dir && U.state.selDir === path ? " sel" : ""));
      const b = U.h("button", null, (e.dir ? (U.state.openDirs.has(path) ? "▾ " : "▸ ") : "  ") + e.name);
      b.type = "button";
      b.title = path;
      const line = U.h("div", "line");
      line.appendChild(b);
      line.appendChild(rowActions(path, e));
      li.appendChild(line);
      if (e.dir && !e.link) {
        const sub = U.h("ul");
        sub.hidden = !U.state.openDirs.has(path);
        li.appendChild(sub);
        if (U.state.openDirs.has(path)) fillDir(path, sub);
        b.addEventListener("click", () => {
          document.querySelectorAll("#file-tree li.sel").forEach((x) => x.classList.remove("sel"));
          li.classList.add("sel");
          U.state.selDir = path;
          const open = !U.state.openDirs.has(path);
          if (open) U.state.openDirs.add(path); else U.state.openDirs.delete(path);
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
    const res = await U.api(`/workspaces/${encodeURIComponent(U.state.ws)}/fs`, { method: "POST", body: JSON.stringify(body) });
    if (!res.ok) { filesMsg(await U.errorText(res)); return false; }
    return true;
  }
  function rowActions(path, e) {
    const acts = U.h("span", "acts");
    const ren = U.h("button", null, "✎");
    ren.type = "button"; ren.title = "Yeniden adlandır"; ren.setAttribute("aria-label", `${path} yeniden adlandır`);
    ren.addEventListener("click", () => startFs("rename", path));
    const del = U.h("button", null, "🗑");
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
        if (U.state.openFile && (U.state.openFile.path === path || U.state.openFile.path.startsWith(`${path}/`))) { U.state.openFile = null; U.showTab("stream"); }
        U.state.openDirs.delete(path);
        if (U.state.selDir === path) U.state.selDir = "";
        refreshTree();
        filesMsg(`${path} silindi.`);
      }
    });
    acts.append(ren, del);
    return acts;
  }
  function startFs(mode, path) {
    U.state.fsMode = { mode, path };
    const label = { create_file: "Yeni dosya adı", create_dir: "Yeni klasör adı", rename: `Yeni ad: ${path}` }[mode];
    $("fs-label").textContent = mode === "rename" ? label : `${label}${U.state.selDir ? ` (${U.state.selDir}/ içine)` : ""}`;
    $("fs-input").value = mode === "rename" ? path.split("/").pop() : "";
    $("fs-form").hidden = false;
    $("fs-input").focus();
  }
  async function submitFs(ev) {
    ev.preventDefault();
    const f = U.state.fsMode;
    const name = $("fs-input").value.trim();
    if (!f || !name || name.includes("\\")) return;
    const base = f.mode === "rename" ? f.path.split("/").slice(0, -1).join("/") : U.state.selDir;
    const target = joinPath(base, name);
    const ok = await fsCall(f.mode === "rename" ? { op: "rename", path: f.path, to: target } : { op: f.mode, path: target });
    if (!ok) return;
    $("fs-form").hidden = true;
    U.state.fsMode = null;
    if (f.mode === "rename" && U.state.openFile && U.state.openFile.path === f.path) { U.state.openFile = null; U.showTab("stream"); }
    refreshTree(true);
    filesMsg(f.mode === "rename" ? `${f.path} → ${target}` : `${target} oluşturuldu.`);
  }
  async function refreshTree(keepMsg) {
    if (keepMsg !== true) filesMsg("");
    const ul = $("file-tree");
    ul.replaceChildren();
    const up = !U.state.ws || U.state.active;
    $("f-up-files").disabled = $("f-up-dir").disabled = $("f-new-file").disabled = $("f-new-dir").disabled = up;
    if (U.state.ws) await fillDir("", ul);
  }
  async function openFile(path) {
    const res = await U.api(`/workspaces/${encodeURIComponent(U.state.ws)}/files?path=${encodeURIComponent(path)}`);
    if (!res.ok) { filesMsg(`${path}: ${await U.errorText(res)}`); return; }
    const f = await res.json();
    U.state.openFile = { path, content: f.content };
    $("fileview-path").textContent = path;
    $("fileview-body").textContent = f.content.length > 200000 ? `${f.content.slice(0, 200000)}\n… [kırpıldı]` : f.content;
    U.showTab("file");
  }
  function attachOpenFile() {
    const f = U.state.openFile;
    if (!f) return;
    if (U.state.files.some((x) => x.name === f.path)) { filesMsg("Zaten ekli."); return; }
    if (f.content.length > U.MAX_ATT_BYTES) { filesMsg("Dosya 100 KB'tan büyük, göreve eklenemez; ajan zaten read_file ile okuyabilir."); return; }
    if (U.state.files.length >= U.MAX_ATT) { filesMsg(`En çok ${U.MAX_ATT} dosya eklenebilir.`); return; }
    U.state.files.push({ name: f.path, content: f.content, size: f.content.length });
    U.renderAttached();
    filesMsg(`${f.path} göreve eklendi.`);
    U.showTab("stream");
  }
  const SKIP_UPLOAD = new Set([".git", "node_modules", ".venv", "__pycache__", ".usta"]);
  async function toB64(file) {
    const buf = new Uint8Array(await file.arrayBuffer());
    let s = "";
    for (let i = 0; i < buf.length; i += 0x8000) s += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
    return btoa(s);
  }
  async function uploadFiles(list) {
    if (!U.state.ws || U.state.active) return;
    const files = Array.from(list).filter((f) => !(f.webkitRelativePath || f.name).split("/").some((p) => SKIP_UPLOAD.has(p)));
    if (!files.length) { filesMsg("Yüklenecek dosya yok."); return; }
    let written = 0, skipped = 0, batch = [], size = 0;
    const flush = async () => {
      if (!batch.length) return true;
      const res = await U.api(`/workspaces/${encodeURIComponent(U.state.ws)}/import`, { method: "POST", body: JSON.stringify({ files: batch }) });
      batch = []; size = 0;
      if (!res.ok) { filesMsg(await U.errorText(res)); return false; }
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
  $("f-refresh").addEventListener("click", () => refreshTree());
  $("f-new-file").addEventListener("click", () => startFs("create_file"));
  $("f-new-dir").addEventListener("click", () => startFs("create_dir"));
  $("fs-form").addEventListener("submit", submitFs);
  $("fs-cancel").addEventListener("click", () => { $("fs-form").hidden = true; U.state.fsMode = null; });
  $("f-up-files").addEventListener("click", () => $("f-input").click());
  $("f-up-dir").addEventListener("click", () => $("f-dir-input").click());
  $("f-input").addEventListener("change", async () => { await uploadFiles($("f-input").files); $("f-input").value = ""; });
  $("f-dir-input").addEventListener("change", async () => { await uploadFiles($("f-dir-input").files); $("f-dir-input").value = ""; });
  $("fileview-attach").addEventListener("click", attachOpenFile);
  Object.assign(U, { refreshTree });
})();
