export const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

const MS_PER_DAY = 86_400_000;

/** Parses 'YYYY-MM-DD' (optionally followed by a time) as a local date. Returns null for any other format. */
export function parseISODate(value?: string | null): Date | null {
  if (!value) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value.trim());
  if (!match) return null;
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return Number.isNaN(date.getTime()) ? null : date;
}

const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
const daysBetween = (a: Date, b: Date) => Math.round((startOfDay(b).getTime() - startOfDay(a).getTime()) / MS_PER_DAY);

/** "15–19 Oct", "28 Oct – 2 Nov", or "15 Oct 2027" when the trip isn't in the current year. Null if start can't be parsed. */
export function formatDateRange(startISO?: string | null, endISO?: string | null, today: Date = new Date()): string | null {
  const start = parseISODate(startISO);
  if (!start) return null;
  const end = parseISODate(endISO);

  const showYear = start.getFullYear() !== today.getFullYear() || (!!end && end.getFullYear() !== start.getFullYear());
  const dayMonth = (d: Date) => `${d.getDate()} ${MONTHS[d.getMonth()]}${showYear ? ` ${d.getFullYear()}` : ''}`;

  if (!end || daysBetween(start, end) === 0) return dayMonth(start);

  const sameMonth = start.getMonth() === end.getMonth() && start.getFullYear() === end.getFullYear();
  if (sameMonth) {
    return `${start.getDate()}–${end.getDate()} ${MONTHS[start.getMonth()]}${showYear ? ` ${start.getFullYear()}` : ''}`;
  }
  return `${dayMonth(start)} – ${dayMonth(end)}`;
}

/** "In 23 days", "Tomorrow", "Starts today", or "Day 2 of 5" while the trip is on. Null once it's over or if dates are unusable. */
export function tripStatus(startISO?: string | null, endISO?: string | null, today: Date = new Date()): string | null {
  const start = parseISODate(startISO);
  if (!start) return null;
  const end = parseISODate(endISO);

  const untilStart = daysBetween(today, start);
  if (untilStart > 1) return `In ${untilStart} days`;
  if (untilStart === 1) return 'Tomorrow';

  if (end) {
    const untilEnd = daysBetween(today, end);
    if (untilEnd >= 0) {
      const total = daysBetween(start, end) + 1;
      const current = daysBetween(start, today) + 1;
      return untilStart === 0 && current === 1 ? 'Starts today' : `Day ${current} of ${total}`;
    }
    return null;
  }
  return untilStart === 0 ? 'Starts today' : null;
}
