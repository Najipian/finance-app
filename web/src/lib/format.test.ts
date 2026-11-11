import {
  addMonths,
  byCurrency,
  formatCompactMoney,
  formatMoney,
  formatRelative,
  isNegative,
  monthKey,
  monthLabel,
  subtractMoney,
  toMinor,
} from "./format";

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

describe("dashboard helpers", () => {
  it("subtracts money exactly in pence, never in floating point", () => {
    // 0.3 - 0.1 is 0.19999999999999998 in floating point.
    expect(subtractMoney("0.30", "0.10")).toBe("0.20");
    expect(subtractMoney("305.86", "1730.12")).toBe("-1424.26");
    expect(subtractMoney("-1.5", "2")).toBe("-3.50");
    expect(toMinor("12.3")).toBe(1230n);
  });

  it("formats chart axis labels compactly so outliers stay readable", () => {
    // ICU versions differ on the suffix case ("K" vs "k"), so compare case-insensitively.
    expect(formatCompactMoney(1200, "GBP")).toMatch(/^£1\.2k$/i);
    expect(formatCompactMoney(30_000_000, "GBP")).toMatch(/^£30m$/i);
    expect(formatCompactMoney(0, "GBP")).toBe("£0");
  });

  it("puts GBP first, then other currencies alphabetically", () => {
    const sorted = byCurrency([{ currency: "USD" }, { currency: "EUR" }, { currency: "GBP" }]);
    expect(sorted.map((c) => c.currency)).toEqual(["GBP", "EUR", "USD"]);
  });

  it("describes sync times relative to now", () => {
    const now = new Date("2026-11-11T12:00:00Z");
    expect(formatRelative("2026-11-11T11:59:40Z", now)).toBe("just now");
    expect(formatRelative("2026-11-11T11:56:00Z", now)).toBe("4 min ago");
    expect(formatRelative("2026-11-11T09:00:00Z", now)).toBe("3 h ago");
    expect(formatRelative("2026-11-10T12:00:00Z", now)).toBe("1 day ago");
  });
});
