import { type FormEvent, useState } from "react";

import { useBudgets, useCategories, useDeleteBudget, useSetBudget } from "../api/hooks";
import { BudgetBar, ErrorMessage, Loading, PageHeader } from "../components/ui";
import { monthKey, monthLabel } from "../lib/format";
import { MonthPicker } from "./DashboardPage";

export function BudgetsPage() {
  const [month, setMonth] = useState(monthKey());
  const budgets = useBudgets(month);
  const { data: categories } = useCategories();
  const setBudget = useSetBudget();
  const deleteBudget = useDeleteBudget();
  const [categoryId, setCategoryId] = useState("");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("GBP");

  function submit(event: FormEvent) {
    event.preventDefault();
    setBudget.mutate(
      { category_id: categoryId, month, limit_amount: amount, currency },
      { onSuccess: () => setAmount("") },
    );
  }

  return (
    <div className="space-y-4">
      <PageHeader title="Budgets" actions={<MonthPicker month={month} onChange={setMonth} />} />
      <form onSubmit={submit} className="card grid gap-3 sm:grid-cols-[1fr_9rem_6rem_auto] sm:items-end" aria-label="Set a budget">
        <div>
          <label htmlFor="budget-category" className="label">
            Category
          </label>
          <select id="budget-category" required className="input" value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
            <option value="" disabled>
              Choose…
            </option>
            {categories?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="budget-amount" className="label">
            Monthly limit
          </label>
          <input
            id="budget-amount"
            required
            inputMode="decimal"
            pattern="^\d+(\.\d{1,2})?$"
            title="An amount like 300 or 300.00"
            className="input"
            placeholder="300.00"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
        </div>
        <div>
          <label htmlFor="budget-currency" className="label">
            Currency
          </label>
          <select id="budget-currency" className="input" value={currency} onChange={(e) => setCurrency(e.target.value)}>
            <option>GBP</option>
            <option>EUR</option>
          </select>
        </div>
        <button type="submit" className="btn-primary" disabled={setBudget.isPending}>
          Save
        </button>
      </form>
      <ErrorMessage error={setBudget.error ?? deleteBudget.error ?? budgets.error} />
      {budgets.isPending && <Loading />}
      {budgets.data?.length === 0 && <p className="text-sm text-muted">No budgets for {monthLabel(month)} yet.</p>}
      <ul className="space-y-3">
        {budgets.data?.map((b) => (
          <li key={b.id} className="card">
            <BudgetBar label={b.category_name} spent={b.spent} limit={b.limit_amount} percent={b.percent_used} status={b.status} currency={b.currency} />
            <div className="mt-3 text-right">
              <button type="button" className="text-sm font-medium text-danger underline-offset-4 hover:underline" onClick={() => deleteBudget.mutate(b.id)}>
                Remove budget
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
