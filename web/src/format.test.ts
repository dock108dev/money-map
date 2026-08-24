import { describe, expect, it } from "vitest";

import { currency, currencyExact, monthLabel, shortDate, signedCurrencyExact } from "./format";

describe("shared display formatting", () => {
  it("keeps unavailable money explicit", () => {
    expect(currency(null)).toBe("—");
    expect(currencyExact(undefined)).toBe("—");
    expect(signedCurrencyExact(null)).toBe("—");
  });

  it("formats whole, exact, and signed dollar values consistently", () => {
    expect(currency("1234.56")).toBe("$1,235");
    expect(currencyExact("1234.5")).toBe("$1,234.50");
    expect(signedCurrencyExact("12.50")).toBe("+$12.50");
    expect(signedCurrencyExact("-12.50")).toBe("-$12.50");
  });

  it("uses UTC for stable date labels", () => {
    expect(monthLabel("2026-08-01")).toBe("Aug 2026");
    expect(shortDate("2026-08-01")).toBe("Aug 1");
  });
});
