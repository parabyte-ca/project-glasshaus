import 'driver.js/dist/driver.css';
import './tour.css';

import { driver, type DriveStep } from 'driver.js';

export type TourOutcome = 'completed' | 'skipped';

/** Elements the tour points at carry data-tour="…" so markup changes don't silently break it. */
export const TOUR_STEPS: DriveStep[] = [
  {
    element: '[data-tour="create-task"]',
    popover: {
      title: 'Create a task',
      description:
        'Type a title and press Enter to add a task to this project. Press C anywhere to jump here.',
      side: 'bottom',
      align: 'start',
    },
  },
  {
    element: '[data-tour="task-view"]',
    popover: {
      title: 'Your tasks',
      description:
        'Tasks show here as a list, a board, a table, a timeline or a calendar. On the board, drag cards between columns to change their status.',
      side: 'top',
      align: 'start',
    },
  },
  {
    element: '[data-tour="timeline-switch"]',
    popover: {
      title: 'Timeline',
      description:
        'Plan dates on a Gantt-style timeline: drag bars, or use the arrow keys, and see the critical path.',
      side: 'bottom',
      align: 'center',
    },
  },
  {
    element: '[data-tour="collaborators"]',
    popover: {
      title: 'People',
      description: 'See who works on this project and add teammates so you can assign them tasks.',
      side: 'bottom',
      align: 'end',
    },
  },
];

/**
 * Spotlight tour of the project page (driver.js). Keyboard: arrow keys move between steps, Escape
 * leaves, Tab stays inside the card. Resolves with how it ended: finished, or skipped/closed early.
 */
export function startTour(onEnd: (outcome: TourOutcome) => void) {
  let outcome: TourOutcome = 'skipped';
  const dark = document.documentElement.classList.contains('dark');
  const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
  const tour = driver({
    steps: TOUR_STEPS.filter((s) => document.querySelector(String(s.element))),
    showProgress: true,
    progressText: 'Step {{current}} of {{total}}',
    nextBtnText: 'Next',
    prevBtnText: 'Back',
    doneBtnText: 'Done',
    allowKeyboardControl: true,
    animate: !reducedMotion,
    smoothScroll: !reducedMotion,
    overlayColor: dark ? '#020617' : '#0f172a',
    overlayOpacity: dark ? 0.7 : 0.5,
    stageRadius: 8,
    stagePadding: 6,
    popoverClass: 'glasshaus-tour',
    onPopoverRender: (popover, { driver: d }) => {
      popover.wrapper.setAttribute('aria-modal', 'true');
      popover.closeButton.setAttribute('aria-label', 'Close tour');
      if (!d.isLastStep()) {
        const skip = document.createElement('button');
        skip.type = 'button';
        skip.className = 'glasshaus-tour-skip';
        skip.textContent = 'Skip tour';
        skip.addEventListener('click', () => d.destroy());
        popover.footer.insertBefore(skip, popover.footer.firstChild);
      }
    },
    // driver.js marks the highlighted element as a popup trigger; that is invalid ARIA on a form or a
    // region (the popover is a labelled dialog already), so take it off again.
    onHighlighted: (element) => {
      for (const attr of ['aria-haspopup', 'aria-expanded', 'aria-controls']) element?.removeAttribute(attr);
    },
    onDoneClick: (_el, _step, { driver: d }) => {
      outcome = 'completed';
      d.destroy();
    },
    onDestroyed: () => onEnd(outcome),
  });
  tour.drive();
  return tour;
}
