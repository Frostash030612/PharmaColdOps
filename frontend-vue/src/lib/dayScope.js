/* Day scoping shared by the event rail (IncidentList) and the map overlay
   (ReroutePanel). Both used to answer "which cases are relevant" differently:
   the rail listed everything and the map drew every archived case, so old
   excursions stayed on the map and buried the current day.

   "Today" is the local calendar day of the demo clock. When the archive holds
   nothing for the real today, we anchor to the newest day that does have
   records rather than showing nothing — and the caller says which day that is,
   so the state stays explicit instead of silently faked. */

const pad = (n) => String(n).padStart(2, "0");

/* Local calendar day (YYYY-MM-DD) of a timestamp; never UTC, so a case closed
   at 00:30 local does not land on "yesterday". */
export function localDay(value) {
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/* Which day the "today" scope actually shows, given every day present in the
   archive. Returns "" when there is no archive at all. */
export function resolveShownDay(days, now = new Date()) {
  const today = localDay(now);
  if (days.includes(today)) return today;
  return days.length ? days[days.length - 1] : "";
}

export const isReallyToday = (days, now = new Date()) => days.includes(localDay(now));
