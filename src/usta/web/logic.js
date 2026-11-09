// Usta web arayüzü: DOM'dan bağımsız saf mantık (node ile test edilir).
(function (root) {
  "use strict";

  // --- SSE ayrıştırıcı: fetch akışından gelen parçaları olaylara çevirir ---
  function createSSEParser(onEvent) {
    let buf = "";
    let cur = { id: null, event: null, data: [] };

    function line(l) {
      if (l === "") {
        if (cur.data.length) {
          onEvent({ id: cur.id, event: cur.event || "message", data: cur.data.join("\n") });
        }
        cur = { id: null, event: null, data: [] };
        return;
      }
      if (l[0] === ":") return; // yorum / keepalive
      const i = l.indexOf(":");
      const field = i < 0 ? l : l.slice(0, i);
      let value = i < 0 ? "" : l.slice(i + 1);
      if (value[0] === " ") value = value.slice(1);
      if (field === "id") cur.id = value;
      else if (field === "event") cur.event = value;
      else if (field === "data") cur.data.push(value);
    }

    return {
      feed(chunk) {
        buf += chunk;
        for (;;) {
          const m = /\r\n|\n|\r/.exec(buf);
          if (!m) return;
          // Sonda tek \r varsa, devamında \n gelebilir: bekle.
          if (m[0] === "\r" && m.index === buf.length - 1) return;
          const l = buf.slice(0, m.index);
          buf = buf.slice(m.index + m[0].length);
          line(l);
        }
      },
    };
  }

  // --- unified diff ayrıştırıcı ---
  function stripPrefix(name) {
    return name.replace(/^[ab]\//, "");
  }

  function parseDiff(text) {
    const lines = text.split("\n");
    const files = [];
    let file = null;
    let old = 0;
    let nw = 0;
    const newFile = (name, status) => {
      file = { name, status, lines: [], stats: { add: 0, del: 0 } };
      files.push(file);
    };
    for (let i = 0; i < lines.length; i++) {
      const l = lines[i];
      if (file && (old > 0 || nw > 0)) {
        const c = l[0];
        if (c === "-") { old--; file.stats.del++; file.lines.push({ kind: "del", text: l.slice(1) }); continue; }
        if (c === "+") { nw--; file.stats.add++; file.lines.push({ kind: "add", text: l.slice(1) }); continue; }
        if (c === "\\") { file.lines.push({ kind: "meta", text: l.slice(1).trim() }); continue; }
        old--; nw--; file.lines.push({ kind: "ctx", text: l.slice(1) });
        continue;
      }
      let m;
      if ((m = /^Binary files (.+) and (.+) differ$/.exec(l))) {
        const pick = m[2] !== "/dev/null" ? m[2] : m[1];
        newFile(stripPrefix(pick), "binary");
      } else if (l.startsWith("--- ") && (lines[i + 1] || "").startsWith("+++ ")) {
        const a = l.slice(4);
        const b = lines[i + 1].slice(4);
        if (a === "/dev/null") newFile(stripPrefix(b), "added");
        else if (b === "/dev/null") newFile(stripPrefix(a), "deleted");
        else newFile(stripPrefix(b), "modified");
        i++;
      } else if ((m = /^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@/.exec(l)) && file) {
        old = m[1] === undefined ? 1 : Number(m[1]);
        nw = m[2] === undefined ? 1 : Number(m[2]);
        file.lines.push({ kind: "hunk", text: l });
      } else if (l[0] === "\\" && file) {
        file.lines.push({ kind: "meta", text: l.slice(1).trim() });
      }
    }
    return files;
  }

  // --- olay özeti: akışta nasıl gösterileceği ---
  const MAX_BODY = 1000;

  function clip(s) {
    s = String(s == null ? "" : s);
    return s.length > MAX_BODY ? s.slice(0, MAX_BODY) + `\n… [kırpıldı: ${s.length} karakter]` : s;
  }

  function brief(args) {
    args = args || {};
    return args.path || args.command || args.query || args.url || "";
  }

  function formatTokens(n) {
    n = Number(n);
    if (!Number.isFinite(n) || n <= 0) return "0";
    const f = (v, unit) => v.toFixed(1).replace(".", ",").replace(/,0$/, "") + unit;
    if (n >= 1e6) return f(n / 1e6, "M");
    if (n >= 1e3) return f(n / 1e3, "K");
    return String(Math.round(n));
  }

  function usageText(u, windowSize) {
    if (!u) return null;
    const total = (u.prompt || 0) + (u.completion || 0);
    const cache = u.cached > 0 && u.prompt > 0 ? `, önbellek %${Math.round((u.cached / u.prompt) * 100)}` : "";
    const text = `${formatTokens(total)} token (girdi ${formatTokens(u.prompt)}${cache}, çıktı ${formatTokens(u.completion)}) · ${u.requests || 0} istek`;
    const ctx = u.context || 0;
    if (!ctx) return { text, context: "", pct: null };
    if (!windowSize) return { text, context: `bağlam ${formatTokens(ctx)}`, pct: null };
    const pct = Math.min(100, Math.round((ctx / windowSize) * 100));
    return { text, context: `bağlam ${formatTokens(ctx)} / ${formatTokens(windowSize)} (%${pct})`, pct };
  }

  function summarize(type, d) {
    d = d || {};
    switch (type) {
      case "message":
        return { kind: "assistant", title: "", body: d.content || "" };
      case "user_message":
        return { kind: "user", title: "", body: d.text };
      case "tool_call":
        return { kind: "tool", title: `${d.tool} ${brief(d.args)}`.trim(), body: clip(JSON.stringify(d.args, null, 2)) };
      case "tool_result":
        return { kind: "result", title: d.tool || "", body: clip(d.result) };
      case "denied":
        return { kind: "warn", title: `Reddedildi: ${d.tool}`, body: "" };
      case "usage":
        return { kind: "usage", title: "", body: "" };
      case "warning":
        return { kind: "warn", title: String(d.message || "Uyarı").slice(0, 300), body: "" };
      case "approval_required":
        return { kind: "approval", title: `Onay gerekli: ${d.tool}`, body: (d.reason ? `Neden: ${clip(String(d.reason), 300)}\n` : "") + clip(JSON.stringify(d.args, null, 2), 20000), approvalId: d.approval_id };
      case "done":
        if (d.status === "failed") return { kind: "error", title: "Görev başarısız", body: d.error || "" };
        if (d.status === "cancelled") return { kind: "status", title: "Durduruldu", body: "" };
        return { kind: "status", title: "Bitti", body: "" };
      case "started":
        return { kind: "meta", title: "Görev başladı", body: "" };
      case "reverted":
        return { kind: "status", title: "Değişiklikler geri alındı", body: "" };
      default:
        return { kind: "meta", title: type, body: "" };
    }
  }

  function isActive(status) {
    return status === "running" || status === "awaiting_approval" || status === "cancelling";
  }

  // Otomatik arayüz ölçeği: 1920x1080 ve altı 1.0; daha büyük pencerede (ultra geniş, 4K) orantılı büyür.
  function autoScale(width, height) {
    const s = Math.min(width / 1920, height / 1080);
    if (!Number.isFinite(s) || s <= 1) return 1;
    return Math.min(2, Math.round(s * 20) / 20);
  }

  function authHeaders(token) {
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  // Servisler ses, görsel ve gömme modellerini de listeler; kodsuz biri yanlışını seçmesin.
  // Süzme tümünü eliyorsa tam liste döner. `prefer` (öneri) varsa başa alınır.
  const NOT_CHAT = /(embed|tts|image|imagen|veo|audio|whisper|dall-e|moderation|transcribe|realtime|live|aqa|robotics)/i;
  function chatModels(models, prefer) {
    const chat = models.filter((m) => !NOT_CHAT.test(m));
    const list = chat.length ? chat : models.slice();
    const bare = (m) => m.replace(/^models\//, "");
    const i = prefer ? list.findIndex((m) => bare(m) === prefer) : -1;
    if (i > 0) list.unshift(list.splice(i, 1)[0]);
    return list;
  }

  const api = { chatModels, autoScale, createSSEParser, parseDiff, summarize, isActive, authHeaders, formatTokens, usageText };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.UstaLogic = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
