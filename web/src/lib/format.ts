/**
 * Display formatting. Amounts arrive from the API as decimal strings and are only
 * ever *formatted* here; the app never does arithmetic on money in floating point.
 */

const LOCALE = "en-GB";

export function formatMoney(amount: string | number, currency: string): string {
  return new Intl.NumberFormat(LOCALE, { style: "currency", currency }).format(Number(amount));
}

export function formatDate(iso: string): string {
  return new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "short", year: "numeric" }).format(
    new Date(iso),
  );
}

/** "2026-11" for the month containing `date` (local time). */
export function monthKey(date: Date = new Date()): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

/** "Nov 2026" from "2026-11". */
export function monthLabel(key: string): string {
  const [year, month] = key.split("-").map(Number);
  return new Intl.DateTimeFormat(LOCALE, { month: "short", year: "numeric" }).format(
    new Date(year, month - 1, 1),
  );
}

/** Shift a "YYYY-MM" key by `delta` months. */
export function addMonths(key: string, delta: number): string {
  const [year, month] = key.split("-").map(Number);
  return monthKey(new Date(year, month - 1 + delta, 1));
}

export function isNegative(amount: string): boolean {
  return amount.trim().startsWith("-");
}
