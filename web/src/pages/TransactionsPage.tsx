import { useState } from "react";

import { useCategories, useRecategorize, useTransactions } from "../api/hooks";
import { ErrorMessage, Loading, Money, PageHeader } from "../components/ui";
import { formatDate } from "../lib/format";

const PAGE = 25;

export function TransactionsPage() {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [applyToSimilar, setApplyToSimilar] = useState(true);
  const transactions = useTransactions({ q: q.length >= 2 ? q : undefined, status: status || undefined, limit: PAGE, offset });
  const { data: categories } = useCategories();
  const recategorize = useRecategorize();
  const page = transactions.data;

  return (
    <div className="space-y-4">
      <PageHeader title="Transactions" />
      <div className="card grid gap-3 sm:grid-cols-[1fr_auto_auto] sm:items-end">
        <div>
          <label htmlFor="search" className="label">
            Search
          </label>
          <input
            id="search"
            type="search"
            className="input"
            placeholder="Merchant or description"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setOffset(0);
            }}
          />
        </div>
        <div>
          <label htmlFor="status" className="label">
            Status
          </label>
          <select
            id="status"
            className="input"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setOffset(0);
            }}
          >
            <option value="">All</option>
            <option value="booked">Booked</option>
            <option value="pending">Pending</option>
          </select>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={applyToSimilar} onChange={(e) => setApplyToSimilar(e.target.checked)} className="size-4 accent-brand-700" />
          Apply category to similar
        </label>
      </div>

      <ErrorMessage error={transactions.error ?? recategorize.error} />
      {transactions.isPending && <Loading />}
      {page && (
        <div className="card p-0 sm:p-0">
          <ul className="divide-y divide-black/5">
            {page.items.map((t) => (
              <li key={t.id} className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-2 px-4 py-3 sm:grid-cols-[1fr_12rem_8rem] sm:items-center">
                <div className="min-w-0">
                  <p className="truncate font-medium">{t.merchant ?? t.description}</p>
                  <p className="text-xs text-muted">
                    {formatDate(t.booking_date)} {t.status === "pending" && <span className="font-semibold text-warning">· pending</span>}
                  </p>
                </div>
                <p className="text-right font-semibold sm:order-last">
                  <Money amount={t.amount} currency={t.currency} signed />
                </p>
                <div className="col-span-2 sm:col-span-1">
                  <label htmlFor={`cat-${t.id}`} className="sr-only">
                    Category for {t.merchant ?? t.description}
                  </label>
                  <select
                    id={`cat-${t.id}`}
                    className="input py-1.5"
                    value={t.category_id ?? ""}
                    disabled={recategorize.isPending}
                    onChange={(e) =>
                      recategorize.mutate({ id: t.id, category_id: e.target.value || null, apply_to_similar: applyToSimilar && !!e.target.value })
                    }
                  >
                    <option value="">Uncategorized</option>
                    {categories?.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                </div>
              </li>
            ))}
          </ul>
          <div className="flex items-center justify-between border-t border-black/5 px-4 py-3 text-sm">
            <span className="text-muted">
              {page.total === 0 ? "No transactions" : `${offset + 1}–${Math.min(offset + PAGE, page.total)} of ${page.total}`}
            </span>
            <div className="flex gap-2">
              <button type="button" className="btn-secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
                Previous
              </button>
              <button type="button" className="btn-secondary" disabled={offset + PAGE >= page.total} onClick={() => setOffset(offset + PAGE)}>
                Next
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
