/* overlay store — which centered modal is open. Only one at a time: opening
   new-inbound closes a history view and vice-versa, so the blurred backdrop
   always highlights exactly one panel. While a modal is open the page behind
   is locked (no scroll under the backdrop). */
import { defineStore } from "pinia";
import { ref, watch } from "vue";

export const useOverlayStore = defineStore("overlay", () => {
  const historyOpen = ref(false);
  const newInboundOpen = ref(false);
  const caseOpen = ref(false);

  function openHistory() { historyOpen.value = true; newInboundOpen.value = false; caseOpen.value = false; }
  function closeHistory() { historyOpen.value = false; }

  function openNewInbound() { newInboundOpen.value = true; historyOpen.value = false; caseOpen.value = false; }
  function closeNewInbound() { newInboundOpen.value = false; }

  function openCase() { caseOpen.value = true; historyOpen.value = false; newInboundOpen.value = false; }
  function closeCase() { caseOpen.value = false; }

  function closeAll() { historyOpen.value = false; newInboundOpen.value = false; caseOpen.value = false; }

  /* lock the body while any modal is up */
  watch([historyOpen, newInboundOpen, caseOpen], () => {
    document.body.style.overflow = (historyOpen.value || newInboundOpen.value || caseOpen.value) ? "hidden" : "";
  });

  return { historyOpen, newInboundOpen, caseOpen, openHistory, closeHistory,
           openNewInbound, closeNewInbound, openCase, closeCase, closeAll };
});
