import { useState } from 'react';

import { GhostButton, linkClass } from '../components/ui';
import { monthGrid, todayIso } from '../lib/dates';
import { tasksOn } from '../lib/schedule';
import type { ViewProps } from './types';

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const MAX_PER_DAY = 4;

export function CalendarView({ tasks, onOpen }: ViewProps) {
  const [month, setMonth] = useState(() => `${todayIso().slice(0, 7)}-01`);
  const [expanded, setExpanded] = useState<string | null>(null);
  const weeks = monthGrid(month);
  const today = todayIso();
  const shift = (n: number) => {
    const [y, m] = month.split('-').map(Number) as [number, number];
    const date = new Date(Date.UTC(y, m - 1 + n, 1));
    setMonth(date.toISOString().slice(0, 10));
  };
  const agenda = weeks
    .flat()
    .filter((day) => day.slice(0, 7) === month.slice(0, 7))
    .map((day) => [day, tasksOn(tasks, day)] as const)
    .filter(([, items]) => items.length > 0);
  const title = new Date(`${month}T00:00:00Z`).toLocaleDateString(undefined, {
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  });

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <GhostButton onClick={() => shift(-1)} aria-label="Previous month">
          ‹
        </GhostButton>
        <GhostButton onClick={() => setMonth(`${today.slice(0, 7)}-01`)}>Today</GhostButton>
        <GhostButton onClick={() => shift(1)} aria-label="Next month">
          ›
        </GhostButton>
        <h2 className="text-lg font-semibold" aria-live="polite">
          {title}
        </h2>
      </div>
      {/* Phones: the month as a list of the days that have tasks. */}
      <ol className="flex flex-col gap-3 sm:hidden" aria-label={`Tasks by date, ${title}`}>
        {agenda.length === 0 && (
          <li className="text-sm text-slate-600 dark:text-slate-400">No dated tasks this month.</li>
        )}
        {agenda.map(([day, items]) => (
          <li key={day}>
            <h3 className={`text-sm font-semibold ${day === today ? 'text-sky-700 dark:text-sky-400' : ''}`}>
              {new Date(`${day}T00:00:00Z`).toLocaleDateString(undefined, {
                weekday: 'short',
                day: 'numeric',
                month: 'short',
                timeZone: 'UTC',
              })}
              {day === today && ' (today)'}
            </h3>
            <ul className="mt-1 flex flex-col gap-1">
              {items.map((t) => (
                <li key={t.id}>
                  <button
                    type="button"
                    onClick={() => onOpen(t)}
                    className={`block min-h-10 w-full rounded-md border border-slate-200 px-3 py-2 text-left text-sm dark:border-slate-700 ${t.completed_at ? 'line-through opacity-60' : ''}`}
                  >
                    <span className="mr-2 font-mono text-xs text-slate-600 dark:text-slate-400">{t.key}</span>
                    {t.title}
                  </button>
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ol>
      <table className="hidden w-full table-fixed border-collapse text-sm sm:table">
        <caption className="sr-only">Tasks by date, {title}</caption>
        <thead>
          <tr>
            {WEEKDAYS.map((d) => (
              <th key={d} scope="col" className="py-1 text-xs font-medium text-slate-600 dark:text-slate-400">
                {d}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {weeks.map((week) => (
            <tr key={week[0]}>
              {week.map((day) => {
                const items = tasksOn(tasks, day);
                const visible = expanded === day ? items : items.slice(0, MAX_PER_DAY);
                const inMonth = day.slice(0, 7) === month.slice(0, 7);
                return (
                  <td
                    key={day}
                    aria-label={day}
                    className={`h-28 border border-slate-200 p-1 align-top dark:border-slate-800 ${inMonth ? '' : 'bg-slate-50 text-slate-600 dark:bg-slate-900 dark:text-slate-400'}`}
                  >
                    <div
                      className={`mb-1 text-xs ${day === today ? 'inline-block rounded-full bg-sky-700 px-1.5 text-white' : ''}`}
                    >
                      {Number(day.slice(8))}
                    </div>
                    <ul className="flex flex-col gap-0.5">
                      {visible.map((t) => (
                        <li key={t.id}>
                          <button
                            type="button"
                            onClick={() => onOpen(t)}
                            title={`${t.key} ${t.title}`}
                            className={`block w-full truncate rounded px-1 text-left text-xs ${
                              (t.due_date ?? t.start_date) === day
                                ? 'bg-sky-100 text-sky-900 dark:bg-sky-900 dark:text-sky-100'
                                : 'bg-slate-100 dark:bg-slate-800'
                            } ${t.completed_at ? 'line-through opacity-60' : ''}`}
                          >
                            {t.title}
                          </button>
                        </li>
                      ))}
                      {items.length > MAX_PER_DAY && (
                        <li>
                          <button
                            type="button"
                            className={`min-h-6 text-xs ${linkClass}`}
                            aria-expanded={expanded === day}
                            onClick={() => setExpanded(expanded === day ? null : day)}
                          >
                            {expanded === day ? 'Show less' : `+${items.length - MAX_PER_DAY} more`}
                          </button>
                        </li>
                      )}
                    </ul>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
