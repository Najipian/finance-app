import type { ReactNode } from "react";

import { ApiError } from "../api/client";
import { formatMoney, isNegative } from "../lib/format";

export function Money({ amount, currency, signed = false }: { amount: string; currency: string; signed?: boolean }) {
  const negative = isNegative(amount);
  return (
    <span className={`tabular-nums ${signed && !negative ? "text-brand-700" : ""}`}>
      {signed && !negative && Number(amount) > 0 ? "+" : ""}
      {formatMoney(amount, currency)}
    </span>
  );
}

export function ErrorMessage({ error }: { error: unknown }) {
  if (!error) return null;
  const message =
    error instanceof ApiError
      ? (error.problem.errors?.[0]?.msg ?? error.message)
      : "Something went wrong. Please try again.";
  return (
    <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-danger">
      {message}
    </p>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <p role="status" className="py-8 text-center text-sm text-muted">
      {label}
    </p>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="card text-center">
      <h2 className="text-base font-semibold">{title}</h2>
      {children && <div className="mt-2 text-sm text-muted">{children}</div>}
    </div>
  );
}

export function PageHeader({ title, actions }: { title: string; actions?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
      <h1 className="text-xl font-bold sm:text-2xl">{title}</h1>
      {actions}
    </div>
  );
}

const STATUS_STYLES: Record<string, string> = {
  ok: "bg-brand-100 text-brand-800",
  warning: "bg-amber-100 text-warning",
  exceeded: "bg-red-100 text-danger",
};

/** Budget progress with an accessible value (WCAG: not colour alone; text says the state). */
export function BudgetBar({
  spent,
  limit,
  percent,
  status,
  currency,
  label,
}: {
  spent: string;
  limit: string;
  percent: string;
  status: "ok" | "warning" | "exceeded";
  currency: string;
  label: string;
}) {
  const width = Math.min(100, Number(percent));
  const barColour = status === "exceeded" ? "bg-danger" : status === "warning" ? "bg-amber-500" : "bg-brand-600";
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between gap-2 text-sm">
        <span className="font-medium">{label}</span>
        <span className="tabular-nums text-muted">
          {formatMoney(spent, currency)} of {formatMoney(limit, currency)}
        </span>
      </div>
      <div
        role="progressbar"
        aria-label={`${label} budget used`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(Number(percent))}
        aria-valuetext={`${percent}% used, ${status}`}
        className="h-2.5 overflow-hidden rounded-full bg-black/10"
      >
        <div className={`h-full rounded-full ${barColour}`} style={{ width: `${width}%` }} />
      </div>
      <div className="mt-1 flex justify-between text-xs">
        <span className={`rounded px-1.5 py-0.5 font-semibold ${STATUS_STYLES[status]}`}>
          {status === "ok" ? "On track" : status === "warning" ? "80% used" : "Over budget"}
        </span>
        <span className="tabular-nums text-muted">{percent}%</span>
      </div>
    </div>
  );
}
