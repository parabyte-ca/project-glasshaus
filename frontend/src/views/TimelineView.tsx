import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';

import { api, unwrap, type Task } from '../api/client';
import { GhostButton, Select } from '../components/ui';
import { formatDay, isWeekend, monthLabel, parseDay, todayIso } from '../lib/dates';
import { shiftPatch } from '../lib/schedule';
import type { ViewProps } from './types';

const ROW = 36;
const LABEL_W = 260;
const ZOOM = { day: 28, week: 10 } as const;

interface Drag {
  taskId: string;
  mode: 'move' | 'resize';
  originX: number;
  deltaDays: number;
}

export function TimelineView({ tasks, project, onOpen, onUpdate }: ViewProps) {
  const queryClient = useQueryClient();
  const [zoom, setZoom] = useState<keyof typeof ZOOM>('day');
  const [baselineId, setBaselineId] = useState('');
  const [drag, setDrag] = useState<Drag | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const dayW = ZOOM[zoom];

  const schedule = useQuery({
    queryKey: ['tasks', project.id, 'schedule'],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/projects/{project_id}/schedule', { params: { path: { project_id: project.id } } }),
      ),
  });
  const baselines = useQuery({
    queryKey: ['tasks', project.id, 'baselines'],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/projects/{project_id}/baselines', { params: { path: { project_id: project.id } } }),
      ),
  });
  const variance = useQuery({
    queryKey: ['tasks', project.id, 'variance', baselineId],
    enabled: !!baselineId,
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/baselines/{baseline_id}/variance', {
          params: { path: { baseline_id: baselineId } },
        }),
      ),
  });
  const warnings = useQuery({
    queryKey: ['tasks', project.id, 'warnings'],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/projects/{project_id}/schedule/warnings', {
          params: { path: { project_id: project.id } },
        }),
      ),
  });
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['tasks', project.id] });
  const saveBaseline = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/v1/projects/{project_id}/baselines', {
          params: { path: { project_id: project.id } },
          body: { name: `Baseline ${new Date().toLocaleDateString()}` },
        }),
      ),
    onSuccess: (b) => {
      setBaselineId(b.id);
      void invalidate();
    },
  });
  const reschedule = useMutation({
    mutationFn: (dryRun: boolean) =>
      unwrap(
        api.POST('/api/v1/projects/{project_id}/reschedule', {
          params: { path: { project_id: project.id }, query: { dry_run: dryRun } },
        }),
      ),
    onSuccess: (r) => r.executed && void invalidate(),
  });
  const toggleAuto = useMutation({
    mutationFn: (on: boolean) =>
      unwrap(
        api.PATCH('/api/v1/projects/{project_id}', {
          params: { path: { project_id: project.id } },
          body: { auto_schedule: on },
        }),
      ),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ['project'] }),
  });

  const scheduled = useMemo(
    () =>
      tasks
        .filter((t) => t.start_date || t.due_date)
        .sort((a, b) => (a.start_date ?? a.due_date!).localeCompare(b.start_date ?? b.due_date!)),
    [tasks],
  );
  const critical = new Set(schedule.data?.critical_path ?? []);
  const baseline = new Map((variance.data?.tasks ?? []).map((v) => [v.task_id, v]));

  const days = scheduled.flatMap((t) => [
    parseDay(t.start_date ?? t.due_date!),
    parseDay(t.due_date ?? t.start_date!),
  ]);
  const today = parseDay(todayIso());
  const first = Math.min(...days, today) - 3;
  const last = Math.max(...days, today) + 10;
  const width = (last - first + 1) * dayW;
  const height = scheduled.length * ROW;
  const xOf = (iso: string) => (parseDay(iso) - first) * dayW;
  const index = new Map(scheduled.map((t, i) => [t.id, i]));

  const bar = (t: Task) => {
    const shift = drag?.taskId === t.id ? drag.deltaDays : 0;
    const start = parseDay(t.start_date ?? t.due_date!) + (drag?.mode === 'move' ? shift : 0);
    const end = parseDay(t.due_date ?? t.start_date!) + shift;
    return { x: (start - first) * dayW, w: Math.max(1, end - start + 1) * dayW };
  };

  const onPointerDown = (e: PointerEvent, task: Task, mode: Drag['mode']) => {
    e.stopPropagation();
    (e.target as Element).setPointerCapture(e.pointerId);
    setDrag({ taskId: task.id, mode, originX: e.clientX, deltaDays: 0 });
  };
  const onPointerMove = (e: PointerEvent) => {
    if (drag) setDrag({ ...drag, deltaDays: Math.round((e.clientX - drag.originX) / dayW) });
  };
  const onPointerUp = (task: Task) => {
    if (drag && drag.taskId === task.id) {
      if (drag.deltaDays !== 0) onUpdate(task, shiftPatch(task, drag.deltaDays, drag.mode));
      else onOpen(task);
    }
    setDrag(null);
  };
  const onKeyDown = (e: KeyboardEvent, task: Task) => {
    const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
    if (step) {
      e.preventDefault();
      onUpdate(task, shiftPatch(task, step, e.shiftKey ? 'resize' : 'move'));
    } else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onOpen(task);
    }
  };

  const months: { x: number; label: string }[] = [];
  for (let d = first; d <= last; d++) {
    if (d === first || formatDay(d).endsWith('-01'))
      months.push({ x: (d - first) * dayW, label: monthLabel(d) });
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3 text-sm" role="toolbar" aria-label="Timeline options">
        <Select aria-label="Zoom" value={zoom} onChange={(e) => setZoom(e.target.value as keyof typeof ZOOM)}>
          <option value="day">Days</option>
          <option value="week">Weeks</option>
        </Select>
        <Select
          aria-label="Compare with baseline"
          value={baselineId}
          onChange={(e) => setBaselineId(e.target.value)}
        >
          <option value="">No baseline</option>
          {baselines.data?.map((b) => (
            <option key={b.id} value={b.id}>
              {b.name}
            </option>
          ))}
        </Select>
        {project.my_role === 'admin' && (
          <>
            <GhostButton onClick={() => saveBaseline.mutate()} disabled={saveBaseline.isPending}>
              Save baseline
            </GhostButton>
            <label className="flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={project.auto_schedule}
                onChange={(e) => toggleAuto.mutate(e.target.checked)}
              />
              Auto-schedule dependents
            </label>
          </>
        )}
        <GhostButton onClick={() => reschedule.mutate(true)}>Check dependencies</GhostButton>
        <span className="flex items-center gap-2 text-xs text-slate-600 dark:text-slate-400">
          <span aria-hidden className="inline-block h-2 w-4 rounded bg-rose-500" /> critical path
          {schedule.data?.project_finish && <> · finish {schedule.data.project_finish}</>}
        </span>
      </div>

      {reschedule.data && (
        <div role="status" className="rounded-md border border-slate-200 p-3 text-sm dark:border-slate-800">
          {reschedule.data.moves.length === 0 ? (
            'Every dependency is satisfied.'
          ) : reschedule.data.executed ? (
            `Moved ${reschedule.data.moves.length} task(s).`
          ) : (
            <div className="flex flex-col gap-2">
              <span>{reschedule.data.moves.length} task(s) start too early for their dependencies:</span>
              <ul className="list-disc pl-5">
                {reschedule.data.moves.map((m) => (
                  <li key={m.task_id}>
                    {m.key}: {m.start_date ?? m.due_date} → {m.new_start_date ?? m.new_due_date} (+{m.days}d)
                  </li>
                ))}
              </ul>
              <GhostButton className="self-start" onClick={() => reschedule.mutate(false)}>
                Move them
              </GhostButton>
            </div>
          )}
        </div>
      )}

      {(warnings.data?.length ?? 0) > 0 && (
        <details className="rounded-md border border-amber-300 bg-amber-50 p-2 text-sm dark:border-amber-800 dark:bg-amber-950">
          <summary className="cursor-pointer font-medium">
            {warnings.data!.length} schedule warning(s)
          </summary>
          <ul className="mt-2 list-disc pl-5">
            {warnings.data!.map((w, i) => (
              <li key={i}>{w.message}</li>
            ))}
          </ul>
        </details>
      )}

      <div className="flex overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-800">
        <ul
          className="sticky left-0 z-10 shrink-0 border-r border-slate-200 bg-white pt-6 dark:border-slate-800 dark:bg-slate-950"
          style={{ width: LABEL_W }}
        >
          {scheduled.map((t) => (
            <li key={t.id} style={{ height: ROW }} className="flex items-center gap-2 truncate px-2 text-sm">
              <span className="font-mono text-xs text-slate-600 dark:text-slate-400">{t.key}</span>
              <button type="button" className="truncate text-left hover:underline" onClick={() => onOpen(t)}>
                {t.title}
              </button>
            </li>
          ))}
        </ul>
        <svg
          ref={svgRef}
          width={width}
          height={height + 24}
          role="group"
          aria-label="Timeline. Focus a bar and use arrow keys to move it a day; Shift+arrows change its length."
          onPointerMove={onPointerMove}
          className="shrink-0 select-none"
        >
          <defs>
            <marker
              id="arrow"
              viewBox="0 0 8 8"
              refX="7"
              refY="4"
              markerWidth="6"
              markerHeight="6"
              orient="auto"
            >
              <path d="M0,0 L8,4 L0,8 z" className="fill-slate-500" />
            </marker>
          </defs>
          {months.map((m) => (
            <text key={m.x} x={m.x + 4} y={14} className="fill-slate-600 text-[11px] dark:fill-slate-400">
              {m.label}
            </text>
          ))}
          <g transform="translate(0,24)">
            {zoom === 'day' &&
              Array.from({ length: last - first + 1 }, (_, i) =>
                isWeekend(first + i) ? (
                  <rect
                    key={i}
                    x={i * dayW}
                    y={0}
                    width={dayW}
                    height={height}
                    className="fill-slate-100 dark:fill-slate-900"
                  />
                ) : null,
              )}
            <line
              x1={(today - first) * dayW}
              x2={(today - first) * dayW}
              y1={0}
              y2={height}
              className="stroke-sky-600"
              strokeDasharray="4 3"
            />
            {schedule.data?.dependencies.map((d) => {
              const pi = index.get(d.predecessor_id);
              const si = index.get(d.successor_id);
              if (pi === undefined || si === undefined) return null;
              const p = bar(scheduled[pi]!);
              const s = bar(scheduled[si]!);
              const fromEnd = d.type === 'fs' || d.type === 'ff';
              const toEnd = d.type === 'ff' || d.type === 'sf';
              const x1 = fromEnd ? p.x + p.w : p.x;
              const x2 = toEnd ? s.x + s.w : s.x;
              const y1 = pi * ROW + ROW / 2;
              const y2 = si * ROW + ROW / 2;
              const mid = Math.max(x1 + 8, Math.min(x2 - 8, x1 + 8));
              return (
                <path
                  key={d.id}
                  d={`M${x1},${y1} H${mid} V${y2} H${x2}`}
                  fill="none"
                  className="stroke-slate-500"
                  markerEnd="url(#arrow)"
                />
              );
            })}
            {scheduled.map((t, i) => {
              const b = bar(t);
              const base = baseline.get(t.id);
              const isCritical = critical.has(t.id);
              return (
                <g key={t.id} transform={`translate(0,${i * ROW})`}>
                  {base?.baseline_due && (
                    <rect
                      x={xOf(base.baseline_start ?? base.baseline_due)}
                      y={ROW - 9}
                      width={
                        (parseDay(base.baseline_due) -
                          parseDay(base.baseline_start ?? base.baseline_due) +
                          1) *
                        dayW
                      }
                      height={4}
                      rx={2}
                      className="fill-slate-400 dark:fill-slate-600"
                    >
                      <title>Baseline</title>
                    </rect>
                  )}
                  <rect
                    data-testid={`bar-${t.key}`}
                    role="button"
                    tabIndex={0}
                    aria-label={`${t.key} ${t.title}, ${t.start_date ?? t.due_date} to ${t.due_date ?? t.start_date}${isCritical ? ', critical' : ''}`}
                    x={b.x}
                    y={8}
                    width={b.w}
                    height={ROW - 18}
                    rx={4}
                    onPointerDown={(e) => onPointerDown(e, t, 'move')}
                    onPointerUp={() => onPointerUp(t)}
                    onKeyDown={(e) => onKeyDown(e, t)}
                    className={`cursor-grab focus:outline-2 focus:outline-sky-600 ${isCritical ? 'fill-rose-500' : 'fill-sky-600'} ${t.completed_at ? 'opacity-50' : ''}`}
                  />
                  <rect
                    x={b.x + b.w - 6}
                    y={8}
                    width={6}
                    height={ROW - 18}
                    className="cursor-ew-resize fill-transparent"
                    onPointerDown={(e) => onPointerDown(e, t, 'resize')}
                    onPointerUp={() => onPointerUp(t)}
                  />
                </g>
              );
            })}
          </g>
        </svg>
      </div>
      {scheduled.length < tasks.length && (
        <p className="text-xs text-slate-600 dark:text-slate-400">
          {tasks.length - scheduled.length} task(s) without dates are not shown.
        </p>
      )}
    </div>
  );
}
