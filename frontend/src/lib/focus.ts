/**
 * Keep keyboard and screen-reader users in place when the control they used goes away (a deleted row's
 * button, an approved suggestion's card). Without this, focus falls to <body> and the next Tab starts
 * again at the top of the page.
 *
 * Call it with the element that has (or will get back) focus. If that element is removed within a few
 * seconds while focus is lost, focus moves to the nearest list item or section still on the page: its
 * first focusable control, else its heading, else the container itself.
 */
const WATCH_MS = 5000;
const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea';

export function rescueFocus(element: Element | null) {
  if (!(element instanceof HTMLElement)) return;
  const ancestors: HTMLElement[] = [];
  for (let node = element.parentElement; node && node !== document.body; node = node.parentElement) {
    ancestors.push(node);
  }
  let done = false;
  const stop = () => {
    done = true;
    observer.disconnect();
    clearTimeout(timer);
  };
  const check = () => {
    if (done || element.isConnected) return;
    stop();
    const lost = !document.activeElement || document.activeElement === document.body;
    if (!lost) return;
    const left = ancestors.filter((a) => a.isConnected);
    if (left.length === 0) return;
    // The nearest container with something to land on (an emptied list falls through to its section).
    const pick = (a: HTMLElement) =>
      a.querySelector<HTMLElement>(`li ${FOCUSABLE}, ${FOCUSABLE}`) ??
      a.querySelector<HTMLElement>('h1, h2, h3, h4');
    const home = left.find((a) => pick(a)) ?? left[0]!;
    const target = pick(home) ?? home;
    if (!target.hasAttribute('tabindex') && !target.matches(FOCUSABLE)) target.tabIndex = -1;
    target.focus();
  };
  const observer = new MutationObserver(check);
  observer.observe(document.body, { childList: true, subtree: true });
  const timer = setTimeout(stop, WATCH_MS);
}
