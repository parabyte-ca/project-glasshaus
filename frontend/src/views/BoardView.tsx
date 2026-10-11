import { useEffect, useRef, useState, type DragEvent, type KeyboardEvent } from 'react';

import type { Task } from '../api/client';
import { Assignee, PriorityBadge } from '../components/TaskBits';
import { ScrollArea } from '../components/ui';
import { groupTasks, patchForGroup, positionBetween, type Group } from '../lib/grouping';
import { toast } from '../lib/toast';
import type { ViewProps } from './types';

const MIME = 'application/x-glasshaus-task';

/**
 * Columns of cards. Cards move by drag and drop, with Alt+arrow keys (Left/Right: column, Up/Down:
 * order), or with each card's Move menu, which also works on touch screens.
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

  const drop = (e: DragEvent, column: Group, before?: Task) => {
    e.preventDefault();
    setOver(null);
    const task = byId.get(e.dataTransfer.getData(MIME));
    if (!task || task.id === before?.id) return;
    const siblings = column.tasks.filter((t) => t.id !== task.id);
    place(task, column, before ? siblings.findIndex((t) => t.id === before.id) : siblings.length);
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
            onDragOver={(e) => {
              e.preventDefault();
              setOver(column.key);
            }}
            onDragLeave={() => setOver((k) => (k === column.key ? null : k))}
            onDrop={(e) => drop(e, column)}
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
                draggable
                onDragStart={(e) => {
                  e.dataTransfer.setData(MIME, task.id);
                  e.dataTransfer.effectAllowed = 'move';
                }}
                onDrop={(e) => {
                  e.stopPropagation();
                  drop(e, column, task);
                }}
                className="flex flex-col gap-1 rounded-md border border-slate-200 bg-white p-2 text-sm shadow-sm hover:border-sky-500 dark:border-slate-700 dark:bg-slate-950"
              >
                <button
                  type="button"
                  data-card={task.id}
                  aria-describedby="board-help"
                  aria-keyshortcuts="Alt+ArrowLeft Alt+ArrowRight Alt+ArrowUp Alt+ArrowDown"
                  onClick={() => onOpen(task)}
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
    </ScrollArea>
  );
}
