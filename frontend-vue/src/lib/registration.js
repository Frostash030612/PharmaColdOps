const copy = (value) => JSON.parse(JSON.stringify(value));
export const registrationStorageKey = (base) => `pharmacoldops:pending-registration:v1:${base}`;

export function createRegistration(payload, source = "new_inbound", id = null, startedAt = null) {
  const registration_id = id || `reg-${globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`}`;
  return { version: 1, source, payload: {
    ...copy(payload), registration_id, started_at: payload.started_at || startedAt || new Date().toISOString(),
  } };
}

export function saveRegistration(storage, base, envelope) {
  try { storage.setItem(registrationStorageKey(base), JSON.stringify(envelope)); return true; }
  catch { return false; }
}

export function restoreRegistration(storage, base) {
  const raw = storage.getItem(registrationStorageKey(base));
  if (!raw) return null;
  const record = JSON.parse(raw);
  if (record?.version !== 1 || !record.payload?.registration_id || !record.payload.product_id) {
    throw new Error("Stored registration draft is invalid");
  }
  return record;
}

export function clearRegistration(storage, base) {
  try { storage.removeItem(registrationStorageKey(base)); return true; }
  catch { return false; }
}

export function sameRegistrationDraft(payload, envelope) {
  const normalize = (value) => value && typeof value === "object"
    ? (Array.isArray(value) ? value.map(normalize) : Object.fromEntries(Object.keys(value).sort().map(k=>[k,normalize(value[k])])))
    : value;
  const strip = (value) => Object.fromEntries(Object.entries(value).filter(([key])=>!['registration_id','started_at'].includes(key)));
  return JSON.stringify(normalize(strip(payload))) === JSON.stringify(normalize(strip(envelope.payload)));
}
