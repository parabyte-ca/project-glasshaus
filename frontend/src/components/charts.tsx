import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';

import { niceScale, TICKS } from '../lib/chartScale';

/* Small inline-SVG charts. Colours come from the --series-* / --seq-* / --status-* tokens in
   index.css (validated for light and dark). Every chart has a hover/keyboard readout and a table. */

const DEFAULT_W = 640;
const PAD = { top: 12, right: 72, bottom: 24, left: 40 };

/** Track the rendered width so SVG text keeps its real size at any container width. */
function useWidth(): [React.RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(DEFAULT_W);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry && entry.contentRect.width > 0) setWidth(Math.round(entry.contentRect.width));
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

export interface Series {
  name: string;
  color: string;
  values: number[];
}

function DataTable({ caption, labels, series }: { caption: string; labels: string[]; series: Series[] }) {
  return (
    <details className="mt-1 text-xs">
      <summary className="cursor-pointer text-slate-600 dark:text-slate-400">Show data table</summary>
      <div className="mt-1 max-h-60 overflow-auto">
        <table className="w-full text-left tabular-nums">
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr>
              <th className="pr-3 font-medium">Date</th>
              {series.map((s) => (
                <th key={s.name} className="pr-3 font-medium">
                  {s.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {labels.map((label, i) => (
              <tr key={label}>
                <td className="pr-3">{label}</td>
                {series.map((s) => (
                  <td key={s.name} className="pr-3">
                    {s.values[i]}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function Legend({ series }: { series: Series[] }) {
  if (series.length < 2) return null;
  return (
    <ul className="mb-1 flex flex-wrap gap-3 text-xs text-slate-700 dark:text-slate-300">
      {series.map((s) => (
        <li key={s.name} className="flex items-center gap-1.5">
          <span aria-hidden className="inline-block h-0.5 w-4 rounded" style={{ backgroundColor: s.color }} />
          {s.name}
        </li>
      ))}
    </ul>
  );
}

function Tooltip({
  x,
  width: W,
  title,
  rows,
}: {
  x: number;
  width: number;
  title: string;
  rows: { name: string; value: string; color: string }[];
}) {
  return (
    <div
      role="status"
      className="pointer-events-none absolute top-0 z-10 rounded-md border border-slate-200 bg-white px-2 py-1 text-xs shadow-sm dark:border-slate-700 dark:bg-slate-900"
      style={{
        left: `${(x / W) * 100}%`,
        transform: x > W / 2 ? 'translateX(calc(-100% - 8px))' : 'translateX(8px)',
      }}
    >
      <p className="text-slate-600 dark:text-slate-400">{title}</p>
      {rows.map((r) => (
        <p key={r.name} className="flex items-center gap-1.5">
          <span
            aria-hidden
            className="inline-block h-2 w-2 rounded-full"
            style={{ backgroundColor: r.color }}
          />
          <strong className="tabular-nums">{r.value}</strong>
          <span className="text-slate-600 dark:text-slate-400">{r.name}</span>
        </p>
      ))}
    </div>
  );
}

/** Lines over a shared x axis (dates). One y axis, 2px lines, crosshair readout. */
export function LineChart({
  title,
  labels,
  series,
  height = 200,
  formatLabel = (l) => l,
}: {
  title: string;
  labels: string[];
  series: Series[];
  height?: number;
  formatLabel?: (label: string) => string;
}) {
  const [active, setActive] = useState<number | null>(null);
  const [ref, W] = useWidth();
  const { max, step } = niceScale(Math.max(...series.flatMap((s) => s.values), 0));
  const plotW = W - PAD.left - PAD.right;
  const plotH = height - PAD.top - PAD.bottom;
  const x = (i: number) => PAD.left + (labels.length > 1 ? (i / (labels.length - 1)) * plotW : plotW / 2);
  const y = (v: number) => PAD.top + plotH - (v / max) * plotH;
  const pick = (e: PointerEvent<SVGRectElement>) => {
    const box = e.currentTarget.ownerSVGElement!.getBoundingClientRect();
    const px = ((e.clientX - box.left) / box.width) * W;
    const i = Math.round(((px - PAD.left) / plotW) * (labels.length - 1));
    setActive(Math.min(labels.length - 1, Math.max(0, i)));
  };
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'ArrowRight') setActive((a) => Math.min(labels.length - 1, (a ?? -1) + 1));
    else if (e.key === 'ArrowLeft') setActive((a) => Math.max(0, (a ?? labels.length) - 1));
    else return;
    e.preventDefault();
  };
  const ticks = Array.from({ length: TICKS + 1 }, (_, i) => i * step);
  return (
    <figure>
      <Legend series={series} />
      <div className="relative" ref={ref}>
        <svg
          viewBox={`0 0 ${W} ${height}`}
          className="w-full focus-visible:outline-2 focus-visible:outline-sky-600"
          role="img"
          aria-label={`${title}. Use the arrow keys to read values.`}
          tabIndex={0}
          onKeyDown={onKey}
          onBlur={() => setActive(null)}
        >
          {ticks.map((t) => (
            <g key={t}>
              <line
                x1={PAD.left}
                x2={W - PAD.right}
                y1={y(t)}
                y2={y(t)}
                stroke="var(--chart-grid)"
                strokeWidth={1}
              />
              <text x={PAD.left - 6} y={y(t) + 4} textAnchor="end" fontSize={11} fill="var(--chart-muted)">
                {Math.round(t)}
              </text>
            </g>
          ))}
          <line
            x1={PAD.left}
            x2={W - PAD.right}
            y1={y(0)}
            y2={y(0)}
            stroke="var(--chart-axis)"
            strokeWidth={1}
          />
          {[0, Math.floor((labels.length - 1) / 2), labels.length - 1]
            .filter((v, i, a) => a.indexOf(v) === i && labels[v] !== undefined)
            .map((i) => (
              <text
                key={i}
                x={x(i)}
                y={height - 6}
                textAnchor={i === 0 ? 'start' : i === labels.length - 1 ? 'end' : 'middle'}
                fontSize={11}
                fill="var(--chart-muted)"
              >
                {formatLabel(labels[i]!)}
              </text>
            ))}
          {series.map((s) => (
            <g key={s.name}>
              <polyline
                points={s.values.map((v, i) => `${x(i)},${y(v)}`).join(' ')}
                fill="none"
                stroke={s.color}
                strokeWidth={2}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
              {series.length <= 4 && s.values.length > 0 && (
                <text
                  x={x(s.values.length - 1) + 6}
                  y={y(s.values[s.values.length - 1]!) + 4}
                  fontSize={11}
                  fill="currentColor"
                >
                  {s.name}
                </text>
              )}
            </g>
          ))}
          {active !== null && (
            <g>
              <line
                x1={x(active)}
                x2={x(active)}
                y1={PAD.top}
                y2={y(0)}
                stroke="var(--chart-axis)"
                strokeWidth={1}
              />
              {series.map((s) => (
                <circle
                  key={s.name}
                  cx={x(active)}
                  cy={y(s.values[active] ?? 0)}
                  r={4}
                  fill={s.color}
                  stroke="var(--chart-surface)"
                  strokeWidth={2}
                />
              ))}
            </g>
          )}
          <rect
            x={PAD.left}
            y={PAD.top}
            width={plotW}
            height={plotH}
            fill="transparent"
            onPointerMove={pick}
            onPointerLeave={() => setActive(null)}
          />
        </svg>
        {active !== null && labels[active] && (
          <Tooltip
            x={x(active)}
            width={W}
            title={formatLabel(labels[active])}
            rows={series.map((s) => ({ name: s.name, value: String(s.values[active] ?? 0), color: s.color }))}
          />
        )}
      </div>
      <DataTable caption={title} labels={labels.map(formatLabel)} series={series} />
    </figure>
  );
}

/** One series of bars (slot 1). Rounded data ends anchored to the baseline, 2px gaps. */
export function BarChart({
  title,
  labels,
  values,
  name,
  height = 160,
  formatLabel = (l) => l,
}: {
  title: string;
  labels: string[];
  values: number[];
  name: string;
  height?: number;
  formatLabel?: (label: string) => string;
}) {
  const [active, setActive] = useState<number | null>(null);
  const [ref, W] = useWidth();
  const { max } = niceScale(Math.max(...values, 0));
  const plotW = W - PAD.left - 16;
  const plotH = height - PAD.top - PAD.bottom;
  const slot = plotW / Math.max(values.length, 1);
  const barW = Math.max(Math.min(slot - 2, 48), 2);
  const y = (v: number) => PAD.top + plotH - (v / max) * plotH;
  const base = y(0);
  const bar = (i: number, v: number) => {
    const x0 = PAD.left + i * slot + (slot - barW) / 2;
    const top = y(v);
    const r = Math.min(4, barW / 2, base - top);
    return `M${x0},${base} V${top + r} Q${x0},${top} ${x0 + r},${top} H${x0 + barW - r} Q${x0 + barW},${top} ${x0 + barW},${top + r} V${base} Z`;
  };
  const series = [{ name, color: 'var(--series-1)', values }];
  return (
    <figure>
      <div className="relative" ref={ref}>
        <svg viewBox={`0 0 ${W} ${height}`} className="w-full" role="img" aria-label={title}>
          {[0, 0.5, 1].map((t) => (
            <g key={t}>
              <line x1={PAD.left} x2={W - 16} y1={y(t * max)} y2={y(t * max)} stroke="var(--chart-grid)" />
              <text
                x={PAD.left - 6}
                y={y(t * max) + 4}
                textAnchor="end"
                fontSize={11}
                fill="var(--chart-muted)"
              >
                {Math.round(t * max)}
              </text>
            </g>
          ))}
          {values.map((v, i) => (
            <g key={labels[i]}>
              {v > 0 && (
                <path
                  d={bar(i, v)}
                  fill="var(--series-1)"
                  opacity={active === null || active === i ? 1 : 0.6}
                />
              )}
              <rect
                x={PAD.left + i * slot}
                y={PAD.top}
                width={slot}
                height={plotH}
                fill="transparent"
                onPointerEnter={() => setActive(i)}
                onPointerLeave={() => setActive(null)}
              />
            </g>
          ))}
          <line x1={PAD.left} x2={W - 16} y1={base} y2={base} stroke="var(--chart-axis)" />
          {[0, values.length - 1]
            .filter((v, i, a) => a.indexOf(v) === i && labels[v] !== undefined)
            .map((i) => (
              <text
                key={i}
                x={PAD.left + i * slot + slot / 2}
                y={height - 6}
                textAnchor={i === 0 ? 'start' : 'end'}
                fontSize={11}
                fill="var(--chart-muted)"
              >
                {formatLabel(labels[i]!)}
              </text>
            ))}
        </svg>
        {active !== null && labels[active] && (
          <Tooltip
            x={PAD.left + active * slot + slot / 2}
            width={W}
            title={formatLabel(labels[active])}
            rows={[{ name, value: String(values[active] ?? 0), color: 'var(--series-1)' }]}
          />
        )}
      </div>
      <DataTable caption={title} labels={labels.map(formatLabel)} series={series} />
    </figure>
  );
}

export function ProgressBar({ value, label }: { value: number; label: string }) {
  const pct = Math.round(Math.min(Math.max(value, 0), 1) * 100);
  return (
    <div className="flex items-center gap-2">
      <div
        role="progressbar"
        aria-label={label}
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800"
      >
        <div
          className="h-full rounded-full"
          style={{ width: `${pct}%`, backgroundColor: 'var(--series-1)' }}
        />
      </div>
      <span className="w-10 text-right text-xs tabular-nums">{pct}%</span>
    </div>
  );
}

const HEALTH = {
  on_track: { label: 'On track', icon: '✓', color: 'var(--status-good)' },
  at_risk: { label: 'At risk', icon: '!', color: 'var(--status-warning)' },
  off_track: { label: 'Off track', icon: '✕', color: 'var(--status-critical)' },
} as const;

/** Status always pairs colour with an icon and a label. */
export function HealthBadge({ health }: { health: string | null | undefined }) {
  if (!health || !(health in HEALTH)) return <span className="text-xs text-slate-500">—</span>;
  const h = HEALTH[health as keyof typeof HEALTH];
  return (
    <span className="inline-flex items-center gap-1 text-xs font-medium whitespace-nowrap">
      <span
        aria-hidden
        className="inline-flex h-4 w-4 items-center justify-center rounded-full text-[10px] font-bold text-white"
        style={{ backgroundColor: h.color }}
      >
        {h.icon}
      </span>
      {h.label}
    </span>
  );
}
