import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router';

import { api, unwrap } from '../api/client';
import { HealthBadge, ProgressBar } from '../components/charts';
import { Button, ErrorText, Field, GhostButton, Input } from '../components/ui';
import { formatMinutes, shortDate } from '../lib/format';

function ProjectPicker({ selected, onChange }: { selected: string[]; onChange: (ids: string[]) => void }) {
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => unwrap(api.GET('/api/v1/projects')) });
  return (
    <fieldset className="flex flex-col gap-1">
      <legend className="mb-1 text-sm font-medium">Projects</legend>
      {projects.data?.map((p) => (
        <label key={p.id} className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={selected.includes(p.id)}
            onChange={(e) =>
              onChange(e.target.checked ? [...selected, p.id] : selected.filter((id) => id !== p.id))
            }
          />
          <span className="font-mono text-xs">{p.key}</span> {p.name}
        </label>
      ))}
    </fieldset>
  );
}

function PortfolioList() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const portfolios = useQuery({
    queryKey: ['portfolios'],
    queryFn: () => unwrap(api.GET('/api/v1/portfolios')),
  });
  const [name, setName] = useState('');
  const [projectIds, setProjectIds] = useState<string[]>([]);
  const create = useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/portfolios', { body: { name, project_ids: projectIds } })),
    onSuccess: (p) => {
      void queryClient.invalidateQueries({ queryKey: ['portfolios'] });
      void navigate(`/portfolios/${p.id}`);
    },
  });
  return (
    <div className="flex max-w-4xl flex-col gap-6">
      <h1 className="text-2xl font-bold">Portfolios</h1>
      <ul className="grid gap-3 sm:grid-cols-2">
        {portfolios.data?.length === 0 && (
          <li className="text-sm text-slate-600 dark:text-slate-400">
            No portfolios yet. Group related projects to see their health together.
          </li>
        )}
        {portfolios.data?.map((p) => (
          <li key={p.id} className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
            <Link to={`/portfolios/${p.id}`} className="font-medium hover:underline">
              {p.name}
            </Link>
            <p className="text-xs text-slate-600 dark:text-slate-400">
              {p.project_count} project{p.project_count === 1 ? '' : 's'}
            </p>
          </li>
        ))}
      </ul>
      <form
        aria-label="New portfolio"
        className="flex flex-col gap-3 rounded-lg border border-slate-200 p-4 dark:border-slate-800"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          create.mutate();
        }}
      >
        <h2 className="font-semibold">New portfolio</h2>
        <Field label="Name" id="pf-name">
          <Input
            id="pf-name"
            required
            maxLength={100}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>
        <ProjectPicker selected={projectIds} onChange={setProjectIds} />
        <div>
          <Button type="submit" disabled={create.isPending}>
            Create portfolio
          </Button>
        </div>
        <ErrorText error={create.error} />
      </form>
    </div>
  );
}

function PortfolioDetailView({ id }: { id: string }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const portfolio = useQuery({
    queryKey: ['portfolio', id],
    queryFn: () =>
      unwrap(api.GET('/api/v1/portfolios/{portfolio_id}', { params: { path: { portfolio_id: id } } })),
  });
  const [editing, setEditing] = useState<string[] | null>(null);
  const save = useMutation({
    mutationFn: (projectIds: string[]) =>
      unwrap(
        api.PATCH('/api/v1/portfolios/{portfolio_id}', {
          params: { path: { portfolio_id: id } },
          body: { project_ids: projectIds },
        }),
      ),
    onSuccess: () => {
      setEditing(null);
      void queryClient.invalidateQueries({ queryKey: ['portfolio', id] });
      void queryClient.invalidateQueries({ queryKey: ['portfolios'] });
    },
  });
  const remove = useMutation({
    mutationFn: () =>
      unwrap(api.DELETE('/api/v1/portfolios/{portfolio_id}', { params: { path: { portfolio_id: id } } })),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['portfolios'] });
      void navigate('/portfolios');
    },
  });
  if (portfolio.error) return <ErrorText error={portfolio.error} />;
  if (!portfolio.data) return <p role="status">Loading…</p>;
  const p = portfolio.data;
  return (
    <div className="flex max-w-5xl flex-col gap-4">
      <div>
        <Link to="/portfolios" className="text-sm text-sky-700 hover:underline dark:text-sky-400">
          ← Portfolios
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-bold">{p.name}</h1>
          <HealthBadge health={p.health} />
        </div>
        {p.description && <p className="text-sm text-slate-600 dark:text-slate-400">{p.description}</p>}
      </div>
      <div className="max-w-md">
        <ProgressBar value={p.progress} label="Portfolio progress" />
      </div>
      <table className="w-full text-left text-sm">
        <caption className="sr-only">Project health</caption>
        <thead className="text-xs text-slate-600 dark:text-slate-400">
          <tr>
            <th className="py-1 font-medium">Project</th>
            <th className="font-medium">Health</th>
            <th className="w-48 font-medium">Progress</th>
            <th className="text-right font-medium">Overdue</th>
            <th className="text-right font-medium">Finish</th>
            <th className="text-right font-medium">Slip</th>
            <th className="text-right font-medium">Logged</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 tabular-nums dark:divide-slate-800">
          {p.projects.map((h) => (
            <tr key={h.project_id}>
              <td className="py-1.5">
                <Link to={`/projects/${h.key}/report`} className="hover:underline">
                  <span className="mr-2 font-mono text-xs">{h.key}</span>
                  {h.name}
                </Link>
              </td>
              <td>
                <HealthBadge health={h.health} />
              </td>
              <td>
                <ProgressBar value={h.progress} label={`${h.key} progress`} />
              </td>
              <td className="text-right">{h.overdue}</td>
              <td className="text-right">{h.finish ? shortDate(h.finish) : '—'}</td>
              <td className="text-right">{h.slip_days ? `${h.slip_days}d` : '—'}</td>
              <td className="text-right">{formatMinutes(h.logged_minutes)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {editing ? (
        <div className="flex flex-col gap-3 rounded-lg border border-slate-200 p-4 dark:border-slate-800">
          <ProjectPicker selected={editing} onChange={setEditing} />
          <div className="flex gap-2">
            <Button onClick={() => save.mutate(editing)} disabled={save.isPending}>
              Save projects
            </Button>
            <GhostButton onClick={() => setEditing(null)}>Cancel</GhostButton>
          </div>
        </div>
      ) : (
        <div className="flex gap-2">
          <GhostButton onClick={() => setEditing(p.projects.map((x) => x.project_id))}>
            Edit projects
          </GhostButton>
          <GhostButton onClick={() => window.confirm(`Delete the portfolio "${p.name}"?`) && remove.mutate()}>
            Delete
          </GhostButton>
        </div>
      )}
      <ErrorText error={save.error ?? remove.error} />
    </div>
  );
}

export function PortfoliosPage() {
  const { portfolioId } = useParams();
  return portfolioId ? <PortfolioDetailView id={portfolioId} /> : <PortfolioList />;
}
