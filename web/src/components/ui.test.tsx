import { render, screen } from "@testing-library/react";

import { BudgetBar, Money } from "./ui";

describe("BudgetBar", () => {
  it("exposes progress accessibly and states the status in words (BR-10)", () => {
    render(<BudgetBar label="Eating out" spent="240.00" limit="300.00" percent="80.0" status="warning" currency="GBP" />);

    const bar = screen.getByRole("progressbar", { name: "Eating out budget used" });
    expect(bar).toHaveAttribute("aria-valuenow", "80");
    expect(bar).toHaveAttribute("aria-valuetext", "80.0% used, warning");
    expect(screen.getByText("80% used")).toBeInTheDocument();
    expect(screen.getByText("£240.00 of £300.00")).toBeInTheDocument();
  });

  it("caps the bar width at 100% when over budget", () => {
    const { container } = render(
      <BudgetBar label="Travel" spent="450.00" limit="300.00" percent="150.0" status="exceeded" currency="GBP" />,
    );

    expect(screen.getByText("Over budget")).toBeInTheDocument();
    expect(container.querySelector('[role="progressbar"] > div')).toHaveStyle({ width: "100%" });
  });
});

describe("Money", () => {
  it("marks positive amounts when signed", () => {
    render(<Money amount="2850.00" currency="GBP" signed />);
    expect(screen.getByText("+£2,850.00")).toBeInTheDocument();
  });
});
