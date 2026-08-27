import type { UsageBucket } from './types';

/**
 * Shorten a usage bucket's period label for the chart's x-axis: a year stays "YYYY", a month
 * becomes "MMM YY" in the given locale, and day/week keep just the "MM-DD" tail of their ISO
 * date.
 *
 * Lives outside the component so it can be tested: the server labels a bucket by its start and
 * the shape varies by granularity, so an off-by-one in the slice or a month parsed as NaN would
 * otherwise only show up as odd axis text in one bucket mode.
 *
 * `locale` is passed in rather than read from the i18n runtime so the formatting is a pure
 * function of its arguments.
 */
export function axisLabel(period: string, bucket: UsageBucket, locale: string): string {
	if (bucket === 'year') return period;
	if (bucket === 'month') {
		const [year, month] = period.split('-').map(Number);
		// A malformed period is rendered as-is rather than as "Invalid Date": it is data from the
		// server, and showing it unchanged makes the cause visible instead of masking it.
		if (!year || !month || month < 1 || month > 12) return period;
		return new Intl.DateTimeFormat(locale, { month: 'short', year: '2-digit' }).format(
			new Date(year, month - 1, 1)
		);
	}
	return period.slice(5); // "YYYY-MM-DD" -> "MM-DD"
}
