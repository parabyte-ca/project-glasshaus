import { useState, type DragEvent } from 'react';

import type { Task } from '../api/client';
import { Assignee, PriorityBadge } from '../components/TaskBits';
import { groupTasks, patchForGroup, positionBetween, type Group } from '../lib/grouping';
import type { ViewProps } from './types';

const MIME = 'application/x-glasshaus-task';

export function BoardView({ tasks, project, fields, users, config, onOpen, onUpdate }: ViewProps) {
  const groupBy = config.group_by ?? 'status';
  const columns = groupTasks(
    [...tasks].sort((a, b) => a.position - b.position),
    groupBy,
    { statuses: project.statuses, users, fields },
  );
  const [over, setOver] = useState<string | null>(null);
  const byId = new Map(tasks.map((t) => [t.id, t]));

  const drop = (e: DragEvent, column: Group, before?: Task) => {
    e.preventDefault();
    setOver(null);
    const task = byId.get(e.dataTransfer.getData(MIME));
    if (!task || task.id === before?.id) return;
    const siblings = column.tasks.filter((t) => t.id !== task.id);
    const index = before ? siblings.findIndex((t) => t.id === before.id) : siblings.length;
    const position = positionBetween(siblings[index - 1]?.position, siblings[index]?.position);
    const sameColumn = column.tasks.some((t) => t.id === task.id);
    onUpdate(task, { ...(sameColumn ? {} : patchForGroup(groupBy, column.key)), position });
  };

  return (
    <div className="flex gap-3 overflow-x-auto pb-4" role="list" aria-label="Board">
      {columns.map((column) => (
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
          className={`flex w-72 shrink-0 flex-col gap-2 rounded-lg bg-slate-50 p-2 dark:bg-slate-900 ${over === column.key ? 'ring-2 ring-sky-600' : ''}`}
        >
          <h2 className="px-1 text-sm font-semibold">
            {column.label} <span className="font-normal text-slate-500">{column.tasks.length}</span>
          </h2>
          {column.tasks.map((task) => (
            <button
              key={task.id}
              type="button"
              draggable
              onDragStart={(e) => {
                e.dataTransfer.setData(MIME, task.id);
                e.dataTransfer.effectAllowed = 'move';
              }}
              onDrop={(e) => {
                e.stopPropagation();
                drop(e, column, task);
              }}
              onClick={() => onOpen(task)}
              className="flex flex-col gap-1 rounded-md border border-slate-200 bg-white p-2 text-left text-sm shadow-sm hover:border-sky-500 focus-visible:outline-2 focus-visible:outline-sky-600 dark:border-slate-700 dark:bg-slate-950"
            >
              <span className="font-mono text-xs text-slate-600 dark:text-slate-400">{task.key}</span>
              <span>{task.title}</span>
              <span className="flex items-center justify-between gap-2 text-xs">
                <Assignee id={task.assignee_id} users={users} />
                <PriorityBadge priority={task.priority} />
              </span>
            </button>
          ))}
        </section>
      ))}
    </div>
  );
}
