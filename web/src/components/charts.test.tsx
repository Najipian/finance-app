import { render, screen, within } from "@testing-library/react";

import type { CurrencySummary } from "../api/types";
import { CategoryBars } from "./charts";

const summary: CurrencySummary = {
  currency: "GBP",
  spending: "305.86",
  income: "0.00",
  trend: [],
  by_category: [
    { category_id: "c1", name: "Fuel", amount: "72.28", share_percent: "23.6" },
    { category_id: "c2", name: "Health and beauty", amount: "65.93", share_percent: "21.6" },
    { category_id: "c3", name: "Shopping", amount: "51.85", share_percent: "17.0" },
    { category_id: "c4", name: "Eating out", amount: "46.30", share_percent: "15.1" },
    { category_id: null, name: "Uncategorized", amount: "40.00", share_percent: "13.1" },
    { category_id: "c6", name: "Transport", amount: "19.40", share_percent: "6.3" },
    { category_id: "c7", name: "Groceries", amount: "10.10", share_percent: "3.3" },
  ],
};

describe("CategoryBars", () => {
  it("ranks the top five categories and groups the rest exactly (BR-11)", () => {
    render(<CategoryBars summary={summary} />);

    const items = within(screen.getByRole("list", { name: "Spending by category in GBP" })).getAllByRole("listitem");
    expect(items).toHaveLength(6);
    expect(items[0]).toHaveTextContent("Fuel");
    // 19.40 + 10.10 summed in pence.
    expect(items[5]).toHaveTextContent("2 more categories");
    expect(items[5]).toHaveTextContent("£29.50");
  });

  it("flags categories whose budget is exceeded in words, not colour alone (BR-10)", () => {
    render(<CategoryBars summary={summary} overBudget={new Set(["c4"])} />);

    const eatingOut = screen.getByText("Eating out").closest("li");
    expect(eatingOut).toHaveTextContent("Over budget");
    expect(screen.getAllByText("Over budget")).toHaveLength(1);
  });
});
