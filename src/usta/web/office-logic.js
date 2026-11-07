// Usta "Ofis" sekmesi: DOM'dan bağımsız saf mantık (node ile test edilir).
// Girdi portalın zaten aldığı olaylardır (logic.js `summarize` ve agent/tasks emit alanları).
// Sayaçlar yalnız gerçek olaylardan artar; hiçbir değer uydurulmaz.
(function (root) {
  "use strict";

  const MAX_LOG = 5;
  const MAX_SAID = 120;

  const TOOL_LABEL = {
    read_file: "dosya okuyor",
    list_dir: "klasöre bakıyor",
    outline: "dosya özetini çıkarıyor",
    read_symbol: "fonksiyonu okuyor",
    find_symbol: "sembol arıyor",
    symbol_context: "sembol çevresine bakıyor",
    related_files: "ilgili dosyaları arıyor",
    write_file: "dosya yazıyor",
    edit_file: "dosya düzenliyor",
    fetch_url: "internetten sayfa alıyor",
    remember: "not yazıyor",
    run: "komut çalıştırıyor",
  };
  const READ_TOOLS = [
    "read_file",
    "list_dir",
    "outline",
    "read_symbol",
    "find_symbol",
    "symbol_context",
    "related_files",
  ];
  const WRITE_TOOLS = ["write_file", "edit_file"];
  const TEST_RE = /\b(?:unittest|pytest|jest|vitest|mocha|nose2?|tox|nox|ctest|rspec|phpunit|click|test)\b/i;

  function clip(s, max) {
    s = String(s == null ? "" : s).replace(/\s+/g, " ").trim();
    return s.length > max ? s.slice(0, max - 1).trimEnd() + "…" : s;
  }

  function isTestCommand(command) {
    return typeof command === "string" && TEST_RE.test(command);
  }

  function isMcpTool(tool) {
    const t = String(tool || "").toLowerCase();
    return t.indexOf("__") >= 0 || t.indexOf("mcp") >= 0;
  }

  // Araç adı → ofisteki bölge (sabit eşleme; komut içeriği yalnız `run` için bakılır).
  function zoneFor(tool, args) {
    const name = String(tool || "");
    if (READ_TOOLS.indexOf(name) >= 0) return "library";
    if (WRITE_TOOLS.indexOf(name) >= 0) return "workshop";
    if (name === "run") {
      return isTestCommand((args || {}).command) ? "testbench" : "workshop";
    }
    if (name === "fetch_url" || isMcpTool(name)) return "post";
    if (name === "remember" || name.toLowerCase().indexOf("memory") >= 0) return "memory";
    return "workshop";
  }

  function toolLabel(tool, zone) {
    const name = String(tool || "");
    if (TOOL_LABEL[name]) return TOOL_LABEL[name];
    if (isMcpTool(name)) return "dış araç çağırıyor";
    return { library: "kitaplıkta çalışıyor", testbench: "testleri koşuyor", post: "mektup alıyor", memory: "dolaba not koyuyor" }[zone] || "çalışıyor";
  }

  // Çalışma alanına göreli yol → okunur kısa ad (postane için alan adı)
  function shortTarget(tool, args) {
    args = args || {};
    if (tool === "fetch_url") {
      try {
        return clip(new URL(String(args.url || "")).host, 40);
      } catch (_) {
        return clip(args.url, 40);
      }
    }
    const path = args.path || args.name || args.command || "";
    return clip(String(path).split("/").filter(Boolean).slice(-1)[0] || "", 40);
  }

  function initial() {
    return {
      status: "idle", // idle | running | awaiting | done | failed | cancelled
      zone: "desk", // desk | library | workshop | testbench | post | memory
      target: "desk", // karakterin hedef bölgesi
      mood: "calm", // calm | happy | sad | alert
      hand: false, // el kaldırma (onay bekliyor)
      bubble: "", // konuşma balonu
      bubbleKind: "say", // say | ask | alarm | none
      pendingReason: "",
      pendingApprovalId: "", // onay bekleyen isteğin kimliği ("" = bekleyen yok); şerit yalnız bu doluyken çizilir
      lastApproval: null, // son onay aracı {tool}: şerit "Usta onay bekliyor: <araç>" yazısını buradan kurar
      lastCall: null, // son tool_call {tool, args}: tool_result olayı args taşımaz, komutu buradan öğreniriz
      counts: { tool_calls: 0, edits: 0, tests_pass: 0, tests_fail: 0 },
      log: [], // son 5 eylem: { type, text }
      ended: null, // bitti durumunun ayrıntısı (done/failed/cancelled)
      // Son `usage` olayının anlık görüntüsü (yalnız bu olayla değişir; araç/düzenleme/test
      // sayaçlarına DOKUNMAZ). Alan adları agent.py `_emit_usage` ile aynıdır.
      usage: null, // { prompt, completion, requests, cached, context }
      // Süre yalnız sıra numaralarıyla işaretlenir: gerçek zaman DOM tarafında ölçülür
      // (mantık saf kalır, olay zamanı verisine ihtiyaç duymaz).
      runSeq: 0, // görevin başladığı olayın fx.seq değeri (0 = bu görevde başlamadı)
      endSeq: 0, // görevin bittiği olayın fx.seq değeri (0 = bitmedi)
      // Efekt tetikleyicileri: yalnız GERÇEK olaylardan türetilir (uydurma yok).
      // seq her olayda artar → çizici "yeni tetikleyici mi" diye karşılaştırır.
      fx: { seq: 0, test: "", testSeq: 0, end: "", endSeq: 0 },
      // Boş zaman davranışı yalnız cosmetic; yalnızca görev yokken/bitmişken true olur.
      idle: false,
    };
  }

  function pushLog(state, type, text) {
    const log = state.log.concat([{ type, text: clip(text, 100) }]);
    state.log = log.slice(Math.max(0, log.length - MAX_LOG));
  }

  function areaName(zone) {
    return {
      desk: "masasında",
      library: "Kitaplık'ta",
      workshop: "Atölye'de",
      testbench: "Test tezgâhında",
      post: "Postane'de",
      memory: "Hafıza dolabında",
    }[zone] || "ofiste";
  }

  function reduce(state, type, data) {
    const d = data || {};
    // eski biçimde fx/idle taşımayan durum da kabul edilir (geriye uyum, testte kolaylık)
    const fx0 = state.fx || { seq: 0, test: "", testSeq: 0, end: "", endSeq: 0 };
    const s = {
      status: state.status,
      zone: state.zone,
      target: state.target,
      mood: state.mood,
      hand: state.hand,
      bubble: state.bubble,
      bubbleKind: state.bubbleKind,
      pendingReason: state.pendingReason,
      pendingApprovalId: state.pendingApprovalId || "",
      lastApproval: state.lastApproval || null,
      lastCall: state.lastCall,
      counts: {
        tool_calls: state.counts.tool_calls,
        edits: state.counts.edits,
        tests_pass: state.counts.tests_pass,
        tests_fail: state.counts.tests_fail,
      },
      log: state.log,
      ended: state.ended,
      usage: state.usage || null,
      runSeq: state.runSeq || 0,
      endSeq: state.endSeq || 0,
      idle: !!state.idle,
      fx: {
        seq: fx0.seq + 1, // her olay tek üretim numarası → aynı olay dizisi aynı durumu verir
        test: fx0.test,
        testSeq: fx0.testSeq,
        end: fx0.end,
        endSeq: fx0.endSeq,
      },
    };

    switch (type) {
      case "started":
        s.status = "running";
        s.mood = "calm";
        s.idle = false;
        s.bubble = "İşe koyuluyorum.";
        s.bubbleKind = "say";
        s.runSeq = s.fx.seq; // süre ölçümünün başlangıç işareti (yerel saat DOM tarafında)
        s.endSeq = 0;
        pushLog(s, "started", "Görev başladı" + (d.mode ? ` (${d.mode})` : ""));
        break;

      case "message": {
        const text = clip(d.content, MAX_SAID);
        if (!text) return s; // boş mesaj balonu silmez
        s.bubble = text;
        s.bubbleKind = "say";
        s.mood = "calm";
        s.idle = false; // model konuşuyorsa boşta değil
        s.zone = "desk";
        s.target = "desk";
        pushLog(s, "message", "Açıklama: " + text);
        break;
      }

      case "tool_call": {
        const tool = String(d.tool || "");
        const zone = zoneFor(tool, d.args);
        s.lastCall = { tool, args: d.args || {} };
        s.counts.tool_calls = s.counts.tool_calls + 1;
        if (WRITE_TOOLS.indexOf(tool) >= 0) s.counts.edits = s.counts.edits + 1;
        const where = shortTarget(tool, d.args);
        const label = toolLabel(tool, zone);
        s.zone = zone;
        s.target = zone;
        s.mood = "calm";
        s.bubble = `${label}${where ? ": " + where : ""}.`;
        s.bubbleKind = "say";
        s.status = "running";
        s.idle = false;
        pushLog(s, "tool_call", `${tool || "araç"} ${where}`.trim());
        break;
      }

      case "tool_result": {
        // Yalnız gerçek bir komut sonucu test geçti/kaldı sayacına işlenir (exit_code satırı).
        const lc = s.lastCall && s.lastCall.tool === d.tool ? s.lastCall.args : {};
        const args = d.args || lc || {};
        const m = /exit_code:\s*(-?\d+)([^\n]*)/.exec(String(d.result || ""));
        if (m && isTestCommand(args.command)) {
          const inter = /\(zaman aşımı\)|\(iptal\)/.test(m[2]);
          if (!inter) {
            if (Number(m[1]) === 0) s.counts.tests_pass = s.counts.tests_pass + 1;
            else s.counts.tests_fail = s.counts.tests_fail + 1;
            // Efekt tetikleyicisi: yalnız gerçek bir test sonucundan (zaman aşımı/iptal sayılmaz)
            s.fx.test = Number(m[1]) === 0 ? "pass" : "fail";
            s.fx.testSeq = s.fx.seq;
          }
        }
        if (d.tool) s.zone = zoneFor(d.tool, args);
        s.lastCall = null;
        break;
      }

      case "approval_required": {
        const tool = String(d.tool || "araç");
        s.status = "awaiting";
        s.hand = true;
        s.mood = "alert";
        s.zone = "desk";
        s.target = "desk";
        s.pendingReason = `İzin içeren eylem: ${tool}`;
        // Onay kimliği yalnız GERÇEK olaydan gelir (logic.js summarize `approvalId` = data.approval_id);
        // kimlik yoksa şerit çizilmez (uydurma kimlik üretilmez).
        s.pendingApprovalId = d.approval_id == null ? "" : String(d.approval_id);
        s.lastApproval = { tool };
        s.bubble = `Şuna izin verir misin: ${tool}?`;
        s.bubbleKind = "ask";
        pushLog(s, "approval_required", `İzin istendi: ${tool}`);
        break;
      }

      case "auto_approved": {
        const tool = String(d.tool || "araç");
        s.hand = false;
        s.pendingReason = "";
        s.pendingApprovalId = ""; // bekleyen onay kalmadı → ofis şeridi kapanır
        s.bubble = `Oto onay: ${tool}.`;
        s.bubbleKind = "say";
        pushLog(s, "auto_approved", `Oto onay: ${tool}`);
        break;
      }

      case "denied": {
        const tool = String(d.tool || "araç");
        s.hand = false;
        s.pendingReason = "";
        s.pendingApprovalId = "";
        s.mood = "alert";
        s.zone = "desk";
        s.target = "desk";
        s.bubble = clip(`Reddedildi: ${tool}${d.reason ? " (" + d.reason + ")" : ""}.`, MAX_SAID);
        s.bubbleKind = "alarm";
        pushLog(s, "denied", `Reddedildi: ${tool}`);
        break;
      }

      case "warning": {
        const msg = clip(d.message || "Uyarı", MAX_SAID);
        s.bubble = msg;
        s.bubbleKind = "alarm";
        s.mood = s.mood === "alert" ? "alert" : "sad";
        pushLog(s, "warning", msg);
        break;
      }

      case "reverted":
        s.bubble = "Değişiklikleri geri aldım.";
        s.bubbleKind = "say";
        s.zone = "workshop";
        s.target = "workshop";
        pushLog(s, "reverted", "Değişiklikler geri alındı");
        break;

      case "done": {
        const st = d.status === "failed" ? "failed" : d.status === "cancelled" ? "cancelled" : "done";
        s.status = st;
        s.hand = false;
        s.pendingReason = "";
        s.pendingApprovalId = "";
        s.zone = "desk";
        s.target = "desk";
        s.ended = st;
        if (!s.endSeq) s.endSeq = s.fx.seq; // süre burada durur (ilk bitiş işareti korunur)
        s.fx.end = st;
        s.fx.endSeq = s.fx.seq;
        s.idle = true; // görev bitti → boş zaman davranışı artık cosmetic olarak serbest
        if (st === "failed") {
          s.mood = "sad";
          s.bubble = clip("Görev başarısız" + (d.error ? ": " + d.error : "."), MAX_SAID);
          s.bubbleKind = "alarm";
          pushLog(s, "done", "Görev başarısız");
        } else if (st === "cancelled") {
          s.mood = "sad";
          s.bubble = "Görev durduruldu.";
          s.bubbleKind = "say";
          pushLog(s, "done", "Görev durduruldu");
        } else {
          s.mood = "happy";
          s.bubble = "Bitti!";
          s.bubbleKind = "say";
          pushLog(s, "done", "Görev bitti");
        }
        break;
      }

      case "user_message":
        s.bubble = clip("Yeni mesaj aldım: " + String(d.text || ""), MAX_SAID);
        s.bubbleKind = "say";
        s.zone = "desk";
        s.target = "desk";
        s.idle = false;
        s.mood = s.status === "done" || s.status === "failed" || s.status === "cancelled" ? "calm" : s.mood;
        pushLog(s, "user_message", "Kullanıcı mesajı");
        break;

      case "usage":
        // Sayaçlar yalnız araç/düzenleme/test olaylarından; token bilgisi ofis sayaçlarına girmez.
        // Yalnız `usage` anlık görüntüsü yenilenir (agent.py `_emit_usage` alanları).
        if (d.prompt != null || d.completion != null || d.requests != null || d.context != null) {
          const num = (v) => (Number.isFinite(Number(v)) ? Math.max(0, Math.round(Number(v))) : 0);
          s.usage = {
            prompt: num(d.prompt),
            completion: num(d.completion),
            requests: num(d.requests),
            cached: num(d.cached),
            context: num(d.context),
          };
        }
        break;

      default:
        // Bilinmeyen olay durumu bozmaz (çözülmemiş olaylar için de yalnız bilinen alanlar işlenir)
        if (type === "verification" && d.status) {
          s.bubble = clip(`Doğrulama: ${d.status}`, MAX_SAID);
          s.bubbleKind = "say";
          pushLog(s, "verification", `Doğrulama: ${d.status}`);
        }
        break;
    }
    return s;
  }

  // Erişilebilirlik satırı: o anki eylemi düz yazıyla söyler
  function describe(state) {
    if (state.hand) return `Usta masasında elini kaldırdı: onay bekliyor (${state.pendingReason || "izin"})`;
    if (state.status === "done") return "Usta bitirdi: görev tamamlandı ve doğrulandı";
    if (state.status === "failed") return "Usta omuzları düşük: görev başarısız";
    if (state.status === "cancelled") return "Usta durdu: görev iptal edildi";
    if (state.status === "idle") return "Usta ofiste, yeni görev bekliyor";
    return `Usta ${areaName(state.zone)} çalışıyor`;
  }

  function countersText(state) {
    const c = state.counts;
    return `araç ${c.tool_calls} · düzenleme ${c.edits} · test geçti ${c.tests_pass} · test kaldı ${c.tests_fail}`;
  }

  // Tahtadaki kısa sayaç satırı: "A:1  D:1  T:0/0" (A araç, D düzenleme, T test geçti/kaldı).
  // Metin satırı açıklaması portalın alt yazısında; burada yalnız sığan biçim.
  // Tahta iç alanı 136 px = en çok 22 karakter (5x7 font, 6 px glif adımı) → satır 19 karakteri geçmez:
  // normalde iki boşluk, uzunsa tek boşluk, hâlâ uzunsa sayılar "999+" ile kısaltılır.
  const SHORT_MAX = 19;
  function shortCounters(state) {
    const c = state.counts || {};
    const fmt = (v, gap) => {
      const n = Number(v) || 0;
      return n > 999 ? "999+" : String(n) + gap; // kısaltılan sayıdan sonra boşluk yok
    };
    for (const gap of ["  ", " "]) {
      const line = "A:" + fmt(c.tool_calls, gap) + "D:" + fmt(c.edits, gap) + "T:" + fmt(c.tests_pass, "") + "/" + fmt(c.tests_fail, "");
      if (line.length <= SHORT_MAX) return line;
    }
    return "A:" + fmt(c.tool_calls, "") + " D:" + fmt(c.edits, ""); // aşırı büyük sayılarda test sayacı düşer (tahtaya sığmaz)
  }

  // --- göstergeler şeridi için DOM'suz biçimlendirme (node testlerinde doğrudan sınanır) ---
  // Not: logic.js'teki formatTokens kopyalanmaz; orada yuvarlama kuralı farklı (812 → "812").
  // Buradaki kural göstergeler şeridi için: 1000 altı tam sayı, üstü tek ondalık (Türkçe virgül).
  function formatTokens(n) {
    const v = Math.round(Number(n));
    if (!Number.isFinite(v) || v <= 0) return "0";
    const f = (x, unit) => {
      const r = x >= 10 ? String(Math.round(x)) : x.toFixed(1).replace(".", ",").replace(/,0$/, "");
      return r + unit;
    };
    if (v >= 1e6) return f(v / 1e6, "M");
    if (v >= 1e3) return f(v / 1e3, "K");
    return String(v);
  }

  // Toplam token: prompt + completion (usage yoksa 0)
  function totalTokens(u) {
    if (!u) return 0;
    const p = Number(u.prompt),
      c = Number(u.completion);
    return Math.max(0, Math.round((Number.isFinite(p) ? p : 0) + (Number.isFinite(c) ? c : 0)));
  }

  // Bağlam doluluğu yüzdesi: pencere bilinmiyorsa/sıfırsa null (yalnız sayı gösterilir),
  // %100 üstü 100'e kenetlenir (pencere aşımı 100'den büyük yüzde üretmez).
  function contextPercent(context, windowSize) {
    if (context == null || windowSize == null) return null; // Number(null) === 0 olduğundan açıkça ele alınır
    const c = Number(context),
      w = Number(windowSize);
    if (!Number.isFinite(c) || !Number.isFinite(w) || w <= 0) return null;
    if (c < 0) return 0;
    return Math.min(100, Math.round((c / w) * 100));
  }

  // Göstergeler için tek metin: "Token", "Bağlam" (yüzde + pencere biliniyorsa oran), "İstek".
  // Süre buraya girmez: doğrudan istemci saatinden ölçülür (saf mantıkta saat okunmaz).
  function metricLines(usage, windowSize) {
    const u = usage || {};
    const total = totalTokens(usage);
    const ctx = Math.max(0, Math.round(Number(u.context) || 0));
    const pct = ctx > 0 ? contextPercent(ctx, windowSize) : null; // bağlam 0 ise yüzde uydurulmaz
    const win = Number(windowSize);
    const ctxText = !ctx
      ? "—"
      : pct == null || !Number.isFinite(win) || win <= 0
        ? formatTokens(ctx)
        : `${formatTokens(ctx)} / ${formatTokens(win)} · %${pct}`;
    return [
      { key: "token", label: "Token", value: formatTokens(total), pct: null },
      { key: "context", label: "Bağlam", value: ctxText, pct },
      { key: "requests", label: "İstek", value: String(Math.max(0, Math.round(Number(u.requests) || 0))), pct: null },
    ];
  }

  // Süre: saniye → "0:07", "2:05", "1:02:03" (saat yalnız gerektiğinde)
  function formatDuration(seconds) {
    let t = Math.floor(Number(seconds));
    if (!Number.isFinite(t) || t < 0) t = 0;
    const h = Math.floor(t / 3600);
    const m = Math.floor((t % 3600) / 60);
    const s = t % 60;
    const two = (v) => (v < 10 ? "0" + v : String(v));
    return h > 0 ? `${h}:${two(m)}:${two(s)}` : `${m}:${two(s)}`;
  }

  // Onay şeridinin başlığı: "Usta onay bekliyor: <araç>" (yalnız gerçek araç adından; uydurma yok)
  function approvalLine(state) {
    const tool = state && state.lastApproval && state.lastApproval.tool ? String(state.lastApproval.tool) : "";
    return tool ? `Usta onay bekliyor: ${tool}` : "Usta onay bekliyor";
  }

  // Geçmiş oturum zaman çubuğu: olay dizisini BAŞTAN sarılı indekse kadar uygular (saf, tekrarlanabilir).
  // i kenetlenir (<0 → 0, >N → N); boş dizi → initial; girdi dizisi ve olay nesneleri DEĞİŞTİRİLMEZ.
  function replayState(events, i) {
    const list = Array.isArray(events) ? events : [];
    const n = list.length;
    const raw = Math.floor(Number(i));
    const upTo = Number.isFinite(raw) ? Math.min(n, Math.max(0, raw)) : 0;
    let s = initial();
    for (let k = 0; k < upTo; k++) {
      const e = list[k] || {};
      s = reduce(s, e.type, e.data || {});
    }
    return s;
  }

  // Son 5 eylem + "şu an: ..." satırı (düz metin; DOM bu satırları çizer)
  function actionLines(state) {
    const lines = ((state && state.log) || []).map((e) => String(e.text || ""));
    const now = describe(state || initial());
    return { lines, now: `şu an: ${now}` };
  }

  const api = {
    initial,
    reduce,
    zoneFor,
    isTestCommand,
    isMcpTool,
    describe,
    countersText,
    shortCounters,
    formatTokens,
    totalTokens,
    contextPercent,
    metricLines,
    formatDuration,
    actionLines,
    approvalLine,
    replayState,
    SHORT_MAX,
    areaName,
    MAX_LOG,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.OfficeLogic = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
