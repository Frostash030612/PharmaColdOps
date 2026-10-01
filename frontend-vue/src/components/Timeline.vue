<script setup>
/* Temperature replay (#timeline + play/scrub/readout). The SVG/readout/scrub
   values are one computed derived from store.nowTime — the store's interval
   advances nowTime during playback and the computed re-renders at 30 ms. */
import { computed } from "vue";
import { useSandboxStore } from "../stores/sandbox.js";
import { timelineSvg } from "../lib/timeline.js";
import { locale, bundle } from "../i18n/index.js";

const sandbox = useSandboxStore();
const L = computed(() => bundle(locale.value));

const view = computed(() =>
  timelineSvg(sandbox.current, sandbox.spec, sandbox.nowTime, L.value)
);

/* scrub → nowTime (ms); the same genProfile/total the SVG used */
function onScrub(e) {
  sandbox.scrubTo(view.value.total * (parseFloat(e.target.value) / 100));
}
</script>

<template>
  <div>
    <p class="timeline-source-note">{{ L.temperature.syntheticTimeline }}</p>
    <div v-html="view.svg"></div>
    <div class="timeline-controls">
      <button class="btn" @click="sandbox.toggleTimeline()">
        {{ sandbox.playing ? L.center.pause : L.center.play }}
      </button>
      <input type="range" min="0" max="100" step="1" :value="view.scrubPct" @input="onScrub">
      <span class="time-readout">{{ view.readout }}</span>
    </div>
  </div>
</template>
