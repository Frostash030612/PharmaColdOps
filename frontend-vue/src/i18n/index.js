/* Lightweight runtime i18n — a ~40-line continuation of the vanilla demo's
   "two parallel dictionaries" pattern (frontend/index.html ↔ index-zh.html).
   No vue-i18n: EN/ZH are plain nested objects; structure is mirrored and every
   per-locale asymmetry is DATA inside them (see en.js / zh.js), never a code
   branch on locale.

   API:
     locale   — Vue ref; components compute `const L = computed(() => bundle(locale.value))`.
     setLocale(loc) — switch locale (persists to localStorage, sets <html lang>).
     t(key, params) — dot-path lookup + {param} interpolation (component labels).
     bundle(loc)    — the raw message object for a locale, passed to pure lib/* as `L`.
   Pure libs never import this module — they receive `L` as a function parameter. */

import { ref } from "vue";
import en from "./en.js";
import zh from "./zh.js";

export const messages = { en, zh };
const SUPPORTED = ["en", "zh"];

const STORAGE_KEY = "pharma-locale";

/* Priority: ?lang= > localStorage > navigator.language. */
function detectLocale() {
  try {
    const fromUrl = new URLSearchParams(window.location.search).get("lang");
    if (fromUrl && SUPPORTED.includes(fromUrl)) return fromUrl;
  } catch { /* noop */ }
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved && SUPPORTED.includes(saved)) return saved;
  } catch { /* noop */ }
  return (navigator.language || "en").toLowerCase().startsWith("zh") ? "zh" : "en";
}

const initial = detectLocale();
export const locale = ref(initial);
document.documentElement.lang = initial; /* scope the html[lang] CSS tweaks (ZH line-height, badges…) */

export function setLocale(loc) {
  if (!SUPPORTED.includes(loc) || loc === locale.value) return;
  locale.value = loc;
  document.documentElement.lang = loc;
  try { localStorage.setItem(STORAGE_KEY, loc); } catch { /* noop */ }
}

/* Dot-path + {param} interpolation, e.g. t("ruleText.3.reason"), t("audit.colTime"). */
export function t(key, params) {
  const node = key.split(".").reduce((o, k) => (o == null ? undefined : o[k]), messages[locale.value]);
  if (node == null) {
    console.warn(`[i18n] missing key: ${key}`);
    return key;
  }
  const s = String(node);
  if (!params) return s;
  return s.replace(/\{(\w+)\}/g, (m, k) => (k in params ? String(params[k]) : m));
}

/* The locale's raw message bundle — hand this to pure lib functions. */
export function bundle(loc) {
  return messages[loc] || en;
}
