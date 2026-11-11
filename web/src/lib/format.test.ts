import { addMonths, formatMoney, isNegative, monthKey, monthLabel } from "./format";

describe("format", () => {
  it("formats decimal strings as currency without float arithmetic", () => {
    expect(formatMoney("1523.47", "GBP")).toBe("£1,523.47");
    expect(formatMoney("-0.10", "GBP")).toBe("-£0.10");
    expect(formatMoney("642.10", "EUR")).toBe("€642.10");
  });

  it("shifts months across year boundaries", () => {
    expect(addMonths("2026-01", -1)).toBe("2025-12");
    expect(addMonths("2026-12", 1)).toBe("2027-01");
    expect(monthKey(new Date(2026, 10, 30))).toBe("2026-11");
    expect(monthLabel("2026-11")).toBe("Nov 2026");
  });

  it("detects negative amounts from the string", () => {
    expect(isNegative("-3.20")).toBe(true);
    expect(isNegative("3.20")).toBe(false);
  });
});
