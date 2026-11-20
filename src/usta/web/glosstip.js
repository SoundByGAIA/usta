// "?" balonu: sözlükteki açıklamayı düğmenin yanında gösterir.
// Ortak yardımcılar app.js'te; paylaşılan adlar window.UstaApp (U) üzerinden çağrı anında okunur.
(function () {
  "use strict";
  const U = (window.UstaApp = window.UstaApp || {});
  const $ = (id) => document.getElementById(id);
  let tipFor = null, tipPinned = false, tipTimer = null;
  // --- "?" balonu: üzerine gelince ya da odaklanınca açıklama çıkar; tıklayınca açık kalır (sayfadan ayrılmaz) ---
  const tipEl = () => $("gloss-tip");
  function hideGlossTip() {
    clearTimeout(tipTimer);
    const el = tipEl();
    if (el) el.hidden = true;
    if (tipFor) tipFor.removeAttribute("aria-describedby");
    tipFor = null; tipPinned = false;
  }
  function showGlossTip(btn, pin) {
    const term = UstaGlossary.find(btn.dataset.gloss);
    if (!term) return;
    clearTimeout(tipTimer);
    if (tipFor && tipFor !== btn) tipFor.removeAttribute("aria-describedby");
    tipFor = btn; tipPinned = !!pin;
    const el = tipEl();
    const open = U.h("button", null, "Sözlükte aç");
    open.type = "button";
    open.addEventListener("click", () => {
      const q = btn.dataset.gloss;
      hideGlossTip();
      U.openGlossary(q);
    });
    el.replaceChildren(U.h("strong", null, term.term), U.h("p", null, term.say), U.h("p", "wiz-note", `Benzetme: ${term.like}`), open);
    el.hidden = false;
    btn.setAttribute("aria-describedby", "gloss-tip");
    const r = btn.getBoundingClientRect();
    const w = Math.min(320, window.innerWidth - 24);
    el.style.width = `${w}px`;
    let left = Math.max(12, Math.min(window.scrollX + r.left + r.width / 2 - w / 2, window.scrollX + window.innerWidth - w - 12));
    el.style.left = `${left}px`;
    const below = r.bottom + 8;
    const fitsBelow = below + el.offsetHeight < window.innerHeight - 8;
    el.style.top = `${window.scrollY + (fitsBelow ? below : Math.max(8, r.top - 8 - el.offsetHeight))}px`;
  }
  const qBtn = (ev) => ev.target.closest && ev.target.closest("button.q[data-gloss]");
  document.addEventListener("mouseover", (ev) => { const b = qBtn(ev); if (b && !tipPinned) showGlossTip(b, false); });
  document.addEventListener("mouseout", (ev) => {
    if (!qBtn(ev) || tipPinned) return;
    clearTimeout(tipTimer);
    tipTimer = setTimeout(() => { if (!tipPinned && !tipEl().matches(":hover")) hideGlossTip(); }, 250);  // balona geçmeye zaman tanır
  });
  tipEl().addEventListener("mouseleave", () => { if (!tipPinned) tipTimer = setTimeout(hideGlossTip, 250); });
  document.addEventListener("focusin", (ev) => { const b = qBtn(ev); if (b) showGlossTip(b, false); });
  document.addEventListener("focusout", (ev) => { if (qBtn(ev) && !tipPinned) tipTimer = setTimeout(() => { if (!tipEl().contains(document.activeElement)) hideGlossTip(); }, 150); });
  document.addEventListener("click", (ev) => {
    const b = qBtn(ev);
    if (b) { if (tipFor === b && tipPinned) hideGlossTip(); else showGlossTip(b, true); return; }
    if (!tipEl().hidden && !tipEl().contains(ev.target)) hideGlossTip();  // dışarı tıklayınca kapanır
  });
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && !tipEl().hidden) { const f = tipFor; hideGlossTip(); if (f) f.focus(); } });
  Object.assign(U, { hideGlossTip });
})();
