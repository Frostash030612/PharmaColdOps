/* Locale-NEUTRAL product + spec data (mirrors frontend/index.html config and
   src/rule_engine/rules_config.json). Display names / badges / stage words live
   in src/i18n — nothing here is user-facing wording except colours. */

export const PRODUCT_NUM = {
  vaccine_2_8:    { id: "vaccine_2_8",    min: 2,  max: 8,  allowable: 30, mktThreshold: 10.0,  retestable: true,  freezeSensitive: true },
  frozen_m20:     { id: "frozen_m20",     min: -25, max: -15, allowable: 15, mktThreshold: -12.0, retestable: false, freezeSensitive: false },
  insulin_2_8:    { id: "insulin_2_8",    min: 2,  max: 8,  allowable: 30, mktThreshold: 10.0,  retestable: true,  freezeSensitive: true },
  mrna_ultracold: { id: "mrna_ultracold", min: -80, max: -60, allowable: 60, mktThreshold: -55.0, retestable: false, freezeSensitive: false },
};

export const PRODUCT_IDS = ["vaccine_2_8", "frozen_m20", "insulin_2_8", "mrna_ultracold"];

/* Slider bounds per product (from the demo's TEMP_RANGE). */
export const TEMP_RANGE = {
  vaccine_2_8: [-5, 35],
  frozen_m20: [-30, 15],
  insulin_2_8: [-5, 35],
  mrna_ultracold: [-90, 0],
};

/* Default excursion shown when a product is first selected (demo DEFAULT_EVENT). */
export const DEFAULT_EVENT = {
  vaccine_2_8:    { excursion_temp_c: 10,  duration_min: 24, mkt_c: 9.5,  packaging: "intact", stage: "transit" },
  frozen_m20:     { excursion_temp_c: -4,  duration_min: 25, mkt_c: -9.5, packaging: "intact", stage: "transit" },
  insulin_2_8:    { excursion_temp_c: 10,  duration_min: 24, mkt_c: 9.5,  packaging: "intact", stage: "transit" },
  mrna_ultracold: { excursion_temp_c: -40, duration_min: 70, mkt_c: -58.0, packaging: "intact", stage: "transit" },
};

/* Disposition → banner/plot fill colour (shared by EN and ZH). */
export const DISPO_COLOR = {
  release: "#16a34a",
  retest: "#d97706",
  quarantine: "#ea580c",
  scrap: "#dc2626",
};

/* Order in which dispositions appear in the zone legend. */
export const DISPO_ORDER = ["release", "retest", "quarantine", "scrap"];

export const STAGE_IDS = ["transit", "warehouse", "airport_dwell", "last_mile"];
export const PACKAGING_IDS = ["intact", "compromised"];
