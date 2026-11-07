// Ofis sekmesi regresyon testleri. Node yoksa test_web.py bu dosyayı atlar ("node yok").
// Çalıştırmak için: node --test tests/web/*.test.cjs
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const O = require(path.resolve(__dirname, "../../src/usta/web/office-logic.js"));

function run(events, from) {
  let s = from || O.initial();
  for (const [type, data] of events) s = O.reduce(s, type, data);
  return s;
}

test("initial: sayaçlar sıfır, bekliyor", () => {
  const s = O.initial();
  assert.deepEqual(s.counts, { tool_calls: 0, edits: 0, tests_pass: 0, tests_fail: 0 });
  assert.equal(s.status, "idle");
  assert.equal(s.target, "desk");
  assert.equal(s.hand, false);
  assert.deepEqual(s.log, []);
});

test("araç → bölge: okuma araçları Kitaplık", () => {
  for (const tool of ["read_file", "list_dir", "outline", "read_symbol", "find_symbol", "symbol_context", "related_files"]) {
    assert.equal(O.zoneFor(tool, { path: "a.py" }), "library", tool);
  }
});

test("araç → bölge: yazma Atölye, run test/komut ayrımı", () => {
  assert.equal(O.zoneFor("write_file", { path: "a" }), "workshop");
  assert.equal(O.zoneFor("edit_file", { path: "a" }), "workshop");
  assert.equal(O.zoneFor("run", { command: "ls -la" }), "workshop");
  assert.equal(O.zoneFor("run", { command: "python3 -m pytest -q" }), "testbench");
  assert.equal(O.zoneFor("run", { command: "python -m unittest" }), "testbench");
  assert.equal(O.zoneFor("run", { command: "npm test" }), "testbench");
  assert.equal(O.zoneFor("run", { command: "npx jest" }), "testbench");
  assert.equal(O.zoneFor("run", {}), "workshop");
});

test("araç → bölge: fetch_url ve MCP Postane, remember Hafıza dolabı", () => {
  assert.equal(O.zoneFor("fetch_url", { url: "https://example.com" }), "post");
  assert.equal(O.zoneFor("mcp__sunucu__arac", {}), "post");
  assert.equal(O.zoneFor("some_mcp_tool", {}), "post");
  assert.equal(O.zoneFor("remember", { text: "x" }), "memory");
});

test("tool_call karakteri yürütür, gerçek sayacı artırır, balona dosya adını yazar", () => {
  const s = run([["started", { task: "t1", mode: "manual" }], ["tool_call", { tool: "read_file", args: { path: "src/a.py" } }]]);
  assert.equal(s.zone, "library");
  assert.equal(s.target, "library");
  assert.equal(s.counts.tool_calls, 1);
  assert.equal(s.counts.edits, 0);
  assert.match(s.bubble, /a\.py/);
  assert.equal(s.status, "running");
});

test("düzenleme sayacı yalnız write_file/edit_file ile artar", () => {
  const s = run([
    ["started", {}],
    ["tool_call", { tool: "read_file", args: { path: "a" } }],
    ["tool_call", { tool: "write_file", args: { path: "a" } }],
    ["tool_call", { tool: "edit_file", args: { path: "a" } }],
  ]);
  assert.equal(s.counts.edits, 2);
  assert.equal(s.counts.tool_calls, 3);
  assert.equal(s.counts.tests_pass + s.counts.tests_fail, 0);
  assert.equal(s.zone, "workshop");
});

test("onay isteği: el kaldırır, ne istediğini yazar, sayaç uydurmaz", () => {
  const before = run([["started", {}], ["tool_call", { tool: "run", args: { command: "pytest" } }]]);
  const s = O.reduce(before, "approval_required", { approval_id: "x1", tool: "run", args: { command: "pytest" } });
  assert.equal(s.hand, true);
  assert.equal(s.status, "awaiting");
  assert.match(s.bubble, /run/);
  assert.equal(s.counts.tool_calls, before.counts.tool_calls);
  assert.match(O.describe(s), /onay/);
});

test("oto onay eli indirir; red kırmızı ünlem balonu üretir", () => {
  const asked = run([["started", {}], ["approval_required", { approval_id: "a", tool: "fetch_url", args: {} }]]);
  const ok = O.reduce(asked, "auto_approved", { tool: "fetch_url", args: {} });
  assert.equal(ok.hand, false);
  const no = O.reduce(asked, "denied", { tool: "fetch_url" });
  assert.equal(no.hand, false);
  assert.equal(no.bubbleKind, "alarm");
  assert.match(no.bubble, /Reddedildi/);
});

test("done: bitti (mutlu), başarısız (üzgün), iptal", () => {
  const base = run([["started", {}], ["message", { content: "merhaba" }]]);
  const ok = O.reduce(base, "done", { status: "done", answer: "tamam" });
  assert.equal(ok.status, "done");
  assert.equal(ok.mood, "happy");
  const bad = O.reduce(base, "done", { status: "failed", error: "model isteği başarısız" });
  assert.equal(bad.status, "failed");
  assert.equal(bad.mood, "sad");
  const stop = O.reduce(base, "done", { status: "cancelled" });
  assert.equal(stop.status, "cancelled");
  assert.match(O.describe(ok), /bitirdi|tamamlandı/i);
});

test("test geçti/kaldı yalnız gerçek test komutu sonucundan artar (tool_result args taşımaz)", () => {
  // Gerçek olay biçimi: tool_result yalnız {tool, result} taşır; komut önceki tool_call'dan öğrenilir.
  const call = (cmd) => ["tool_call", { tool: "run", args: { command: cmd } }];
  const res = (txt) => ["tool_result", { tool: "run", result: txt }];
  let s = run([["started", {}], call("pytest -q"), res("exit_code: 0\n3 passed")]);
  assert.deepEqual([s.counts.tests_pass, s.counts.tests_fail], [1, 0]);
  s = run([call("pytest -q"), res("exit_code: 1\n1 failed")], s);
  assert.deepEqual([s.counts.tests_pass, s.counts.tests_fail], [1, 1]);
  s = run([call("ls"), res("exit_code: 0")], s);
  assert.deepEqual([s.counts.tests_pass, s.counts.tests_fail], [1, 1], "test olmayan komut sayılmaz");
  s = run([res("exit_code: 0\nok")], s);
  assert.deepEqual([s.counts.tests_pass, s.counts.tests_fail], [1, 1], "önceki çağrı yoksa sayılmaz");
  s = run([["tool_call", { tool: "read_file", args: { path: "a" } }], res("exit_code: 0")], s);
  assert.deepEqual([s.counts.tests_pass, s.counts.tests_fail], [1, 1], "araç adı uyuşmazsa sayılmaz");
});

test("usage olayı ofis sayaçlarını değiştirmez", () => {
  const s = run([["started", {}], ["usage", { prompt: 100, completion: 50, requests: 1, context: 10 }]]);
  assert.deepEqual(s.counts, { tool_calls: 0, edits: 0, tests_pass: 0, tests_fail: 0 });
});

test("bilinmeyen olay durumu bozmaz", () => {
  const s = run([["started", {}], ["tool_call", { tool: "write_file", args: { path: "a.py" } }], ["approval_required", { tool: "run" }]]);
  for (const type of ["bilinmeyen", "compact", "", "compacted", "breaker", "tool_call_unknown"]) {
    // bilinmeyen olay yalnız üretim numarasını (fx.seq) ilerletir; başka hiçbir alan değişmez
    const same = (r) => assert.deepEqual({ ...r, fx: { ...r.fx, seq: 0 } }, { ...s, fx: { ...s.fx, seq: 0 } }, type);
    same(O.reduce(s, type, { x: 1 }));
    same(O.reduce(s, type, undefined));
  }
});

test("aynı olay dizisi aynı durumu üretir; girdi durumu değişmez", () => {
  const events = [
    ["started", { task: "t", mode: "auto" }],
    ["user_message", { text: "testleri çalıştır" }],
    ["tool_call", { tool: "run", args: { command: "python3 -m pytest" } }],
    ["auto_approved", { tool: "run", args: { command: "python3 -m pytest" } }],
    ["tool_result", { tool: "run", result: "exit_code: 0", args: { command: "python3 -m pytest" } }],
    ["message", { content: "Testler geçti." }],
    ["done", { status: "done" }],
  ];
  const s0 = O.initial();
  const a = run(events);
  const b = run(events);
  assert.deepEqual(a, b);
  assert.deepEqual(s0, O.initial());
  assert.equal(a.counts.tool_calls, 1);
  assert.equal(a.counts.tests_pass, 1);
  assert.equal(a.status, "done");
});

test("günlük son 5 eylemle sınırlı", () => {
  const events = [["started", {}]];
  for (let i = 0; i < 9; i++) events.push(["tool_call", { tool: "read_file", args: { path: `f${i}.py` } }]);
  const s = run(events);
  assert.equal(s.log.length, 5);
  assert.match(s.log[4].text, /f8\.py/);
});

test("fx: initial tetikleyici yok, seq 0, idle false", () => {
  const s = O.initial();
  assert.deepEqual(s.fx, { seq: 0, test: "", testSeq: 0, end: "", endSeq: 0 });
  assert.equal(s.idle, false);
});

test("fx.test: yalnız gerçek test sonucu tetikler (geçti=pass, kaldı=fail)", () => {
  const call = (cmd) => ["tool_call", { tool: "run", args: { command: cmd } }];
  const res = (txt) => ["tool_result", { tool: "run", result: txt }];
  const pass = run([["started", {}], call("pytest -q"), res("exit_code: 0\n3 passed")]);
  assert.equal(pass.fx.test, "pass");
  assert.ok(pass.fx.testSeq > 0);
  const fail = run([call("pytest -q"), res("exit_code: 1\n1 failed")], pass);
  assert.equal(fail.fx.test, "fail");
  assert.ok(fail.fx.testSeq > pass.fx.testSeq, "her gerçek sonuç yeni tetikleyici üretir");
  // test olmayan komut ve zaman aşımı tetiklemez
  const before = fail.fx;
  const other = run([call("ls"), res("exit_code: 0")], fail);
  assert.deepEqual([other.fx.test, other.fx.testSeq], [before.test, before.testSeq]);
  const timeout = run([call("pytest"), res("exit_code: 124 (zaman aşımı)")], fail);
  assert.deepEqual([timeout.fx.test, timeout.fx.testSeq], [before.test, before.testSeq]);
  assert.equal(timeout.counts.tests_pass + timeout.counts.tests_fail, 2, "zaman aşımı sayılmaz");
});

test("fx.end: done olayının gerçek sonucunu taşır; done yoksa boş kalır", () => {
  const base = run([["started", {}]]);
  assert.equal(base.fx.end, "");
  for (const [status, expect] of [["done", "done"], ["failed", "failed"], ["cancelled", "cancelled"], [undefined, "done"]]) {
    const s = O.reduce(base, "done", { status });
    assert.equal(s.fx.end, expect);
    assert.ok(s.fx.endSeq > base.fx.seq, "tetikleyici yayınlandıktan sonraki seq'i taşır");
  }
});

test("fx.seq her olayda artar; bilinmeyen olay da tek adım ilerletir", () => {
  let s = O.initial();
  let prev = s.fx.seq;
  for (const type of ["started", "tool_call", "bilinmeyen", "usage", "done"]) {
    s = O.reduce(s, type, { tool: "read_file", args: { path: "a" }, command: "ls" });
    assert.equal(s.fx.seq, prev + 1, type);
    prev = s.fx.seq;
  }
});

test("idle yalnız görev yokken/bitmişken true: çalışırken ve model konuşurken false", () => {
  assert.equal(O.initial().idle, false);
  let s = run([["started", {}]]);
  assert.equal(s.idle, false, "çalışırken boşta değil");
  s = O.reduce(s, "message", { content: "düşünüyorum" });
  assert.equal(s.idle, false, "model konuşurken boşta değil");
  s = O.reduce(s, "tool_call", { tool: "read_file", args: { path: "a" } });
  assert.equal(s.idle, false);
  s = O.reduce(s, "done", { status: "done" });
  assert.equal(s.idle, true, "bittikten sonra boş zaman");
  s = O.reduce(s, "user_message", { text: "yeni iş" });
  assert.equal(s.idle, false, "yeni mesajla boş zaman biter");
});

test("shortCounters kısa biçim: 'A:2  D:1  T:0/0' ve tahtaya sığar", () => {
  const s = run([["started", {}], ["tool_call", { tool: "read_file", args: { path: "a" } }], ["tool_call", { tool: "edit_file", args: { path: "a" } }]]);
  assert.equal(O.shortCounters(s), "A:2  D:1  T:0/0"); // okuma + düzenleme = 2 araç çağrısı, 1 düzenleme
  const big = run([["started", {}]]);
  const wide = O.shortCounters({ counts: { tool_calls: 123, edits: 456, tests_pass: 78, tests_fail: 90 } });
  assert.equal(wide, "A:123 D:456 T:78/90", "dar alanda iki boşluk yerine tek boşluk");
  assert.ok(wide.length <= O.SHORT_MAX && O.SHORT_MAX <= 19, "tahta iç alanı ≤19 karakter");
  assert.equal(
    O.shortCounters({ counts: { tool_calls: 1234, edits: 5678, tests_pass: 9999, tests_fail: 1000 } }),
    "A:999+ D:999+",
    "hâlâ uzunsa sayılar 999+ ile kısaltılır ve test sayacı düşer"
  );
  const huge = O.shortCounters({ counts: { tool_calls: 1e9, edits: 1e9, tests_pass: 1e9, tests_fail: 1e9 } });
  assert.ok(huge.length <= 19, "kısaltma da tahtaya sığar (" + huge + ")");
  assert.equal(O.shortCounters(big), "A:0  D:0  T:0/0");
});

test("reduce saf: aynı olay dizisi (efekt alanları dahil) aynı durumu üretir", () => {
  const events = [
    ["started", {}],
    ["tool_call", { tool: "run", args: { command: "pytest" } }],
    ["tool_result", { tool: "run", result: "exit_code: 1\n1 failed" }],
    ["tool_call", { tool: "edit_file", args: { path: "a.py" } }],
    ["tool_result", { tool: "run", result: "exit_code: 0\nok" }],
    ["done", { status: "failed", error: "x" }],
  ];
  const a = run(events);
  const b = run(events);
  assert.deepEqual(a, b);
  assert.deepEqual(a.fx, { seq: 6, test: "fail", testSeq: 3, end: "failed", endSeq: 6 });
  assert.equal(a.counts.tests_fail, 1, "araç adı uyuşmayan tool_result sayılmaz");
  // girdi durumu paylaşılan referansla değiştirilmez
  const base = run(events.slice(0, 1));
  const snapshot = JSON.stringify(base);
  O.reduce(base, "done", { status: "done" });
  assert.equal(JSON.stringify(base), snapshot);
});

test("erişilebilirlik metni bölgeyi düz yazıyla söyler", () => {
  const s = run([["started", {}], ["tool_call", { tool: "edit_file", args: { path: "app.js" } }]]);
  assert.equal(O.describe(s), "Usta Atölye'de çalışıyor");
  assert.match(O.describe(O.initial()), /bekliyor/);
  assert.match(O.countersText(s), /araç 1/);
});

// --- tur B1: kullanım (usage) alanı + gösterge biçimleme yardımcıları ---

test("usage: son anlık görüntü saklanır, sayaçlara dokunmaz", () => {
  const u = { prompt: 1200, completion: 340, requests: 3, cached: 900, context: 2048 };
  const s = run([["started", {}], ["usage", u]]);
  assert.deepEqual(s.usage, u);
  assert.deepEqual(s.counts, { tool_calls: 0, edits: 0, tests_pass: 0, tests_fail: 0 }, "tool/edit/test sayaçları değişmez");
  // sonraki usage öncekinin üzerine yazılır (anlık görüntü, birikim değil)
  const s2 = O.reduce(s, "usage", { prompt: 10, completion: 2, requests: 1, context: 0 });
  assert.deepEqual(s2.usage, { prompt: 10, completion: 2, requests: 1, cached: 0, context: 0 });
  assert.deepEqual(s2.counts, s.counts);
});

test("usage araç/düzenleme/test sayaçlarını etkilemez (gerçek olaylarla aynı dizide)", () => {
  const events = [
    ["started", {}],
    ["tool_call", { tool: "edit_file", args: { path: "a.py" } }],
    ["tool_call", { tool: "run", args: { command: "pytest -q" } }],
    ["tool_result", { tool: "run", result: "exit_code: 0" }],
  ];
  const without = run(events);
  const withUsage = run(events.slice(0, 2).concat([["usage", { prompt: 5, completion: 5, requests: 1, context: 5 }]], events.slice(2)));
  assert.deepEqual(withUsage.counts, without.counts);
  assert.deepEqual(without.usage, null);
});

test("usage: bozuk/eksik alanlar güvenli; usage alanı taşımayan olay anlık görüntüyü silmez", () => {
  const base = run([["started", {}], ["usage", { prompt: 7, completion: 3 }]]);
  assert.deepEqual(base.usage, { prompt: 7, completion: 3, requests: 0, cached: 0, context: 0 });
  const bad = O.reduce(base, "usage", { prompt: "x", completion: -4, requests: null, context: "abc" });
  assert.deepEqual(bad.usage, { prompt: 0, completion: 0, requests: 0, cached: 0, context: 0 });
  const empty = O.reduce(bad, "usage", {});
  assert.deepEqual(empty.usage, bad.usage, "alansız usage olayı anlık görüntüyü bozmaz");
  assert.deepEqual(O.reduce(base, "usage", undefined).usage, base.usage, "veri yoksa (undefined) anlık görüntü korunur");
  assert.equal(O.initial().usage, null);
});

test("reduce saf: usage alanı dahil aynı dizi aynı durumu üretir, girdi değişmez", () => {
  const events = [
    ["started", { mode: "manual" }],
    ["usage", { prompt: 100, completion: 20, requests: 1, context: 500 }],
    ["tool_call", { tool: "read_file", args: { path: "a.py" } }],
    ["usage", { prompt: 200, completion: 30, requests: 2, context: 700, cached: 100 }],
    ["done", { status: "done" }],
  ];
  const a = run(events);
  const b = run(events);
  assert.deepEqual(a, b);
  assert.deepEqual(a.usage, { prompt: 200, completion: 30, requests: 2, cached: 100, context: 700 });
  const base = run(events.slice(0, 2));
  const snap = JSON.stringify(base);
  O.reduce(base, "usage", { prompt: 999, completion: 999, requests: 9, context: 999 });
  assert.equal(JSON.stringify(base), snap, "girdi durumu paylaşılan referansla değişmez");
});

test("süre işaretleri: runSeq started'da, endSeq done'da (saat okunmaz)", () => {
  assert.equal(O.initial().runSeq, 0);
  assert.equal(O.initial().endSeq, 0);
  const started = run([["started", {}]]);
  assert.equal(started.runSeq, started.fx.seq, "başlangıç işareti olayın sıra numarası");
  assert.equal(started.endSeq, 0);
  const running = O.reduce(started, "tool_call", { tool: "read_file", args: { path: "a" } });
  assert.equal(running.endSeq, 0, "çalışırken bitiş işareti yok → süre ilerler");
  const done = O.reduce(running, "done", { status: "done" });
  assert.equal(done.endSeq, done.fx.seq, "bitiş işareti → süre durur");
  const again = O.reduce(done, "verification", { status: "passed" });
  assert.equal(again.endSeq, done.endSeq, "ilk bitiş işareti korunur");
});

test("formatTokens: göstergeler için kısa Türkçe biçim", () => {
  assert.equal(O.formatTokens(0), "0");
  assert.equal(O.formatTokens(null), "0");
  assert.equal(O.formatTokens("x"), "0");
  assert.equal(O.formatTokens(-12), "0");
  assert.equal(O.formatTokens(9), "9");
  assert.equal(O.formatTokens(999), "999");
  assert.equal(O.formatTokens(1000), "1K", "1,0 → 1 (sondaki sıfır atılır)");
  assert.equal(O.formatTokens(1540), "1,5K");
  assert.equal(O.formatTokens(12345), "12K", "10 ve üstü tam sayıya yuvarlanır");
  assert.equal(O.formatTokens(2500000), "2,5M");
});

test("totalTokens: prompt + completion", () => {
  assert.equal(O.totalTokens(null), 0);
  assert.equal(O.totalTokens({ prompt: 100, completion: 50 }), 150);
  assert.equal(O.totalTokens({ prompt: 100 }), 100);
  assert.equal(O.totalTokens({ completion: "80" }), 80);
  assert.equal(O.totalTokens({ prompt: 0.4, completion: 0.4 }), 1, "toplam tam sayıya yuvarlanır");
});

test("contextPercent: pencere 0/bilinmiyor → null, %100 üstü 100'e kenetlenir", () => {
  assert.equal(O.contextPercent(1000, 8192), 12);
  assert.equal(O.contextPercent(4096, 8192), 50);
  assert.equal(O.contextPercent(7000, 8192), 85);
  assert.equal(O.contextPercent(99999, 8192), 100, "pencere aşımı 100'ü geçmez");
  assert.equal(O.contextPercent(100, 0), null, "pencere 0 → bilinmiyor");
  assert.equal(O.contextPercent(100, null), null);
  assert.equal(O.contextPercent(100, undefined), null);
  assert.equal(O.contextPercent(null, 8192), null, "bağlam yok → yüzde yok");
  assert.equal(O.contextPercent(-5, 8192), 0);
});

test("metricLines: Token/Bağlam/İstek; pencere yoksa bağlam yalnız sayı", () => {
  const usage = { prompt: 1200, completion: 340, requests: 3, cached: 0, context: 2000 };
  const noWin = O.metricLines(usage, 0);
  const byKey = Object.fromEntries(noWin.map((r) => [r.key, r]));
  assert.equal(byKey.token.value, "1,5K");
  assert.equal(byKey.context.value, "2K");
  assert.equal(byKey.context.pct, null);
  assert.equal(byKey.requests.value, "3");
  const withWin = Object.fromEntries(O.metricLines(usage, 8000).map((r) => [r.key, r]));
  assert.equal(withWin.context.pct, 25);
  assert.match(withWin.context.value, /%25/);
  assert.match(withWin.context.value, /2K \/ 8K/);
  const empty = Object.fromEntries(O.metricLines(null, 8000).map((r) => [r.key, r]));
  assert.equal(empty.token.value, "0");
  assert.equal(empty.context.value, "—");
  assert.equal(empty.requests.value, "0");
  const zeroCtx = Object.fromEntries(O.metricLines({ prompt: 10, completion: 0, requests: 1, context: 0 }, 8000).map((r) => [r.key, r]));
  assert.equal(zeroCtx.context.value, "—", "bağlam 0 ise yüzde uydurulmaz");
  assert.equal(zeroCtx.context.pct, null);
});

test("formatDuration: saniye → dk:sn, saat yalnız gerektiğinde", () => {
  assert.equal(O.formatDuration(0), "0:00");
  assert.equal(O.formatDuration(7), "0:07");
  assert.equal(O.formatDuration(65), "1:05");
  assert.equal(O.formatDuration(125.9), "2:05", "küsurat aşağı yuvarlanır");
  assert.equal(O.formatDuration(3725), "1:02:05");
  assert.equal(O.formatDuration(-3), "0:00");
  assert.equal(O.formatDuration("x"), "0:00");
});

test("actionLines: son 5 eylem düz metin + 'şu an: ...' satırı", () => {
  const events = [["started", {}]];
  for (let i = 0; i < 7; i++) events.push(["tool_call", { tool: "read_file", args: { path: `f${i}.py` } }]);
  const s = run(events);
  const { lines, now } = O.actionLines(s);
  assert.equal(lines.length, 5);
  assert.match(lines[4], /f6\.py$/, "araç dosya biçiminde düz satır");
  assert.match(lines[4], /^[a-z_]+ /, "satır araç adıyla başlar (düz metin)");
  assert.match(now, /^şu an: /);
  assert.ok(now.indexOf(O.describe(s)) > 0);
  const empty = O.actionLines(O.initial());
  assert.deepEqual(empty.lines, []);
  assert.match(empty.now, /bekliyor/);
});
