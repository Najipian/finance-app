import { type ReactNode, useEffect, useState } from "react";
import { Link, useLocation } from "react-router";

import {
  useAccounts,
  useBudgets,
  useConnections,
  useDashboard,
  useMarkRead,
  useNotifications,
  useStartConsent,
  useTransactions,
} from "../api/hooks";
import type { Budget, CurrencySummary } from "../api/types";
import { CategoryBars, MonthlyTrend } from "../components/charts";
import { Icon } from "../components/icons";
import { BudgetBar, Empty, ErrorMessage, Money, PageHeader, Skeleton } from "../components/ui";
import { addMonths, byCurrency, formatMoney, formatShortDate, isNegative, monthKey, monthLabel, subtractMoney } from "../lib/format";

const RECENT_COUNT = 5;
const ACCOUNTS_SHOWN = 5;

function longMonth(key: string): string {
  const [year, month] = key.split("-").map(Number);
  return new Intl.DateTimeFormat("en-GB", { month: "long", year: "numeric" }).format(new Date(year, month - 1, 1));
}

export function MonthPicker({ month, onChange }: { month: string; onChange: (m: string) => void }) {
  const current = monthKey();
  const step = "rounded-full p-1.5 text-muted hover:bg-black/5 hover:text-ink disabled:opacity-30 disabled:hover:bg-transparent";
  return (
    <div className="flex items-center gap-1 rounded-full bg-white px-1 py-1 ring-1 ring-black/10" role="group" aria-label="Month">
      <button type="button" className={step} onClick={() => onChange(addMonths(month, -1))} aria-label="Previous month">
        <Icon name="chevronLeft" className="size-4" />
      </button>
      <span className="min-w-20 text-center text-sm font-medium tabular-nums" aria-live="polite">
        {monthLabel(month)}
      </span>
      <button type="button" className={step} onClick={() => onChange(addMonths(month, 1))} disabled={month >= current} aria-label="Next month">
        <Icon name="chevronRight" className="size-4" />
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
        <div key={c.id} role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-amber-50 p-4 ring-1 ring-amber-300">
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
  const { hash } = useLocation();

  // The header bell links to "/#alerts"; scroll there once alerts have rendered.
  const ready = data !== undefined;
  useEffect(() => {
    if (ready && hash === "#alerts") document.getElementById("alerts")?.scrollIntoView({ block: "start" });
  }, [ready, hash]);

  if (!data || data.length === 0) return null;
  return (
    <section id="alerts" aria-label="Alerts" className="scroll-mt-20 space-y-2">
      {data.map((n) => (
        <div key={n.id} className="flex items-start justify-between gap-3 rounded-2xl bg-white p-4 ring-1 ring-danger/25">
          <div className="flex gap-3">
            <Icon name="alert" className="mt-0.5 size-5 shrink-0 text-danger" />
            <div>
              <p className="text-sm font-medium text-danger">{n.title}</p>
              <p className="text-sm text-muted">{n.body}</p>
            </div>
          </div>
          <button type="button" className="text-sm font-medium text-brand-700 underline-offset-4 hover:underline" onClick={() => markRead.mutate(n.id)}>
            Dismiss
          </button>
        </div>
      ))}
    </section>
  );
}

function StatCard({ label, children, footnote }: { label: string; children: ReactNode; footnote?: ReactNode }) {
  return (
    <div className="card">
      <p className="text-sm text-muted">{label}</p>
      <p className="mt-1 text-[26px] leading-tight font-semibold tracking-tight">{children}</p>
      {footnote && <div className="mt-1 text-sm text-muted">{footnote}</div>}
    </div>
  );
}

/** Net worth from current balances; the primary currency leads, others are listed below. */
function NetWorthCard() {
  const { data, isPending } = useAccounts();
  if (isPending) return <StatSkeleton />;
  const [primary, ...others] = byCurrency(data?.totals ?? []);
  if (!primary) return <StatCard label="Net worth">–</StatCard>;
  return (
    <StatCard
      label={`Net worth · ${primary.account_count} account${primary.account_count === 1 ? "" : "s"}`}
      footnote={others.length > 0 && others.map((t) => `+ ${formatMoney(t.amount, t.currency)}`).join(" · ")}
    >
      <Money amount={primary.amount} currency={primary.currency} />
    </StatCard>
  );
}

function SpendingCard({ summary, month }: { summary: CurrencySummary; month: string }) {
  const previousKey = addMonths(month, -1);
  const previous = summary.trend.find((m) => m.month === previousKey);
  const isCurrent = month === monthKey();
  let footnote: ReactNode = null;
  if (previous && Number(previous.spending) > 0) {
    const diff = subtractMoney(summary.spending, previous.spending);
    const less = isNegative(diff);
    const amount = formatMoney(less ? diff.slice(1) : diff, summary.currency);
    const prevName = monthLabel(previousKey).split(" ")[0];
    footnote = (
      <span className={less ? "text-brand-700" : undefined}>
        {amount} {less ? "less" : "more"} than {prevName}
        {isCurrent && " so far"}
      </span>
    );
  }
  return (
    <StatCard label={`Spent in ${monthLabel(month).split(" ")[0]}`} footnote={footnote}>
      <Money amount={summary.spending} currency={summary.currency} />
    </StatCard>
  );
}

function BudgetsCard({ budgets }: { budgets: Budget[] | undefined }) {
  if (!budgets) return <StatSkeleton />;
  if (budgets.length === 0) {
    return (
      <StatCard label="Budgets" footnote={<Link to="/budgets" className="font-medium text-brand-700 hover:underline">Set a budget</Link>}>
        None yet
      </StatCard>
    );
  }
  const over = budgets.filter((b) => b.status === "exceeded");
  const near = budgets.filter((b) => b.status === "warning");
  const worst = over[0] ?? near[0];
  return (
    <StatCard
      label={`Budgets · ${budgets.length} set`}
      footnote={
        worst ? (
          <span>
            {worst.category_name} {formatMoney(worst.spent, worst.currency)} / {formatMoney(worst.limit_amount, worst.currency)}
          </span>
        ) : (
          "Every budget is on track"
        )
      }
    >
      {over.length > 0 ? (
        <span className="text-danger">{over.length} over</span>
      ) : near.length > 0 ? (
        <span className="text-warning">{near.length} near limit</span>
      ) : (
        <span className="text-brand-700">On track</span>
      )}
    </StatCard>
  );
}

function StatSkeleton() {
  return (
    <div className="card space-y-3" aria-hidden="true">
      <Skeleton className="h-3.5 w-1/2" />
      <Skeleton className="h-7 w-2/3" />
      <Skeleton className="h-3.5 w-2/5" />
    </div>
  );
}

function SectionCard({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="card" aria-label={title}>
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="font-medium">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function ViewAll({ to, label = "View all" }: { to: string; label?: string }) {
  return (
    <Link to={to} className="flex items-center gap-1 text-sm text-brand-700 hover:underline">
      {label}
      <Icon name="arrowRight" className="size-4" />
    </Link>
  );
}

function RecentActivity() {
  const { data, isPending } = useTransactions({ limit: RECENT_COUNT, offset: 0 });
  return (
    <SectionCard title="Recent activity" action={<ViewAll to="/transactions" />}>
      {isPending ? (
        <RowsSkeleton rows={RECENT_COUNT} />
      ) : !data || data.items.length === 0 ? (
        <p className="text-sm text-muted">No transactions yet.</p>
      ) : (
        <ul className="-my-2 divide-y divide-black/5">
          {data.items.map((t) => (
            <li key={t.id} className="flex items-center justify-between gap-3 py-2.5 text-sm">
              <div className="min-w-0">
                <p className="truncate">{t.merchant ?? t.description}</p>
                <p className="text-xs text-muted">
                  {formatShortDate(t.booking_date)}
                  {t.status === "pending" && " · pending"}
                </p>
              </div>
              <span className="shrink-0 font-medium">
                <Money amount={t.amount} currency={t.currency} signed />
              </span>
            </li>
          ))}
        </ul>
      )}
    </SectionCard>
  );
}

function AccountsSummary() {
  const { data, isPending } = useAccounts();
  const accounts = byCurrency(data?.accounts ?? []);
  return (
    <SectionCard title="Accounts" action={<ViewAll to="/accounts" />}>
      {isPending ? (
        <RowsSkeleton rows={3} />
      ) : accounts.length === 0 ? (
        <p className="text-sm text-muted">No accounts yet.</p>
      ) : (
        <ul className="-my-2 divide-y divide-black/5">
          {accounts.slice(0, ACCOUNTS_SHOWN).map((a) => (
            <li key={a.id} className="flex items-center justify-between gap-3 py-2.5 text-sm">
              <div className="flex min-w-0 items-center gap-3">
                <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-700">
                  <Icon name="wallet" className="size-4" />
                </span>
                <div className="min-w-0">
                  <p className="truncate">{a.name}</p>
                  <p className="truncate text-xs text-muted">
                    {a.institution_name}
                    {a.account_number_masked && ` · ${a.account_number_masked}`}
                  </p>
                </div>
              </div>
              <span className="shrink-0 font-medium">
                {a.balance ? <Money amount={a.balance.amount} currency={a.balance.currency} /> : <span className="text-muted">–</span>}
              </span>
            </li>
          ))}
          {accounts.length > ACCOUNTS_SHOWN && (
            <li className="py-2.5 text-sm text-muted">
              {accounts.length - ACCOUNTS_SHOWN} more account{accounts.length - ACCOUNTS_SHOWN === 1 ? "" : "s"}
            </li>
          )}
        </ul>
      )}
    </SectionCard>
  );
}

function RowsSkeleton({ rows }: { rows: number }) {
  return (
    <div className="space-y-4" aria-hidden="true">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center justify-between gap-4">
          <div className="flex-1 space-y-2">
            <Skeleton className="h-3.5 w-1/2" />
            <Skeleton className="h-3 w-1/4" />
          </div>
          <Skeleton className="h-4 w-16" />
        </div>
      ))}
    </div>
  );
}

function SpendingSections({ summary, month, overBudget }: { summary: CurrencySummary; month: string; overBudget: ReadonlySet<string> }) {
  return (
    <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
      <SectionCard title={`Where it went · ${summary.currency}`}>
        {summary.by_category.length ? (
          <CategoryBars summary={summary} overBudget={overBudget} />
        ) : (
          <p className="text-sm text-muted">No spending this month.</p>
        )}
      </SectionCard>
      <SectionCard title="Last 6 months">
        <MonthlyTrend summary={summary} month={month} />
      </SectionCard>
    </div>
  );
}

function DashboardSkeleton() {
  return (
    <div role="status" className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
      <span className="sr-only">Loading your overview…</span>
      {[0, 1].map((i) => (
        <div key={i} className="card space-y-4" aria-hidden="true">
          <Skeleton className="h-4 w-1/3" />
          <Skeleton className="h-40 w-full" />
        </div>
      ))}
    </div>
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
        <PageHeader title="Overview" />
        <Empty title="Connect your first bank">
          <p>See every account, your spending by category and your budgets in one place.</p>
          <Link to="/banks" className="btn-primary mt-4">
            Connect a bank
          </Link>
        </Empty>
      </>
    );
  }

  const [primary, ...others] = byCurrency(dashboard.data?.currencies ?? []);
  const overBudget = new Set((budgets.data ?? []).filter((b) => b.status === "exceeded").map((b) => b.category_id));

  return (
    <div className="space-y-5">
      <PageHeader title="Overview" subtitle={longMonth(month)} actions={<MonthPicker month={month} onChange={setMonth} />} />
      <RenewBanner />
      <Alerts />

      <div className="grid gap-4 sm:grid-cols-3">
        <NetWorthCard />
        {dashboard.isPending ? (
          <StatSkeleton />
        ) : primary ? (
          <SpendingCard summary={primary} month={month} />
        ) : (
          <StatCard label={`Spent in ${monthLabel(month).split(" ")[0]}`}>–</StatCard>
        )}
        <BudgetsCard budgets={budgets.data} />
      </div>

      <ErrorMessage error={dashboard.error} />
      {dashboard.isPending && <DashboardSkeleton />}
      {dashboard.data && !primary && <Empty title={`No transactions in ${monthLabel(month)}`} />}
      {primary && <SpendingSections summary={primary} month={month} overBudget={overBudget} />}

      <div className="grid gap-4 lg:grid-cols-2">
        <RecentActivity />
        <AccountsSummary />
      </div>

      {budgets.data && budgets.data.length > 0 && (
        <SectionCard title="Budgets" action={<ViewAll to="/budgets" label="Manage" />}>
          <div className="grid gap-x-8 gap-y-5 md:grid-cols-2">
            {budgets.data.map((b) => (
              <BudgetBar key={b.id} label={b.category_name} spent={b.spent} limit={b.limit_amount} percent={b.percent_used} status={b.status} currency={b.currency} />
            ))}
          </div>
        </SectionCard>
      )}

      {/* Secondary currencies appear only when there was spending in them this month. */}
      {others.filter((summary) => summary.by_category.length > 0).map((summary) => (
        <SpendingSections key={summary.currency} summary={summary} month={month} overBudget={overBudget} />
      ))}
    </div>
  );
}
