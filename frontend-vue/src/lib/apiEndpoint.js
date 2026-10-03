// Explicit ?api= disables a deployment default; absent query preserves offline
// static builds. Same-origin deployments need no machine-specific backend URL.
export function resolveApiEndpoint(search, deploymentDefault = "") {
  const params = new URLSearchParams(search);
  const value = params.has("api") ? params.get("api") : deploymentDefault;
  return {
    useApi: Boolean(value),
    apiBase: value === "same-origin" ? "" : (value || "").replace(/\/+$/, ""),
  };
}
