import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useId, useRef, useState, type FocusEvent } from 'react';
import { useNavigate } from 'react-router';

import { api, unwrap, type Notification, type Project } from '../api/client';
import { GhostButton } from './ui';
import { useEscapeLayer } from './useModal';

export function NotificationsBell() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const popover = useRef<HTMLDivElement>(null);
  const popoverId = useId();
  const count = useQuery({
    queryKey: ['notifications', 'count'],
    queryFn: () => unwrap(api.GET('/api/v1/notifications/unread-count')),
    refetchInterval: 120_000,
  });
  const list = useQuery({
    queryKey: ['notifications', 'list'],
    enabled: open,
    queryFn: () => unwrap(api.GET('/api/v1/notifications', { params: { query: { limit: 20 } } })),
  });
  const markRead = useMutation({
    mutationFn: (ids: string[] | null) => unwrap(api.POST('/api/v1/notifications/read', { body: { ids } })),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ['notifications'] }),
  });

  // Escape closes the list (and only the list) and puts focus back on the button; Up and Down move
  // between notifications.
  const close = () => {
    setOpen(false);
    button.current?.focus();
  };
  useEscapeLayer(open, close, (e) => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    const items = [...(popover.current?.querySelectorAll<HTMLElement>('li button') ?? [])];
    if (!items.length) return;
    e.preventDefault();
    const at = items.indexOf(document.activeElement as HTMLElement);
    const next = e.key === 'ArrowDown' ? (at + 1) % items.length : (at - 1 + items.length) % items.length;
    items[at === -1 ? 0 : next]?.focus();
  });
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);
  // Opening moves focus into the list (its heading until the notifications arrive).
  useEffect(() => {
    if (open) popover.current?.focus();
  }, [open]);
  // Leaving the list with Tab closes it.
  const onBlur = (e: FocusEvent) => {
    if (!ref.current?.contains(e.relatedTarget as Node | null)) setOpen(false);
  };

  const go = (n: Notification) => {
    if (!n.read_at) markRead.mutate([n.id]);
    setOpen(false);
    const project = queryClient.getQueryData<Project[]>(['projects'])?.find((p) => p.id === n.project_id);
    if (project && n.task_id) void navigate(`/projects/${project.key}?task=${n.task_id}`);
  };

  const unread = count.data?.unread ?? 0;
  return (
    <div ref={ref} className="relative" onBlur={onBlur}>
      <GhostButton
        ref={button}
        aria-expanded={open}
        aria-controls={open ? popoverId : undefined}
        onClick={() => setOpen((o) => !o)}
      >
        Notifications
        {unread > 0 && (
          <span
            className="ml-1.5 rounded-full bg-sky-700 px-1.5 text-xs text-white"
            aria-label={`${unread} unread`}
          >
            {unread}
          </span>
        )}
      </GhostButton>
      {open && (
        <div
          ref={popover}
          id={popoverId}
          role="region"
          aria-label="Notifications"
          tabIndex={-1}
          className="absolute right-0 z-30 mt-2 w-80 max-w-[calc(100vw-1.5rem)] rounded-lg border outline-none border-slate-200 bg-white shadow-lg dark:border-slate-700 dark:bg-slate-900"
        >
          <div className="flex items-center justify-between border-b border-slate-200 px-3 py-2 dark:border-slate-700">
            <span className="text-sm font-semibold">Notifications</span>
            <button
              type="button"
              className="rounded px-1 py-0.5 text-xs text-sky-700 hover:underline focus-visible:outline-2 focus-visible:outline-sky-600 dark:text-sky-400"
              onClick={() => markRead.mutate(null)}
            >
              Mark all read
            </button>
          </div>
          <ul className="max-h-96 overflow-y-auto">
            {list.data?.items.length === 0 && (
              <li className="p-3 text-sm text-slate-600 dark:text-slate-400">You're all caught up.</li>
            )}
            {list.data?.items.map((n) => (
              <li key={n.id}>
                <button
                  type="button"
                  onClick={() => go(n)}
                  className={`block w-full px-3 py-2 text-left text-sm hover:bg-slate-50 focus-visible:bg-slate-100 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-sky-600 dark:hover:bg-slate-800 dark:focus-visible:bg-slate-800 ${n.read_at ? 'text-slate-500 dark:text-slate-400' : 'font-medium'}`}
                >
                  {n.title}
                  <span className="block text-xs font-normal text-slate-500 dark:text-slate-400">
                    {new Date(n.created_at).toLocaleString()}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
