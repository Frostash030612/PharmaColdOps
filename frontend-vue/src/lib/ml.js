export const contextKey = value => JSON.stringify(value);
export function replaceContext(contexts, task, context = null) {
  const others = (contexts || []).filter(c => c.task !== task);
  return context ? [...others, JSON.parse(JSON.stringify(context))] : others;
}
export function contextPayload(task, fields, values, sampleId = null) {
  const features = {};
  for (const field of fields) {
    const value = values[field.key];
    if (value === '' || value == null) throw new Error(`Missing feature: ${field.key}`);
    if (field.kind === 'category') features[field.key] = String(value);
    else {
      const number = Number(value);
      if (!Number.isFinite(number)) throw new Error(`Invalid feature: ${field.key}`);
      features[field.key] = number;
    }
  }
  return { task, source: sampleId ? 'dataset_sample' : 'manual_simulated', sample_id: sampleId, features };
}
