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

/** A grey placeholder block that pulses while data loads (motion off for reduced-motion users). */
export function Skeleton({ className = "" }: { className?: string }) {
  return <div aria-hidden="true" className={`animate-pulse rounded-md bg-black/6 motion-reduce:animate-none ${className}`} />;
}

/**
 * Loading state shaped like the list it replaces, so the page does not jump when data
 * arrives. Screen readers hear the label once (role="status").
 */
export function Loading({ label = "Loading…", rows = 4 }: { label?: string; rows?: number }) {
  return (
    <div role="status" className="card space-y-4">
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center justify-between gap-4">
          <div className="flex-1 space-y-2">
            <Skeleton className="h-3.5 w-2/5" />
            <Skeleton className="h-3 w-1/4" />
          </div>
          <Skeleton className="h-4 w-20" />
        </div>
      ))}
    </div>
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

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-muted">{subtitle}</p>}
      </div>
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
