import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';

import { api, unwrap, type KeyResult, type Objective, type Schemas } from '../api/client';
import { useAuth } from '../auth/useAuth';
import { LoadError } from '../components/PageState';
import { HealthBadge, ProgressBar } from '../components/charts';
import { Button, ErrorText, Field, GhostButton, Input, Select } from '../components/ui';
import { currentQuarter } from '../lib/format';
import { usePageTitle } from '../lib/pageTitle';
import { useConfirm } from '../lib/confirm';

type KrInput = Schemas['KeyResultCreate'];
type Confidence = Schemas['Confidence'];

function CheckInForm({ kr, onDone }: { kr: KeyResult; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [value, setValue] = useState(String(kr.current_value ?? ''));
  const [confidence, setConfidence] = useState<Confidence>(kr.confidence ?? 'on_track');
  const [note, setNote] = useState('');
  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/v1/key-results/{kr_id}/check-ins', {
          params: { path: { kr_id: kr.id } },
          body: { confidence, note, value: kr.kind === 'metric' ? Number(value) : null },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['objectives'] });
      onDone();
    },
  });
  return (
    <form
      aria-label={`Check in on ${kr.title}`}
      className="mt-2 flex flex-wrap items-end gap-2"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      {kr.kind === 'metric' && (
        <Field label={`Current value${kr.unit ? ` (${kr.unit})` : ''}`} id={`ci-v-${kr.id}`}>
          <Input
            id={`ci-v-${kr.id}`}
            type="number"
            step="any"
            required
            className="w-28"
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
        </Field>
      )}
      <Field label="Confidence" id={`ci-c-${kr.id}`}>
        <Select
          id={`ci-c-${kr.id}`}
          value={confidence}
          onChange={(e) => setConfidence(e.target.value as Confidence)}
        >
          <option value="on_track">On track</option>
          <option value="at_risk">At risk</option>
          <option value="off_track">Off track</option>
        </Select>
      </Field>
      <Field label="Note" id={`ci-n-${kr.id}`}>
        <Input id={`ci-n-${kr.id}`} maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
      <Button type="submit" disabled={save.isPending}>
        Save check-in
      </Button>
      <GhostButton onClick={onDone}>Cancel</GhostButton>
      <ErrorText error={save.error} />
    </form>
  );
}

function KeyResultRow({ kr, canEdit }: { kr: KeyResult; canEdit: boolean }) {
  const [checkingIn, setCheckingIn] = useState(false);
  const detail =
    kr.kind === 'tasks'
      ? kr.progress === null
        ? 'Linked project not visible to you'
        : `${kr.current_value ?? 0} of ${kr.total_tasks ?? 0} tasks done${kr.tag ? ` (tag ${kr.tag})` : ''}`
      : `${kr.current_value} of ${kr.target_value}${kr.unit ? ` ${kr.unit}` : ''} (from ${kr.start_value})`;
  return (
    <li className="py-2">
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <span>{kr.title}</span>
        <span className="flex items-center gap-2">
          <HealthBadge health={kr.confidence} />
          {canEdit && !checkingIn && (
            <GhostButton className="px-2 py-0.5 text-xs" onClick={() => setCheckingIn(true)}>
              Check in
            </GhostButton>
          )}
        </span>
      </div>
      {kr.progress !== null && <ProgressBar value={kr.progress} label={`${kr.title} progress`} />}
      <p className="text-xs text-slate-600 dark:text-slate-400">{detail}</p>
      {checkingIn && <CheckInForm kr={kr} onDone={() => setCheckingIn(false)} />}
    </li>
  );
}

function ObjectiveCard({
  objective,
  ownerName,
  canEdit,
}: {
  objective: Objective;
  ownerName: string;
  canEdit: boolean;
}) {
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const remove = useMutation({
    mutationFn: () =>
      unwrap(
        api.DELETE('/api/v1/objectives/{objective_id}', { params: { path: { objective_id: objective.id } } }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['objectives'] }),
  });
  return (
    <li className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="font-semibold">{objective.title}</h2>
          <p className="text-xs text-slate-600 dark:text-slate-400">
            {objective.period} · {ownerName}
          </p>
        </div>
        <span className="flex items-center gap-2">
          <HealthBadge health={objective.confidence} />
          {canEdit && (
            <GhostButton
              className="px-2 py-0.5 text-xs"
              aria-label={`Delete objective ${objective.title}`}
              onClick={async () =>
                (await confirm({
                  title: `Delete the objective "${objective.title}"?`,
                  body: 'Its key results and check-ins are deleted too.',
                  confirmLabel: 'Delete',
                  danger: true,
                })) && remove.mutate()
              }
            >
              Delete
            </GhostButton>
          )}
        </span>
      </div>
      {objective.progress !== null && (
        <div className="mt-2">
          <ProgressBar value={objective.progress} label={`${objective.title} progress`} />
        </div>
      )}
      <ul className="mt-2 divide-y divide-slate-100 dark:divide-slate-800">
        {objective.key_results.map((kr) => (
          <KeyResultRow key={kr.id} kr={kr} canEdit={canEdit} />
        ))}
      </ul>
    </li>
  );
}

function NewObjective({ period, onCreated }: { period: string; onCreated: () => void }) {
  const queryClient = useQueryClient();
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => unwrap(api.GET('/api/v1/projects')) });
  const [title, setTitle] = useState('');
  const [krs, setKrs] = useState<KrInput[]>([
    { title: '', kind: 'metric', start_value: 0, target_value: 100 },
  ]);
  const setKr = (i: number, patch: Partial<KrInput>) =>
    setKrs(krs.map((k, j) => (j === i ? { ...k, ...patch } : k)));
  const create = useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/objectives', { body: { title, period, key_results: krs } })),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['objectives'] });
      onCreated();
    },
  });
  return (
    <form
      aria-label="New objective"
      className="flex flex-col gap-3 rounded-lg border border-slate-200 p-4 dark:border-slate-800"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        create.mutate();
      }}
    >
      <Field label="Objective" id="obj-title">
        <Input
          id="obj-title"
          required
          maxLength={200}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
      </Field>
      <fieldset className="flex flex-col gap-3">
        <legend className="mb-1 text-sm font-semibold">Key results</legend>
        {krs.map((kr, i) => (
          <div key={i} className="flex flex-wrap items-end gap-2">
            <Field label="Key result" id={`kr-t-${i}`}>
              <Input
                id={`kr-t-${i}`}
                required
                value={kr.title}
                onChange={(e) => setKr(i, { title: e.target.value })}
              />
            </Field>
            <Field label="Measured by" id={`kr-k-${i}`}>
              <Select
                id={`kr-k-${i}`}
                value={kr.kind}
                onChange={(e) => setKr(i, { kind: e.target.value as KrInput['kind'] })}
              >
                <option value="metric">A number</option>
                <option value="tasks">Tasks done in a project</option>
              </Select>
            </Field>
            {kr.kind === 'tasks' ? (
              <>
                <Field label="Project" id={`kr-p-${i}`}>
                  <Select
                    id={`kr-p-${i}`}
                    required
                    value={kr.project_id ?? ''}
                    onChange={(e) => setKr(i, { project_id: e.target.value || null })}
                  >
                    <option value="">Choose…</option>
                    {projects.data?.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.key} — {p.name}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Only tag (optional)" id={`kr-tag-${i}`}>
                  <Input
                    id={`kr-tag-${i}`}
                    className="w-28"
                    value={kr.tag ?? ''}
                    onChange={(e) => setKr(i, { tag: e.target.value || null })}
                  />
                </Field>
              </>
            ) : (
              <>
                <Field label="Start" id={`kr-s-${i}`}>
                  <Input
                    id={`kr-s-${i}`}
                    type="number"
                    step="any"
                    className="w-24"
                    value={kr.start_value ?? 0}
                    onChange={(e) => setKr(i, { start_value: Number(e.target.value) })}
                  />
                </Field>
                <Field label="Target" id={`kr-g-${i}`}>
                  <Input
                    id={`kr-g-${i}`}
                    type="number"
                    step="any"
                    className="w-24"
                    value={kr.target_value ?? 100}
                    onChange={(e) => setKr(i, { target_value: Number(e.target.value) })}
                  />
                </Field>
                <Field label="Unit" id={`kr-u-${i}`}>
                  <Input
                    id={`kr-u-${i}`}
                    className="w-20"
                    maxLength={20}
                    value={kr.unit ?? ''}
                    onChange={(e) => setKr(i, { unit: e.target.value })}
                  />
                </Field>
              </>
            )}
            {krs.length > 1 && (
              <GhostButton
                aria-label={`Remove key result ${i + 1}`}
                onClick={() => setKrs(krs.filter((_, j) => j !== i))}
              >
                ✕
              </GhostButton>
            )}
          </div>
        ))}
        <div>
          <GhostButton
            disabled={krs.length >= 10}
            onClick={() => setKrs([...krs, { title: '', kind: 'metric', start_value: 0, target_value: 100 }])}
          >
            Add key result
          </GhostButton>
        </div>
      </fieldset>
      <div className="flex gap-2">
        <Button type="submit" disabled={create.isPending}>
          Create objective
        </Button>
        <GhostButton onClick={onCreated}>Cancel</GhostButton>
      </div>
      <ErrorText error={create.error} />
    </form>
  );
}

export function GoalsPage() {
  usePageTitle('Goals');
  const { user } = useAuth();
  const [period, setPeriod] = useState(currentQuarter);
  const [creating, setCreating] = useState(false);
  const users = useQuery({ queryKey: ['users'], queryFn: () => unwrap(api.GET('/api/v1/users')) });
  const objectives = useQuery({
    queryKey: ['objectives', period],
    queryFn: () =>
      unwrap(api.GET('/api/v1/objectives', { params: { query: { period: period || undefined } } })),
  });
  const names = new Map(users.data?.map((u) => [u.id, u.name]));
  const isAdmin = user.org_role === 'owner' || user.org_role === 'admin';
  const year = new Date().getFullYear();
  const periods = [year - 1, year, year + 1].flatMap((y) => [
    `${y}`,
    `${y}-Q1`,
    `${y}-Q2`,
    `${y}-Q3`,
    `${y}-Q4`,
  ]);
  return (
    <div className="flex max-w-4xl flex-col gap-4">
      <h1 className="text-2xl font-bold">Goals</h1>
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Period" id="okr-period">
          <Select id="okr-period" value={period} onChange={(e) => setPeriod(e.target.value)}>
            <option value="">All periods</option>
            {periods.map((p) => (
              <option key={p}>{p}</option>
            ))}
          </Select>
        </Field>
        {!creating && period && <Button onClick={() => setCreating(true)}>New objective</Button>}
      </div>
      {creating && <NewObjective period={period} onCreated={() => setCreating(false)} />}
      {objectives.error && (
        <LoadError
          inline
          error={objectives.error}
          what="these objectives"
          onRetry={() => void objectives.refetch()}
        />
      )}
      {objectives.data?.length === 0 && !creating && (
        <p className="text-sm text-slate-600 dark:text-slate-400">No objectives for this period yet.</p>
      )}
      <ul className="flex flex-col gap-3">
        {objectives.data?.map((o) => (
          <ObjectiveCard
            key={o.id}
            objective={o}
            ownerName={(o.owner_id && names.get(o.owner_id)) || 'No owner'}
            canEdit={isAdmin || o.owner_id === user.id}
          />
        ))}
      </ul>
    </div>
  );
}
