import { groupTasks } from '../lib/grouping';
import { Assignee, PriorityBadge, StatusPill } from '../components/TaskBits';
import type { ViewProps } from './types';

export function ListView({ tasks, project, fields, users, config, onOpen }: ViewProps) {
  const groups = groupTasks(tasks, config.group_by, { statuses: project.statuses, users, fields }).filter(
    (g) => g.tasks.length > 0,
  );
  if (tasks.length === 0) return <p className="py-6 text-slate-600 dark:text-slate-400">No tasks match.</p>;
  return (
    <div className="flex flex-col gap-6">
      {groups.map((group) => (
        <section key={group.key} aria-label={group.label}>
          {config.group_by && (
            <h2 className="mb-2 text-sm font-semibold">
              {group.label} <span className="text-slate-500 dark:text-slate-400">{group.tasks.length}</span>
            </h2>
          )}
          <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
            {group.tasks.map((task) => (
              <li key={task.id}>
                <button
                  type="button"
                  onClick={() => onOpen(task)}
                  className="flex w-full items-center gap-3 px-3 py-2 text-left text-sm hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-sky-600 dark:hover:bg-slate-900"
                >
                  <span className="w-20 shrink-0 font-mono text-xs text-slate-600 dark:text-slate-400">
                    {task.key}
                  </span>
                  <span className="flex-1 truncate">{task.title}</span>
                  <StatusPill status={task.status} />
                  <PriorityBadge priority={task.priority} />
                  <span className="hidden w-36 truncate text-xs md:inline">
                    <Assignee id={task.assignee_id} users={users} />
                  </span>
                  <span className="hidden w-24 text-xs text-slate-600 sm:inline dark:text-slate-400">
                    {task.due_date ?? ''}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
