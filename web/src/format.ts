const usd = (minimumFractionDigits: number, maximumFractionDigits: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits,
    maximumFractionDigits,
  });

const wholeDollarFormatter = usd(0, 0);
const exactDollarFormatter = usd(2, 2);

export const currency = (value: string | null | undefined) =>
  value == null ? "—" : wholeDollarFormatter.format(Number(value));

export const currencyExact = (value: string | null | undefined) =>
  value == null ? "—" : exactDollarFormatter.format(Number(value));

export const signedCurrencyExact = (value: string | null | undefined) => {
  if (value == null) return "—";
  return `${Number(value) > 0 ? "+" : ""}${currencyExact(value)}`;
};

export const monthLabel = (value: string) =>
  new Intl.DateTimeFormat("en-US", { month: "short", year: "numeric", timeZone: "UTC" }).format(
    new Date(value),
  );

export const shortDate = (value: string) =>
  new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" }).format(
    new Date(value),
  );
