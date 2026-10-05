/**
 * Game Dev OS theme switcher — persists to localStorage.
 */
(function () {
  const KEY = "gameDevOS.theme";
  const DEFAULT = "cosmic";
  const ALLOWED = new Set(["cosmic", "dark", "light", "tokyo", "neon"]);

  function apply(theme) {
    const t = ALLOWED.has(theme) ? theme : DEFAULT;
    document.documentElement.setAttribute("data-theme", t);
    try {
      localStorage.setItem(KEY, t);
    } catch (_) {}
    const sel = document.getElementById("themeSelect");
    if (sel && sel.value !== t) sel.value = t;
  }

  function init() {
    let saved = DEFAULT;
    try {
      saved = localStorage.getItem(KEY) || DEFAULT;
    } catch (_) {}
    apply(saved);

    const sel = document.getElementById("themeSelect");
    if (sel) {
      sel.addEventListener("change", () => apply(sel.value));
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.gameDevOSTheme = { apply, themes: [...ALLOWED] };
})();
