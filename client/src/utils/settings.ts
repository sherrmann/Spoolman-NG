import { useGetSetting } from "./querySettings";

export function useCurrency() {
  const { data: currency } = useGetSetting("currency");
  return JSON.parse(currency?.value ?? '"EUR"');
}

/**
 * Whether large weights/lengths should be shown auto-scaled to kg/m instead of raw g/mm (#85).
 * Defaults to false (current behavior) when the setting is unset.
 */
export function useUnitScaling(): boolean {
  return JSON.parse(useGetSetting("unit_scaling").data?.value ?? "false");
}

export function getCurrencySymbol(locale: string | undefined, currency: string) {
  return (0)
    .toLocaleString(locale, {
      style: "currency",
      currency,
      currencyDisplay: "narrowSymbol",
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    })
    .replace(/\d/g, "")
    .trim();
}

export function useCurrencyFormatter() {
  const currency = useCurrency();
  const roundPrices = JSON.parse(useGetSetting("round_prices").data?.value ?? "false");

  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: currency,
    currencyDisplay: "narrowSymbol",
    notation: roundPrices ? "compact" : "standard",
  });
}
