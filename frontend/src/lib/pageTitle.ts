import { useEffect } from 'react';

export const APP_NAME = 'Glasshaus';

/** Name the browser tab (and the page screen readers announce) after what is on screen. */
export function usePageTitle(title: string | null | undefined) {
  useEffect(() => {
    document.title = title ? `${title} · ${APP_NAME}` : APP_NAME;
  }, [title]);
}
