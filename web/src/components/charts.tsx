import { BarElement, CategoryScale, Chart as ChartJS, LinearScale, Tooltip } from "chart.js";
import { Bar } from "react-chartjs-2";

import type { CurrencySummary } from "../api/types";
import { formatCompactMoney, formatMoney, monthLabel, toMinor } from "../lib/format";

ChartJS.register(BarElement, CategoryScale, LinearScale, Tooltip);

const BRAND = "#0f5d5a";
const BRAND_SOFT = "#c9e4e1";
const INCOME = "#9ca3af";

/** How many categories get their own bar before the rest are grouped. */
const TOP_CATEGORIES = 5;

/** "24%", or "<1%" so a small but real share never reads as nothing. */
function sharePercent(share: string): string {
  const value = Number(share);
  return value > 0 && value < 1 ? "<1%" : `${Math.round(value)}%`;
}

function sumMinor(amounts: string[]): string {
  const total = amounts.reduce((acc, a) => acc + toMinor(a), 0n);
  return `${total / 100n}.${String(total % 100n).padStart(2, "0")}`;
}

/**
 * Spending by category as ranked horizontal bars. Bars compare lengths far better
 * than doughnut slices, and stay readable when one category dominates. Plain HTML,
 * so the list itself is the accessible version (no hidden duplicate needed).
 */
export function CategoryBars({
  summary,
  overBudget = new Set<string>(),
}: {
  summary: CurrencySummary;
  /** Category IDs whose budget is exceeded this month. */
  overBudget?: ReadonlySet<string>;
}) {
  const items = [...summary.by_category].sort((a, b) => Number(b.amount) - Number(a.amount));
  const top = items.slice(0, TOP_CATEGORIES);
  const rest = items.slice(TOP_CATEGORIES);
  const max = Math.max(...top.map((c) => Number(c.amount)), 1);

  return (
    <ul className="space-y-3.5" aria-label={`Spending by category in ${summary.currency}`}>
      {top.map((c) => {
        const over = c.category_id !== null && overBudget.has(c.category_id);
        const uncategorized = c.category_id === null;
        const colour = over ? "bg-danger" : uncategorized ? "bg-black/20" : "bg-brand-700";
        return (
          <li key={c.category_id ?? "uncategorized"}>
            <div className="mb-1.5 flex items-baseline justify-between gap-3 text-sm">
              <span className="truncate">
                {c.name}
                {over && <span className="ml-1.5 text-xs font-medium text-danger">Over budget</span>}
              </span>
              <span className="shrink-0 tabular-nums">
                {formatMoney(c.amount, summary.currency)}
                <span className="ml-2 inline-block w-10 text-right text-xs text-muted">{sharePercent(c.share_percent)}</span>
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-black/5" aria-hidden="true">
              <div className={`h-full rounded-full ${colour}`} style={{ width: `${Math.max(2, (Number(c.amount) / max) * 100)}%` }} />
            </div>
          </li>
        );
      })}
      {rest.length > 0 && (
        <li className="flex justify-between pt-1 text-sm text-muted">
          <span>
            {rest.length} more categor{rest.length === 1 ? "y" : "ies"}
          </span>
          <span className="tabular-nums">{formatMoney(sumMinor(rest.map((c) => c.amount)), summary.currency)}</span>
        </li>
      )}
    </ul>
  );
}

/**
 * Six months of spending (selected month highlighted) with income for context.
 * Axis labels are compact ("£1.2k", "£30M") so a large outlier cannot push the axis
 * into unreadable full-precision currency. A visually hidden table is the text
 * alternative (WCAG 1.1.1).
 */
export function MonthlyTrend({ summary, month }: { summary: CurrencySummary; month: string }) {
  const labels = summary.trend.map((m) => monthLabel(m.month).split(" ")[0]);
  const highlight = summary.trend.map((m) => (m.month === month ? BRAND : BRAND_SOFT));
  return (
    <div>
      <div aria-hidden="true" className="h-52">
        <Bar
          data={{
            labels,
            datasets: [
              {
                label: "Spending",
                data: summary.trend.map((m) => Number(m.spending)),
                backgroundColor: highlight,
                borderRadius: 6,
                maxBarThickness: 28,
              },
              {
                label: "Income",
                data: summary.trend.map((m) => Number(m.income)),
                backgroundColor: INCOME,
                borderRadius: 6,
                maxBarThickness: 6,
              },
            ],
          }}
          options={{
            maintainAspectRatio: false,
            plugins: {
              legend: { display: false },
              tooltip: {
                callbacks: { label: (item) => `${item.dataset.label}: ${formatMoney(Number(item.raw), summary.currency)}` },
              },
            },
            scales: {
              x: { grid: { display: false }, border: { display: false } },
              y: {
                border: { display: false },
                grid: { color: "rgba(0,0,0,0.06)" },
                ticks: { maxTicksLimit: 5, callback: (v) => formatCompactMoney(Number(v), summary.currency) },
              },
            },
          }}
        />
      </div>
      <div className="mt-3 flex gap-4 text-xs text-muted" aria-hidden="true">
        <span className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-sm" style={{ background: BRAND }} />
          Spending
        </span>
        <span className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-sm" style={{ background: INCOME }} />
          Income
        </span>
      </div>
      <table className="sr-only">
        <caption>Spending and income by month in {summary.currency}</caption>
        <thead>
          <tr>
            <th>Month</th>
            <th>Spending</th>
            <th>Income</th>
          </tr>
        </thead>
        <tbody>
          {summary.trend.map((m) => (
            <tr key={m.month}>
              <td>{monthLabel(m.month)}</td>
              <td>{formatMoney(m.spending, summary.currency)}</td>
              <td>{formatMoney(m.income, summary.currency)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
