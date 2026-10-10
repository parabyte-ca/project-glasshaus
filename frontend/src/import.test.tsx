import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import App from './App';
import {
  buildRows,
  detectDateFormat,
  guessMapping,
  guessPriority,
  guessStatus,
  readFile,
} from './lib/importer';
import { keysFor } from './lib/realtime';
import { baseRoutes, mockApi, statuses, user, type Route } from './test/mockApi';

function renderAt(path: string) {
  window.history.pushState({}, '', path);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
}

const signedIn: Route = { method: 'GET', path: '/api/v1/users/me', body: user };
const CSV = [
  'Work Item ID,Title,Lane,Priority,Owner,Due Date,Labels',
  'N-1,Draft brief,In Progress,Major,ada@example.com,15/10/2026,"ux, copy"',
  'N-2,Review brief,Closed,Minor,pat@example.com,20/10/2026,',
  ',,,,,,',
].join('\n');

beforeEach(() => {
  document.cookie = 'gh_csrf=csrf-123; path=/';
});
afterEach(() => vi.restoreAllMocks());

describe('import helpers', () => {
  it('reads CSV and guesses columns, including Nimble names and custom fields', async () => {
    const [sheet] = await readFile(new File(['﻿' + CSV], 'export.csv', { type: 'text/csv' }));
    expect(sheet!.rows[0]![0]).toBe('Work Item ID');
    expect(sheet!.rows).toHaveLength(3); // blank lines are skipped
    const mapping = guessMapping(sheet!.rows[0]!, 'nimble');
    expect(mapping).toEqual(['external_id', 'title', 'status', 'priority', 'assignee', 'due_date', 'tags']);
    expect(
      guessMapping(['Summary', 'Severity', 'Summary'], 'spreadsheet', [{ id: 'f1', name: 'Severity' }]),
    ).toEqual(['title', 'cf:f1', '']);
    const rows = buildRows(sheet!.rows.slice(1), mapping);
    expect(rows).toHaveLength(2);
    expect(buildRows([['', '']], ['title', 'status'])).toEqual([]); // empty rows are dropped
    expect(rows[0]).toMatchObject({ row: 2, external_id: 'N-1', title: 'Draft brief', tags: 'ux, copy' });
    expect(
      buildRows([['a', 'https://x.test/1 https://x.test/2', 'note']], ['title', 'links', 'comments'])[0],
    ).toMatchObject({ links: ['https://x.test/1', 'https://x.test/2'], comments: ['note'] });
  });

  it('guesses date formats, statuses and priorities', () => {
    expect(detectDateFormat(['15/10/2026', '01/02/2026'])).toBe('dmy');
    expect(detectDateFormat(['10/15/2026'])).toBe('mdy');
    expect(detectDateFormat(['01/02/2026', '2026-10-01'])).toBeNull();
    expect(guessStatus('done', statuses)).toBe('s-done');
    expect(guessStatus('Closed', statuses)).toBe('s-done');
    expect(guessStatus('Open', statuses)).toBe('s-todo');
    expect(guessStatus('Mystery', statuses)).toBe('');
    expect(guessPriority('Major')).toBe('high');
    expect(guessPriority('Expedite')).toBe('urgent');
    expect(guessPriority('?')).toBe('none');
  });

  it('refreshes task lists after an import', () => {
    expect(keysFor({ type: 'project.imported', aggregate_id: 'p1', project_id: 'p1' })).toContainEqual([
      'tasks',
      'p1',
    ]);
  });
});

describe('import page', () => {
  it('maps a Nimble export, checks it, then imports', async () => {
    const posts: Record<string, unknown>[] = [];
    mockApi([
      ...baseRoutes,
      signedIn,
      {
        method: 'POST',
        path: '/api/v1/projects/p1/import',
        handler: async (req) => {
          const body = (await req.json()) as Record<string, unknown>;
          posts.push(body);
          return {
            dry_run: body.dry_run,
            created: 2,
            updated: 0,
            unchanged: 0,
            skipped: 0,
            comments_added: 0,
            problems: [],
            unmatched_people: body.dry_run
              ? [{ value: 'pat@example.com', rows: 1, reason: 'not found in Glasshaus' }]
              : [],
            warnings: [],
          };
        },
      },
    ]);
    renderAt('/projects/WEB/import');
    expect(await screen.findByRole('heading', { name: 'Import tasks', level: 1 })).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText('Exported from'), 'nimble');
    await userEvent.upload(
      screen.getByLabelText('File'),
      new File([CSV], 'export.csv', { type: 'text/csv' }),
    );

    expect(await screen.findByRole('heading', { name: /Columns \(2 rows\)/ })).toBeInTheDocument();
    expect(screen.getByLabelText('Import Lane as')).toHaveValue('status');
    expect(screen.getByLabelText('Dates in this file are written')).toHaveValue('dmy');
    const statusesBox = screen.getByRole('group', { name: 'Statuses' });
    expect(
      within(statusesBox)
        .getAllByRole('combobox')
        .map((s) => (s as HTMLSelectElement).value),
    ).toEqual(['', 's-done']);
    // Moving the title to another column frees the first one.
    await userEvent.selectOptions(screen.getByLabelText('Import Labels as'), 'title');
    expect(screen.getByLabelText('Import Title as')).toHaveValue('');
    await userEvent.selectOptions(screen.getByLabelText('Import Title as'), 'title');
    await userEvent.selectOptions(screen.getByLabelText('Import Labels as'), 'tags');

    await userEvent.click(screen.getByRole('button', { name: 'Check' }));
    expect(await screen.findByText(/pat@example.com: not found in Glasshaus/)).toBeInTheDocument();
    expect(posts[0]).toMatchObject({
      source: 'nimble',
      file_name: 'export.csv',
      date_format: 'dmy',
      dry_run: true,
      status_map: { closed: 's-done' },
      priority_map: { major: 'high', minor: 'low' },
    });
    expect(posts[0]!.fields).toEqual(
      expect.arrayContaining(['external_id', 'title', 'status', 'priority', 'assignee', 'due_date', 'tags']),
    );

    await userEvent.click(screen.getByRole('button', { name: 'Import 2 rows' }));
    await waitFor(() => expect(posts).toHaveLength(2));
    expect(posts[1]).toMatchObject({ dry_run: false });
    expect(await screen.findByRole('link', { name: 'Open Website' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Import 2 rows' })).toBeDisabled();
  });

  it('is linked from the project page for editors', async () => {
    mockApi([
      ...baseRoutes,
      signedIn,
      { method: 'GET', path: '/api/v1/tasks', body: { items: [], next_cursor: null } },
    ]);
    renderAt('/projects/WEB');
    expect(await screen.findByRole('link', { name: 'Import' })).toHaveAttribute(
      'href',
      '/projects/WEB/import',
    );
  });
});
