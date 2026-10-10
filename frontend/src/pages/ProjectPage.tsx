import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router';

import { api, unwrap, type Task, type ViewConfig, type ViewKind } from '../api/client';
import { Beacon } from '../components/onboarding/Beacon';
import { ProjectPeople } from '../components/ProjectPeople';
import { Button, ErrorText, GhostButton, Input, linkClass, Select } from '../components/ui';
import { PRIORITIES } from '../lib/grouping';
import { configWithParams, defaultConfig, OPEN, paramsForConfig } from '../lib/views';
import { useAiStatus } from '../lib/ai';
import { useOnboarding } from '../lib/onboarding';
import { useProject } from '../lib/useProject';
import { ListView } from '../views/ListView';
import { useTaskUpdate, type TaskPatch } from '../lib/taskUpdates';
import { toast } from '../lib/toast';
import { usePageTitle } from '../lib/pageTitle';
import { LoadError } from '../components/PageState';

// Layouts and the task drawer load on demand to keep the first page small.
const TaskDrawer = lazy(() => import('../components/TaskDrawer').then((m) => ({ default: m.TaskDrawer })));
const BoardView = lazy(() => import('../views/BoardView').then((m) => ({ default: m.BoardView })));
const CalendarView = lazy(() => import('../views/CalendarView').then((m) => ({ default: m.CalendarView })));
const TableView = lazy(() => import('../views/TableView').then((m) => ({ default: m.TableView })));
const AiAssistant = lazy(() => import('../components/AiAssistant').then((m) => ({ default: m.AiAssistant })));
const TimelineView = lazy(() => import('../views/TimelineView').then((m) => ({ default: m.TimelineView })));

const KINDS: { kind: ViewKind; label: string }[] = [
  { kind: 'list', label: 'List' },
  { kind: 'board', label: 'Board' },
  { kind: 'table', label: 'Table' },
  { kind: 'timeline', label: 'Timeline' },
  { kind: 'calendar', label: 'Calendar' },
];
export function ProjectPage() {
  const { projectKey = '' } = useParams();
  // A fresh page per project: filters, search and a half-typed task never carry over to another one.
  return <ProjectPageFor key={projectKey} projectKey={projectKey} />;
}

function ProjectPageFor({ projectKey }: { projectKey: string }) {
  const [params, setParams] = useSearchParams();
  const queryClient = useQueryClient();
  const { project, fields, views, users } = useProject(projectKey);
  const p = project.data;
  usePageTitle(p?.name ?? 'Project');
  const ai = useAiStatus();
  const aiFeatures = (ai.data?.features ?? []).filter(
    (f) => f === 'summaries' || f === 'drafting' || f === 'risks',
  );
  const [assistant, setAssistant] = useState(false);

  const viewId = params.get('view');
  const savedView = views.find((v) => v.id === viewId);
  const kind = (params.get('kind') as ViewKind | null) ?? savedView?.kind ?? 'list';
  const baseConfig = savedView?.config ?? defaultConfig(kind);
  const config = configWithParams(baseConfig, params);
  // Filter changes replace the address entry instead of adding one per keystroke.
  const setConfig = (next: ViewConfig) =>
    setParams((prev) => paramsForConfig(baseConfig, next, prev), { replace: true });
  const setParam = (key: string, value: string | null) =>
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      if (value === null) next.delete(key);
      else next.set(key, value);
      return next;
    });

  const filters = config.filters ?? {};
  const tasksQuery = useQuery({
    queryKey: ['tasks', p?.id, config],
    enabled: !!p,
    placeholderData: keepPreviousData,
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/tasks', {
          params: {
            query: {
              project_id: p!.id,
              ...filters,
              sort: config.sort,
              descending: config.descending,
              sort_field: config.sort_field ?? undefined,
              limit: 500,
            },
          },
        }),
      ),
  });
  const tasks = useMemo(() => tasksQuery.data?.items ?? [], [tasksQuery.data]);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['tasks', p?.id] });
  const update = useTaskUpdate(p?.id, p?.statuses);
  const [title, setTitle] = useState('');
  const create = useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/tasks', { body: { project_id: p!.id, title } })),
    onSuccess: (created) => {
      setTitle('');
      toast(`${created.key} created`);
      void invalidate();
    },
  });
  const [saveName, setSaveName] = useState<string | null>(null);
  const [shareView, setShareView] = useState(false);
  const saveView = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/v1/projects/{project_id}/views', {
          params: { path: { project_id: p!.id } },
          body: { name: saveName!, kind, shared: shareView, config },
        }),
      ),
    onSuccess: (view) => {
      setSaveName(null);
      void queryClient.invalidateQueries({ queryKey: ['views', p!.id] });
      setParams({ view: view.id });
    },
  });

  // Product tour: starts by itself the first time someone opens a project, or on demand (?tour=1
  // from Help, the command palette or the getting-started checklist).
  const onboarding = useOnboarding();
  const tourRequested = params.get('tour') === '1';
  const autoStarted = useRef(false);
  const activeTour = useRef<{ destroy: () => void } | null>(null);
  const ready = !!p && tasksQuery.isSuccess && !params.get('task');
  useEffect(() => {
    if (!ready || activeTour.current) return;
    const firstVisit = onboarding.state?.tour === null && !autoStarted.current;
    if (!tourRequested && !firstVisit) return;
    autoStarted.current = true;
    if (tourRequested) setParam('tour', null);
    const previous = onboarding.state?.tour;
    activeTour.current = { destroy: () => undefined };
    void import('../components/onboarding/tour').then(({ startTour }) => {
      if (!activeTour.current) return; // left the page meanwhile
      activeTour.current = startTour((outcome) => {
        activeTour.current = null;
        // Skipping a repeat tour never undoes a finished one.
        if (outcome === 'completed' || previous !== 'completed') onboarding.update({ tour: outcome });
      });
    });
  }, [ready, tourRequested, onboarding]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(
    () => () => {
      activeTour.current?.destroy();
      activeTour.current = null;
    },
    [],
  );

  // Opening a task adds one history entry and closing it goes back, so Back after closing leaves the
  // project instead of reopening the task. A drawer reached by a link closes in place.
  const location = useLocation();
  const navigate = useNavigate();
  const openedHere = (location.state as { drawer?: boolean } | null)?.drawer === true;
  const openTask = useCallback(
    (task: Task) =>
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set('task', task.key);
          return next;
        },
        { state: { drawer: true }, replace: !!params.get('task') },
      ),
    [setParams, params],
  );
  const closeTask = useCallback(() => {
    if (openedHere) void navigate(-1);
    else
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.delete('task');
          return next;
        },
        { replace: true },
      );
  }, [openedHere, navigate, setParams]);

  if (project.isError) {
    return <LoadError error={project.error} what="project" onRetry={() => void project.refetch()} />;
  }
  if (!p) return <p role="status">Loading…</p>;

  const showCompleted = !filters.status_categories;
  const selectFields = fields.filter((f) => f.type === 'select' || f.type === 'multi_select');
  const props = {
    tasks,
    project: p,
    fields,
    users,
    config,
    onOpen: openTask,
    onUpdate: (task: Task, patch: TaskPatch) => update.mutate({ task, patch }),
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-bold">
          {p.name} <span className="font-mono text-sm text-slate-600 dark:text-slate-400">{p.key}</span>
        </h1>
        <div className="flex flex-wrap items-center gap-4">
          <ProjectPeople project={p} users={users} defaultOpen={params.get('people') === '1'} />
          {aiFeatures.length > 0 && (
            <GhostButton aria-expanded={assistant} onClick={() => setAssistant((v) => !v)}>
              AI tools
            </GhostButton>
          )}
          <Link to={`/projects/${p.key}/report`} className={`text-sm ${linkClass}`}>
            Report
          </Link>
          <Link to={`/projects/${p.key}/assistant`} className={`text-sm ${linkClass}`}>
            Project assistant
          </Link>
          {p.my_role === 'admin' && (
            <span className="flex items-center gap-1">
              <Link to={`/projects/${p.key}/settings`} className={`text-sm ${linkClass}`}>
                Project settings
              </Link>
              <Beacon id="automations" title="Automations">
                Project settings hold automations (“when a task moves to Done, notify the reporter”),
                recurring tasks and custom fields.
              </Beacon>
            </span>
          )}
        </div>
      </div>

      {assistant && aiFeatures.length > 0 && (
        <Suspense fallback={<p role="status">Loading assistant…</p>}>
          <AiAssistant project={p} features={aiFeatures} />
        </Suspense>
      )}

      <div className="flex flex-wrap items-end gap-3" role="toolbar" aria-label="View options">
        <div
          className="flex rounded-md border border-slate-300 dark:border-slate-600"
          role="group"
          aria-label="Layout"
        >
          {KINDS.map((k) => (
            <button
              key={k.kind}
              type="button"
              aria-pressed={kind === k.kind}
              data-tour={k.kind === 'timeline' ? 'timeline-switch' : undefined}
              onClick={() => setParam('kind', k.kind)}
              className={`px-3 py-1.5 text-sm first:rounded-l-md last:rounded-r-md ${kind === k.kind ? 'bg-sky-700 text-white' : 'hover:bg-slate-100 dark:hover:bg-slate-800'}`}
            >
              {k.label}
            </button>
          ))}
        </div>
        <span className="self-center">
          <Beacon id="timeline" title="Timeline view">
            Plan dates on a Gantt-style timeline: drag bars or use the arrow keys, and check the critical path
            and dependencies.
          </Beacon>
        </span>
        <Select
          aria-label="Saved view"
          value={viewId ?? ''}
          onChange={(e) => setParams(e.target.value ? { view: e.target.value } : {})}
        >
          <option value="">Default view</option>
          {views.map((v) => (
            <option key={v.id} value={v.id}>
              {v.name}
              {v.shared ? ' (shared)' : ''}
            </option>
          ))}
        </Select>
        <Input
          aria-label="Search tasks"
          data-shortcut="search"
          aria-keyshortcuts="/"
          placeholder="Search…"
          value={filters.q ?? ''}
          onChange={(e) => setConfig({ ...config, filters: { ...filters, q: e.target.value || null } })}
        />
        <Select
          aria-label="Priority filter"
          value={filters.priorities?.[0] ?? ''}
          onChange={(e) =>
            setConfig({
              ...config,
              filters: {
                ...filters,
                priorities: e.target.value ? [e.target.value as Task['priority']] : null,
              },
            })
          }
        >
          <option value="">Any priority</option>
          {PRIORITIES.map((pr) => (
            <option key={pr} value={pr}>
              {pr}
            </option>
          ))}
        </Select>
        <Select
          aria-label="Group by"
          value={config.group_by ?? ''}
          onChange={(e) => setConfig({ ...config, group_by: e.target.value || null })}
        >
          <option value="">No grouping</option>
          <option value="status">Group: status</option>
          <option value="assignee">Group: assignee</option>
          <option value="priority">Group: priority</option>
          {selectFields.map((f) => (
            <option key={f.id} value={`cf:${f.id}`}>
              Group: {f.name}
            </option>
          ))}
        </Select>
        <Select
          aria-label="Sort by"
          value={config.sort_field ? `cf:${config.sort_field}` : config.sort}
          onChange={(e) => {
            const v = e.target.value;
            setConfig(
              v.startsWith('cf:')
                ? { ...config, sort_field: v.slice(3) }
                : { ...config, sort_field: null, sort: v as ViewConfig['sort'] },
            );
          }}
        >
          <option value="position">Sort: manual</option>
          <option value="due_date">Sort: due date</option>
          <option value="priority">Sort: priority</option>
          <option value="updated_at">Sort: recently updated</option>
          <option value="title">Sort: title</option>
          {fields
            .filter((f) => ['number', 'date', 'text'].includes(f.type))
            .map((f) => (
              <option key={f.id} value={`cf:${f.id}`}>
                Sort: {f.name}
              </option>
            ))}
        </Select>
        <label className="flex items-center gap-2 pb-1.5 text-sm">
          <input
            type="checkbox"
            checked={showCompleted}
            onChange={(e) =>
              setConfig({
                ...config,
                filters: { ...filters, status_categories: e.target.checked ? null : [...OPEN] },
              })
            }
          />
          Show completed
        </label>
        {saveName === null ? (
          <GhostButton onClick={() => setSaveName(savedView ? `${savedView.name} copy` : 'My view')}>
            Save view
          </GhostButton>
        ) : (
          <form
            className="flex items-end gap-2"
            onSubmit={(e: FormEvent) => {
              e.preventDefault();
              saveView.mutate();
            }}
          >
            <Input
              aria-label="View name"
              required
              maxLength={100}
              value={saveName}
              onChange={(e) => setSaveName(e.target.value)}
            />
            {p.my_role === 'admin' && (
              <label className="flex items-center gap-1 pb-1.5 text-sm">
                <input type="checkbox" checked={shareView} onChange={(e) => setShareView(e.target.checked)} />
                Shared
              </label>
            )}
            <Button type="submit" disabled={saveView.isPending}>
              Save
            </Button>
            <GhostButton onClick={() => setSaveName(null)}>Cancel</GhostButton>
          </form>
        )}
      </div>

      <form
        className="flex gap-2"
        data-tour="create-task"
        onSubmit={(e) => {
          e.preventDefault();
          if (title.trim()) create.mutate();
        }}
      >
        <label htmlFor="new-task" className="sr-only">
          New task title
        </label>
        <Input
          id="new-task"
          data-shortcut="new-task"
          aria-keyshortcuts="c"
          placeholder="Add a task and press Enter"
          className="flex-1"
          value={title}
          maxLength={500}
          onChange={(e) => setTitle(e.target.value)}
        />
        <Button type="submit" disabled={create.isPending || !title.trim()}>
          Add
        </Button>
      </form>
      <ErrorText error={create.error ?? update.error ?? saveView.error} />
      <div data-tour="task-view">
        <Suspense fallback={<p role="status">Loading view…</p>}>
          {tasksQuery.isPending ? (
            <p role="status" className="py-6 text-slate-600 dark:text-slate-400">
              Loading tasks…
            </p>
          ) : tasksQuery.isError && !tasksQuery.data ? (
            <LoadError error={tasksQuery.error} what="task list" onRetry={() => void tasksQuery.refetch()} />
          ) : (
            {
              board: <BoardView {...props} />,
              table: <TableView {...props} />,
              timeline: <TimelineView {...props} />,
              calendar: <CalendarView {...props} />,
              list: <ListView {...props} />,
            }[kind]
          )}
        </Suspense>
      </div>

      {params.get('task') && (
        <Suspense fallback={null}>
          <TaskDrawer
            taskRef={params.get('task')!}
            project={p}
            fields={fields}
            users={users}
            onClose={closeTask}
          />
        </Suspense>
      )}
    </div>
  );
}
