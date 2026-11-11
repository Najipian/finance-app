import { useState } from "react";
import { Link } from "react-router";

import { useBudgets, useConnections, useDashboard, useMarkRead, useNotifications, useStartConsent } from "../api/hooks";
import { MonthlyTrend, SpendByCategory } from "../components/charts";
import { BudgetBar, Empty, ErrorMessage, Loading, Money, PageHeader } from "../components/ui";
import { addMonths, monthKey, monthLabel } from "../lib/format";

export function MonthPicker({ month, onChange }: { month: string; onChange: (m: string) => void }) {
  const current = monthKey();
  return (
    <div className="flex items-center gap-2" role="group" aria-label="Month">
      <button type="button" className="btn-secondary px-3" onClick={() => onChange(addMonths(month, -1))} aria-label="Previous month">
        ‹
      </button>
      <span className="min-w-24 text-center text-sm font-semibold" aria-live="polite">
        {monthLabel(month)}
      </span>
      <button
        type="button"
        className="btn-secondary px-3"
        onClick={() => onChange(addMonths(month, 1))}
        disabled={month >= current}
        aria-label="Next month"
      >
        ›
      </button>
    </div>
  );
}

function RenewBanner() {
  const { data: connections } = useConnections();
  const renew = useStartConsent();
  const due = (connections ?? []).filter((c) => c.renewal_due || c.status === "needs_renewal");
  if (due.length === 0) return null;
  return (
    <div className="space-y-2">
      {due.map((c) => (
        <div key={c.id} role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-amber-50 p-4 ring-1 ring-amber-300">
          <p className="text-sm text-warning">
            <strong>{c.institution_name}:</strong>{" "}
            {c.status === "needs_renewal"
              ? "access has expired. Syncing has stopped until you renew."
              : `access expires in ${c.days_until_expiry} day${c.days_until_expiry === 1 ? "" : "s"}.`}
          </p>
          <button type="button" className="btn-primary" disabled={renew.isPending} onClick={() => renew.mutate({ renew: c.id })}>
            Renew access
          </button>
        </div>
      ))}
    </div>
  );
}

function Alerts() {
  const { data } = useNotifications();
  const markRead = useMarkRead();
  if (!data || data.length === 0) return null;
  return (
    <section aria-label="Alerts" className="space-y-2">
      {data.map((n) => (
        <div key={n.id} className="flex items-start justify-between gap-3 rounded-xl bg-white p-4 shadow-sm ring-1 ring-danger/30">
          <div>
            <p className="text-sm font-semibold text-danger">{n.title}</p>
            <p className="text-sm text-muted">{n.body}</p>
          </div>
          <button type="button" className="text-sm font-medium text-brand-700 underline-offset-4 hover:underline" onClick={() => markRead.mutate(n.id)}>
            Dismiss
          </button>
        </div>
      ))}
    </section>
  );
}

export function DashboardPage() {
  const [month, setMonth] = useState(monthKey());
  const dashboard = useDashboard(month);
  const budgets = useBudgets(month);
  const connections = useConnections();

  if (connections.data && connections.data.length === 0) {
    return (
      <>
        <PageHeader title="Dashboard" />
        <Empty title="Connect your first bank">
          <p>See every account, your spending by category and your budgets in one place.</p>
          <Link to="/banks" className="btn-primary mt-4">
            Connect a bank
          </Link>
        </Empty>
      </>
    );
  }

  return (
    <div className="space-y-4">
      <PageHeader title="Dashboard" actions={<MonthPicker month={month} onChange={setMonth} />} />
      <RenewBanner />
      <Alerts />
      {dashboard.isPending && <Loading />}
      <ErrorMessage error={dashboard.error} />
      {dashboard.data?.currencies.length === 0 && <Empty title={`No transactions in ${monthLabel(month)}`} />}
      {dashboard.data?.currencies.map((summary) => (
        <section key={summary.currency} className="space-y-4" aria-label={`${summary.currency} summary`}>
          <div className="grid grid-cols-2 gap-3">
            <div className="card">
              <p className="text-sm text-muted">Spent in {monthLabel(month)}</p>
              <p className="text-2xl font-bold">
                <Money amount={summary.spending} currency={summary.currency} />
              </p>
            </div>
            <div className="card">
              <p className="text-sm text-muted">Income</p>
              <p className="text-2xl font-bold text-brand-700">
                <Money amount={summary.income} currency={summary.currency} />
              </p>
            </div>
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="card">
              <h2 className="mb-3 font-semibold">Spending by category</h2>
              {summary.by_category.length ? <SpendByCategory summary={summary} /> : <p className="text-sm text-muted">No spending this month.</p>}
            </div>
            <div className="card">
              <h2 className="mb-3 font-semibold">Last 6 months</h2>
              <MonthlyTrend summary={summary} />
            </div>
          </div>
        </section>
      ))}
      {budgets.data && budgets.data.length > 0 && (
        <section className="card space-y-4" aria-label="Budgets">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold">Budgets</h2>
            <Link to="/budgets" className="text-sm font-medium text-brand-700 underline-offset-4 hover:underline">
              Manage
            </Link>
          </div>
          {budgets.data.map((b) => (
            <BudgetBar key={b.id} label={b.category_name} spent={b.spent} limit={b.limit_amount} percent={b.percent_used} status={b.status} currency={b.currency} />
          ))}
        </section>
      )}
    </div>
  );
}
