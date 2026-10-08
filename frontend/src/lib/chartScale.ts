export const TICKS = 4;

/** Tick step from {1, 2, 5} x 10^n so every gridline lands on a round number. */
export function niceScale(value: number): { max: number; step: number } {
  const raw = Math.max(value, 1) / TICKS;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = Math.max(1, ([1, 2, 5, 10].find((m) => raw <= m * magnitude) ?? 10) * magnitude);
  return { max: step * TICKS, step };
}
