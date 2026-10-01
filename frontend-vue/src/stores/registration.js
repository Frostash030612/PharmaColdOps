import { defineStore } from "pinia";
import { ref } from "vue";
import { useDecisionsStore } from "./decisions.js";
import { useSandboxStore } from "./sandbox.js";
import { postJson } from "../lib/api.js";
import { createRegistration, saveRegistration, restoreRegistration, clearRegistration, sameRegistrationDraft } from "../lib/registration.js";

export const useRegistrationStore = defineStore("registration", () => {
  const decisions = useDecisionsStore();
  const sandbox = useSandboxStore();
  const pending = ref(null);
  const busy = ref(false);
  const storageAvailable = ref(true);
  let inflight = null;
  function storage() {
    try { return window.sessionStorage; } catch { storageAvailable.value = false; return null; }
  }
  function restore() {
    if (pending.value) return pending.value;
    const target = storage();
    if (!target) return null;
    pending.value = restoreRegistration(target, decisions.apiBase);
    return pending.value;
  }
  function clear() {
    pending.value = null;
    const target = storage();
    if (target && !clearRegistration(target, decisions.apiBase)) storageAvailable.value = false;
  }
  function submit(payload = null, source = "new_inbound") {
    if (sandbox.offlinePreview || !decisions.useApi || decisions.apiUp !== true) {
      return Promise.reject(new Error("Local sandbox cannot register incidents; connect the backend first"));
    }
    if (inflight) return payload && !sameRegistrationDraft(payload, pending.value)
      ? Promise.reject(new Error("A different registration is already in flight")) : inflight;
    restore();
    if (pending.value && payload) return Promise.reject(new Error("An unresolved registration draft exists; reopen it and retry before creating a new incident"));
    if (!pending.value) {
      if (!payload) return Promise.reject(new Error("No registration draft to retry"));
      pending.value = createRegistration(payload, source);
      const target = storage();
      if (!target || !saveRegistration(target, decisions.apiBase, pending.value)) storageAvailable.value = false;
    }
    busy.value = true;
    const body = JSON.parse(JSON.stringify(pending.value.payload));
    inflight = postJson(`${decisions.apiBase}/api/case_close`, body)
      .then((record) => { clear(); return record; })
      .catch((error) => {
        if (error.status === 422) clear(); // definitive validation refusal, not an ambiguous network failure
        throw error;
      })
      .finally(() => { inflight = null; busy.value = false; });
    return inflight;
  }
  return { pending, busy, storageAvailable, restore, clear, submit };
});
