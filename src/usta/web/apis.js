// API'ler paneli: eklenen uç noktalar, modelleri ve anahtarları.
// Ortak yardımcılar ve durum app.js'te; paylaşılan adlar window.UstaApp (U) üzerinden çağrı anında okunur.
(function () {
  "use strict";
  const U = (window.UstaApp = window.UstaApp || {});
  const $ = (id) => document.getElementById(id);
  // --- API'ler ---
  function apisMsg(text, cls) { const m = $("apis-msg"); m.textContent = text || ""; m.className = cls || "empty"; }
  async function loadApis() {
    const box = $("apis-list");
    box.replaceChildren();
    const [res, info] = await Promise.all([U.api("/apis"), U.api("/model").then((r) => (r.ok ? r.json() : null)).catch(() => null)]);
    if (!res.ok) { apisMsg(await U.errorText(res), "error"); return; }
    const byApi = {};
    for (const g of (info && info.apis) || []) byApi[g.api] = g;
    for (const a of await res.json()) {
      const card = U.h("div", "card");
      const g = byApi[a.name];
      card.append(U.h("strong", null, a.name), U.h("span", "chip", a.has_key ? "anahtar var" : "anahtarsız"), U.h("code", "cmd", a.endpoint));
      const models = U.h("div", "models");
      if (g && g.models.length) for (const m of g.models) models.appendChild(U.h("span", info && info.api === a.name && info.model === m ? "cur" : null, m));
      else models.appendChild(U.h("span", null, g && g.error ? g.error : "model yok"));
      card.appendChild(models);
      if (a.builtin) { card.appendChild(U.h("p", "empty", "Terminalden açılan varsayılan uç nokta.")); box.appendChild(card); continue; }
      const row = U.h("div", "key-row");
      const input = U.h("input");
      input.type = "password"; input.autocomplete = "off"; input.spellcheck = false;
      input.placeholder = a.has_key ? "yeni anahtar (değiştirmek için yaz)" : "anahtar gir";
      input.setAttribute("aria-label", `${a.name} anahtarı`);
      const save = U.h("button", null, "Kaydet");
      save.type = "button";
      save.addEventListener("click", async () => {
        const v = input.value.trim();
        if (!v) return;
        const r = await U.api(`/apis/${encodeURIComponent(a.name)}/key`, { method: "PUT", body: JSON.stringify({ key: v }) });
        if (r.ok) { apisMsg("Anahtar kaydedildi.", "ok"); loadApis(); U.loadModels(); } else apisMsg(await U.errorText(r), "error");
      });
      row.append(input, save);
      const remove = U.h("button", null, "Kaldır");
      remove.type = "button";
      let armed = null;
      remove.addEventListener("click", async () => {
        if (!armed) { remove.textContent = "Emin misin? Tekrar tıkla"; armed = setTimeout(() => { armed = null; remove.textContent = "Kaldır"; }, 4000); return; }
        clearTimeout(armed);
        const r = await U.api(`/apis/${encodeURIComponent(a.name)}`, { method: "DELETE" });
        if (r.ok) { loadApis(); U.loadModels(); } else apisMsg(await U.errorText(r), "error");
      });
      const actions = U.h("div", "row");
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
    const res = await U.api("/apis", { method: "POST", body: JSON.stringify(body) });
    if (!res.ok) { apisMsg(await U.errorText(res), "error"); return; }
    $("api-form").reset();
    apisMsg("API eklendi; modelleri model listesinde görünür.", "ok");
    loadApis(); U.loadModels();
  }
  Object.assign(U, { addApi, apisMsg, loadApis });
})();
