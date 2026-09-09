<script setup>
/* Brand row + static pills + backend-mode pill (id apiState) + SPA locale switch. */
import { computed } from "vue";
import { useDecisionsStore } from "../stores/decisions.js";
import { locale, setLocale, bundle } from "../i18n/index.js";

const decisions = useDecisionsStore();
const L = computed(() => bundle(locale.value));

/* Backend pill: connecting (null) → good → bad, shown only in ?api= mode. */
const apiClass = computed(() =>
  decisions.apiUp === null ? "pill" : decisions.apiUp ? "pill good" : "pill bad"
);
const apiText = computed(() =>
  decisions.apiUp === null ? L.value.apiPill.connecting
    : decisions.apiUp ? L.value.apiPill.good : L.value.apiPill.bad
);
</script>

<template>
  <header>
    <div class="brand">
      <div class="logo">❄</div>
      <div>
        <h1>PharmaColdOps</h1>
        <div class="sub">{{ L.header.sub }}</div>
      </div>
    </div>
    <div class="pills">
      <span class="pill live">{{ L.header.pillLive }}</span>
      <span class="pill">{{ L.header.pillWHO }}</span>
      <span class="pill">{{ L.header.pillEU }}</span>
      <span class="pill">{{ L.header.pillDemo }}</span>
      <span v-if="decisions.useApi" :class="apiClass">{{ apiText }}</span>
      <div class="locale-switch">
        <button :class="{ on: locale === 'en' }" @click="setLocale('en')">EN</button>
        <button :class="{ on: locale === 'zh' }" @click="setLocale('zh')">中文</button>
      </div>
    </div>
  </header>
</template>
