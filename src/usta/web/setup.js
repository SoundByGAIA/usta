// Kurulum sihirbazı: yapay zekânın nerede çalışacağı, bu bilgisayardaki model, evdeki başka bilgisayar.
// Ortak yardımcılar ve durum app.js'te; paylaşılan adlar window.UstaApp (U) üzerinden okunur.
(function () {
  "use strict";
  const U = (window.UstaApp = window.UstaApp || {});
  const L = window.UstaLogic;
  const $ = (id) => document.getElementById(id);
  // --- bilgisayarımdaki model ---
  const LOCAL_SLUG = { 11434: "ollama", 1234: "lm-studio", 8080: "llama-cpp", 8000: "vllm" };
  const CTX_CHOICES = [4096, 8192, 16384, 32768, 65536, 131072];
  async function scanLocal() {
    const box = $("local-found");
    box.replaceChildren();
    const raw = $("local-port").value.trim();
    const body = raw ? { port: Number(raw) } : {};
    const res = await U.api("/local/scan", { method: "POST", body: JSON.stringify(body) });
    if (!res.ok) { U.apisMsg(await U.errorText(res), "error"); return; }
    const found = await res.json();
    if (!found.length) { box.appendChild(U.h("p", "empty", "Bu portlarda çalışan bir model sunucusu bulamadım. Program açık mı?")); return; }
    for (const f of found) {
      const card = U.h("div", "card");
      card.append(U.h("strong", null, `${f.name} (port ${f.port})`), U.h("code", "cmd", f.endpoint));
      const models = U.h("div", "models");
      for (const m of f.models) models.appendChild(U.h("span", null, m));
      if (!f.models.length) models.appendChild(U.h("span", null, "model yok"));
      card.appendChild(models);
      const add = U.h("button", "primary", "Ekle");
      add.type = "button";
      add.addEventListener("click", async () => {
        const name = LOCAL_SLUG[f.port] || `yerel-${f.port}`;
        const r = await U.api("/apis", { method: "POST", body: JSON.stringify({ name, endpoint: f.endpoint }) });
        if (r.ok) { U.apisMsg(`Eklendi (${name}); modeller model listesinde görünür.`, "ok"); U.loadApis(); U.loadModels(); }
        else U.apisMsg(await U.errorText(r), "error");
      });
      const actions = U.h("div", "row");
      actions.appendChild(add);
      card.appendChild(actions);
      if (f.port === 11434 && f.models.length) {
        const row = U.h("div", "key-row");
        const msel = U.h("select");
        msel.setAttribute("aria-label", "Model");
        for (const m of f.models) { const o = U.h("option", null, m); o.value = m; msel.appendChild(o); }
        const csel = U.h("select");
        csel.setAttribute("aria-label", "Bağlam");
        for (const c of CTX_CHOICES) { const o = U.h("option", null, `${c / 1024}K`); o.value = String(c); csel.appendChild(o); }
        csel.value = "16384";
        const go = U.h("button", null, "Bağlamı uygula");
        go.type = "button";
        go.title = "Ollama'da bu bağlamla yeni bir model kopyası oluşturur (ağırlıklar kopyalanmaz)";
        go.addEventListener("click", async () => {
          go.disabled = true;
          const r = await U.api("/local/context", { method: "POST", body: JSON.stringify({ port: f.port, model: msel.value, num_ctx: Number(csel.value) }) });
          go.disabled = false;
          if (r.ok) { const d = await r.json(); U.apisMsg(`Oluşturuldu: ${d.model}. Model listesinden seçebilirsin.`, "ok"); scanLocal(); U.loadApis(); U.loadModels(); }
          else U.apisMsg(await U.errorText(r), "error");
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
  const WIZ_STEPS = ["wiz-start", "wiz-lan-step", "wiz-local-step", "wiz-cloud-step", "wiz-test-step"];
  const WIZ_RAIL = { "wiz-start": 1, "wiz-lan-step": 2, "wiz-local-step": 2, "wiz-cloud-step": 2, "wiz-test-step": 3 };
  const WIZ_EXAMPLES = ["Bir hesap makinesi web sayfası yap.", "Bu klasördeki dosyaları incele ve ne işe yaradıklarını kısaca anlat.", "Bugünün tarihini büyük yazıyla gösteren basit bir sayfa yap."];
  const wizMsg = (t, c) => { const m = $("wiz-msg"); m.textContent = t || ""; m.className = c || "empty"; };
  function wizBusy(on, text) { $("wizard").classList.toggle("wiz-busy", !!on); wizMsg(on ? text : "", on ? "ok" : "empty"); }
  function wizShow(id) {
    for (const s of WIZ_STEPS) $(s).hidden = s !== id;
    const n = WIZ_RAIL[id] || 1;
    for (const li of $("wiz-rail").children) {
      const k = Number(li.dataset.n);
      li.classList.toggle("done", k < n);
      if (k === n) li.setAttribute("aria-current", "step"); else li.removeAttribute("aria-current");
    }
    wizMsg("");
    if (id === "wiz-start") wizReco();
  }
  function openWizard() { if ($("wizard").hidden) U.togglePanel("wizard"); else wizShow("wiz-start"); }
  const trimSlash = (u) => String(u || "").replace(/\/+$/, "");
  function wizLink(url, text) {
    const a = U.h("a", "wiz-link", text);
    a.href = url; a.target = "_blank"; a.rel = "noopener noreferrer";
    return a;
  }

  async function wizReco() {
    const el = $("wiz-reco-text");
    el.textContent = "Bilgisayarına bakıyorum…";
    let d = null;
    try { const r = await U.api("/system/info"); if (r.ok) d = await r.json(); } catch (_) { /* yoksay */ }
    const ram = d && d.ram_gb ? `${d.ram_gb} GB` : null;
    $("wiz-pick-cloud").classList.add("reco");
    if (d && d.recommend && !d.recommend.model) {
      el.textContent = `Bilgisayarının belleği az (${ram}). İnternet servisiyle başla; ücretsiz seçenek olarak Google Gemini'yi deneyebilirsin.`;
    } else {
      el.textContent = "Yeni başlıyorsan ve anahtar almaktan çekinmiyorsan: İnternet servisiyle başla, ücretsiz seçenek olarak Google Gemini'yi dene. "
        + `Yazdıklarının bilgisayarından çıkmaması senin için çok önemliyse: Bu bilgisayarda${ram ? ` (belleğin ${ram}, bu iş için uygun)` : ""}, ama zor işlerde zayıf kalabileceğini bil. `
        + "Evde daha güçlü bir bilgisayarın varsa: Evdeki başka bilgisayarda.";
    }
  }

  async function wizUse(apiName, model) {
    wizBusy(true, "Modeli tanıyorum, bu yarım dakika sürebilir. Lütfen bekle…");
    let r;
    try { r = await U.api("/model", { method: "PUT", body: JSON.stringify({ model, api: apiName }) }); }
    finally { wizBusy(false); }
    if (!r.ok) { wizMsg(await U.errorText(r), "error"); return; }
    await U.loadModels();
    wizTest();
  }
  async function wizEnsureLocalApi() {
    const endpoint = "http://127.0.0.1:11434/v1";
    const rows = await (await U.api("/apis")).json();
    const row = rows.find((a) => trimSlash(a.endpoint) === endpoint);
    if (row) return row.name;
    const r = await U.api("/apis", { method: "POST", body: JSON.stringify({ name: "ollama", endpoint }) });
    if (!r.ok) throw new Error(await U.errorText(r));
    return "ollama";
  }
  const fmtGb = (n) => `${(n / 1073741824).toFixed(1)} GB`;
  let wizPullTimer = null;
  function wizStopPull() { clearTimeout(wizPullTimer); wizPullTimer = null; }

  async function wizLocal() {
    wizStopPull();
    wizShow("wiz-local-step");
    const body = $("wiz-local-body");
    body.replaceChildren(U.h("p", null, "Bilgisayarına bakıyorum…"));
    const res = await U.api("/system/info");
    if (!res.ok) { body.replaceChildren(U.h("p", "error", await U.errorText(res))); return; }
    const d = await res.json();
    const rec = d.recommend || {};
    const out = [U.h("p", null, d.ram_gb ? `Bilgisayarının belleği: ${d.ram_gb} GB.` : "Bilgisayarının belleğini öğrenemedim.")];
    if (!rec.model) {
      out.push(U.h("p", null, rec.reason || ""));
      const go = U.h("button", "primary", "İnternet servisine geç");
      go.type = "button"; go.addEventListener("click", wizCloud);
      body.replaceChildren(...out, go);
      return;
    }
    out.push(U.h("p", null, rec.reason));
    if (!d.ollama_running) {
      const card = U.h("div", "card");
      card.append(U.h("strong", null, "1. Ollama programını kur"),
        U.h("p", null, "Ollama, yapay zekâ modellerini bilgisayarında çalıştıran ücretsiz bir programdır."));
      const canAuto = d.can_install && d.can_install.ollama;
      if (canAuto) {
        card.append(U.h("p", "wiz-note", "İstersen düğmeye bas, Usta senin için kurar (yaklaşık 1 GB iner)."), U.installButton("ollama", "Ollama'yı benim için kur", wizLocal));
      }
      card.appendChild(wizLink("https://ollama.com/download", canAuto ? "Ya da kendin indir: Ollama sayfasını aç" : "Ollama indirme sayfasını aç"));
      const ol = U.h("ol", "wiz-steps");
      for (const t of canAuto ? ["Kurulum bitince bu sayfa kendiliğinden devam eder."] : ["İndirdiğin dosyayı aç ve kur.", "Kurulum bitince Ollama'yı bir kez aç (Başlat menüsünde \"Ollama\").", "Bu pencereye dön ve aşağıdaki \"Tekrar ara\" düğmesine bas."]) ol.appendChild(U.h("li", null, t));
      card.appendChild(ol);
      body.replaceChildren(...out, card);
      return;
    }
    const have = (d.installed || []).includes(rec.model);
    const card = U.h("div", "card");
    if (!have) {
      card.append(U.h("strong", null, `2. Modeli indir: ${rec.model}`),
        U.h("p", null, `Yaklaşık ${rec.size_gb} GB indirir. Hızlı internetle birkaç dakika sürer, yavaşta daha uzun. İndirirken bu pencereyi kapatma.`));
      const dl = U.h("button", "primary", `İndir (≈ ${rec.size_gb} GB)`);
      dl.type = "button";
      dl.addEventListener("click", () => wizPull(rec.model, card));
      card.appendChild(dl);
    } else {
      card.append(U.h("strong", null, `Önerilen model zaten kurulu: ${rec.model}`));
      const use = U.h("button", "primary", "Bunu kullan");
      use.type = "button";
      use.addEventListener("click", async () => { try { wizUse(await wizEnsureLocalApi(), rec.model); } catch (e) { wizMsg(String(e.message || e), "error"); } });
      card.appendChild(use);
    }
    body.replaceChildren(...out, card);
    const others = (d.installed || []).filter((m) => m !== rec.model);
    if (others.length) {
      body.appendChild(U.h("p", "wiz-group", "Bilgisayarında kurulu diğer modeller:"));
      for (const m of others) {
        const b = U.h("button", "card wiz-choice");
        b.type = "button"; b.append(U.h("strong", null, m));
        b.addEventListener("click", async () => { try { wizUse(await wizEnsureLocalApi(), m); } catch (e) { wizMsg(String(e.message || e), "error"); } });
        body.appendChild(b);
      }
    }
  }
  async function wizPull(model, card) {
    const r = await U.api("/local/pull", { method: "POST", body: JSON.stringify({ model }) });
    if (!r.ok && r.status !== 409) { wizMsg(await U.errorText(r), "error"); return; }
    const bar = U.h("progress", "wiz-progress"); bar.max = 100; bar.value = 0;
    const label = U.h("p", "note", "İndirme başlıyor…");
    card.replaceChildren(U.h("strong", null, `İndiriliyor: ${model}`), bar, label);
    const poll = async () => {
      if ($("wiz-local-step").hidden) return;  // kullanıcı başka adıma geçti
      let s = null;
      try { const p = await U.api("/local/pull"); if (p.ok) s = await p.json(); } catch (_) { /* tekrar dene */ }
      if (s && s.error) {
        card.replaceChildren(U.h("p", "error", s.error));
        const again = U.h("button", null, "Tekrar dene"); again.type = "button"; again.addEventListener("click", wizLocal);
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

  // --- evdeki başka bilgisayar ---
  const lanApiName = (host) => `ev-${String(host).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "")}`.slice(0, 30).replace(/-+$/, "") || "ev-pc";
  async function wizLanUse(found, model) {
    try {
      const endpoint = trimSlash(found.endpoint);
      const rows = await (await U.api("/apis")).json();
      let name = (rows.find((a) => trimSlash(a.endpoint) === endpoint) || {}).name;
      if (!name) {
        name = lanApiName(found.host || found.endpoint);
        const r = await U.api("/apis", { method: "POST", body: JSON.stringify({ name, endpoint }) });
        if (!r.ok) { wizMsg(await U.errorText(r), "error"); return; }
      }
      wizUse(name, model);
    } catch (e) { wizMsg(String(e.message || e), "error"); }
  }
  function lanCard(found) {
    const card = U.h("div", "card wiz-lan-card");
    const where = found.host || found.endpoint;
    card.append(U.h("strong", null, `${found.name} · ${where}`));
    if (!found.models.length) {
      card.append(U.h("p", "wiz-note", "Bu bilgisayarda henüz indirilmiş bir model yok. Öbür bilgisayarda bir model indir, sonra \"Tekrar ara\"ya bas."));
      return card;
    }
    card.append(U.h("p", "wiz-note", `${found.models.length} model var. Hangisini kullanalım?`));
    const sel = U.h("select");
    sel.setAttribute("aria-label", "Model");
    for (const m of found.models) sel.append(U.h("option", null, m));
    const go = U.h("button", "primary", "Bunu kullan");
    go.type = "button";
    go.addEventListener("click", () => wizLanUse(found, sel.value));
    const row = U.h("div", "row");
    row.append(sel, go);
    card.append(row);
    return card;
  }
  async function wizLan() {
    wizStopPull();
    wizShow("wiz-lan-step");
    const box = $("wiz-lan-found");
    box.replaceChildren(U.h("p", null, "Evdeki ağa bakıyorum… (birkaç saniye sürer)"));
    $("wiz-lan-rescan").disabled = true;
    let list = [];
    try {
      const r = await U.api("/local/scan-lan", { method: "POST" });
      if (!r.ok) { box.replaceChildren(U.h("p", "error", await U.errorText(r))); return; }
      list = await r.json();
    } finally { $("wiz-lan-rescan").disabled = false; }
    if (!list.length) {
      box.replaceChildren(U.h("p", null, "Evdeki ağda yapay zekâ bulamadım. Öbür bilgisayar açık ve \"ağa açık\" mı? Aşağıdan nasıl hazırlanacağına bak ya da adresi kendin yaz."));
      return;
    }
    box.replaceChildren(U.h("p", null, list.length === 1 ? "Bir tane buldum:" : `${list.length} tane buldum:`), ...list.map(lanCard));
  }
  async function wizLanTry(ev) {
    ev.preventDefault();
    const host = $("wiz-lan-host").value.trim();
    if (!host) return;
    const box = $("wiz-lan-found");
    box.replaceChildren(U.h("p", null, `${host} adresine bakıyorum…`));
    const r = await U.api("/local/probe-host", { method: "POST", body: JSON.stringify({ host }) });
    if (!r.ok) { box.replaceChildren(U.h("p", "error", await U.errorText(r))); return; }
    box.replaceChildren(lanCard(await r.json()));
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
      box.appendChild(U.h("p", "wiz-group", title));
      const row = U.h("div", "wiz-choices");
      for (const svc of WIZ_SERVICES.filter((x) => x.free === free)) {
        const b = U.h("button", "card wiz-choice");
        b.type = "button";
        const name = U.h("strong", null, svc.label);
        name.appendChild(U.h("span", free ? "wiz-tag" : "wiz-tag paid", free ? "ücretsiz katmanı var" : "ücretli"));
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
    const ol = U.h("ol", "wiz-steps");
    for (const t of svc.steps) ol.appendChild(U.h("li", null, t));
    help.replaceChildren(U.h("strong", null, `${svc.label}: anahtarı nasıl alırım?`), wizLink(svc.url, svc.linkText), ol, U.h("p", "wiz-note", svc.note));
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
      let r = await U.api("/apis", { method: "POST", body: JSON.stringify({ name: svc.id, endpoint: svc.endpoint, key }) });
      if (r.status === 409) r = await U.api(`/apis/${svc.id}/key`, { method: "PUT", body: JSON.stringify({ key }) });
      if (!r.ok) { wizBusy(false); wizMsg(await U.errorText(r), "error"); return; }
      $("wiz-key").value = "";
      const info = await (await U.api("/model")).json();
      const g = (info.apis || []).find((x) => x.api === svc.id);
      wizBusy(false);
      if (!g || !g.models.length) { wizMsg("Anahtar kabul edilmedi ya da servise ulaşılamadı. Doğru kopyaladığından emin ol (başında/sonunda boşluk olmasın) ve tekrar dene.", "error"); return; }
      const sel = $("wiz-model");
      const list = L.chatModels(g.models, svc.prefer);
      sel.replaceChildren(...list.map((m) => { const o = U.h("option", null, m.replace(/^models\//, "")); o.value = m; return o; }));
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
    const res = await U.api("/setup/ping", { method: "POST" });
    const d = res.ok ? await res.json() : { ok: false, error: await U.errorText(res) };
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
      const b = U.h("button", "card wiz-choice");
      b.type = "button";
      b.append(U.h("strong", null, t));
      b.addEventListener("click", () => { U.closePanels(); $("prompt").value = t; $("prompt").focus(); });
      return b;
    }));
    box.hidden = false;
  }

  $("wiz-model-go").addEventListener("click", () => wizUse(wizService.id, $("wiz-model").value));
  Object.assign(U, { openWizard, scanLocal, wizCloud, wizLan, wizLanTry, wizLink, wizLocal, wizMsg, wizShow, wizTryKey });
})();
