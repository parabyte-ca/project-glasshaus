import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import App from './App';

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe('App shell', () => {
  it('shows the API version in the footer', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ name: 'Project Glasshaus', version: '9.9.9', build: 'abc' }), {
        status: 200,
      }),
    );
    renderApp();
    expect(await screen.findByTestId('version')).toHaveTextContent('v9.9.9 (abc)');
  });

  it('reports when the API is unavailable', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('', { status: 503 }));
    renderApp();
    expect(await screen.findByRole('alert')).toHaveTextContent('API unavailable');
  });

  it('toggles dark mode', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 503 }));
    renderApp();
    const button = screen.getByRole('button', { name: 'Dark mode' });
    const before = document.documentElement.classList.contains('dark');
    await userEvent.click(button);
    expect(document.documentElement.classList.contains('dark')).toBe(!before);
    expect(button).toHaveAttribute('aria-pressed', String(!before));
  });
});
