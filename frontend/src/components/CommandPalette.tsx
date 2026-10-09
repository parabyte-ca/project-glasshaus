import { useMutation, useQuery } from '@tanstack/react-query';
import { useEffect, useId, useMemo, useState, type KeyboardEvent } from 'react';
import { useNavigate } from 'react-router';

import { api, unwrap, type Task } from '../api/client';
import { useAuth } from '../auth/useAuth';
import { useAiStatus } from '../lib/ai';
import { useOnboarding } from '../lib/onboarding';
import { GO_TO } from '../lib/shortcuts';
import { toggleTheme } from '../lib/theme';
import { Dialog } from './Dialog';
import { useStartTour } from './onboarding/useStartTour';
import { ErrorText } from './ui';

type Item = { id: string; label: string; hint?: string; group: string; run: () => void };

const projectOf = (task: Task) => task.key.slice(0, task.key.lastIndexOf('-'));

function useDebounced<T>(value: T, ms: number): T {
  const [current, setCurrent] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setCurrent(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return current;
}

/** Ctrl/⌘ K: go to pages and projects, find tasks by key or title, or ask the AI assistant. */
export function CommandPalette({ onClose, onHelp }: { onClose: () => void; onHelp: () => void }) {
  const navigate = useNavigate();
  const { user } = useAuth();
  const ai = useAiStatus();
  const canAsk = ai.data?.features.includes('search') ?? false;
  const startTour = useStartTour();
  const onboarding = useOnboarding();
  const [text, setText] = useState('');
  const [active, setActive] = useState(0);
  const listId = useId();
  const q = useDebounced(text.trim(), 200);

  const projects = useQuery({ queryKey: ['projects'], queryFn: () => unwrap(api.GET('/api/v1/projects')) });
  const tasks = useQuery({
    queryKey: ['palette-tasks', q],
    enabled: q.length >= 2,
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/tasks', {
          params: { query: { q, limit: 8, sort: 'updated_at', descending: true } },
        }),
      ),
  });
  const ask = useMutation({
    mutationFn: (query: string) => unwrap(api.POST('/api/v1/ai/search', { body: { query, limit: 20 } })),
  });

  const go = (to: string) => () => {
    onClose();
    navigate(to);
  };
  const openTask = (t: Task) => go(`/projects/${projectOf(t)}?task=${t.key}`);

  const items = useMemo<Item[]>(() => {
    const needle = text.trim().toLowerCase();
    const match = (s: string) => !needle || s.toLowerCase().includes(needle);
    const out: Item[] = [];
    if (ask.data) {
      for (const t of ask.data.items) {
        out.push({ id: `ai-${t.id}`, label: `${t.key} ${t.title}`, group: 'Answer', run: openTask(t) });
      }
    }
    if (canAsk && needle.length >= 3) {
      out.push({
        id: 'ask',
        label: `Ask: “${text.trim()}”`,
        hint: 'AI turns your question into task filters',
        group: 'Assistant',
        run: () => ask.mutate(text.trim()),
      });
    }
    for (const t of tasks.data?.items ?? []) {
      out.push({ id: `t-${t.id}`, label: `${t.key} ${t.title}`, group: 'Tasks', run: openTask(t) });
    }
    for (const p of projects.data ?? []) {
      if (match(`${p.key} ${p.name}`)) {
        out.push({
          id: `p-${p.id}`,
          label: p.name,
          hint: p.key,
          group: 'Projects',
          run: go(`/projects/${p.key}`),
        });
      }
    }
    const pages: [string, string, string?][] = Object.entries(GO_TO).map(([key, [to, label]]) => [
      to,
      label,
      `g ${key}`,
    ]);
    if (user.org_role === 'owner' || user.org_role === 'admin') pages.push(['/admin', 'Admin']);
    for (const [to, label, hint] of pages) {
      if (match(label))
        out.push({ id: `nav-${to}`, label: `Go to ${label}`, hint, group: 'Go to', run: go(to) });
    }
    const actions: Item[] = [
      { id: 'theme', label: 'Toggle dark mode', group: 'Actions', run: () => toggleTheme() },
      {
        id: 'help',
        label: 'Keyboard shortcuts',
        hint: '?',
        group: 'Actions',
        run: () => {
          onClose();
          onHelp();
        },
      },
    ];
    if (startTour) {
      actions.push({
        id: 'tour',
        label: 'Take the product tour',
        group: 'Actions',
        run: () => {
          onClose();
          startTour();
        },
      });
    }
    if (onboarding.state && onboarding.state.checklist !== 'open') {
      actions.push({
        id: 'checklist',
        label: 'Show the getting-started checklist',
        group: 'Actions',
        run: () => {
          onClose();
          onboarding.update({ checklist: 'open' });
        },
      });
    }
    out.push(...actions.filter((a) => match(a.label)));
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, ask.data, canAsk, tasks.data, projects.data, user.org_role, startTour, onboarding.state]);

  const current = Math.min(active, Math.max(items.length - 1, 0));
  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActive((current + 1) % Math.max(items.length, 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((current - 1 + items.length) % Math.max(items.length, 1));
    } else if (e.key === 'Enter' && items[current]) {
      e.preventDefault();
      items[current].run();
    }
  };

  let lastGroup = '';
  return (
    <Dialog title="Command palette" onClose={onClose} wide>
      <input
        data-autofocus
        role="combobox"
        aria-expanded={items.length > 0}
        aria-controls={listId}
        aria-activedescendant={items[current] ? `${listId}-${items[current].id}` : undefined}
        aria-autocomplete="list"
        aria-label="Search or type a command"
        placeholder={canAsk ? 'Search, go to, or ask a question…' : 'Search tasks and projects, or go to…'}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setActive(0);
          ask.reset();
        }}
        onKeyDown={onKeyDown}
        className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 dark:border-slate-600 dark:bg-slate-950"
      />
      {ask.data && (
        <p role="status" className="text-sm text-slate-700 dark:text-slate-300">
          {ask.data.filters.explanation} · {ask.data.items.length} found
        </p>
      )}
      {ask.isPending && (
        <p role="status" className="text-sm">
          Asking…
        </p>
      )}
      <ErrorText error={ask.error} />
      <ul id={listId} role="listbox" aria-label="Results" className="flex flex-col">
        {items.map((item, i) => {
          const header = item.group !== lastGroup;
          lastGroup = item.group;
          return (
            // Keyboard selection goes through the combobox input (aria-activedescendant).
            // eslint-disable-next-line jsx-a11y/click-events-have-key-events
            <li
              key={item.id}
              id={`${listId}-${item.id}`}
              role="option"
              aria-selected={i === current}
              onMouseMove={() => setActive(i)}
              onClick={item.run}
              className={`flex cursor-pointer items-center justify-between gap-3 rounded px-2 py-1.5 text-sm ${i === current ? 'bg-sky-700 text-white' : ''} ${header ? 'mt-2' : ''}`}
            >
              <span className="truncate">
                {header && <span className="sr-only">{item.group}: </span>}
                {item.label}
              </span>
              <span
                className={`shrink-0 text-xs ${i === current ? 'text-white' : 'text-slate-600 dark:text-slate-400'}`}
              >
                {item.hint ?? item.group}
              </span>
            </li>
          );
        })}
      </ul>
      {items.length === 0 && <p className="text-sm text-slate-600 dark:text-slate-400">No matches.</p>}
    </Dialog>
  );
}

export function ShortcutHelp({ onClose, shortcuts }: { onClose: () => void; shortcuts: [string, string][] }) {
  return (
    <Dialog title="Keyboard shortcuts" onClose={onClose}>
      <table className="text-sm">
        <caption className="sr-only">Keyboard shortcuts</caption>
        <thead>
          <tr>
            <th scope="col" className="pr-4 text-left">
              Keys
            </th>
            <th scope="col" className="text-left">
              Action
            </th>
          </tr>
        </thead>
        <tbody>
          {shortcuts.map(([keys, action]) => (
            <tr key={keys}>
              <td className="py-1 pr-4">
                <kbd className="rounded border border-slate-300 px-1.5 font-mono text-xs dark:border-slate-600">
                  {keys}
                </kbd>
              </td>
              <td className="py-1">{action}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <button
        type="button"
        onClick={onClose}
        className="self-end rounded-md border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-600"
      >
        Close
      </button>
    </Dialog>
  );
}
