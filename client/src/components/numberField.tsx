import { NumberFieldProps } from "@refinedev/antd/dist/components/fields/types";
import { Typography } from "antd";
import { scaleUnitValue } from "../utils/parsing";

const { Text } = Typography;

function toLocaleStringSupportsOptions() {
  return !!(typeof Intl == "object" && Intl && typeof Intl.NumberFormat == "function");
}

type Props = NumberFieldProps & {
  unit: string;
  // #85: when true, large gram/millimeter values are shown auto-scaled (kg/m). Passed down from the
  // hook-reading page components so this stays a pure presentational component (no settings hook here).
  autoScale?: boolean;
};

/**
 * This field is used to display a number formatted according to the browser locale, right aligned. and uses {@link https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Intl `Intl`} to display date format.
 *
 * @see {@link https://refine.dev/docs/ui-frameworks/antd/components/fields/number} for more details.
 */
export const NumberFieldUnit = ({ value, locale, options, unit, autoScale }: Props) => {
  const scaled = scaleUnitValue(Number(value), unit, autoScale ?? false);
  // When scaled to kg/m, cap decimals (and drop trailing zeros) rather than inherit the base unit's
  // maximumFractionDigits (often 0), so 1500 g reads "1.5 kg" not "2 kg".
  const displayOptions =
    scaled.maxDecimals !== undefined
      ? { ...options, maximumFractionDigits: scaled.maxDecimals, minimumFractionDigits: 0 }
      : options;

  return (
    <Text>
      {toLocaleStringSupportsOptions() ? scaled.value.toLocaleString(locale, displayOptions) : scaled.value}{" "}
      {scaled.unit}
    </Text>
  );
};

/**
 * Like a {@link NumberFieldUnit} but for a range of numbers.
 * @param props
 * @returns
 */
export function NumberFieldUnitRange(props: {
  value: (number | null)[] | undefined;
  unit?: string;
  options?: Intl.NumberFormatOptions;
  autoScale?: boolean;
}) {
  const { value, unit, options, autoScale } = props;

  if (value === undefined) {
    console.warn("NumberFieldUnitRange received undefined value");
    return <></>;
  }

  if (!Array.isArray(value) || value.length !== 2) {
    console.warn("NumberFieldUnitRange received invalid value", value);
    return <></>;
  }

  const [min, max] = value;

  return (
    <>
      {min === null ? <></> : <NumberFieldUnit value={min} unit={unit ?? ""} options={options} autoScale={autoScale} />}
      {" \u2013 "}
      {max === null ? <></> : <NumberFieldUnit value={max} unit={unit ?? ""} options={options} autoScale={autoScale} />}
    </>
  );
}
