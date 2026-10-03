export function v2Context(response, observation, productId) {
  if (!['candidate_only', 'abstained'].includes(response?.status) || observation?.product_id !== productId ||
      response.product_id !== productId || response.event_id !== observation.event_id ||
      response.shadow_only !== true || response.review_required !== true || response.automatic_actions_allowed !== false ||
      !response.temperature_series || !matchesV2Temperature(response.temperature_series, observation) || !response.model_sha256 || !response.policy_sha256) {
    throw new Error('Unsupported or mismatched v2 shadow preview');
  }
  return {
    eventContext: { observation: JSON.parse(JSON.stringify(observation)) },
    temperatureContext: { series: JSON.parse(JSON.stringify(response.temperature_series)), window_id: null },
    event: { excursion_temp_c: null, duration_min: null, mkt_c: null },
  };
}

export function eventReasonLabel(key, labels) {
  const code = key.replace(/^event_model_/, '').replace(/^event_v2_/, '');
  return labels[code] || labels[key] || key;
}

export function matchesV2Temperature(series, observation) {
  return !!series && series.source === 'simulated' && series.observation_end_min === observation.observation_end_min &&
    series.activation_energy_kj_mol === 83.144 && series.intervals.length === observation.records.length &&
    series.intervals.every((r,i) => r.start_min === observation.records[i].start_min && r.end_min === observation.records[i].end_min && r.temp_c === observation.records[i].product_temp_c);
}
