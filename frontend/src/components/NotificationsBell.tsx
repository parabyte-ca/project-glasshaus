import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router';

import { api, unwrap, type Notification, type Project } from '../api/client';
import { GhostButton } from './ui';

export function NotificationsBell() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
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

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const go = (n: Notification) => {
    if (!n.read_at) markRead.mutate([n.id]);
    setOpen(false);
    const project = queryClient.getQueryData<Project[]>(['projects'])?.find((p) => p.id === n.project_id);
    if (project && n.task_id) void navigate(`/projects/${project.key}?task=${n.task_id}`);
  };

  const unread = count.data?.unread ?? 0;
  return (
    <div ref={ref} className="relative">
      <GhostButton aria-haspopup="true" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
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
        <div className="absolute right-0 z-30 mt-2 w-80 rounded-lg border border-slate-200 bg-white shadow-lg dark:border-slate-700 dark:bg-slate-900">
          <div className="flex items-center justify-between border-b border-slate-200 px-3 py-2 dark:border-slate-700">
            <span className="text-sm font-semibold">Notifications</span>
            <button
              type="button"
              className="text-xs text-sky-700 hover:underline"
              onClick={() => markRead.mutate(null)}
            >
              Mark all read
            </button>
          </div>
          <ul className="max-h-96 overflow-y-auto">
            {list.data?.items.length === 0 && (
              <li className="p-3 text-sm text-slate-600">You're all caught up.</li>
            )}
            {list.data?.items.map((n) => (
              <li key={n.id}>
                <button
                  type="button"
                  onClick={() => go(n)}
                  className={`block w-full px-3 py-2 text-left text-sm hover:bg-slate-50 dark:hover:bg-slate-800 ${n.read_at ? 'text-slate-500' : 'font-medium'}`}
                >
                  {n.title}
                  <span className="block text-xs font-normal text-slate-500">
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
