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

/** "£1.2k", "£30M": short labels for chart axes, where pennies are noise. */
export function formatCompactMoney(amount: string | number, currency: string): string {
  return new Intl.NumberFormat(LOCALE, {
    style: "currency",
    currency,
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(Number(amount));
}

/** "10 Nov" for dates in the current year, "10 Nov 2025" otherwise. */
export function formatShortDate(iso: string, today: Date = new Date()): string {
  const date = new Date(iso);
  const sameYear = date.getFullYear() === today.getFullYear();
  return new Intl.DateTimeFormat(LOCALE, {
    day: "numeric",
    month: "short",
    ...(sameYear ? {} : { year: "numeric" }),
  }).format(date);
}

/** "just now", "4 min ago", "3 h ago", "2 days ago". */
export function formatRelative(iso: string, now: Date = new Date()): string {
  const minutes = Math.round((now.getTime() - new Date(iso).getTime()) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

/** The currency shown first. The product targets UK users, so GBP leads. */
export const PRIMARY_CURRENCY = "GBP";

/** Sort items by currency: GBP first, then alphabetically. */
export function byCurrency<T extends { currency: string }>(items: readonly T[]): T[] {
  return [...items].sort((a, b) => {
    if (a.currency === b.currency) return 0;
    if (a.currency === PRIMARY_CURRENCY) return -1;
    if (b.currency === PRIMARY_CURRENCY) return 1;
    return a.currency.localeCompare(b.currency);
  });
}

/** Parse a decimal string ("-12.3", "4.56") into integer minor units (pence), exactly. */
export function toMinor(amount: string): bigint {
  const trimmed = amount.trim();
  const negative = trimmed.startsWith("-");
  const [whole, fraction = ""] = trimmed.replace(/^[-+]/, "").split(".");
  const minor = BigInt(whole || "0") * 100n + BigInt((fraction + "00").slice(0, 2));
  return negative ? -minor : minor;
}

/** `a - b` for decimal strings, computed in integer pence and returned as "12.34". */
export function subtractMoney(a: string, b: string): string {
  const diff = toMinor(a) - toMinor(b);
  const sign = diff < 0n ? "-" : "";
  const abs = diff < 0n ? -diff : diff;
  return `${sign}${abs / 100n}.${String(abs % 100n).padStart(2, "0")}`;
}
