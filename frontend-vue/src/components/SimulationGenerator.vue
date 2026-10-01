<script setup>
import { computed } from "vue";
import { useDispatchStore } from "../stores/dispatch.js";
import { locale, bundle } from "../i18n/index.js";
import { PRODUCT_IDS } from "../data/products.js";
import routes from "../data/singaporeRoutes.json";
import { SIMULATION_SCENARIOS, simulationFilename } from "../lib/simulation.js";
const dispatch = useDispatchStore();
const L = computed(() => bundle(locale.value));
const form = computed(() => dispatch.simulationForm);
const metadata = computed(() => dispatch.dailyBatch?.metadata);
const inputs = computed(() => dispatch.dailyBatch?.plan?.orders || []);
const sources = routes.nodes.filter((n) => ["depot", "distribution"].includes(n.role));
const names = Object.fromEntries(routes.nodes.map((n) => [n.facility_id, n.name]));
const clock = (min) => `${String(Math.floor(min / 60)).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}`;
function download() {
  const batch = dispatch.dailyBatch;
  if (!batch) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(batch, null, 2)], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url; link.download = simulationFilename(batch); link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
</script>

<template>
  <section class="simulation-generator">
    <h3>{{ L.simulation.title }}</h3>
    <p class="sg-note">{{ L.simulation.disclosure }}</p>
    <form @submit.prevent="dispatch.generateSimulation()">
      <fieldset :disabled="dispatch.pending">
        <div class="simulation-fields">
          <label>{{ L.simulation.scenario }}<select :value="form.scenario" @change="dispatch.setSimulationScenario($event.target.value)"><option v-for="scenario in SIMULATION_SCENARIOS" :key="scenario" :value="scenario">{{ L.simulation[scenario] }}</option></select></label>
          <label>{{ L.simulation.date }}<input v-model="form.operating_date" type="date" required :disabled="form.scenario === 'legacy'" /></label>
          <label>{{ L.simulation.seed }}<input v-model="form.seed" type="number" min="0" max="4294967295" step="1" :placeholder="L.simulation.autoSeed" /></label>
          <label>{{ L.simulation.count }}<input v-model.number="form.order_count" type="number" min="2" max="14" step="1" required :disabled="form.scenario === 'legacy'" /></label>
        </div>
        <p class="sg-note">{{ L.simulation[`${form.scenario}Hint`] }}</p>
        <details v-if="form.scenario !== 'legacy'" class="sg-advanced">
          <summary>{{ L.simulation.parameters }}</summary>
          <p class="sg-note">{{ L.simulation.presetHint }}</p>
          <div class="simulation-fields">
            <label>{{ L.simulation.products }}<select v-model="form.product_ids" multiple size="4"><option v-for="id in PRODUCT_IDS" :key="id" :value="id">{{ L.products[id] }}</option></select></label>
            <label>{{ L.simulation.origins }}<select v-model="form.origin_facility_ids" multiple size="4"><option v-for="node in sources" :key="node.facility_id" :value="node.facility_id">{{ node.name }}</option></select></label>
            <label>{{ L.simulation.quantityMin }}<input v-model="form.quantity_min" type="number" min="1" max="1000" step="1" /></label>
            <label>{{ L.simulation.quantityMax }}<input v-model="form.quantity_max" type="number" min="1" max="1000" step="1" /></label>
            <label>{{ L.simulation.windowMin }}<input v-model="form.window_min" type="number" min="30" max="480" step="1" /></label>
            <label>{{ L.simulation.windowMax }}<input v-model="form.window_max" type="number" min="30" max="480" step="1" /></label>
            <label>{{ L.simulation.fleet }}<input v-model="form.fleet_size" type="number" min="1" max="20" step="1" /></label>
            <label>{{ L.simulation.capacity }}<input v-model.number="form.vehicle_capacity" type="number" min="1" max="10000" step="1" required /></label>
            <label>{{ L.simulation.spare }}<input v-model.number="form.spare_quantity" type="number" min="0" max="1000" step="1" required /></label>
            <label v-if="form.scenario === 'urgent'">{{ L.simulation.slack }}<input v-model.number="form.urgent_slack_min" type="number" min="0" max="120" step="1" required /></label>
          </div>
        </details>
        <button type="submit" class="sg-primary">{{ dispatch.pending ? L.simulation.generating : L.simulation.generate }}</button>
      </fieldset>
    </form>
    <p v-if="!dispatch.simulationInputsCurrent" class="sg-error" role="status">{{ L.simulation.changed }}</p>
    <div v-if="dispatch.dailyBatch" class="simulation-snapshot">
      <p v-if="metadata">{{ L.simulation.snapshot }}: {{ metadata.batch_id }} · {{ metadata.config.operating_date }} · {{ L.simulation.seed }} {{ metadata.config.seed }} · {{ metadata.generator_version }}</p>
      <button @click="download">{{ L.simulation.export }}</button>
      <details>
        <summary>{{ L.simulation.orders }} · {{ inputs.length }}</summary>
        <div class="simulation-table-wrap">
          <table class="htable simulation-orders">
            <thead><tr><th>{{ L.simulation.orderId }}</th><th>{{ L.center.product }}</th><th>{{ L.simulation.source }}</th><th>{{ L.workflow.hospital }}</th><th>{{ L.simulation.quantity }}</th><th>{{ L.simulation.window }}</th></tr></thead>
            <tbody><tr v-for="order in inputs" :key="order.order_id">
              <td>{{ order.order_id }} <strong v-if="metadata?.urgent_order_ids.includes(order.order_id)">{{ L.simulation.urgentTag }}</strong></td>
              <td>{{ L.products[order.product_id] || order.product_id }}</td>
              <td>{{ names[order.origin_facility_id] || order.origin_facility_id || names['W-WESTGATE'] }}</td>
              <td>{{ names[order.destination_facility_id] || order.destination_facility_id }}</td>
              <td>{{ order.quantity }}</td><td>{{ clock(order.earliest_min) }}–{{ clock(order.latest_min) }}</td>
            </tr></tbody>
          </table>
        </div>
      </details>
    </div>
  </section>
</template>

<style scoped>
.simulation-generator { margin: 12px 0; padding: 12px; border: 1px solid #cbd5e1; border-radius: 10px; background: #f8fafc; }
.simulation-generator h3 { margin: 0 0 8px; }
.simulation-generator fieldset { border: none; padding: 0; margin: 0; }
.simulation-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.simulation-fields label { display: grid; gap: 4px; font-size: 12px; min-width: 0; }
.simulation-fields input, .simulation-fields select { width: 100%; box-sizing: border-box; min-width: 0; }
.simulation-snapshot { margin-top: 12px; overflow-wrap: anywhere; }
.simulation-table-wrap { overflow-x: auto; margin-top: 10px; }
.simulation-orders { min-width: 760px; }
.simulation-orders td { font-size: 11px; }
@media (max-width: 520px) { .simulation-fields { grid-template-columns: 1fr; } }
</style>
