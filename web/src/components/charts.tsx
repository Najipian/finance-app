import {
  ArcElement,
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LinearScale,
  Tooltip,
} from "chart.js";
import { Bar, Doughnut } from "react-chartjs-2";

import type { CurrencySummary } from "../api/types";
import { formatMoney, monthLabel } from "../lib/format";

ChartJS.register(ArcElement, BarElement, CategoryScale, LinearScale, Tooltip, Legend);

// Distinguishable palette (also readable for common colour-vision deficiencies).
const PALETTE = ["#0f5d5a", "#2a9d8f", "#e9c46a", "#f4a261", "#e76f51", "#6d597a", "#457b9d", "#a8dadc", "#b5838d", "#606c38", "#9c6644", "#8d99ae"];

/** Spending by category. The list beside it is the text alternative (WCAG 1.1.1). */
export function SpendByCategory({ summary }: { summary: CurrencySummary }) {
  const items = summary.by_category;
  return (
    <div className="grid gap-4 sm:grid-cols-2 sm:items-center">
      <div className="mx-auto w-full max-w-60" aria-hidden="true">
        <Doughnut
          data={{
            labels: items.map((c) => c.name),
            datasets: [
              {
                data: items.map((c) => Number(c.amount)),
                backgroundColor: items.map((_, i) => PALETTE[i % PALETTE.length]),
                borderWidth: 0,
              },
            ],
          }}
          options={{ plugins: { legend: { display: false } }, cutout: "62%" }}
        />
      </div>
      <ul className="space-y-1.5 text-sm" aria-label={`Spending by category in ${summary.currency}`}>
        {items.map((c, i) => (
          <li key={c.category_id ?? "uncategorized"} className="flex items-center gap-2">
            <span className="size-3 shrink-0 rounded-sm" style={{ background: PALETTE[i % PALETTE.length] }} />
            <span className="flex-1 truncate">{c.name}</span>
            <span className="tabular-nums">{formatMoney(c.amount, summary.currency)}</span>
            <span className="w-12 text-right tabular-nums text-muted">{c.share_percent}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Six-month spending vs income, with a visually hidden table as the text alternative. */
export function MonthlyTrend({ summary }: { summary: CurrencySummary }) {
  const labels = summary.trend.map((m) => monthLabel(m.month));
  return (
    <div>
      <div aria-hidden="true" className="h-56">
        <Bar
          data={{
            labels,
            datasets: [
              { label: "Spending", data: summary.trend.map((m) => Number(m.spending)), backgroundColor: "#e76f51", borderRadius: 4 },
              { label: "Income", data: summary.trend.map((m) => Number(m.income)), backgroundColor: "#2a9d8f", borderRadius: 4 },
            ],
          }}
          options={{
            maintainAspectRatio: false,
            plugins: { legend: { position: "bottom" } },
            scales: { y: { ticks: { callback: (v) => formatMoney(Number(v), summary.currency) } } },
          }}
        />
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
