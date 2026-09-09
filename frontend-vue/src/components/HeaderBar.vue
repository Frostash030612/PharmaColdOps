<script setup>
/* Brand row + static pills + backend-mode pill (id apiState) + new-inbound "+"
   (header entry point for a fresh case, API mode only) + SPA locale switch. */
import { computed } from "vue";
import { useDecisionsStore } from "../stores/decisions.js";
import { useOverlayStore } from "../stores/overlay.js";
import { locale, setLocale, bundle } from "../i18n/index.js";

const decisions = useDecisionsStore();
const overlay = useOverlayStore();
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
      <button
        v-if="decisions.useApi"
        class="header-hist"
        :disabled="decisions.apiUp !== true"
        :title="L.history.expand"
        @click="overlay.openHistory()"
      >{{ L.history.title }}</button>
      <button
        v-if="decisions.useApi"
        class="header-plus"
        :disabled="decisions.apiUp !== true"
        :title="L.newInbound.openTip"
        @click="overlay.openNewInbound()"
      >+</button>
      <div class="locale-switch">
        <button :class="{ on: locale === 'en' }" @click="setLocale('en')">EN</button>
        <button :class="{ on: locale === 'zh' }" @click="setLocale('zh')">中文</button>
      </div>
    </div>
  </header>
</template>
