import { useEffect, useRef } from 'react';
import { useBlocker } from 'react-router';

import { useConfirm } from './confirm';

/**
 * Ask before leaving a page with unsaved changes: in-app navigation shows a confirm dialog, and
 * closing or reloading the tab gets the browser's own prompt. Call `allowNext()` right before a
 * navigation that follows a save (the "dirty" state hasn't re-rendered yet).
 */
export function useUnsavedGuard(dirty: boolean) {
  const confirm = useConfirm();
  const bypass = useRef(false);
  const blocker = useBlocker(({ currentLocation, nextLocation }) => {
    if (bypass.current) {
      bypass.current = false;
      return false;
    }
    return (
      dirty &&
      (currentLocation.pathname !== nextLocation.pathname || currentLocation.search !== nextLocation.search)
    );
  });
  useEffect(() => {
    if (blocker.state !== 'blocked') return;
    void confirm({
      title: 'Leave without saving?',
      body: "Your changes on this page haven't been saved.",
      confirmLabel: 'Leave without saving',
      danger: true,
    }).then((leave) => (leave ? blocker.proceed() : blocker.reset()));
  }, [blocker, confirm]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = ''; // older browsers need it set to show the prompt
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  return {
    allowNext: () => {
      bypass.current = true;
    },
  };
}
