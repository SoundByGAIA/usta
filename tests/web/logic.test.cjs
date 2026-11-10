const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const L = require(path.resolve(__dirname, "../../src/usta/web/logic.js"));

function collect(chunks) {
  const out = [];
  const p = L.createSSEParser((e) => out.push(e));
  for (const c of chunks) p.feed(c);
  return out;
}

test("sse: tek olay", () => {
  assert.deepEqual(collect(['id: 3\nevent: message\ndata: {"a":1}\n\n']), [
    { id: "3", event: "message", data: '{"a":1}' },
  ]);
});

test("sse: olay parçalara bölünse de birleşir", () => {
  const whole = 'id: 1\nevent: done\ndata: {"x":"ü"}\n\n';
  for (let cut = 1; cut < whole.length; cut++) {
    const got = collect([whole.slice(0, cut), whole.slice(cut)]);
    assert.equal(got.length, 1, `kesim ${cut}`);
    assert.equal(got[0].event, "done");
  }
});

test("sse: CRLF, yorum (keepalive) ve çoklu data satırı", () => {
  const got = collect([": keepalive\r\n\r\nevent: m\r\ndata: a\r\ndata: b\r\n\r\n"]);
  assert.deepEqual(got, [{ id: null, event: "m", data: "a\nb" }]);
});

test("sse: yalnız yorumdan olay çıkmaz; yarım olay bekler", () => {
  assert.deepEqual(collect([": x\n\n"]), []);
  assert.deepEqual(collect(["event: a\ndata: 1\n"]), []);
});

test("sse: ardışık olaylar", () => {
  const got = collect(["event: a\ndata: 1\n\nevent: b\ndata: 2\n\n"]);
  assert.deepEqual(got.map((e) => e.event), ["a", "b"]);
});

const DIFF = [
  "--- a/a.txt", "+++ b/a.txt", "@@ -1,2 +1,2 @@", " bir", "-iki", "+2",
  "--- /dev/null", "+++ b/yeni.py", "@@ -0,0 +1 @@", "+print(1)",
  "--- a/sil.txt", "+++ /dev/null", "@@ -1 +0,0 @@", "-gidecek",
  "Binary files a/b.bin and b/b.bin differ",
  "",
].join("\n");

test("diff: dosyalar ve durumlar", () => {
  const files = L.parseDiff(DIFF);
  assert.deepEqual(files.map((f) => [f.name, f.status]), [
    ["a.txt", "modified"], ["yeni.py", "added"], ["sil.txt", "deleted"], ["b.bin", "binary"],
  ]);
});

test("diff: satır türleri", () => {
  const f = L.parseDiff(DIFF)[0];
  assert.deepEqual(f.lines.map((l) => l.kind), ["hunk", "ctx", "del", "add"]);
  assert.equal(f.lines[2].text, "iki");
  assert.deepEqual(L.parseDiff(DIFF)[0].stats, { add: 1, del: 1 });
});

test("diff: boş girdi", () => {
  assert.deepEqual(L.parseDiff(""), []);
});

test("diff: '+++' ile başlayan içerik satırı dosya başlığı sanılmaz", () => {
  const d = ["--- a/x", "+++ b/x", "@@ -1 +1 @@", "-a", "+++ b", ""].join("\n");
  const f = L.parseDiff(d);
  assert.equal(f.length, 1);
  assert.deepEqual(f[0].lines.map((l) => l.kind), ["hunk", "del", "add"]);
});

test("diff: 'Dosya sonu satırı yok' notu meta olur", () => {
  const d = ["--- a/x", "+++ b/x", "@@ -1 +1 @@", "-a", "+b", "\\ Dosya sonu satırı yok", ""].join("\n");
  assert.equal(L.parseDiff(d)[0].lines.at(-1).kind, "meta");
});

test("özet: mesaj, araç, red, onay, bitiş", () => {
  assert.deepEqual(L.summarize("message", { content: "selam" }), { kind: "assistant", title: "", body: "selam" });
  const tc = L.summarize("tool_call", { tool: "write_file", args: { path: "a.py", content: "x" } });
  assert.equal(tc.kind, "tool"); assert.match(tc.title, /write_file/); assert.match(tc.title, /a\.py/);
  assert.equal(L.summarize("denied", { tool: "run" }).kind, "warn");
  const ap = L.summarize("approval_required", { approval_id: "z", tool: "web_search", args: { query: "q" } });
  assert.equal(ap.kind, "approval"); assert.equal(ap.approvalId, "z");
  assert.equal(L.summarize("done", { status: "cancelled", answer: "" }).kind, "status");
  assert.equal(L.summarize("done", { status: "failed", error: "model isteği başarısız" }).kind, "error");
  assert.equal(L.summarize("bilinmeyen", {}).kind, "meta");
});

test("özet: uzun araç sonucu kırpılır, tam metin kaybolmaz uyarısı", () => {
  const s = L.summarize("tool_result", { tool: "read_file", result: "x".repeat(5000) });
  assert.ok(s.body.length < 1500 && s.body.includes("kırpıldı"));
});

test("durum etiketleri", () => {
  assert.equal(L.isActive("running"), true);
  assert.equal(L.isActive("awaiting_approval"), true);
  assert.equal(L.isActive("cancelling"), true);
  assert.equal(L.isActive("done"), false);
  assert.equal(L.isActive("failed"), false);
});

test("jeton başlığı", () => {
  assert.deepEqual(L.authHeaders("abc"), { Authorization: "Bearer abc" });
  assert.deepEqual(L.authHeaders(""), {});
});

test("uyarı olayı (ör. MCP sunucusu başlamadı) uyarı olarak görünür", () => {
  const s = L.summarize("warning", { message: "MCP sunucusu 'x' başlatılamadı: komut bulunamadı" });
  assert.equal(s.kind, "warn");
  assert.ok(s.title.includes("komut bulunamadı"));
  assert.equal(L.summarize("warning", {}).title, "Uyarı");
  assert.ok(L.summarize("warning", { message: "a".repeat(1000) }).title.length <= 300);
});

test("token biçimlendirme", () => {
  assert.equal(L.formatTokens(0), "0");
  assert.equal(L.formatTokens(812), "812");
  assert.equal(L.formatTokens(1234), "1,2K");
  assert.equal(L.formatTokens(15600), "15,6K");
  assert.equal(L.formatTokens(2500000), "2,5M");
  assert.equal(L.formatTokens(-5), "0");
  assert.equal(L.formatTokens("x"), "0");
});

test("token sayacı metni ve bağlam doluluğu", () => {
  const u = { prompt: 11000, completion: 1300, requests: 4, context: 4100 };
  const a = L.usageText(u, null);
  assert.equal(a.text, "12,3K token (girdi 11K, çıktı 1,3K) · 4 istek");
  assert.equal(a.context, "bağlam 4,1K");
  assert.equal(a.pct, null);
  const b = L.usageText(u, 8192);
  assert.equal(b.context, "bağlam 4,1K / 8,2K (%50)");
  assert.equal(b.pct, 50);
  assert.equal(L.usageText({ ...u, context: 7000 }, 8192).pct, 85);
  assert.equal(L.usageText({ ...u, context: 99999 }, 8192).pct, 100);
  assert.equal(L.usageText(null, 8192), null);
});

test("usage olayı akışa düğüm eklemez, özet türü usage", () => {
  assert.equal(L.summarize("usage", { prompt: 1, completion: 1, requests: 1, context: 1 }).kind, "usage");
});

test("autoScale: küçük pencere 1, büyük ekran orantılı, üst sınır 2", () => {
  assert.equal(L.autoScale(1366, 768), 1);
  assert.equal(L.autoScale(1920, 1080), 1);
  assert.equal(L.autoScale(2560, 1440), 1.35);
  assert.equal(L.autoScale(3440, 1300), 1.2);
  assert.equal(L.autoScale(3840, 2160), 2);
  assert.equal(L.autoScale(7680, 4320), 2);
  assert.equal(L.autoScale(0, 0), 1);
  assert.equal(L.autoScale(NaN, 900), 1);
});

test("chatModels drops audio/image/embedding models and puts the preferred one first", () => {
  const all = ["models/gemini-2.5-flash-preview-tts", "models/gemini-2.5-pro", "models/gemini-2.5-flash",
    "models/gemini-2.5-flash-image", "models/text-embedding-004", "models/gemini-2.0-flash-live-001"];
  assert.deepEqual(L.chatModels(all, "gemini-2.5-flash"), ["models/gemini-2.5-flash", "models/gemini-2.5-pro"]);
  assert.deepEqual(L.chatModels(all, ""), ["models/gemini-2.5-pro", "models/gemini-2.5-flash"]);
});

test("chatModels falls back to the full list when filtering removes everything", () => {
  assert.deepEqual(L.chatModels(["a-embed", "b-tts"], ""), ["a-embed", "b-tts"]);
  assert.deepEqual(L.chatModels([], "x"), []);
});

test("plainApproval turns tool calls into plain Turkish sentences", () => {
  assert.match(L.plainApproval("write_file", { path: "index.html" }).title, /"index.html" dosyasını yazmak istiyor/);
  assert.match(L.plainApproval("edit_file", { path: "a.css" }).title, /"a.css" dosyasında değişiklik/);
  assert.match(L.plainApproval("run", { command: "pytest -q" }).title, /komutu çalıştırmak istiyor: pytest -q/);
  assert.match(L.plainApproval("fetch_url", { url: "https://x.test/" }).title, /internet sayfasını okumak/);
  assert.match(L.plainApproval("mcp__arac__ara", {}).title, /ek araç/);
  assert.match(L.plainApproval("bilinmeyen", null).title, /"bilinmeyen" işlemini/);
  assert.equal(L.plainApproval("write_file", { path: "x" }).warn, "");
});

test("plainApproval explains the taint-gate reason and never throws on odd input", () => {
  const w = L.plainApproval("write_file", { path: "leak.txt" }, "hedef 'leak.txt' okunan içerikte geçiyor ama isteğinde geçmiyor").warn;
  assert.match(w, /Emin değilsen Reddet/);
  assert.match(L.plainApproval("run", { command: "x" }, "başka bir neden").warn, /Neden soruyor/);
  assert.doesNotThrow(() => L.plainApproval(undefined, undefined, undefined));
});

test("friendlyModelError maps common service failures to plain sentences", () => {
  assert.match(L.friendlyModelError("model isteği başarısız: HTTP 401"), /Anahtar kabul edilmedi/);
  assert.match(L.friendlyModelError("model isteği başarısız: HTTP 402"), /bakiye yok/);
  assert.match(L.friendlyModelError("model isteği başarısız: HTTP 429"), /ücretsiz hakkın doldu/);
  assert.match(L.friendlyModelError("model isteği başarısız: ConnectError"), /ulaşılamıyor/);
  assert.equal(L.friendlyModelError("başka bir hata"), "başka bir hata");
});

test("summarize shows friendly text for failed tasks and carries approval details", () => {
  const f = L.summarize("done", { status: "failed", error: "model isteği başarısız: HTTP 429" });
  assert.equal(f.kind, "error"); assert.match(f.body, /ücretsiz hakkın doldu/);
  const ap = L.summarize("approval_required", { approval_id: "z", tool: "run", args: { command: "ls" }, reason: "r" });
  assert.equal(ap.tool, "run"); assert.deepEqual(ap.args, { command: "ls" }); assert.equal(ap.reason, "r");
});

test("plainProgress describes tool calls in plain Turkish for the simple view", () => {
  assert.equal(L.plainProgress("write_file", { path: "index.html" }), "Dosya yazılıyor: index.html");
  assert.equal(L.plainProgress("edit_file", { path: "a.css" }), "Dosya düzenleniyor: a.css");
  assert.equal(L.plainProgress("list_dir", {}), "Klasör inceleniyor");
  assert.equal(L.plainProgress("run", { command: "x" }), "Komut çalıştırılıyor");
  assert.equal(L.plainProgress("mcp__x__y", {}), "Ek araç kullanılıyor");
  assert.doesNotThrow(() => L.plainProgress(undefined, undefined));
  const tc = L.summarize("tool_call", { tool: "write_file", args: { path: "p.txt" } });
  assert.equal(tc.tool, "write_file"); assert.deepEqual(tc.args, { path: "p.txt" });
});

// --- Sözlük (5 yaşındaki çocuğa göre) ---
const G = require(path.resolve(__dirname, "../../src/usta/web/glossary.js"));

test("sözlük: her terimin açıklaması ve benzetmesi var, kısa ve tekrarsız", () => {
  const seen = new Set();
  for (const t of G.TERMS) {
    assert.ok(t.term && t.say && t.like, `eksik alan: ${t.term}`);
    assert.ok(t.say.length <= 230, `uzun açıklama: ${t.term}`);
    assert.ok(!seen.has(t.term.toLocaleLowerCase("tr")), `yinelenen terim: ${t.term}`);
    seen.add(t.term.toLocaleLowerCase("tr"));
  }
  for (const must of ["JSON", "Docker", "Ollama", "API anahtarı", "Token", "Model", "Terminal"]) {
    assert.ok(G.TERMS.some((t) => t.term === must), `eksik terim: ${must}`);
  }
});

test("sözlük: arama ad, takma ad ve açıklamada bulur; ad eşleşmesi önde", () => {
  assert.equal(G.search("json")[0].term, "JSON");
  assert.equal(G.search("DOCKER")[0].term, "Docker");
  assert.equal(G.search("ctx")[0].term, "Bağlam penceresi");
  assert.equal(G.search("siyah pencere")[0].term, "Terminal");
  assert.equal(G.search("yapay zeka")[0].term, "Yapay zekâ"); // aksansız yazım takma adla bulunur
  assert.deepEqual(G.search("zzzzqqq"), []);
  assert.equal(G.search("").length, G.TERMS.length);
});
