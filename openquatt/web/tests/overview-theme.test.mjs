import assert from "node:assert/strict";
import test from "node:test";

const storage = new Map();
const colorSchemeMedia = {
  matches: true,
  listeners: [],
  addEventListener(type, listener) {
    if (type === "change") {
      this.listeners.push(listener);
    }
  },
  emit(matches) {
    this.matches = matches;
    this.listeners.forEach((listener) => listener({ matches }));
  },
};

globalThis.__OQ_PREVIEW__ = false;
globalThis.window = {
  clearTimeout,
  location: { pathname: "/" },
  localStorage: {
    getItem: (key) => (storage.has(key) ? storage.get(key) : null),
    setItem: (key, value) => storage.set(key, String(value)),
  },
  matchMedia: (query) => (query === "(prefers-color-scheme: dark)" ? colorSchemeMedia : { matches: false }),
  setTimeout,
};

const { getStoredOverviewThemePreference, resolveOverviewTheme, state } = await import("../js/src/core/state.js");
const { bindColorSchemePreference, setOverviewTheme } = await import("../js/src/core/runtime.js");
const { setRenderCallback } = await import("../js/src/core/render-scheduler.js");
const { renderHeaderStatus } = await import("../js/src/features/header-status.js");

test("theme preference defaults to automatic and keeps stored light/dark choices", () => {
  storage.clear();
  assert.equal(getStoredOverviewThemePreference(), "auto");
  storage.set("oq-overview-theme", "dark");
  assert.equal(getStoredOverviewThemePreference(), "dark");
  storage.set("oq-overview-theme", "light");
  assert.equal(getStoredOverviewThemePreference(), "light");
  storage.set("oq-overview-theme", "auto");
  assert.equal(getStoredOverviewThemePreference(), "auto");
  storage.set("oq-overview-theme", "unexpected");
  assert.equal(getStoredOverviewThemePreference(), "auto");
});

test("automatic theme follows the device color scheme and explicit choices ignore it", (t) => {
  let renders = 0;
  setRenderCallback(() => {
    renders += 1;
  });
  t.after(() => setRenderCallback(null));

  colorSchemeMedia.matches = true;
  assert.equal(resolveOverviewTheme("auto"), "dark");
  assert.equal(resolveOverviewTheme("light"), "light");

  setOverviewTheme("auto");
  bindColorSchemePreference();
  assert.equal(storage.get("oq-overview-theme"), "auto");
  assert.equal(state.overviewTheme, "dark");

  colorSchemeMedia.emit(false);
  assert.equal(state.overviewTheme, "light");
  assert.equal(renders, 1);

  colorSchemeMedia.emit(false);
  assert.equal(renders, 1);

  setOverviewTheme("dark");
  assert.equal(storage.get("oq-overview-theme"), "dark");
  colorSchemeMedia.emit(true);
  colorSchemeMedia.emit(false);
  assert.equal(state.overviewTheme, "dark");
  assert.equal(state.overviewThemePreference, "dark");
  assert.equal(renders, 1);
});

test("interface panel offers automatic, light and dark theme choices", () => {
  state.interfacePanelOpen = true;
  state.entities = {};
  setOverviewTheme("auto");

  const html = renderHeaderStatus();
  const themeChips = [...html.matchAll(/<button class="([^"]*)"[^>]*data-overview-theme="([^"]+)"/g)]
    .map(([, className, theme]) => ({ theme, active: className.split(" ").includes("is-active") }));

  assert.deepEqual(themeChips, [
    { theme: "auto", active: true },
    { theme: "light", active: false },
    { theme: "dark", active: false },
  ]);
  assert.doesNotMatch(html, /toggle-overview-theme/);
});
