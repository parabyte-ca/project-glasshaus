import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router';

import { api, fieldError, unwrap } from '../api/client';
import { useAuth } from '../auth/useAuth';
import { LoadError } from '../components/PageState';
import { Button, ErrorText, Field, Input, linkClass, Select } from '../components/ui';
import { usePageTitle } from '../lib/pageTitle';

export function HomePage() {
  usePageTitle('Home');
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const workspaces = useQuery({
    queryKey: ['workspaces'],
    queryFn: () => unwrap(api.GET('/api/v1/workspaces')),
  });
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => unwrap(api.GET('/api/v1/projects')) });
  const [wsName, setWsName] = useState('');
  const [workspaceId, setWorkspaceId] = useState('');
  const [key, setKey] = useState('');
  const [name, setName] = useState('');
  const [templateId, setTemplateId] = useState('');
  const templates = useQuery({
    queryKey: ['project-templates'],
    queryFn: () => unwrap(api.GET('/api/v1/project-templates')),
  });

  const createWorkspace = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/v1/workspaces', {
          body: {
            name: wsName,
            slug:
              wsName
                .toLowerCase()
                .replace(/[^a-z0-9]+/g, '-')
                .replace(/^-|-$/g, '') || 'workspace',
          },
        }),
      ),
    onSuccess: (ws) => {
      setWsName('');
      setWorkspaceId(ws.id);
      void queryClient.invalidateQueries({ queryKey: ['workspaces'] });
    },
  });
  const createProject = useMutation({
    mutationFn: () => {
      const body = {
        workspace_id: workspaceId || workspaces.data?.[0]?.id || '',
        key: key.toUpperCase(),
        name,
      };
      return templateId
        ? unwrap(
            api.POST('/api/v1/project-templates/{template_id}/instantiate', {
              params: { path: { template_id: templateId } },
              body,
            }),
          )
        : unwrap(api.POST('/api/v1/projects', { body }));
    },
    onSuccess: (project) => {
      void queryClient.invalidateQueries({ queryKey: ['projects'] });
      void navigate(`/projects/${project.key}`);
    },
  });

  const onWorkspace = (e: FormEvent) => {
    e.preventDefault();
    createWorkspace.mutate();
  };
  const onProject = (e: FormEvent) => {
    e.preventDefault();
    createProject.mutate();
  };

  return (
    <div className="flex max-w-3xl flex-col gap-8">
      <section aria-labelledby="projects-heading">
        <h1 id="projects-heading" className="text-2xl font-bold">
          Projects
        </h1>
        {(user.direct_reports ?? 0) > 0 && (
          <p className="mt-1 text-sm">
            <Link to="/team" className={linkClass}>
              My team
            </Link>
            : the work of the {user.direct_reports} {user.direct_reports === 1 ? 'person' : 'people'} who
            report to you.
          </p>
        )}
        {projects.isPending && (
          <p role="status" className="mt-2">
            Loading…
          </p>
        )}
        {projects.error && (
          <LoadError error={projects.error} what="your projects" onRetry={() => void projects.refetch()} />
        )}
        {projects.data?.length === 0 && (
          <p className="mt-2 text-slate-600 dark:text-slate-400">No projects yet. Create one below.</p>
        )}
        <ul className="mt-4 grid gap-3 sm:grid-cols-2">
          {projects.data?.map((p) => (
            <li key={p.id} className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
              <Link to={`/projects/${p.key}`} className="font-medium hover:underline">
                {p.name}
              </Link>
              <p className="font-mono text-xs text-slate-600 dark:text-slate-400">{p.key}</p>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="new-project" className="flex flex-col gap-3">
        <h2 id="new-project" className="text-lg font-semibold">
          New project
        </h2>
        {workspaces.data?.length === 0 ? (
          <form onSubmit={onWorkspace} className="flex flex-wrap items-end gap-3">
            <Field label="First, name a workspace" id="ws-name">
              <Input id="ws-name" required value={wsName} onChange={(e) => setWsName(e.target.value)} />
            </Field>
            <Button type="submit" disabled={createWorkspace.isPending}>
              Create workspace
            </Button>
            <ErrorText error={createWorkspace.error} />
          </form>
        ) : (
          <form onSubmit={onProject} className="flex flex-wrap items-end gap-3">
            <Field label="Workspace" id="ws">
              <Select id="ws" value={workspaceId} onChange={(e) => setWorkspaceId(e.target.value)}>
                {workspaces.data?.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Key" id="key" error={fieldError(createProject.error, 'key')}>
              <Input
                id="key"
                required
                pattern="[A-Za-z][A-Za-z0-9]{1,9}"
                className="w-24 uppercase"
                value={key}
                onChange={(e) => setKey(e.target.value)}
              />
            </Field>
            <Field label="Name" id="name" error={fieldError(createProject.error, 'name')}>
              <Input id="name" required value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            {!!templates.data?.length && (
              <Field label="Start from" id="template">
                <Select id="template" value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
                  <option value="">Blank project</option>
                  {templates.data.map((t) => (
                    <option key={t.id} value={t.id}>
                      Template: {t.name} ({t.summary.tasks} tasks)
                    </option>
                  ))}
                </Select>
              </Field>
            )}
            <Button type="submit" disabled={createProject.isPending}>
              Create project
            </Button>
            <ErrorText error={createProject.error} />
          </form>
        )}
      </section>
    </div>
  );
}
