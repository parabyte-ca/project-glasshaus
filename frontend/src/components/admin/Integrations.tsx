import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';

import { api, unwrap, type Schemas } from '../../api/client';
import { Button, ErrorText, Field, GhostButton, Input, Select } from '../ui';
import { Copyable, SecretOnce, Section } from './common';
import { dateTime, table, td, th } from './format';

type Integration = Schemas['IntegrationRead'];
type Kind = Integration['kind'];

const KINDS: { kind: Kind; label: string; help: string }[] = [
  { kind: 'slack', label: 'Slack', help: 'Paste a Slack incoming-webhook URL (Apps → Incoming Webhooks).' },
  {
    kind: 'teams',
    label: 'Microsoft Teams',
    help: 'Paste a Teams workflow webhook URL ("Post to a channel when a webhook request is received").',
  },
  {
    kind: 'webhook',
    label: 'Signed webhook',
    help: 'Any HTTPS endpoint. Requests carry an HMAC-SHA256 signature.',
  },
  {
    kind: 'github',
    label: 'GitHub',
    help: 'Links commits and pull requests that mention task keys; "fixes KEY-12" completes on merge.',
  },
  { kind: 'gitlab', label: 'GitLab', help: 'Links commits and merge requests that mention task keys.' },
  {
    kind: 'email',
    label: 'Email to task',
    help: 'Polls an IMAP mailbox every two minutes; each new email becomes a task.',
  },
];
const OUTBOUND: Kind[] = ['slack', 'teams', 'webhook'];

function Deliveries({ id }: { id: string }) {
  const log = useQuery({
    queryKey: ['deliveries', id],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/integrations/{integration_id}/deliveries', {
          params: { path: { integration_id: id } },
        }),
      ),
  });
  if (log.data?.length === 0)
    return <p className="text-sm text-slate-600 dark:text-slate-400">No deliveries yet.</p>;
  return (
    <table className={table}>
      <thead>
        <tr>
          <th className={th}>When</th>
          <th className={th}>Event</th>
          <th className={th}>Status</th>
          <th className={th}>Attempts</th>
          <th className={th}>Error</th>
        </tr>
      </thead>
      <tbody>
        {(log.data ?? []).map((d) => (
          <tr key={d.id}>
            <td className={td}>{dateTime(d.created_at)}</td>
            <td className={td}>{d.event_type}</td>
            <td className={td}>{d.status}</td>
            <td className={td}>{d.attempts}</td>
            <td className={td}>{d.error ?? ''}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Row({ i, projects }: { i: Integration; projects: Map<string, string> }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['integrations'] });
  const path = { params: { path: { integration_id: i.id } } };
  const toggle = useMutation({
    mutationFn: () =>
      unwrap(api.PATCH('/api/v1/integrations/{integration_id}', { ...path, body: { enabled: !i.enabled } })),
    onSuccess: refresh,
  });
  const test = useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/integrations/{integration_id}/test', path)),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['deliveries', i.id] }),
  });
  const remove = useMutation({
    mutationFn: () => unwrap(api.DELETE('/api/v1/integrations/{integration_id}', path)),
    onSuccess: refresh,
  });
  return (
    <>
      <tr>
        <td className={td}>{i.name}</td>
        <td className={td}>{KINDS.find((k) => k.kind === i.kind)?.label}</td>
        <td className={td}>{i.project_id ? (projects.get(i.project_id) ?? 'project') : 'all projects'}</td>
        <td className={td}>
          {!i.enabled ? (
            'Off'
          ) : i.last_error && (!i.last_success_at || (i.last_error_at ?? '') > i.last_success_at) ? (
            <span className="text-red-700 dark:text-red-400">Failing: {i.last_error}</span>
          ) : i.last_success_at ? (
            `OK ${dateTime(i.last_success_at)}`
          ) : (
            'Waiting'
          )}
          {i.inbound_url && (
            <div className="mt-1 text-xs">
              Payload URL: <Copyable value={i.inbound_url} />
            </div>
          )}
        </td>
        <td className={`${td} whitespace-nowrap`}>
          <div className="flex flex-wrap gap-1">
            <GhostButton onClick={() => toggle.mutate()}>{i.enabled ? 'Turn off' : 'Turn on'}</GhostButton>
            {(OUTBOUND.includes(i.kind) || i.kind === 'email') && (
              <GhostButton
                aria-label={`Test ${i.name}`}
                onClick={() => test.mutate()}
                disabled={test.isPending}
              >
                Test
              </GhostButton>
            )}
            {OUTBOUND.includes(i.kind) && (
              <GhostButton aria-expanded={open} onClick={() => setOpen(!open)}>
                Deliveries
              </GhostButton>
            )}
            <GhostButton
              aria-label={`Remove ${i.name}`}
              onClick={() => window.confirm(`Remove ${i.name}?`) && remove.mutate()}
            >
              Remove
            </GhostButton>
          </div>
          {test.data && (
            <p role="status" className="mt-1 text-xs">
              Test: {test.data.status}
              {test.data.error ? ` (${test.data.error})` : ''}
            </p>
          )}
          <ErrorText error={toggle.error ?? test.error ?? remove.error} />
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={5} className={td}>
            <Deliveries id={i.id} />
          </td>
        </tr>
      )}
    </>
  );
}

export function Integrations() {
  const queryClient = useQueryClient();
  const list = useQuery({
    queryKey: ['integrations'],
    queryFn: () => unwrap(api.GET('/api/v1/integrations')),
  });
  const eventTypes = useQuery({
    queryKey: ['integration-event-types'],
    queryFn: () => unwrap(api.GET('/api/v1/integrations/event-types')),
    staleTime: Infinity,
  });
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => unwrap(api.GET('/api/v1/projects')) });
  const names = new Map((projects.data ?? []).map((p) => [p.id, `${p.key} ${p.name}`]));
  const [kind, setKind] = useState<Kind>('slack');
  const [form, setForm] = useState({
    name: '',
    project_id: '',
    url: '',
    secret: '',
    host: '',
    username: '',
    senders: '',
  });
  const [events, setEvents] = useState<string[]>(['task.created', 'task.completed', 'comment.created']);
  const [secret, setSecret] = useState<string | null>(null);
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm({ ...form, [k]: e.target.value });
  const create = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/v1/integrations', {
          body: {
            kind,
            name: form.name,
            project_id: form.project_id || null,
            events: OUTBOUND.includes(kind) ? events : [],
            url: OUTBOUND.includes(kind) ? form.url : null,
            secret: form.secret || null,
            email:
              kind === 'email'
                ? {
                    host: form.host,
                    username: form.username,
                    allowed_senders: form.senders
                      .split(',')
                      .map((s) => s.trim())
                      .filter(Boolean),
                  }
                : null,
          },
        }),
      ),
    onSuccess: async (created) => {
      setSecret(created.signing_secret ?? null);
      setForm({ name: '', project_id: '', url: '', secret: '', host: '', username: '', senders: '' });
      await queryClient.invalidateQueries({ queryKey: ['integrations'] });
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setSecret(null);
    create.mutate();
  };
  const needsProject = !OUTBOUND.includes(kind);

  return (
    <div className="flex flex-col gap-8">
      <Section
        title="Integrations"
        intro="Secrets (webhook URLs, signing secrets, mailbox passwords) are encrypted and never shown again. Task and comment text is passed on as plain text."
      >
        <ErrorText error={list.error} />
        {list.data?.length === 0 && <p className="text-sm text-slate-600 dark:text-slate-400">None yet.</p>}
        {(list.data?.length ?? 0) > 0 && (
          <div className="overflow-x-auto">
            <table className={table}>
              <thead>
                <tr>
                  <th className={th}>Name</th>
                  <th className={th}>Type</th>
                  <th className={th}>Scope</th>
                  <th className={th}>Status</th>
                  <th className={th}>
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {(list.data ?? []).map((i) => (
                  <Row key={i.id} i={i} projects={names} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
      <Section title="Connect">
        <form onSubmit={submit} className="grid max-w-3xl gap-3 sm:grid-cols-2">
          <Field label="Type" id="int-kind">
            <Select id="int-kind" value={kind} onChange={(e) => setKind(e.target.value as Kind)}>
              {KINDS.map((k) => (
                <option key={k.kind} value={k.kind}>
                  {k.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Name" id="int-name">
            <Input
              id="int-name"
              required
              value={form.name}
              onChange={set('name')}
              placeholder="#project-updates"
            />
          </Field>
          <p className="text-sm text-slate-600 sm:col-span-2 dark:text-slate-400">
            {KINDS.find((k) => k.kind === kind)?.help}
          </p>
          <Field label={needsProject ? 'Project' : 'Project (optional)'} id="int-project">
            <Select
              id="int-project"
              required={needsProject}
              value={form.project_id}
              onChange={set('project_id')}
            >
              <option value="">{needsProject ? 'Choose…' : 'All projects'}</option>
              {(projects.data ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.key} {p.name}
                </option>
              ))}
            </Select>
          </Field>
          {OUTBOUND.includes(kind) && (
            <Field label="Webhook URL" id="int-url">
              <Input id="int-url" type="url" required value={form.url} onChange={set('url')} />
            </Field>
          )}
          {kind === 'email' && (
            <>
              <Field label="IMAP host (TLS, port 993)" id="int-host">
                <Input id="int-host" required value={form.host} onChange={set('host')} />
              </Field>
              <Field label="Username" id="int-user">
                <Input id="int-user" required value={form.username} onChange={set('username')} />
              </Field>
              <Field label="Allowed senders (addresses or @domains, comma-separated)" id="int-senders">
                <Input id="int-senders" value={form.senders} onChange={set('senders')} />
              </Field>
            </>
          )}
          {kind !== 'slack' && kind !== 'teams' && (
            <Field
              label={kind === 'email' ? 'Password' : 'Signing secret (empty: generate one)'}
              id="int-secret"
            >
              <Input
                id="int-secret"
                type="password"
                autoComplete="off"
                required={kind === 'email'}
                value={form.secret}
                onChange={set('secret')}
              />
            </Field>
          )}
          {OUTBOUND.includes(kind) && (
            <fieldset className="sm:col-span-2">
              <legend className="mb-1 text-sm font-medium">Events</legend>
              <div className="flex flex-wrap gap-x-4 gap-y-1">
                {(eventTypes.data ?? []).map((t) => (
                  <label key={t} className="flex items-center gap-1 text-sm">
                    <input
                      type="checkbox"
                      checked={events.includes(t)}
                      onChange={() =>
                        setEvents(events.includes(t) ? events.filter((x) => x !== t) : [...events, t])
                      }
                    />
                    {t}
                  </label>
                ))}
              </div>
            </fieldset>
          )}
          <div className="sm:col-span-2">
            <Button type="submit" disabled={create.isPending}>
              Connect
            </Button>
          </div>
        </form>
        {secret && <SecretOnce label="Signing secret" value={secret} />}
        <ErrorText error={create.error} />
      </Section>
    </div>
  );
}
