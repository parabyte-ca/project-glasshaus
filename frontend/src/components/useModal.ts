import { useEffect, useRef, type RefObject } from 'react';

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

// Open layers (modals, popovers, tips), innermost last: Escape and Tab belong to the top one only, so
// one Escape closes one thing (a palette opened over the task drawer closes on its own).
const stack: object[] = [];

/** Register an open layer; Escape calls onEscape only while it is the top layer. */
export function useEscapeLayer(active: boolean, onEscape: () => void, onKey?: (e: KeyboardEvent) => void) {
  const handlers = useRef({ onEscape, onKey });
  useEffect(() => {
    handlers.current = { onEscape, onKey };
  });
  useEffect(() => {
    if (!active) return;
    const token = {};
    stack.push(token);
    const listener = (e: KeyboardEvent) => {
      if (stack[stack.length - 1] !== token || e.defaultPrevented) return;
      if (e.key === 'Escape') {
        e.preventDefault();
        handlers.current.onEscape();
      } else {
        handlers.current.onKey?.(e);
      }
    };
    document.addEventListener('keydown', listener);
    return () => {
      document.removeEventListener('keydown', listener);
      stack.splice(stack.indexOf(token), 1);
    };
  }, [active]);
}

/** Focus trap for a modal: focus moves in, Tab cycles inside, Escape calls onClose, focus returns. */
export function useModal(ref: RefObject<HTMLElement | null>, onClose: () => void) {
  useEscapeLayer(true, onClose, (e) => {
    const node = ref.current;
    if (e.key !== 'Tab' || !node) return;
    const items = [...node.querySelectorAll<HTMLElement>(FOCUSABLE)];
    const first = items[0];
    const last = items[items.length - 1];
    if (!first || !last) return;
    if (!node.contains(document.activeElement)) {
      e.preventDefault();
      first.focus();
    } else if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  });
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const node = ref.current;
    if (node && !node.contains(document.activeElement)) {
      (node.querySelector<HTMLElement>('[autofocus], [data-autofocus]') ?? node).focus();
    }
    return () => previous?.focus?.();
  }, [ref]);
}
