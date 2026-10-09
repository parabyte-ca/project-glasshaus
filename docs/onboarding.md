# First-run onboarding

New people get three kinds of help. All of it is optional, keyboard accessible and remembered on the
person's account (so it follows them across browsers and devices).

## Product tour

A spotlight tour of the project page, built on [driver.js](https://driverjs.com) (MIT, loaded only when
the tour runs):

1. **Create a task**: the new-task box (press **C** anywhere to jump there).
2. **Your tasks**: the task area (list, board, table, timeline or calendar).
3. **Timeline**: the Gantt-style timeline switch.
4. **People**: the project's collaborators panel.

Each card has **Next**, **Back**, **Skip tour** and **Done** (and × to close). **→ / ←** move between
steps, **Escape** leaves, and **Tab** stays inside the card. The tour follows *Reduce motion*.

- It starts by itself the first time a person opens any project.
- Restart it any time: **Product tour** in the footer, **Take the product tour** in the command palette
  (Ctrl K / ⌘ K), or the last checklist item.
- Accounts that existed before 0.10.0 are treated as having skipped it: no automatic tour, but tips
  appear and the tour is one click away.

Steps point at elements marked `data-tour="…"` (`create-task`, `task-view`, `timeline-switch`,
`collaborators`); steps whose element is missing are left out.

## Getting-started checklist

A small panel docked bottom-right on every page:

- Create your first project or task
- Assign a teammate or add a collaborator
- Set a due date on a task
- Take the product tour

Items tick themselves from what the person has actually done (the server checks their tasks and
projects), with a progress bar. **Minimize** shrinks it to a "Getting started · 2/4" button;
**Dismiss** hides it for good. To bring it back, use **Show the getting-started checklist** in the
command palette.

## Feature tips (beacons)

For people who skipped the tour, a pulsing dot appears next to **Timeline** and **Project settings**
(automations). Hover, focus or click it for a short tip; **Got it** hides that tip for good. Pulsing stops
when *Reduce motion* is on.

## API

| Call | Purpose |
| --- | --- |
| `GET /api/v1/users/me/onboarding` | `tour` (`completed`, `skipped` or null), `checklist` (`open`, `minimized`, `dismissed`), `dismissed_tips`, and derived `milestones` |
| `PATCH /api/v1/users/me/onboarding` | `{"tour": "completed"}`, `{"checklist": "minimized"}`, `{"dismiss_tip": "timeline"}`, or `{"reset": true}` to start over |

State is stored in `users.onboarding` (JSON). An administrator can reset someone's onboarding by calling
the PATCH with `reset` as that person, or in SQL: `UPDATE users SET onboarding = '{}' WHERE email = '…'`.

## Testing

- Unit: `frontend/src/onboarding.test.tsx` (checklist progress, minimize and dismiss; automatic tour,
  keyboard steps and skip; restart and finish; tips; people panel).
- Backend: `backend/tests/test_onboarding.py` (state, milestones, validation, per-person isolation).
- End-to-end: `e2e/tests/onboarding.spec.ts` runs the whole flow as a brand-new person, including an
  axe check of the open tour. The shared e2e administrator has onboarding marked done in
  `e2e/global-setup.ts`, so other tests see the plain app.
- By hand: `PATCH /api/v1/users/me/onboarding {"reset": true}`, then open any project.
