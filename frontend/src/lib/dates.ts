/** Date-only helpers working in UTC so local time zones never shift a day. */
const DAY = 86_400_000;

export function parseDay(iso: string): number {
  const [y, m, d] = iso.split('-').map(Number) as [number, number, number];
  return Date.UTC(y, m - 1, d) / DAY;
}

export function formatDay(day: number): string {
  return new Date(day * DAY).toISOString().slice(0, 10);
}

export function addDays(iso: string, days: number): string {
  return formatDay(parseDay(iso) + days);
}

export function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

export function isWeekend(day: number): boolean {
  const dow = new Date(day * DAY).getUTCDay();
  return dow === 0 || dow === 6;
}

export function monthLabel(day: number): string {
  return new Date(day * DAY).toLocaleDateString(undefined, {
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  });
}

/** Monday-first weeks covering the month of ``iso``. */
export function monthGrid(iso: string): string[][] {
  const [y, m] = iso.split('-').map(Number) as [number, number];
  const first = Date.UTC(y, m - 1, 1) / DAY;
  const offset = (new Date(first * DAY).getUTCDay() + 6) % 7;
  const start = first - offset;
  const weeks: string[][] = [];
  for (let w = 0; w < 6; w++) {
    const week = Array.from({ length: 7 }, (_, i) => formatDay(start + w * 7 + i));
    if (w > 3 && !week.some((d) => d.slice(0, 7) === iso.slice(0, 7))) break;
    weeks.push(week);
  }
  return weeks;
}
