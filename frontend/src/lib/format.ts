import { addDays, parseDay } from './dates';

/** 95 -> "1h 35m", 60 -> "1h", 5 -> "5m", 0 -> "0m". */
export function formatMinutes(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  if (!h) return `${m}m`;
  return m ? `${h}h ${m}m` : `${h}h`;
}

/** Hours with one decimal, for dense tables: 90 -> "1.5". */
export function hours(minutes: number): string {
  return (minutes / 60).toFixed(minutes % 60 ? 1 : 0);
}

/** Parse "1h 30m", "1.5h", "90m", "90" (minutes) or "1:30". Returns null when invalid. */
export function parseDuration(text: string): number | null {
  const s = text.trim().toLowerCase();
  if (!s) return null;
  const colon = /^(\d+):([0-5]\d)$/.exec(s);
  if (colon) return Number(colon[1]) * 60 + Number(colon[2]);
  if (/^\d+$/.test(s)) return Number(s);
  const match = /^(?:(\d+(?:\.\d+)?)\s*h)?\s*(?:(\d+)\s*m)?$/.exec(s);
  if (!match || (!match[1] && !match[2])) return null;
  const total = Math.round(Number(match[1] ?? 0) * 60 + Number(match[2] ?? 0));
  return total > 0 ? total : null;
}

/** Monday of the week containing ``iso`` (ISO date strings, UTC-safe). */
export function mondayOf(iso: string): string {
  const dow = (new Date(parseDay(iso) * 86_400_000).getUTCDay() + 6) % 7;
  return addDays(iso, -dow);
}

export function shortDay(iso: string): string {
  return new Date(parseDay(iso) * 86_400_000).toLocaleDateString(undefined, {
    weekday: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  });
}

export function shortDate(iso: string): string {
  return new Date(parseDay(iso) * 86_400_000).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  });
}

export function currentQuarter(now = new Date()): string {
  return `${now.getFullYear()}-Q${Math.floor(now.getMonth() / 3) + 1}`;
}
