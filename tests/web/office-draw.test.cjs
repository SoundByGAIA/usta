// Ofis çizicisi testleri: DOM yok — office.js sahte `window` içine yüklenir, sahte 2D bağlam kullanılır.
// Yalnız GERÇEK olaylardan gelen tetikleyiciler/karakter durumları sınanır.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const WEB = path.resolve(__dirname, "../../src/usta/web");
const SRC = ["office-logic.js", "office.js"].map((f) => fs.readFileSync(path.join(WEB, f), "utf8"));

// Sahte ortam: pencere/bağlam yalnız kayıt tutar (fillRect + drawImage)
function load(opts) {
  const win = {};
  win.window = win;
  win.globalThis = win;
  win.document = { hidden: false, createElement: () => makeCanvas() };
  if (opts && opts.canvas) {
    win.document.getElementById = (id) => (id === "office-canvas" ? makeCanvas() : null);
  }
  vm.createContext(win);
  for (const code of SRC) vm.runInContext(code, win);
  return win;
}

function makeCanvas() {
  const ops = [];
  const ctx = {
    ops,
    fillStyle: "",
    imageSmoothingEnabled: false,
    fillRect() {},
    drawImage() {
      ops.push({ k: "img" });
    },
    beginPath() {},
    moveTo() {},
    lineTo() {},
    closePath() {},
    ellipse() {},
    fill() {},
  };
  const elem = {
    width: 0,
    height: 0,
    style: {},
    parentElement: null,
    getContext: () => ctx,
    getAttribute: () => null,
    setAttribute: () => {},
  };
  return elem;
}

function draw(win, setup) {
  const D = win.OfficeDraw;
  const ctx = D.fakeCtx();
  setup(D, ctx);
  return ctx.ops;
}

function texts(ops) {
  return ops.filter((o) => o.k === "t").map((o) => o.s);
}

test("dayPhase: 06-18 gündüz, 18-20 gün batımı, gerisi gece (onur saat başı)", () => {
  const { dayPhase } = load().OfficeDraw;
  assert.equal(dayPhase(6), "day");
  assert.equal(dayPhase(11.99), "day");
  assert.equal(dayPhase(17), "day");
  assert.equal(dayPhase(18), "sunset");
  assert.equal(dayPhase(19.5), "sunset");
  assert.equal(dayPhase(20), "night");
  assert.equal(dayPhase(5), "night");
  assert.equal(dayPhase(0), "night");
  assert.equal(dayPhase(23), "night");
  assert.equal(dayPhase(undefined), "day", "geçersiz saat gündüze düşer");
  assert.equal(dayPhase(99), "day");
});

test("gökyüzü: gündüz güneş, gün batımı turuncu, gece ay/yıldız (duvar tonu da değişir)", () => {
  const win = load();
  const { skyPalette, drawWindowSky } = win.OfficeDraw;
  assert.notDeepEqual(skyPalette("day").wall, skyPalette("night").wall);
  assert.notDeepEqual(skyPalette("sunset").wall, skyPalette("night").wall);
  const winOps = (phase) => draw(win, (D, ctx) => D.drawWindowSky(ctx, phase, skyPalette(phase).sky));
  const cols = (ops) => ops.map((o) => o.c).filter(Boolean);
  assert.ok(cols(winOps("day")).includes("#f6e07a"), "gündüz güneş sarısı");
  assert.ok(cols(winOps("sunset")).includes("#fbd07a"), "gün batımı turuncu güneş");
  assert.ok(cols(winOps("night")).includes("#f2e7c0"), "gece ayı");
  assert.ok(cols(winOps("night")).includes("#cfd8e6"), "gece yıldızları");
  assert.ok(!cols(winOps("day")).includes("#f2e7c0"), "gündüz ay çizilmez");
});

test("tahta: kısa sayaç biçimi ve durum metni tahta iç alanından taşmaz", () => {
  const win = load();
  const D = win.OfficeDraw;
  const O = win.OfficeLogic;
  const IN = { x: 62, y: 8, w: 136, h: 19 }; // drawScene çerçevesiyle aynı iç alan
  const statuses = ["idle", "running", "awaiting", "done", "failed", "cancelled"];
  for (const status of statuses) {
    const s = Object.assign(O.initial(), {
      status,
      counts: { tool_calls: 123, edits: 456, tests_pass: 78, tests_fail: 90 },
    });
    const ops = draw(win, (W, ctx) => D.drawBoard(ctx, s));
    const lines = ops.filter((o) => o.k === "t");
    assert.equal(lines.length, 2, status + ": iki satır");
    for (const o of lines) {
      assert.ok(o.x >= IN.x, `${status}: sol sınır (${o.x})`);
      assert.ok(o.x + o.w <= IN.x + IN.w, `${status}: sağ sınır (${o.x}+${o.w})`);
      assert.ok(o.y >= IN.y && o.y + o.h <= IN.y + IN.h, `${status}: dikey sınır`);
      assert.ok(!o.s.includes("…"), `${status}: kesilme yok → "${o.s}"`);
    }
    assert.ok(
      lines[0].y + lines[0].h <= lines[1].y,
      status + ": satırlar üst üste binmez"
    );
  }
  // sayaç satırı istenen kısa biçimde
  const s = Object.assign(O.initial(), { counts: { tool_calls: 1, edits: 1, tests_pass: 0, tests_fail: 0 } });
  assert.ok(texts(draw(win, (W, ctx) => D.drawBoard(ctx, s))).includes("A:1  D:1  T:0/0"));
});

test("konfeti: az sayıda (en çok 12), 1,5 sn sonra biter, tohum sabit → aynı", () => {
  const D = load().OfficeDraw;
  const a = D.confettiBits(7, 12);
  const b = D.confettiBits(7, 12);
  assert.deepEqual(a, b, "aynı tohum aynı parçacıklar");
  assert.ok(a.length <= 12 && a.length <= D.FX_CAP);
  assert.ok(a.every((p) => p.x >= 0 && p.x < 256));
  const fx = D.createFx();
  fx.endKind = "done";
  fx.endAt = 1000;
  fx.confetti = a;
  assert.ok(D.confettiParts(fx, 1000).length > 0, "başlangıçta yağar");
  assert.equal(D.confettiParts(fx, 1000 + D.CONF_TTL).length, 0, "1,5 sn sonra durur");
  assert.ok(D.confettiParts(fx, 1000 + D.CONF_TTL + 60000).length === 0, "sonra hep boş");
  fx.endKind = "failed";
  assert.equal(D.confettiParts(fx, 1050).length, 0, "başarısız/iptalde konfeti yok");
});

test("efekt yalnız yeni tetikleyicide: aynı seq tekrar efekt üretmez", () => {
  const D = load().OfficeDraw;
  const O = require(path.resolve(WEB, "office-logic.js"));
  const fx = D.createFx();
  const s1 = O.reduce(O.initial(), "done", { status: "done" });
  D.fxEvent(fx, s1, 100);
  const first = fx.endAt;
  D.fxEvent(fx, s1, 500);
  assert.equal(fx.endAt, first, "aynı olay yeniden tetiklemez");
});

test("boş zaman: çalışırken çay/uyku yok; bitince çay, 20 sn beklemede uyku, yeni işte durur", () => {
  const win = load();
  const D = win.OfficeDraw;
  const O = win.OfficeLogic;
  const fx = D.createFx();
  const running = O.reduce(O.initial(), "started", {});
  const modes = new Set();
  for (let t = 0; t <= 60000; t += 500) modes.add(D.stageMode(running, D.createFx(), t, 42));
  assert.deepEqual([...modes], ["work"], "görev sürerken yalnız work");

  const done = O.reduce(running, "done", { status: "done" });
  const idleFx = D.createFx();
  const seen = {};
  for (let t = 0; t <= 30000; t += 250) {
    const m = D.stageMode(done, idleFx, t, 42);
    if (!(m in seen)) seen[m] = t; // her modun İLK görüldüğü an
  }
  assert.ok(seen.coffee != null, "boş zamanda çay içer");
  assert.ok(seen.sleep != null, "uzun beklemede uyuklar");
  assert.ok(seen.sleep <= O.initial().fx.seq + 30000);
  assert.ok(seen.sleep >= 20000 && seen.sleep < 20000 + 4200 + 500, "uyku 20 sn dolmadan başlamaz; çay sürüyorsa bitiminden sonra başlar (" + seen.sleep + ")");
  // erken değil: 20 sn eşiği dolmadan uyku başlamaz
  const early = D.createFx();
  for (let t = 0; t < D.NAP_MS; t += 500) assert.notEqual(D.stageMode(done, early, t, 42), "sleep", "20 sn dolmadan uyumaz (t=" + t + ")");
  // eşik dolunca uyur; o anda çay sürüyorsa çay biter bitmez (çay içerken uyumaz)
  assert.equal(D.stageMode(done, early, D.NAP_MS + D.COFFEE_MS, 42), "sleep", "eşik + çay süresi sonunda uyuklar");
  // yeni görev → hemen işe döner
  const busy = O.reduce(done, "user_message", { text: "yeni" });
  assert.equal(D.stageMode(busy, idleFx, 30000, 42), "work", "yeni görevle boş zaman biter");
});

test("iptal: lamba söner gibi kısa kararma (lamp), sonra normal", () => {
  const D = load().OfficeDraw;
  const O = require(path.resolve(WEB, "office-logic.js"));
  const fx = D.createFx();
  const s = O.reduce(O.reduce(O.initial(), "started", {}), "done", { status: "cancelled" });
  D.fxEvent(fx, s, 0);
  assert.equal(D.stageMode(s, fx, 10, 42), "lamp");
  assert.equal(D.stageMode(s, fx, 5000, 42), "work");
});

test("çizim hatasız çalışır: sahne, tahta, karakter, efekt (sahte bağlam)", () => {
  const win = load();
  const D = win.OfficeDraw;
  const O = win.OfficeLogic;
  let s = O.initial();
  const events = [
    ["started", {}],
    ["tool_call", { tool: "run", args: { command: "pytest -q" } }],
    ["tool_result", { tool: "run", result: "exit_code: 1\n1 failed" }],
    ["done", { status: "failed", error: "x" }],
  ];
  for (const [type, data] of events) s = O.reduce(s, type, data);
  const ctx = D.fakeCtx();
  for (const phase of ["day", "sunset", "night"]) D.drawScene(ctx, phase);
  D.drawBoard(ctx, s);
  D.drawCharacter(ctx, s, 3, { x: 122, y: 104, dx: 0, dy: 0 }, false);
  D.drawOffice(ctx, s, 3, false, "sleep");
  assert.ok(ctx.ops.length > 50, "çizim kayıtları üretildi");
  assert.ok(ctx.ops.some((o) => o.k === "img"), "karakter sprite'ı basıldı");
  // kollar havada: bitti durumunda karakterin iki yanında ten el kareleri (pos.y=104; yüz y+3..y+8)
  const ok = O.reduce(O.reduce(O.initial(), "started", {}), "done", { status: "done" });
  const armOps = D.fakeCtx();
  D.drawCharacter(armOps, ok, 0, { x: 122, y: 104, dx: 0, dy: 0 }, false);
  const hands = armOps.ops.filter((o) => o.c === "#f2c69a" && o.y >= 104 && o.y <= 104 + 10);
  assert.equal(hands.length, 2, "iki ten el (kollar havada): " + JSON.stringify(hands));
  assert.ok(hands.some((o) => o.x <= 122 + 3) && hands.some((o) => o.x >= 122 + 12), "eller iki yanda");
});

test("office.js: hazırlık katmanı güvenli (innerHTML/eval/ağ yok)", () => {
  const js = SRC[1];
  for (const bad of ["innerHTML", "outerHTML", "eval(", "new Function", "fetch(", "XMLHttpRequest", "localStorage", "font="]) {
    const stripped = bad === "font=" ? js.replace("ctx.font", "") : js;
    assert.ok(!stripped.includes(bad), bad);
  }
});
