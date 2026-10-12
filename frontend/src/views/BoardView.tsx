import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';

import type { Task } from '../api/client';
import { Assignee, PriorityBadge } from '../components/TaskBits';
import { ScrollArea } from '../components/ui';
import { groupTasks, patchForGroup, positionBetween, type Group } from '../lib/grouping';
import { toast } from '../lib/toast';
import type { ViewProps } from './types';

const HOLD_MS = 300; // touch: press and hold this long to pick a card up (a quick swipe still scrolls)
const SLOP = 6; // mouse and pen: move this far before it counts as a drag rather than a click

interface Held {
  task: Task;
  pointerId: number;
  type: string;
  x: number;
  y: number;
  active: boolean;
  timer: number | null;
  width: number;
}

/**
 * Columns of cards. Cards move by dragging (mouse, pen or touch: press and hold, then drag), with
 * Alt+arrow keys (Left/Right: column, Up/Down: order), or with each card's Move menu. Dragging uses
 * pointer events, not the browser's drag and drop, which is unreliable on touch and in some browsers.
 */
export function BoardView({ tasks, project, fields, users, config, onOpen, onUpdate }: ViewProps) {
  const groupBy = config.group_by ?? 'status';
  const columns = groupTasks(
    [...tasks].sort((a, b) => a.position - b.position),
    groupBy,
    { statuses: project.statuses, users, fields },
  );
  const [over, setOver] = useState<string | null>(null);
  // A moved card is drawn again in its new place; keyboard focus follows it there once it arrives.
  const follow = useRef<{ id: string; column: string; index: number } | null>(null);
  useEffect(() => {
    const target = follow.current;
    if (!target) return;
    const cards = document.querySelectorAll<HTMLElement>(`[data-column="${target.column}"] [data-card]`);
    const card = cards[target.index];
    if (card?.dataset.card !== target.id) return;
    follow.current = null;
    card.focus();
  });
  const byId = new Map(tasks.map((t) => [t.id, t]));

  /** Put `task` into `column` before the card at `index` (or at the end). */
  const place = (task: Task, column: Group, index: number) => {
    const siblings = column.tasks.filter((t) => t.id !== task.id);
    const at = Math.max(0, Math.min(index, siblings.length));
    const position = positionBetween(siblings[at - 1]?.position, siblings[at]?.position);
    const sameColumn = column.tasks.some((t) => t.id === task.id);
    onUpdate(task, { ...(sameColumn ? {} : patchForGroup(groupBy, column.key)), position });
    return { at, count: siblings.length + 1 };
  };

  const [ghost, setGhost] = useState<{ task: Task; x: number; y: number; width: number } | null>(null);
  const held = useRef<Held | null>(null);
  const justDragged = useRef(false);
  const blockScroll = (e: globalThis.TouchEvent) => {
    if (e.cancelable) e.preventDefault(); // a picked-up card must not scroll the page under the finger
  };
  const columnAt = (x: number, y: number) => {
    const el = document.elementFromPoint(x, y)?.closest<HTMLElement>('[data-column]');
    return el ? columns.find((c) => c.key === el.dataset.column) : undefined;
  };
  const release = () => {
    const h = held.current;
    if (h?.timer) window.clearTimeout(h.timer);
    held.current = null;
    document.removeEventListener('touchmove', blockScroll);
    setGhost(null);
    setOver(null);
  };
  const pickUp = (target: Element) => {
    const h = held.current;
    if (!h) return;
    h.active = true;
    try {
      target.setPointerCapture(h.pointerId);
    } catch {
      /* the pointer may already be gone */
    }
    if (h.type === 'touch') document.addEventListener('touchmove', blockScroll, { passive: false });
    setGhost({ task: h.task, x: h.x, y: h.y, width: h.width });
  };
  const onCardDown = (e: PointerEvent<HTMLElement>, task: Task) => {
    if (held.current || (e.pointerType === 'mouse' && e.button !== 0)) return;
    if ((e.target as Element).closest('select, a, input, textarea')) return;
    const card = e.currentTarget;
    const h: Held = {
      task,
      pointerId: e.pointerId,
      type: e.pointerType,
      x: e.clientX,
      y: e.clientY,
      active: false,
      timer: null,
      width: card.getBoundingClientRect().width,
    };
    held.current = h;
    if (e.pointerType === 'touch') h.timer = window.setTimeout(() => pickUp(card), HOLD_MS);
  };
  const onCardMove = (e: PointerEvent<HTMLElement>) => {
    const h = held.current;
    if (!h || e.pointerId !== h.pointerId) return;
    if (!h.active) {
      const moved = Math.hypot(e.clientX - h.x, e.clientY - h.y);
      if (h.type === 'touch') {
        if (moved > 8) release(); // the finger is scrolling, not holding
      } else if (moved > SLOP) {
        pickUp(e.currentTarget);
        h.x = e.clientX;
        h.y = e.clientY;
      }
      if (!held.current?.active) return;
    }
    h.x = e.clientX;
    h.y = e.clientY;
    setGhost((g) => (g ? { ...g, x: e.clientX, y: e.clientY } : g));
    setOver(columnAt(e.clientX, e.clientY)?.key ?? null);
  };
  const onCardUp = (e: PointerEvent<HTMLElement>) => {
    const h = held.current;
    if (!h || e.pointerId !== h.pointerId) return;
    if (h.active) {
      justDragged.current = true; // the click that follows a drag must not open the task
      window.setTimeout(() => (justDragged.current = false), 0);
      const column = columnAt(e.clientX, e.clientY);
      if (column) {
        const siblings = column.tasks.filter((t) => t.id !== h.task.id);
        const wraps = document.querySelectorAll<HTMLElement>(
          `[data-column="${column.key}"] [data-card-wrap]`,
        );
        let index = siblings.length;
        for (const wrap of wraps) {
          const t = byId.get(wrap.dataset.cardWrap ?? '');
          const box = wrap.getBoundingClientRect();
          if (t && t.id !== h.task.id && e.clientY < box.top + box.height / 2) {
            index = siblings.findIndex((s) => s.id === t.id);
            break;
          }
        }
        const { at, count } = place(h.task, column, index);
        toast(`${h.task.key} moved to ${column.label}, ${at + 1} of ${count}`);
      }
    }
    release();
  };

  /** Move one step: dx changes the column, dy the order within it. */
  const step = (task: Task, ci: number, ti: number, dx: number, dy: number) => {
    const column = columns[ci + dx];
    if (!column) return;
    const index = dx === 0 ? ti + dy : Math.min(ti, column.tasks.length);
    if (dx === 0 && (index < 0 || index >= column.tasks.length)) return;
    const { at, count } = place(task, column, index);
    follow.current = { id: task.id, column: column.key, index: at };
    toast(`${task.key} moved to ${column.label}, ${at + 1} of ${count}`);
  };

  const onKeyDown = (e: KeyboardEvent, task: Task, ci: number, ti: number) => {
    if (!e.altKey) return;
    const move = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
    if (!move) return;
    e.preventDefault();
    step(task, ci, ti, move[0]!, move[1]!);
  };

  return (
    <ScrollArea label="Board columns" className="overflow-x-auto pb-4">
      <p id="board-help" className="sr-only">
        Alt plus Left or Right arrow moves a card to the next column; Alt plus Up or Down changes its order.
      </p>
      <div className="flex gap-3" role="list" aria-label="Board">
        {columns.map((column, ci) => (
          <section
            key={column.key}
            role="listitem"
            aria-label={`${column.label}, ${column.tasks.length} tasks`}
            data-testid={`column-${column.label}`}
            data-column={column.key}
            className={`flex w-64 shrink-0 flex-col gap-2 rounded-lg bg-slate-50 p-2 sm:w-72 dark:bg-slate-900 ${over === column.key ? 'ring-2 ring-sky-600' : ''}`}
          >
            <h2 className="px-1 text-sm font-semibold">
              {column.label}{' '}
              <span className="font-normal text-slate-500 dark:text-slate-400">{column.tasks.length}</span>
            </h2>
            {column.tasks.map((task, ti) => (
              <div
                key={task.id}
                data-card-wrap={task.id}
                onPointerDown={(e) => onCardDown(e, task)}
                onPointerMove={onCardMove}
                onPointerUp={onCardUp}
                onPointerCancel={release}
                onContextMenu={(e) => {
                  if (held.current?.active) e.preventDefault(); // a long press must not open the browser menu
                }}
                className={`flex touch-manipulation flex-col gap-1 rounded-md border border-slate-200 bg-white p-2 text-sm shadow-sm select-none hover:border-sky-500 dark:border-slate-700 dark:bg-slate-950 ${ghost?.task.id === task.id ? 'opacity-40' : ''}`}
              >
                <button
                  type="button"
                  data-card={task.id}
                  aria-describedby="board-help"
                  aria-keyshortcuts="Alt+ArrowLeft Alt+ArrowRight Alt+ArrowUp Alt+ArrowDown"
                  onClick={() => {
                    if (!justDragged.current) onOpen(task);
                  }}
                  onKeyDown={(e) => onKeyDown(e, task, ci, ti)}
                  className="flex flex-col gap-1 rounded text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-600"
                >
                  <span className="font-mono text-xs text-slate-600 dark:text-slate-400">{task.key}</span>
                  <span>{task.title}</span>
                </button>
                <span className="flex items-center justify-between gap-2 text-xs">
                  <Assignee id={task.assignee_id} users={users} />
                  <span className="flex items-center gap-1">
                    <PriorityBadge priority={task.priority} />
                    <select
                      aria-label={`Move ${task.key}`}
                      value=""
                      onChange={(e) => {
                        const choice = e.target.value;
                        if (choice === 'up') step(task, ci, ti, 0, -1);
                        else if (choice === 'down') step(task, ci, ti, 0, 1);
                        else if (choice) step(task, ci, ti, Number(choice) - ci, 0);
                      }}
                      className="h-7 max-w-20 rounded border border-slate-300 bg-white px-1 text-xs dark:border-slate-600 dark:bg-slate-900"
                    >
                      <option value="">Move…</option>
                      {ti > 0 && <option value="up">Up</option>}
                      {ti < column.tasks.length - 1 && <option value="down">Down</option>}
                      {columns.map((c, i) =>
                        i === ci ? null : (
                          <option key={c.key} value={i}>
                            To {c.label}
                          </option>
                        ),
                      )}
                    </select>
                  </span>
                </span>
              </div>
            ))}
          </section>
        ))}
      </div>
      {ghost && (
        <div
          aria-hidden="true"
          style={{ left: ghost.x, top: ghost.y, width: ghost.width }}
          className="pointer-events-none fixed z-50 -translate-x-1/2 -translate-y-1/2 rotate-1 rounded-md border border-sky-500 bg-white p-2 text-sm shadow-lg dark:bg-slate-950"
        >
          <span className="block font-mono text-xs text-slate-600 dark:text-slate-400">{ghost.task.key}</span>
          {ghost.task.title}
        </div>
      )}
    </ScrollArea>
  );
}
