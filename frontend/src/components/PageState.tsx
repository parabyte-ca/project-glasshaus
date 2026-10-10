import { ApiError } from '../api/client';
import { usePageTitle } from '../lib/pageTitle';
import { GhostButton, TextLink } from './ui';

/** The 404 page: unknown addresses and things that no longer exist (or that you can't see). */
export function NotFound({ what = 'page' }: { what?: string }) {
  usePageTitle('Not found');
  return (
    <div className="flex max-w-xl flex-col gap-3">
      <h1 className="text-2xl font-bold">Not found</h1>
      <p className="text-sm text-slate-700 dark:text-slate-300">
        This {what} doesn't exist, was deleted, or you don't have access to it.
      </p>
      <p>
        <TextLink to="/">Go to the home page</TextLink>
      </p>
    </div>
  );
}

/**
 * What a page shows when its data could not be loaded, instead of "Loading…" forever: "Not found"
 * for a 404 or 403, otherwise the error with a Retry button. `inline` (part of a page or a dialog) never
 * replaces the page with "Not found".
 */
export function LoadError({
  error,
  what,
  onRetry,
  inline = false,
}: {
  error: unknown;
  what?: string;
  onRetry?: () => void;
  inline?: boolean;
}) {
  if (!inline && error instanceof ApiError && (error.status === 404 || error.status === 403)) {
    return <NotFound what={what} />;
  }
  return (
    <div role="alert" className="flex max-w-xl flex-col items-start gap-2">
      <p className="text-sm text-red-700 dark:text-red-400">
        Could not load this {what ?? 'page'}: {error instanceof Error ? error.message : String(error)}
      </p>
      {onRetry && <GhostButton onClick={onRetry}>Try again</GhostButton>}
    </div>
  );
}
