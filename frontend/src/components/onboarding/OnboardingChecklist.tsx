import { useQuery } from '@tanstack/react-query';
import { useId } from 'react';
import { Link } from 'react-router';

import { api, unwrap } from '../../api/client';
import { MILESTONES, progressOf, useOnboarding } from '../../lib/onboarding';
import { linkClass } from '../ui';

/**
 * Getting-started checklist docked bottom-right. Items tick from what the person has actually done;
 * the widget can be minimized to a pill or dismissed (bring it back from Help or the command palette).
 */
export function OnboardingChecklist() {
  const { state, update } = useOnboarding();
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => unwrap(api.GET('/api/v1/projects')) });
  const headingId = useId();
  if (!state || state.checklist === 'dismissed') return null;
  const { done, total, percent } = progressOf(state);
  const project = projects.data?.[0];
  const projectUrl = project ? `/projects/${project.key}` : '/';
  const targets: Record<string, string> = {
    created_work: '/',
    added_collaborator: project ? `${projectUrl}?people=1` : '/',
    set_due_date: projectUrl,
    toured: project ? `${projectUrl}?tour=1` : '/',
  };

  if (state.checklist === 'minimized') {
    return (
      <button
        type="button"
        aria-expanded="false"
        onClick={() => update({ checklist: 'open' })}
        className="fixed right-4 bottom-4 z-30 rounded-full border border-slate-300 bg-white px-4 py-2 text-sm font-medium shadow-lg hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-sky-600 dark:border-slate-600 dark:bg-slate-900 dark:hover:bg-slate-800"
      >
        Getting started · {done}/{total}
      </button>
    );
  }

  return (
    <section
      aria-labelledby={headingId}
      className="fixed right-4 bottom-4 z-30 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-3 rounded-lg border border-slate-200 bg-white p-4 text-sm shadow-xl dark:border-slate-700 dark:bg-slate-900"
    >
      <div className="flex items-center justify-between gap-2">
        <h2 id={headingId} className="font-semibold">
          {done === total ? 'You’re all set' : 'Getting started'}
        </h2>
        <div className="flex gap-1">
          <button
            type="button"
            aria-expanded="true"
            onClick={() => update({ checklist: 'minimized' })}
            className="rounded px-2 py-0.5 text-xs hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-sky-600 dark:hover:bg-slate-800"
          >
            Minimize
          </button>
          <button
            type="button"
            onClick={() => update({ checklist: 'dismissed' })}
            className="rounded px-2 py-0.5 text-xs hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-sky-600 dark:hover:bg-slate-800"
          >
            Dismiss
          </button>
        </div>
      </div>
      <div className="flex flex-col gap-1">
        <div
          role="progressbar"
          aria-label="Getting started progress"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent}
          aria-valuetext={`${done} of ${total} done`}
          className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700"
        >
          <div
            className="h-full rounded-full bg-sky-600 transition-[width] motion-reduce:transition-none dark:bg-sky-400"
            style={{ width: `${percent}%` }}
          />
        </div>
        <p className="text-xs text-slate-600 dark:text-slate-400">{percent}% complete</p>
      </div>
      <ul className="flex flex-col gap-1.5">
        {MILESTONES.map((m) => {
          const ok = state.milestones[m.key];
          return (
            <li key={m.key} className="flex items-center gap-2">
              <span
                aria-hidden="true"
                className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-xs ${ok ? 'border-emerald-600 bg-emerald-600 text-white' : 'border-slate-400 dark:border-slate-500'}`}
              >
                {ok ? '✓' : ''}
              </span>
              {ok ? (
                <span className="text-slate-600 line-through dark:text-slate-400">
                  {m.label}
                  <span className="sr-only"> (done)</span>
                </span>
              ) : (
                <Link to={targets[m.key]!} className={linkClass}>
                  {m.label}
                </Link>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
