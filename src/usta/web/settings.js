// Ayarlar bölümleri: ek araçlar (MCP), program kurma, profil, ortak hafıza, beceriler, yardımcı programlar.
// Ortak yardımcılar ve durum app.js'te; paylaşılan adlar window.UstaApp (U) üzerinden okunur.
(function () {
  "use strict";
  const U = (window.UstaApp = window.UstaApp || {});
  const L = window.UstaLogic;
  const $ = (id) => document.getElementById(id);
  // --- ek araçlar (MCP): yalnız katalogdan ekleme, serbest komut yok ---
  function toolsMsg(text, cls) {
    const m = $("tools-msg");
    m.textContent = text || "";
    m.className = cls || "empty";
  }
  async function toolsCall(path, method, body) {
    const res = await U.api(`/mcp${path}`, { method, body: body ? JSON.stringify(body) : undefined });
    if (!res.ok) { toolsMsg(await U.errorText(res), "error"); return null; }
    return res.json();
  }
  async function loadTools() {
    const res = await U.api("/mcp");
    if (!res.ok) { toolsMsg(await U.errorText(res), "error"); return; }
    const data = await res.json();
    const inst = $("tools-installed"), cat = $("tools-catalog");
    inst.replaceChildren();
    cat.replaceChildren();
    if (!data.servers.length) inst.appendChild(U.h("p", "empty", "Henüz araç eklenmedi."));
    for (const s of data.servers) inst.appendChild(serverCard(s));
    const avail = data.catalog.filter((c) => !c.added);
    if (!avail.length) cat.appendChild(U.h("p", "empty", "Eklenebilecek başka araç yok."));
    for (const c of avail) cat.appendChild(catalogCard(c));
    const found = $("tools-found");
    found.replaceChildren();
    const fr = await U.api("/mcp/bulunanlar");
    const list = fr.ok ? await fr.json() : [];
    if (!list.length) found.appendChild(U.h("p", "empty", "Başka bir uygulamada kurulu araç bulamadım."));
    for (const f of list) found.appendChild(foundCard(f));
  }
  // Resmî kayıt defterinde bulunan sunucu: eklerken sunucu kaydı yeniden okur (buradaki komuta güvenmez)
  async function searchRegistry(ev) {
    ev.preventDefault();
    const box = $("tools-reg");
    box.replaceChildren();
    toolsMsg("Kayıt defterinde arıyorum...");
    const list = await toolsCall("/kayit/ara", "POST", { sorgu: $("tools-reg-q").value.trim() });
    if (!list) return;
    toolsMsg("");
    if (!list.length) box.appendChild(U.h("p", "empty", "Resmî MCP kayıt defterinde bulamadım. Bu araç otomatik kurulamıyor."));
    for (const e of list) box.appendChild(registryCard(e));
  }
  function registryCard(e) {
    const card = U.h("div", "card");
    const owner = (e.repository.match(/github\.com\/([\w.-]+)/i) || [])[1];
    card.append(U.h("strong", null, e.name), U.h("span", "chip", e.verified ? `doğrulanmış yayıncı: ${owner}` : "yayıncı doğrulanmamış"));
    if (e.description) card.appendChild(U.h("p", null, e.description));
    if (!e.command.length) { card.appendChild(U.h("p", "empty", `Eklenemez: ${e.reason}.`)); return card; }
    card.append(U.h("p", "empty", `Sürüm ${e.version}: kendi kutusunda çalışır, internete çıkabilir, dosyalarını görmez.`), U.h("code", "cmd", e.command.join(" ")));
    const need = e.env.filter((v) => v.required).map((v) => v.name);
    if (need.length) card.appendChild(U.h("p", "empty", `Ekledikten sonra şu anahtarı girmen gerekecek: ${need.join(", ")}`));
    const add = U.h("button", "primary", "Ekle");
    add.type = "button";
    add.addEventListener("click", async () => {
      add.disabled = true;
      const r = await toolsCall("/kayit", "POST", { name: e.name, version: e.version });
      if (r) { toolsMsg(`${r.name} eklendi. ${need.length ? "Anahtarını gir, " : ""}Hazırla'ya bas, sonra Test et.`, "ok"); $("tools-reg").replaceChildren(); await loadTools(); }
      else add.disabled = false;
    });
    card.appendChild(add);
    return card;
  }
  U.searchRegistry = searchRegistry;
  // Başka uygulamada bulunan sunucu: komutu Usta kurar (sürüm sabit, kendi kabında); anahtar değeri arayüze hiç gelmez
  function foundCard(f) {
    const card = U.h("div", "card");
    card.append(U.h("strong", null, f.name), U.h("span", "chip", f.app));
    if (f.added) { card.appendChild(U.h("span", "chip", "eklendi")); return card; }
    if (!f.kind) { card.appendChild(U.h("p", "empty", `Eklenemez: ${f.reason}.`)); return card; }
    card.append(U.h("p", null, `${f.package}: kendi kutusunda çalışır, internete çıkabilir, dosyalarını görmez.`), U.h("code", "cmd", f.command.join(" ")));
    const keys = f.env.filter((e) => e.has_value).map((e) => e.name);
    let copy = null;
    if (keys.length) {
      const label = U.h("label");
      copy = U.h("input");
      copy.type = "checkbox";
      copy.checked = true;
      label.append(copy, ` Anahtarı da Usta'ya kopyala (${keys.join(", ")})`);
      card.appendChild(U.h("p")).appendChild(label);
    }
    const add = U.h("button", "primary", "Ekle");
    add.type = "button";
    add.addEventListener("click", async () => {
      add.disabled = true;
      toolsMsg("Ekleniyor: paketin son sürümü öğreniliyor...");
      const r = await toolsCall("/bulunanlar", "POST", { app: f.app, name: f.name, copy_secrets: !!(copy && copy.checked) });
      if (r) { toolsMsg(`${r.name} eklendi. Şimdi Hazırla'ya bas, sonra Test et.`, "ok"); await loadTools(); }
      else add.disabled = false;
    });
    card.appendChild(add);
    return card;
  }
  function catalogCard(c) {
    const card = U.h("div", "card");
    card.append(U.h("strong", null, c.title), U.h("p", null, c.description), U.h("code", "cmd", c.command.join(" ")));
    card.appendChild(U.h("p", "empty", `Yalıtılmış konteynerde çalışır (imaj: ${c.image}; ağ: ${c.allow_hosts.length ? c.allow_hosts.join(", ") : "kapalı"}). İmaj yerelde olmalı: docker pull ${c.image}`));
    if (c.homepage.startsWith("https://")) {
      const a = U.h("a", null, c.homepage);
      a.href = c.homepage;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      card.appendChild(U.h("p", "empty")).appendChild(a);
    }
    const add = U.h("button", "primary", "Ekle");
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
    const card = U.h("div", "card");
    const title = U.h("strong", null, s.name);
    const host = s.isolation === "host", remote = s.isolation === "remote";
    card.append(title, U.h("span", "chip", s.enabled ? "açık" : "kapalı"), U.h("span", "chip", host ? "ANA MAKİNE (yalıtımsız)" : remote ? "başka bilgisayarda" : "yalıtılmış konteyner"));
    if (!host && !remote) card.appendChild(U.h("span", "chip", s.pinned ? "sabitlendi" : "sabitlenmedi"));
    card.append(U.h("p", "empty", `onay: ${s.approve === "allow" ? "sormadan çalışır" : "her çağrıda sorulur"}${host || remote ? "" : ` · imaj: ${s.image || "YOK"} · ağ: ${s.allow_hosts.length ? s.allow_hosts.join(", ") : "kapalı"}`}`), U.h("code", "cmd", remote ? s.url : s.command.join(" ")));
    for (const e of s.env) {
      const row = U.h("div", "key-row");
      const input = U.h("input");
      input.type = "password";
      input.autocomplete = "off";
      input.spellcheck = false;
      input.placeholder = e.set ? `${e.name} tanımlı (değiştirmek için yaz)` : `${e.name} değerini gir`;
      input.setAttribute("aria-label", e.name);
      const save = U.h("button", null, "Kaydet");
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
    const actions = U.h("div", "row");
    const test = U.h("button", null, "Test et");
    test.type = "button";
    test.addEventListener("click", async () => {
      test.disabled = true;
      toolsMsg(remote ? "Bağlanılıyor..." : "Konteyner başlatılıyor...");
      const r = await toolsCall(`/${encodeURIComponent(s.name)}/test`, "POST");
      test.disabled = false;
      if (r) toolsMsg(`${r.tools.length} araç bulundu: ${r.tools.map((t) => t.name).join(", ")}`.slice(0, 600), "ok");
    });
    const prepare = U.h("button", null, s.pinned ? "Yeniden hazırla" : "Hazırla");
    prepare.type = "button";
    prepare.hidden = host || remote;
    prepare.addEventListener("click", async () => {
      prepare.disabled = true;
      toolsMsg("Hazırlanıyor: paketler yalnız paket kayıtlarına açık ağda indirilir, kurulum betikleri çalışmaz (birkaç dakika sürebilir)...");
      const r = await toolsCall(`/${encodeURIComponent(s.name)}/prepare`, "POST");
      prepare.disabled = false;
      if (r) { toolsMsg("Hazır: imaj ve paketler sabitlendi.", "ok"); await loadTools(); }
    });
    const toggle = U.h("button", null, s.enabled ? "Kapat" : "Aç");
    toggle.type = "button";
    toggle.addEventListener("click", async () => {
      if (await toolsCall(`/${encodeURIComponent(s.name)}/enabled`, "POST", { enabled: !s.enabled })) await loadTools();
    });
    const remove = U.h("button", null, "Kaldır");
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
  function renderGlossary() {
    const found = UstaGlossary.search($("gloss-q").value);
    $("gloss-list").replaceChildren(...(found.length ? found.map((t) => {
      const card = U.h("div", "card");
      card.append(U.h("strong", null, t.term), U.h("p", null, t.say), U.h("p", "wiz-note", `Benzetme: ${t.like}`));
      return card;
    }) : [U.h("p", "empty", "Bunu bulamadım. Başka bir kelimeyle dene ya da Usta'ya sor.")]));
  }
  // --- eksik programı Usta kursun (şimdilik Ollama, yalnız Windows'ta) ---
  let installTimer = null;
  function installButton(what, label, onDone) {
    const box = U.h("div", "install-box");
    const btn = U.h("button", "primary", label);
    btn.type = "button";
    const msg = U.h("p", "wiz-note", "");
    msg.setAttribute("role", "status");
    const bar = U.h("progress", "wiz-progress");
    bar.hidden = true;
    const poll = async () => {
      let s = {};
      try { const r = await U.api("/system/install"); if (r.ok) s = await r.json(); } catch { /* sonraki turda dene */ }
      if (s.active) { const mins = Math.floor((s.elapsed || 0) / 60);
      msg.textContent = `${s.status || "Kuruluyor"}… ${mins} dakikadır sürüyor. Program yaklaşık 1 GB; yavaş internette saatler sürebilir. Pencereyi kapatma; istersen aşağıdaki bağlantıdan kendin indir.`; installTimer = setTimeout(poll, 2000); return; }
      bar.hidden = true; btn.disabled = false;
      if (s.done) { msg.textContent = s.status || "Hazır."; onDone(); return; }
      msg.textContent = s.error || "Kurulum olmadı. Aşağıdaki bağlantıdan kendin indirebilirsin.";
    };
    btn.addEventListener("click", async () => {
      btn.disabled = true; bar.hidden = false; msg.textContent = "Başlıyorum…";
      const r = await U.api("/system/install", { method: "POST", body: JSON.stringify({ what }) });
      if (!r.ok) { btn.disabled = false; bar.hidden = true; msg.textContent = await U.errorText(r); return; }
      clearTimeout(installTimer);
      installTimer = setTimeout(poll, 1500);
    });
    box.append(btn, bar, msg);
    return box;
  }

  // --- "Seni tanıyayım" (kişisel profil; yalnız kullanıcı yazar) ---
  let kisiFacts = [];
  const kisiMsg = (t, c) => { const m = $("kisi-msg"); m.textContent = t || ""; m.className = "wiz-note" + (c ? ` ${c}` : ""); };
  function renderKisiFacts() {
    $("kisi-liste").replaceChildren(...kisiFacts.map((f, i) => {
      const li = U.h("li");
      const del = U.h("button", null, "Sil");
      del.type = "button"; del.setAttribute("aria-label", `Sil: ${f}`);
      del.addEventListener("click", () => { kisiFacts.splice(i, 1); renderKisiFacts(); kisiMsg("Silindi. Kalıcı olması için Kaydet'e bas."); });
      li.append(U.h("span", null, f), del);
      return li;
    }));
  }
  async function loadProfile() {
    const r = await U.api("/profile");
    if (!r.ok) return;
    const k = await r.json();
    $("kisi-ad").value = k.ad || "";
    $("kisi-uslup").value = k.uslup || "sade";
    $("kisi-hakkimda").value = k.hakkimda || "";
    kisiFacts = Array.isArray(k.bilgiler) ? k.bilgiler.slice() : [];
    renderKisiFacts();
    kisiMsg("");
  }
  async function saveProfile() {
    const body = { ad: $("kisi-ad").value, uslup: $("kisi-uslup").value, hakkimda: $("kisi-hakkimda").value, bilgiler: kisiFacts };
    const r = await U.api("/profile", { method: "PUT", body: JSON.stringify(body) });
    if (!r.ok) { kisiMsg(await U.errorText(r), "error"); return; }
    kisiMsg("Kaydettim. Bundan sonraki görevlerde bunları bilerek çalışırım.", "ok");
  }

  // --- evdeki ortak hafıza ---
  const ortakMsg = (t, c) => { const m = $("ortak-msg"); m.textContent = t || ""; m.className = "wiz-note" + (c ? ` ${c}` : ""); };
  async function ortakCall(path, method, body) {
    const r = await U.api(path, { method: method || "POST", body: body ? JSON.stringify(body) : undefined });
    if (!r.ok) { ortakMsg(await U.errorText(r), "error"); return null; }
    return r.json();
  }
  function ortakRow(text, who, buttons) {
    const li = U.h("li");
    const left = U.h("span", null, text);
    if (who) left.append(U.h("span", "who", `  (${who})`));
    const acts = U.h("span", "acts");
    for (const [label, fn] of buttons) { const b = U.h("button", null, label); b.type = "button"; b.setAttribute("aria-label", `${label}: ${text}`); b.addEventListener("click", fn); acts.append(b); }
    li.append(left, acts);
    return li;
  }
  async function loadOrtak() {
    const r = await U.api("/ortak");
    if (!r.ok) { $("ortak-durum").textContent = "Ortak hafıza durumunu alamadım."; return; }
    const d = await r.json();
    for (const id of ["ortak-yok", "ortak-sahip", "ortak-bagli", "ortak-notlar-kutu"]) $(id).hidden = true;
    $("ortak-kod-kutu").hidden = true; $("ortak-kod-not").hidden = true;
    const profileLocked = d.rol === "bagli";
    for (const id of ["kisi-ad", "kisi-uslup", "kisi-hakkimda", "kisi-yeni"]) $(id).disabled = profileLocked;
    for (const id of ["kisi-save", "kisi-clear"]) $(id).disabled = profileLocked;
    $("kisi-form").querySelector("button").disabled = profileLocked;
    if (d.rol === "yok") {
      $("ortak-durum").textContent = "Şu an kapalı: bilgilerin yalnız bu bilgisayarda.";
      $("ortak-yok").hidden = false;
      return;
    }
    $("ortak-notlar-kutu").hidden = false;
    $("ortak-notlar").replaceChildren(...(d.notlar || []).map((n) => ortakRow(n.text, n.kaynak, d.rol === "ev-sahibi" ? [["Sil", async () => { if (await ortakCall(`/ortak/notlar/${n.id}`, "DELETE")) loadOrtak(); }]] : [])));
    if (d.rol === "ev-sahibi") {
      $("ortak-durum").textContent = d.calisiyor ? `Bu bilgisayar ortak hafızayı tutuyor (${d.adres}). Adı: ${d.ad}.` : "Ortak hafıza açık ama şu an dinlemiyor (ağa bağlı mısın?).";
      $("ortak-sahip").hidden = false;
      $("ortak-esler").replaceChildren(...((d.eslesmeler || []).length ? d.eslesmeler.map((e) => ortakRow(e.ad, e.eski ? "eski bağlantı: kaldırıp yeniden eşleştir" : "", [["Kaldır", async () => { if (await ortakCall(`/ortak/eslesmeler/${e.id}`, "DELETE")) loadOrtak(); }]])) : [U.h("li", "wiz-note", "Henüz bağlı bilgisayar yok.")]));
      $("ortak-bekleyen").replaceChildren(...((d.bekleyen || []).length ? d.bekleyen.map((n) => ortakRow(n.text, `${n.kaynak} ekledi`, [
        ["Onayla", async () => { if (await ortakCall(`/ortak/notlar/${n.id}/onayla`)) loadOrtak(); }],
        ["Reddet", async () => { if (await ortakCall(`/ortak/notlar/${n.id}`, "DELETE")) loadOrtak(); }],
      ])) : [U.h("li", "wiz-note", "Bekleyen not yok.")]));
    } else {
      $("ortak-durum").textContent = `Bu bilgisayar "${d.baglanti.ad}" bilgisayarındaki (${d.baglanti.adres}) ortak hafızaya bağlı. Bilgilerini orada değiştirirsin.`;
      $("ortak-bagli").hidden = false;
      const w = $("ortak-uyari");
      w.hidden = !d.ulasilamiyor;
      w.textContent = d.ulasilamiyor ? `Ev sahibine şu an ulaşamıyorum (${d.hata}). Son bildiğim kopyayı kullanıyorum.` : "";
      if (d.profil) { $("kisi-ad").value = d.profil.ad || ""; $("kisi-uslup").value = d.profil.uslup || "sade"; $("kisi-hakkimda").value = d.profil.hakkimda || ""; kisiFacts = (d.profil.bilgiler || []).slice(); renderKisiFacts(); }
      kisiMsg("Bu bilgiler ev sahibi bilgisayardan geliyor; burada değiştirilemez.");
    }
  }

  // --- Beceri tasarımcısı: Usta önerir, SEN onaylarsan kaydedilir ---
  function setDesignSkill(on) {
    U.state.designSkill = !!on;
    $("design-note").hidden = !on;
  }
  function startSkillDesign() {
    closePanels();
    U.showTab("stream");
    setDesignSkill(true);
    U.fillPrompt("Şu işi her seferinde aynı şekilde yapan bir beceri tasarla: ");
  }
  const rowOf = (...nodes) => { const r = U.h("div", "row"); r.append(...nodes); return r; };  // h() yalnız metin alır
  function skillProposalNode(args) {
    const body = { name: String(args.name ?? ""), description: String(args.description ?? ""), instructions: String(args.instructions ?? "") };
    return proposalCard("Usta yeni bir beceri önerdi", () => U.api("/skills/check", { method: "POST", body: JSON.stringify(body) }));
  }
  // Bağlantıdaki beceri (GitHub). Depo bağlantısında önce içindeki becerilerden biri seçilir.
  function skillFromLinkNode(url) {
    return proposalCard("Bağlantıdaki beceri", () => U.api("/skills/baglanti", { method: "POST", body: JSON.stringify({ url }) }), (choices, box) => {
      const list = U.h("div", "row");
      for (const c of choices) {
        const b = U.h("button", null, c.split("/").slice(-2, -1)[0] || c); b.type = "button";
        b.addEventListener("click", () => box.replaceWith(skillFromLinkNode(c)));
        list.append(b);
      }
      return choices.length ? [U.h("p", null, "Bu depoda birden çok beceri var. Hangisini alayım?"), list] : [U.h("p", "error", "Bu depoda beceri (SKILL.md) bulamadım.")];
    });
  }
  // Öneri kartı: içerik sunucuda denetlenir (uyarılar), kullanıcı okuyup onaylamadan kaydedilmez
  function proposalCard(title, request, choose) {
    const box = U.h("div", "msg skill-proposal");
    box.append(U.h("strong", null, title), U.h("p", "wiz-note", "Okuyup beğenirsen Kaydet'e bas. Sen onaylamadan hiçbir şey kaydedilmez."));
    const body = U.h("div");
    body.append(U.h("p", "wiz-note", "Kontrol ediliyor…"));
    box.append(body);
    (async () => {
      let d;
      try {
        const r = await request();
        if (!r.ok) { body.replaceChildren(U.h("p", "error", `Bu beceri kaydedilemez: ${await U.errorText(r)}`)); return; }
        d = await r.json();
      } catch (_) { body.replaceChildren(U.h("p", "error", "Beceri kontrol edilemedi.")); return; }
      if (d.secenekler && choose) { body.replaceChildren(...choose(d.secenekler, box)); return; }
      const parts = [U.h("p", null, `Adı: /${d.name}`), U.h("pre", "skill-text", d.content)];
      if (d.kaynak) parts.splice(1, 0, U.h("p", "wiz-note", `Kaynak: ${d.kaynak} (yalnız yönerge metni alındı; yanındaki dosyalar alınmadı)`));
      const ack = U.h("input"); ack.type = "checkbox"; ack.id = `ack-${d.name}-${Math.random().toString(36).slice(2, 7)}`;
      const save = U.h("button", "primary", "Kaydet"); save.type = "button";
      const drop = U.h("button", null, "Vazgeç"); drop.type = "button";
      const msg = U.h("p", "wiz-note", ""); msg.setAttribute("role", "status");
      if (d.risky) {
        box.classList.add("risky");
        const list = U.h("ul", "wiz-list con");
        for (const w of d.warnings) list.append(U.h("li", null, w));
        const lab = U.h("label"); lab.htmlFor = ack.id; lab.append(" Uyarıları okudum, yine de kaydetmek istiyorum.");
        parts.push(U.h("p", "plain-warn", "Dikkat: bu öneride şunlar var."), list, rowOf(ack, lab));
        save.disabled = true;
        ack.addEventListener("change", () => { save.disabled = !ack.checked; });
      }
      parts.push(rowOf(save, drop), msg);
      body.replaceChildren(...parts);
      save.addEventListener("click", async () => {
        save.disabled = true; drop.disabled = true;
        const r = await U.api(`/skills/${encodeURIComponent(d.name)}`, { method: "PUT", body: JSON.stringify({ content: d.content }) });  // kullanıcının gördüğü metin
        if (!r.ok) { msg.textContent = await U.errorText(r); msg.className = "error"; save.disabled = d.risky && !ack.checked; drop.disabled = false; return; }
        for (const b of box.querySelectorAll("button, input")) b.disabled = true;
        msg.textContent = `Kaydettim. Kullanmak için /${d.name} yaz ya da Ayarlar → Becerilerim → Kullan.`; msg.className = "wiz-note ok";
        loadMySkills();
      });
      drop.addEventListener("click", () => { for (const b of box.querySelectorAll("button, input")) b.disabled = true; msg.textContent = "Vazgeçtin, bir şey kaydedilmedi."; });
    })();
    return box;
  }
  async function loadMySkills() {
    const list = $("my-skills");
    const r = await U.api("/skills");
    if (!r.ok) { list.replaceChildren(U.h("li", "wiz-note", "Becerileri alamadım.")); return; }
    const rows = await r.json();
    list.replaceChildren(...(rows.length ? rows.map((s) => {
      const li = U.h("li");
      const left = U.h("span", null, `/${s.name}`);
      left.append(U.h("span", "who", `  ${s.description}`));
      const acts = U.h("span", "acts");
      const use = U.h("button", null, "Kullan"); use.type = "button";
      use.addEventListener("click", () => { closePanels(); U.showTab("stream"); U.fillPrompt(`/${s.name} `); });
      const del = U.h("button", null, "Sil"); del.type = "button"; del.setAttribute("aria-label", `Sil: /${s.name}`);
      del.addEventListener("click", async () => { const d = await U.api(`/skills/${encodeURIComponent(s.name)}`, { method: "DELETE" }); if (d.ok) loadMySkills(); });
      acts.append(use, del);
      li.append(left, acts);
      return li;
    }) : [U.h("li", "wiz-note", "Henüz becerin yok. \"Usta'ya yeni bir iş öğret\"e basarak başla.")]));
  }

  // --- yardımcı yapay zekâ programları (orkestra şefi): hepsi KAPALI başlar ---
  async function loadHarnesses() {
    const list = $("harness-list");
    const r = await U.api("/harnesses");
    if (!r.ok) { list.replaceChildren(U.h("li", "wiz-note", "Programları alamadım.")); return; }
    const rows = (await r.json()).programlar || [];
    list.replaceChildren(...rows.map((p) => {
      const li = U.h("li");
      const left = U.h("span");
      left.append(U.h("strong", null, p.label));
      left.append(U.h("span", "who", p.installed ? `  ${p.version || "kurulu"}` : "  bu bilgisayarda kurulu değil"));
      const facts = [p.read_only ? "Yalnız okuma kipi var (varsayılan bu)." : (p.note ? "" : "Yalnız okuma kipi YOK: dosya yazabilir."), p.unsupported, p.note].filter(Boolean);  // not aynı şeyi söylüyorsa tekrar etme
      if (p.installed) left.append(U.h("div", "wiz-note", facts.join(" ")));
      const acts = U.h("span", "acts");
      const id = `hn-${p.id}`;
      const box = U.h("input"); box.type = "checkbox"; box.id = id; box.checked = !!p.enabled;
      box.disabled = !p.installed || !!p.unsupported;
      const lab = U.h("label"); lab.htmlFor = id; lab.textContent = " Usta çağırabilsin";
      box.addEventListener("change", async () => {
        box.disabled = true;
        const res = await U.api(`/harnesses/${encodeURIComponent(p.id)}`, { method: "PUT", body: JSON.stringify({ enabled: box.checked }) });
        const m = $("harness-msg");
        if (!res.ok) { box.checked = !box.checked; m.textContent = await U.errorText(res); m.className = "wiz-note error"; }
        else { m.textContent = box.checked ? `${p.label} açıldı. Usta onu çağırmadan önce her seferinde sana soracak.` : `${p.label} kapatıldı.`; m.className = "wiz-note ok"; }
        box.disabled = false;
      });
      acts.append(box, lab);
      li.append(left, acts);
      return li;
    }));
  }

  async function loadPrograms() {
    const box = $("programs");
    let d = {};
    try { const res = await U.api("/system/info"); if (res.ok) d = await res.json(); } catch { /* durum bilinmiyor */ }
    const items = [
      { name: "Ollama", ok: d.ollama_installed, why: "Yapay zekâyı kendi bilgisayarında çalıştırır. Gerekli mi? Yalnız \"Bu bilgisayarda\" seçeneğini seçersen. İnternet servisi kullanıyorsan gerekmez.", url: "https://ollama.com/download", text: "Ollama'yı indir", install: d.can_install && d.can_install.ollama ? "ollama" : null },
      { name: "Docker Desktop", ok: d.docker_installed, why: "Usta'nın bilgisayarında komut çalıştırmasını güvenli bir kutuda yapar. Gerekli mi? Sayfa, yazı, hesap makinesi gibi basit işler için hayır. Yazdığı kodu denemesini istiyorsan evet.", url: "https://www.docker.com/products/docker-desktop/", text: "Docker Desktop'ı indir" },
    ];
    box.replaceChildren(...items.map((it) => {
      const card = U.h("div", "card");
      const kurulu = d.os === undefined ? "" : (it.ok ? " (kurulu ✓)" : " (kurulu değil)");
      const ask = U.h("button", "q", "?");
      ask.type = "button"; ask.dataset.gloss = it.name.split(" ")[0]; ask.title = "Bu ne demek?"; ask.setAttribute("aria-label", `Bu ne demek? ${it.name}`);
      card.append(U.h("strong", null, `${it.name}${kurulu} `), ask, U.h("p", null, it.why));
      if (!it.ok && it.install) card.appendChild(installButton(it.install, `${it.name}'ı benim için kur`, loadPrograms));
      if (!it.ok) card.appendChild(U.wizLink(it.url, it.install ? "ya da kendin indir" : it.text));
      return card;
    }));
  }
  // Açık bölümün düğmesi "Sayfaya dön" olur; basınca BİR ÖNCEKİ yere döner (ana ekran ya da geldiğin bölüm)
  function showPanel(name) {
    for (const p of U.PANELS) {
      const on = p === name;
      const btn = $(`${p}-btn`);
      // üst çubuktaki "Sayfaya dön" kalabalıkta görülmüyor: bölümün kendi başında da geri düğmesi olur
      if (on && !$(p).querySelector(".panel-back")) {
        const back = U.h("button", "panel-back", "← Geri dön");
        back.type = "button";
        back.addEventListener("click", () => togglePanel(p));
        $(p).prepend(back);
      }
      $(p).hidden = !on;
      btn.setAttribute("aria-pressed", String(on));
      if (!btn.dataset.label) btn.dataset.label = btn.textContent;
      btn.textContent = on ? "Sayfaya dön" : btn.dataset.label;
    }
    document.querySelector("main").hidden = !!name;
    U.hideGlossTip();
    if (!name) return;
    if (name === "tools") { toolsMsg(""); loadTools(); loadSkills(); }
    else if (name === "privacy") loadPrivacy();
    else if (name === "wizard") U.wizShow("wiz-start");
    else if (name === "tablet") loadTablet();
    else if (name === "settings") { loadPrograms(); loadMySkills(); loadHarnesses(); loadProfile().then(loadOrtak); }
    else { U.apisMsg(""); U.loadApis(); }
  }
  function togglePanel(name) {
    const current = U.openPanel();
    if (current === name) { showPanel(U.state.panelStack.pop() || null); return; }  // "Sayfaya dön"
    if (current) U.state.panelStack.push(current); else U.state.panelStack = [];
    showPanel(name);
  }
  // sözlük bir bölüm değil, köşede açılan küçük penceredir: üstündeki işi kapatmaz
  function openGlossary(q = "") {
    $("glossary").hidden = false;
    $("glossary-btn").setAttribute("aria-pressed", "true");
    $("gloss-q").value = q; renderGlossary(); $("gloss-q").focus();
  }
  function closeGlossary() {
    $("glossary").hidden = true;
    $("glossary-btn").setAttribute("aria-pressed", "false");
    $("glossary-btn").focus();
  }
  function closePanels() { U.state.panelStack = []; showPanel(null); }
  const fmtBytes = (n) => (n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`);
  async function loadTablet() {
    const res = await U.api("/pair", { method: "POST" });
    $("tablet-off").hidden = res.ok;
    $("tablet-on").hidden = !res.ok;
    $("tablet-msg").textContent = "";
    if (!res.ok) { if (res.status !== 404) $("tablet-msg").textContent = await U.errorText(res); return; }
    const d = await res.json();
    $("tablet-pin").textContent = d.pin;
    $("tablet-ttl").textContent = `Bu kod ${Math.round(d.ttl / 60)} dakika geçerli.`;
    $("tablet-urls").replaceChildren(...(d.urls.length ? d.urls.map((u) => U.h("code", "cmd", u)) : [U.h("p", "empty", "Yerel ağ adresi bulunamadı. Bilgisayarın Wi-Fi'a bağlı mı?")]));
  }
  async function loadPrivacy() {
    const res = await U.api("/privacy");
    if (!res.ok) { $("privacy-sends").replaceChildren(U.h("p", "error", await U.errorText(res))); return; }
    const d = await res.json();
    const where = { "bu-bilgisayar": "bu bilgisayar", "yerel-ağ": "yerel ağ", internet: "internet" };
    $("privacy-sends").replaceChildren(...d.sends.map((t) => U.h("p", null, t)));
    const list = U.h("div", "models");
    for (const a of d.apis) list.appendChild(U.h("span", d.model && d.model.name === a.name ? "cur" : null, `${a.name}: ${where[a.where]}`));
    $("privacy-sends").appendChild(list);
    $("privacy-other").replaceChildren(...d.other.map((t) => U.h("li", null, t)));
    $("privacy-home").textContent = `Klasör: ${d.home}`;
    $("privacy-stored").replaceChildren(...d.stored.map((f) => {
      const card = U.h("div", "card");
      card.append(U.h("strong", null, f.name), U.h("span", "chip", fmtBytes(f.bytes)), U.h("p", "empty", f.what));
      return card;
    }));
  }
  const toggleTools = () => togglePanel("tools");

  // --- beceriler: klasörü göster, yükle, sil ---
  function skillsMsg(text, cls) { const m = $("skills-msg"); m.textContent = text || ""; m.className = cls || "empty"; }
  async function loadSkills() {
    const box = $("skills-list");
    box.replaceChildren();
    const res = await U.api("/skills");
    if (!res.ok) { skillsMsg(await U.errorText(res), "error"); return; }
    const list = await res.json();
    if (!list.length) box.appendChild(U.h("p", "empty", "Henüz beceri yok."));
    for (const s of list) {
      const row = U.h("div", "skill-row");
      row.append(U.h("span", null, `/${s.name}  ${s.description}`));
      const del = U.h("button", null, "Sil");
      del.type = "button";
      del.addEventListener("click", async () => {
        const r = await U.api(`/skills/${encodeURIComponent(s.name)}`, { method: "DELETE" });
        if (r.ok) loadSkills(); else skillsMsg(await U.errorText(r), "error");
      });
      row.appendChild(del);
      box.appendChild(row);
    }
  }
  async function uploadSkills(files) {
    for (const f of Array.from(files)) {
      const name = f.name.replace(/\.md$/i, "").toLowerCase().replace(/[^a-z0-9çğıöşü_-]+/g, "-").replace(/^-+/, "").slice(0, 30);
      if (!name || f.size > 20000) { skillsMsg(`${f.name}: ad geçersiz ya da 20 KB'tan büyük`, "error"); continue; }
      const res = await U.api(`/skills/${encodeURIComponent(name)}`, { method: "PUT", body: JSON.stringify({ content: await f.text() }) });
      skillsMsg(res.ok ? `/${name} yüklendi.` : `${f.name}: ${await U.errorText(res)}`, res.ok ? "ok" : "error");
    }
    loadSkills();
  }

  $("kisi-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const v = $("kisi-yeni").value.trim();
    if (!v) return;
    if (kisiFacts.length >= 20) { kisiMsg("En çok 20 madde yazabilirsin. Birini silip yenisini ekle.", "error"); return; }
    kisiFacts.push(v); $("kisi-yeni").value = ""; renderKisiFacts(); kisiMsg("Eklendi. Kalıcı olması için Kaydet'e bas.");
  });
  Object.assign(U, { closeGlossary, closePanels, openGlossary, installButton, kisiMsg, loadOrtak, loadProfile, loadTablet, ortakCall, ortakMsg, renderGlossary, saveProfile, setDesignSkill, skillFromLinkNode, skillProposalNode, startSkillDesign, togglePanel, uploadSkills });
})();
