/* history store — the cross-session case archive behind the history panel.

   A new inbound case is entered in a modal and archived there with one explicit
   POST /api/case_close (which appends ONE record per closed case to the backend
   run log, data/audit/runs.jsonl). This store only reads the archive: it pulls
   GET /api/runs when the API comes up, and the modal / table call refresh()
   right after a successful close so the new case appears immediately. */
import { defineStore } from "pinia";
import { ref, watch } from "vue";
import { useDecisionsStore } from "./decisions.js";
import { fetchRuns } from "../lib/api.js";

export const useHistoryStore = defineStore("history", () => {
  const decisions = useDecisionsStore();

  /* ---- archive state ---- */
  const runs = ref([]);        // raw /api/runs records, newest first (server order)
  const count = ref(0);
  const loading = ref(false);
  const loaded = ref(false);   // a fetch has completed (so "no rows" = genuinely empty)
  const error = ref(false);

  /* One GET /api/runs. Requests arriving mid-flight queue one follow-up so a
     close that landed while a fetch ran is never dropped. Idempotent read — a
     manual double-click is harmless. */
  let inflight = false;
  let rerun = false;
  function fetchOnce() {
    if (inflight) { rerun = true; return; }
    if (!decisions.useApi || decisions.apiUp !== true) return;
    inflight = true;
    loading.value = true;
    error.value = false;
    fetchRuns(decisions.apiBase)
      .then((res) => {
        runs.value = res.runs;
        count.value = res.count;
      })
      .catch(() => { error.value = true; })
      .finally(() => {
        inflight = false;
        loading.value = false;
        loaded.value = true;
        if (rerun) { rerun = false; fetchOnce(); }
      });
  }

  function refresh() { fetchOnce(); }

  /* Boot / reconnect entry. Offline mode has no archive to show. */
  function load() {
    if (!decisions.useApi) {
      runs.value = [];
      count.value = 0;
      loaded.value = false;
      error.value = false;
      return;
    }
    refresh();
  }

  /* Re-load when the API comes up (boot health-check or reconnect). */
  let timer = null;
  watch(() => decisions.apiUp, (up) => {
    if (up === true) {
      clearTimeout(timer);
      timer = setTimeout(refresh, 200);
    }
  });

  return { runs, count, loading, loaded, error, refresh, load };
});
