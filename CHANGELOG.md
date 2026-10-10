# Changelog

All notable changes to Project Glasshaus are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Pre-1.0 minor versions map to delivery phases.

## [Unreleased]

## [0.24.0] - 2026-10-10

Easier to use: plain error messages, undo, no lost work, consistent names, and better on phones and
with a keyboard or screen reader.

### Added
- **Undo on My tasks.** A ticked task disappears at once, and the "Done" message has an **Undo** button
  for 10 seconds.
- **Unsaved changes are kept.** Leaving the report builder, a project assistant's settings or the
  directory sync form with unsaved changes asks first, and so does closing the tab.
- **Easier to find:**
  - **My team** is on the home page for managers and in the command palette (`g y`);
  - each project's **Project assistant** is in the command palette (type "assistant" or the project's
    name);
  - **About, privacy and source code** is in the command palette.
- Confirmations before removing a dependency, a report alert, report emails or a scheduled channel post.

### Changed
- **Plain error messages.** When the server can't be reached, is updating or is busy, Glasshaus says so
  in words instead of showing a status code or a server message. Messages about your input are
  unchanged.
- **Error messages stay until you close them**; other messages close by themselves.
- **One name for each AI feature:**
  - **AI tools**: the panel on a project (summaries, task drafts, search);
  - **Project assistant**: the digests and suggestions page of a project;
  - **Admin → AI**: the organization's AI settings.
- **Phones:** buttons and menu links are at least 44 px tall on small screens. Wide tables on
  portfolios, automation run history and provisioning tokens scroll sideways instead of overflowing.
- **Keyboard and screen readers:**
  - focus stays nearby when the control you used goes away (for example after approving a
    suggestion or closing a dialog), instead of jumping back to the top of the page;
  - the notifications button says how many are unread;
  - "Write a digest now" says "Writing…" while it works;
  - the command palette says when it is still searching tasks;
  - saving AI settings or changing what managers see confirms it with a message;
  - the meeting-notes box explains its task markers as help text, not only as a placeholder.
- **Clearer labels:**
  - priorities read "Urgent" and "High" instead of `urgent` and `high`;
  - on My team, a project with no health set says "Health not set" instead of "On track";
  - the "At risk" icon is dark on amber, so it is readable.
- Goals, Workload and Time show a **Try again** button when they can't load. The task list on My team
  shows its error inside the dialog.
- The footer says "Glasshaus is unavailable right now" instead of "API unavailable".

## [0.23.0] - 2026-10-10

Faster with large organizations: fewer database round-trips, lighter live updates and indexed search.

### Changed
- **Project list:** the sidebar, command palette and admin pages load your projects with the same few
  queries whether you see 3 projects or 300. Before, each project cost its own permission lookups.
- **Portfolios and OKRs:**
  - portfolio health now comes from a few totals across all its projects, instead of loading every
    task and baseline of each project;
  - OKR progress from linked projects takes one query instead of several per key result.

  The project status summary and the assistant's briefs use the same faster health check.
- **Workload:**
  - reads only the fields it needs, with logged time in the same query;
  - no longer fails when an organization has more than about 32,000 open assigned tasks.
- **Bulk edits:** shifting dates on many tasks in an auto-scheduled project reschedules the project once,
  not once per task.
- **Live updates:**
  - when someone edits a task, open lists fetch just that task and swap it in, instead of reloading
    up to 500 tasks;
  - lists that are filtered, and lists a task may have joined or left, still reload;
  - comments no longer reload task lists;
  - each open tab receives only identifiers over the live connection, not the whole task.
- **Search:** task title search (command palette, `search_tasks`) uses a trigram index instead of
  scanning every task. The upgrade enables PostgreSQL's built-in `pg_trgm` extension.
- **Activity feed:**
  - has an index;
  - pages with a position cursor, so later pages are as fast as the first. Older page cursors still
    work.
- **Smaller fixes:**
  - push-notification bookkeeping no longer grows with every notification;
  - dragging a timeline bar redraws only when it crosses a day;
  - each release now replaces the previous one's offline cache;
  - the web image no longer ships public source maps;
  - a new index on task reporters speeds up erasing or removing a person.
- Tests now count database queries on list pages, so these slowdowns can't quietly come back.

## [0.22.0] - 2026-10-10

Privacy and compliance: people can get their data, admins can erase a person, the audit log is sealed,
backups are encrypted, and less personal data is kept.

### Added
- **Download my data.** Everyone can download everything Glasshaus holds about them from **Account**:
  their profile, work assigned to or created by them, comments, time, sign-ins, notifications, and the
  activity and audit entries they caused. Admins can do the same for anyone in **Admin → People**
  (a subject access request).
- **Erase a person.** **Admin → People → Erase…** keeps their tasks, time and history but removes who
  they were. Their name and email become "Former user". Their sign-ins, tokens, devices and
  notifications are deleted, and so is the text of their comments. You type their email to confirm.
  Erased people can't sign in or be brought back by SCIM.
- **Sealed audit log.** Each organization's audit entries are numbered and chained by hash in the
  database. **Admin → Audit log → Check integrity** shows any entry that was changed, removed or
  inserted, even by someone with database access. Keep the "latest seal" it shows to prove that later.
- **Encrypted backups.** Backups are encrypted with age and checksummed. Restores and the restore
  drill check the checksum and decrypt automatically. The key is generated into `.env`
  (`GLASSHAUS_BACKUP_KEY`); keep a copy off the server.
- **About, privacy and source code** (footer on every page):
  - the version and the AGPL licence;
  - a link to this server's source code (`GLASSHAUS_SOURCE_URL`);
  - what personal data is kept;
  - the third-party packages and their licences.
- `docs/privacy.md`: what is stored and for how long, where data can go (subprocessors), people's
  rights, and audit and backup integrity.

### Changed
- **Activity history is kept 2 years by default** (it was forever). Organizations still on "forever"
  move to 2 years; admins can change it in **Data & retention**.
- **Audit entries are kept at least 30 days.** Changing a retention setting is audited with the old and
  new values. The database refuses changes to audit entries from the application.
- **Comment text is no longer copied into the activity history, the audit log or webhooks.** The
  0.22 upgrade also removes it from past entries. Deleting a comment now removes its text everywhere.
  Slack and Teams posts still quote new comments.
- Ended sign-in sessions, with their IP address and browser, are deleted after 90 days.
- Only admins see when someone last signed in.
- Signing out and approving or denying an app's access (OAuth) are now audited.
- The backup service has its own small image, `glasshaus-backup`: PostgreSQL tools plus `age` (a
  pinned release, built with the current Go so it carries Go's security fixes).

## [0.21.1] - 2026-10-10

Security fixes from a full review, and a more private default for My team.

### Security
- **Sign-in lockout can no longer be used against you.** Wrong passwords from many addresses still
  lock an account for 15 minutes, but the person can still sign in with the right password from an
  address they've used before.
- **Copied sign-ins end.** Reusing an old refresh token (a stolen cookie) signs out every session from
  that sign-in. An OAuth code used twice also cancels the tokens issued from it.
- **Single sign-on is tied to the browser that started it.** This stops someone signing you in to
  their own account with a link. Linking a provider from Account now needs the page's CSRF token.
- **Read-only API tokens change nothing.** Before, they could edit or delete time entries and saved
  views.
- **OAuth apps (MCP) can only register safe return addresses:**
  - https;
  - http on this computer;
  - an app's own scheme.

  `javascript:` and `data:` addresses are refused, and the consent page checks too.
- **Making someone an admin or owner** needs a signed-in person in Admin. API tokens and AI agents
  can't do it.
- **A Slack command must have its signing secret.** An empty one is refused.
- **Spreadsheet exports neutralise formulas in every cell and heading.** This covers tags, statuses,
  names and report labels.
- **Backups are readable only by the backup service** (mode 600).

### Changed
- **My team is private by default.** Managers see their reports' work only in projects they can open
  (counts elsewhere); an admin can widen it, with a confirmation. Guests who manage someone always get
  the private view. **Existing organizations move to the private setting**: re-choose "every project"
  in Admin → Provisioning if you want it.

### Fixed
- Saving **Admin → AI assistant** when no AI provider is set up no longer clears the organization's
  AI switch and features.

## [0.21.0] - 2026-10-10

Reporting lines from your identity provider, and **My team** for managers.

### Added
- **My team** (`/team`, in the menu for anyone with direct reports). For each person who reports to you:
  - open, overdue, due this week and in-progress work;
  - hours logged this week (against their weekly capacity) and last week;
  - their projects, with each project's health;
  - what they finished in the last 7 days, and stale in-progress work.

  **See tasks** opens a person's open or recently finished work. **Include everyone below me** adds
  their reports' reports.
- **What managers see** (Admin → Provisioning). Choose between:
  - their reports' work in every project (the default);
  - only work in projects the manager can open, with counts elsewhere.

  Opening someone's task list is always audited (`team.tasks_viewed`).
- **Managers from SCIM.** Entra ID's default mapping (the SCIM enterprise extension's `manager` and
  `department`, and `title`) is stored. Loops are refused.
- **Managers from Microsoft Graph.** A nightly sync (or **Sync now**) for people SCIM doesn't cover.
  - Register an app with `User.Read.All`, then enter its details in Admin → Provisioning.
  - People are matched by email, and SCIM wins where it sends a manager.
  - The secret is encrypted at rest.
- **API:**
  - `GET /api/v1/team`, `GET /api/v1/team/{id}/tasks`;
  - `GET/PUT /api/v1/admin/directory-sync`, `POST /api/v1/admin/directory-sync/run`;
  - `manager_visibility` in org settings;
  - `manager_id`, `job_title`, `department` on users, and `direct_reports` on `/users/me`.
- **MCP:** `my_team`.

### Fixed
- Signing in now loads your full profile, so menu items that depend on it (such as **My team**) show
  straight away instead of after a reload.

## [0.20.1] - 2026-10-09

A review and hardening pass over 0.17–0.20 (phone notifications, My tasks and the project assistant).

### Security
- **Phone notifications:**
  - device keys and push addresses are checked more strictly, so one broken device cannot stop
    everyone else's notifications;
  - a device can only move to another account with its own keys, not just its address;
  - at most 10 devices per person (the oldest go), and **Send a test** is limited to 3 a minute;
  - deactivating someone, resetting their password or signing them out everywhere also turns off
    their devices, and inactive people get no pushes;
  - the service worker only opens pages of this site from a notification.
- **Project assistant:**
  - text the AI writes (follow-ups, digests, weekly drafts) is plain: links and images are removed,
    so text slipped into a task title cannot make the assistant post a link;
  - its email address is reserved, and its account is refused by every kind of sign-in token;
  - at most 50 tasks from notes wait for approval at once.
- **Signing out:** the offline copy of My tasks is removed even when you sign out offline or your
  session has expired.

### Fixed
- **Project assistant:**
  - digests are written a few at a time in small batches, so a busy morning no longer cuts some
    projects' digests;
  - unexpected errors now show on the Digests page instead of the last success;
  - two runs at once (scheduled and **Write a digest now**) no longer exceed the daily limit or fail
    on a duplicate suggestion;
  - only today's follow-ups post on their own; older ones wait for a person;
  - an expired suggestion is not proposed again straight away;
  - a digest no longer loads every finished task in the project.
- **Phone notifications:** sent in parallel, and results are kept even when a run is cut short, so
  dead devices are still removed.
- **My tasks:**
  - updates live when tasks change elsewhere;
  - a task ticked while earlier ticks are being sent is no longer lost;
  - shows "as of" whenever it is showing the saved copy;
  - keeps keyboard focus in the list after ticking a task.
- **Digests page:**
  - clearing a time no longer saves midnight;
  - the **New owner** list shows the suggested person instead of the first name in the list;
  - approving or undoing refreshes the task and its comments.

## [0.20.0] - 2026-10-09

The project assistant, phase 3: trusted follow-ups.

### Added
- **Follow-ups without approval, if you choose.** The assistant can post its follow-up comments on its
  own, but only when both of these are on:
  - the organization allows it (**Admin → AI assistant → What the project assistant may do without
    approval**);
  - the project turns it on (**Post follow-up comments without approval**).
- **Safeguards:**
  - a daily limit per project (**At most per day**, default 10), counted in the project's time zone;
  - the task's owner is mentioned, so they're notified, and the comment says it was automatic and how to
    undo it;
  - each automatic action is audited (`assistant.action_automatic`).
- **Undo for 7 days.** **Done on its own** on the Digests page lists automatic follow-ups. Project editors
  and admins can undo them, and approved follow-ups too; undoing deletes the comment and is audited.
- Due dates, owners and tasks from notes always wait for approval.
- API:
  - `POST …/assistant/suggestions/{sid}/undo`;
  - `assistant_trusted` in org settings;
  - `trusted` and `auto_daily_cap` in project assistant settings;
  - suggestions show `automatic` and `can_undo`.

### Changed
- An undone suggestion counts as a decision: the same follow-up isn't suggested again for 7 days.
- AI settings can be saved without an AI provider configured, so admins can set the assistant's limits
  either way. The digest rules work without AI.

## [0.19.0] - 2026-10-09

The project assistant, phase 2: an approval queue.

### Added
- **Suggestions** on the project's Digests page, refreshed with each digest:
  - follow-up comments on overdue work and on in-progress work with no recent update;
  - new due dates for long-overdue work that hasn't started;
  - owners for unassigned work due soon, preferring the editor with the fewest open tasks.

  Simple rules make them without AI. With the **Project assistant** AI feature on, the model proposes
  better ones, checked against the project's tasks and people. The model can't mention anyone itself.
- **Turn meeting notes or an email into tasks.** With AI, it finds the action items. Without AI, it
  takes lines starting with `- [ ]`, `TODO:`, `Action:` or `AI:`.
- **Approve, edit or dismiss.** Project editors and admins decide; viewers can see the queue.
  - Approved changes are made by the *Project assistant (AI)* account and signed "approved by <name>".
  - Each approval is audited under the approver's name.
  - A suggestion whose task has changed since it was made is set aside, not applied.
  - The same suggestion isn't repeated while one is waiting or within 7 days of a decision.
  - Unapproved suggestions expire after 7 days.
- The digest (in the app, email and Slack/Teams) says how many suggestions are waiting.
- New project setting: **Suggest follow-ups, new dates and owners** (on by default).
- API:
  - `GET /api/v1/projects/{id}/assistant/suggestions`
  - `POST …/suggestions/{sid}/approve` and `…/dismiss`
  - `POST /api/v1/projects/{id}/assistant/notes`

## [0.18.0] - 2026-10-09

The project assistant, phase 1.

### Added
- **Project assistant** (project → **Digests**). Project admins turn it on per project. It writes a
  **daily stand-up digest** for everyone on the project (overdue with days late, due today and soon,
  in-progress work with no update for a set number of days, unassigned work due soon, what was done,
  schedule warnings) and a **weekly status draft** for project admins, delivered by notification (and
  phone push), email and, for the digest, a Slack or Teams channel. **Write a digest now** and **Write a
  weekly draft now** store one on the page without notifying anyone. Details in
  [docs/assistant.md](docs/assistant.md).
- **AI write-ups** for the assistant (new AI feature **Project assistant**, off until an organization
  admin ticks it): a short summary and focus list for the digest, and a headline, write-up, highlights
  and concerns for the weekly draft. Without it, or if the model fails, briefs still go out with the
  facts.
- **The assistant's account:** one *Project assistant (AI)* account per organization, added to a project
  as a Viewer while the assistant is on. It cannot sign in, is not listed or provisioned as a person,
  cannot be promoted or assigned tasks, and its AI requests are audited under its name.
- API: `GET/PUT/DELETE /api/v1/projects/{id}/assistant`, `POST /api/v1/projects/{id}/assistant/run`,
  `GET /api/v1/projects/{id}/assistant/briefs`, `GET /api/v1/assistant/briefs/{id}`; project members
  now say which one is the assistant (`assistant`).

### Changed
- The project's **Assistant** button only appears for the features it holds (status updates, drafting,
  risks).

## [0.17.0] - 2026-10-09

Glasshaus on your phone.

### Added
- **My tasks** (`/my`, shortcut **G** then **M**): your open tasks in every project, grouped Overdue, Today,
  Next 7 days, Later and No due date, with a tick box to mark each done.
- **Works offline.** My tasks keeps a copy on the device and opens without a connection; tasks ticked
  offline are marked done when the app can reach the server again. The rest of the app opens with
  your last-known profile and points you to My tasks while offline. Signing out removes the copy.
- **Notifications on this device** (Account): Web Push to phones and desktops for your notifications,
  with a test button; tapping one opens the right page. Needs HTTPS; on iPhone and iPad, add the app
  to the Home Screen first. Details in [docs/mobile.md](docs/mobile.md).
- API: `POST /api/v1/tasks/{ref}/complete` and `/reopen` (safe to repeat); `GET /api/v1/push`,
  `POST /api/v1/push/subscriptions`, `POST /api/v1/push/subscriptions/remove`, `POST /api/v1/push/test`.

### Changed
- ESLint 10 for the frontend.
- Signing out also turns off notifications on that device.

## [0.16.0] - 2026-10-09

Slack and Microsoft Teams.

### Added
- **Scheduled channel posts.** On a Slack or Teams integration, **Scheduled posts** sends a saved
  report (its table with totals) or a project's status (health, numbers, overdue, due-soon and
  recently completed tasks) daily, weekly or monthly; **Post now** sends one straight away. Posts run
  with the access of the person who set them up, a project's channel only gets that project, and
  they go through the usual delivery log and retries.
- **`/glasshaus` in Slack.** Your open tasks (`my`), a task (`WEB-12`), a saved report
  (`report <name>`), or a question answered by the AI assistant when it is on. Answers are private
  to the person asking and use their access (read-only); people are matched by their Slack email.
  Requests are checked against the Slack app's signing secret. Set-up in
  [docs/connectors.md](docs/connectors.md#slack-command-glasshaus).
- API: `/api/v1/integrations/{id}/posts` (list, create, delete, send now) and
  `POST /api/v1/integrations/{id}/slack`; new integration kind `slack_command`.

## [0.15.0] - 2026-10-09

Report alerts, backup health and safer upgrades.

### Added
- **Report alerts.** **Alert me** on a saved report: "tell me when Overdue goes above 5", checked
  daily, weekly or monthly with your access. You get a notification (and optionally an email) when
  it goes off and when it is back, never on every check. **Check now** checks straight away.
- **Restore drill.** Every 7 days (`GLASSHAUS_BACKUP_DRILL_DAYS`) the backup service restores the
  newest backup into a scratch database, checks it and drops it, so you know your backups work.
- **Admin → Backups**: newest backups, sizes and the last restore drill. Owners and admins get a
  notification (and an email, if set up) once a day while backups are late or a drill failed.
- **Upgrade pre-flight check.** `update.sh` now tries the new release on a copy of your database
  (migrations, then the new API must become ready) before touching the running stack. If it fails,
  nothing changes. `--skip-preflight` skips it.
- Notifications can open a page (report alerts open the report; backup notices open Admin → Backups).
- API: `GET/PUT/DELETE /api/v1/reports/{id}/alert`, `POST /api/v1/reports/{id}/alert/check`,
  `GET /api/v1/reports/alerts`, `GET /api/v1/admin/backups`.

### Changed
- The API and worker containers mount the backup folder read-only.
- CI's stack smoke test runs a restore drill and an upgrade with the pre-flight check.

## [0.14.0] - 2026-10-09

Report emails and release housekeeping.

### Added
- **Report emails.** On a saved report, **Email me this report** sends it daily, weekly or monthly
  at your chosen time and time zone, with the table in the email and an optional CSV of the full
  report. **Email me now** sends one straight away. Each email is run with your access at the time
  it is sent; emails stop on their own if you are deactivated or lose access to the report, and a
  failed send shows its reason on the report.
- **Outgoing email** settings (`GLASSHAUS_SMTP_HOST`, `_PORT`, `_SECURITY`, `_USERNAME`,
  `_PASSWORD`, `_FROM`). Email stays off until a host is set. See [docs/reports.md](docs/reports.md).
- API: `GET/PUT/DELETE /api/v1/reports/{id}/email`, `POST /api/v1/reports/{id}/email/send`,
  `GET /api/v1/reports/subscriptions`.

### Changed
- `scripts/bump-version.sh` now updates the README status line, and `scripts/release_docs.py`
  rebuilds the changelog's compare links; `scripts/check-version.sh` fails when either is stale.
- README roadmap brought up to date, with the planned phases.
- A `release` skill (`.claude/skills/release`) records the release steps for AI assistants.

## [0.13.0] - 2026-10-09

The AI assistant can answer questions from reports.

### Added
- **Questions about reports** (a new AI feature, off until an admin ticks it in **Admin → AI
  assistant**). Ask on the Reports page, on a saved report (**Ask about this report**) or from
  **Ctrl K** (*Ask reports: …*). The assistant picks a saved report or fills in a report definition,
  Glasshaus runs it with your access, and the answer is written from that table and shown beside it.
  **Open in the report builder** takes the definition to the builder to adjust or save. Only the
  question, project keys and names, people's names, saved report names and the report table are sent;
  never task titles or descriptions. Audited as `ai.reports`. `POST /api/v1/ai/reports`.
- MCP tools for reports: `list_reports`, `run_report` (a saved report with date and project filters,
  or a definition), `manage_reports` (create, update, delete with a preview) and `ai_ask_reports`.

## [0.12.0] - 2026-10-09

Custom reports and dashboards.

### Added
- **Report builder** (Reports in the navigation, `g` then `r`): build reports from tasks or logged
  time. Group by up to two fields (project, status, priority, people, tags, weeks or months, and a
  project's single-select custom fields), pick up to six measures (counts, overdue, estimate, average
  age, average time to complete, % on time, hours, billable hours, people), filter by project,
  people, dates, status, priority, tags or billable, and show it as a table, bar chart, line chart
  or a single number. Live preview, CSV download, four templates.
- **Saved and shared reports.** Each run uses the viewer's own access, so a shared report shows
  everyone only the projects they can see. Guests can keep private reports.
- **Report tiles on dashboards**, including single numbers with a target ("On target" / "Off
  target", shown with an icon and words). **Dashboard filters** (date range, project) apply to all
  report tiles at once and stay in the address.
- Dashboard editing: drag tiles to reorder, set each tile's width, and give tiles their own titles.
- API: `POST /api/v1/reports/run`, `/api/v1/reports` (CRUD), `POST /api/v1/reports/{id}/run` (with
  dashboard filters), `GET /api/v1/reports/{id}/export` (CSV). See [docs/reports.md](docs/reports.md).


## [0.11.1] - 2026-10-09

### Fixed
- **Upgrades could roll back on some hosts** with "container glasshaus-api-1 is unhealthy". Since
  0.9.2 the API looked up the `web` container's name inside every request, blocking it; during an
  upgrade `web` is not running yet, and where DNS is slow to answer (seen on TrueNAS) each health
  check stalled past its timeout. The lookup now runs in the background and never delays a request.
- Command palette: the hint text on the highlighted item has enough contrast.

### Changed
- Colours now match ghsystems.com exactly: `#1c75bc` buttons and links, `#00aeef` bright blue in dark
  mode, `#ff8900` orange, `#121212` / `#212121` / `#303030` panels; buttons and fields have 8 px
  corners.


## [0.11.0] - 2026-10-09

New look, and the remaining usability and accessibility fixes from the code review (U8–U25).

### Changed
- **New visual style**: black surfaces in dark mode with a faint warm glow, a clearer blue for actions
  and links, orange for section labels and the current page, and the Inter typeface (served by
  Glasshaus itself, no outside requests) with heavy headings. New app icon and browser theme colour.
- Confirmations are an in-app dialog instead of the browser's prompt, and now also guard revoking API
  and SCIM tokens, disconnecting apps, changing or turning off the calendar link, changing someone's
  role, removing someone from a project and deleting logged time.
- Search, priority, grouping, sort and *Show completed* are kept in the address, so links, reloads and
  Back keep them.
- Board cards have a **Move** menu, and move with Alt+arrow keys.
- On phones the calendar is an agenda list, the timeline's label column is narrower, and the dark mode
  switch is a symbol.

### Fixed
- Pages name the browser tab, and navigating moves focus to the new page's heading.
- Unknown addresses show **Not found**; a project, dashboard, portfolio or report that can't be loaded
  says so (with **Try again**) instead of showing "Loading…" forever.
- The task list says "Loading tasks…" instead of briefly showing "No tasks match".
- One Escape closes one thing: popovers and tips no longer close together with the dialog below them.
- Closing a task goes back in history, so Back no longer reopens it.
- Timeline bars can be dragged on touch screens; moves of bars and cards are announced to screen
  readers.
- Notifications: focus moves into the list, Up/Down move between items, Escape returns focus to the
  button; links are readable in dark mode (also in comments and descriptions).
- Tabs (administration, project settings, time, assistant) work with arrow keys.
- Validation errors name the field, and forms mark the field the server rejected.
- Copy buttons on shown-once secrets (API, SCIM and webhook secrets, calendar link) and setup URLs.
- Small controls are at least 24 px; *Reduce motion* is respected everywhere; no 9 px text.


## [0.10.0] - 2026-10-09

First-run onboarding.

### Added
- **Product tour** of the project page (driver.js, MIT, loaded on demand). It covers creating a task, the
  task views, the timeline switch, and the new People panel. It starts by itself the first time someone
  opens a project. It has Next, Back, Skip tour and Done; arrow keys move between steps, Escape leaves,
  focus stays in the card, and it follows *Reduce motion*. Restart it from **Product tour** in the
  footer or the command palette.
- **Getting-started checklist** docked bottom-right: create a project or task, assign a teammate or add
  a collaborator, set a due date, take the tour. Items tick from real work; there is a progress bar; it
  can be minimized or dismissed (restore it from the command palette).
- **Feature tips**: pulsing dots next to Timeline and Project settings for people who skipped the tour;
  each can be hidden for good.
- **People panel** on every project: see members and their roles; project admins add or remove people.
- `GET/PATCH /api/v1/users/me/onboarding`: tour, checklist and tip state stored on the account, with
  derived milestones. See [docs/onboarding.md](docs/onboarding.md).

### Changed
- Accounts that existed before this release are treated as having skipped the tour (no automatic tour;
  tips and the checklist appear).

## [0.9.3] - 2026-10-09

Patch release: editing fixes from the code review (UX batch).

### Fixed
- **Switching projects** starts with a clean page: search, filters and a half-typed task no longer
  carry over, so Enter can't create a task in the wrong project.
- **Edits show at once** (board drops, status and priority selects, timeline moves) and are put back if
  the server refuses them. Quick successive edits to one task are sent in order with the latest
  version, so they no longer fail with "the task changed".
- **Date fields** save when you leave them or press Enter, not on every keystroke (typing a year used to
  save 0002, 0020, 0202…). Years outside 1900–2200 are refused and the saved date comes back.
- **Task drawer:** Escape, Close or a click outside save the field being edited instead of discarding
  it, and ask before dropping an unsent comment. Enter in the title saves it. Focus stays inside the
  drawer, and Escape in a palette or menu opened over it closes only that.
- **Comments** stay in the box until the server has saved them; a failed send keeps the text.
- **Automation editor:** removing a condition or action no longer shows the removed row's values in
  the next one (what you see is what is saved).
- **Phones:** the navigation is a **Menu** button instead of a list above every page, and the header
  fits at 375 px (Account and Sign out move into the menu).

## [0.9.2] - 2026-10-09

Patch release: performance fixes from the code review.

### Changed
- **Compression:** the web container serves gzip. Scripts, styles and the page are compressed when the
  image is built (`gzip_static`); API responses are compressed on the fly. The main script drops from
  about 310 KB to about 95 KB on the wire.
- **Live updates** are batched: a burst of events (bulk edits, imports, another person's busy session)
  refreshes each affected list once per 400 ms instead of once per event, refetches already in flight
  are not restarted, and only the open task's activity is refreshed.
- **AI assistant** requests no longer hold a database connection while the model works. The facts are
  read in a short transaction, the provider is called with no connection open, then the call is audited.
  A slow model can no longer exhaust the connection pool.
- **Slack, Teams and webhook deliveries** are committed before they are sent and are sent with no
  transaction or row lock open, up to 10 at a time. Retries claim their rows with a five-minute lease,
  so a crash mid-send is retried and two workers never send the same delivery.
- **Event processing** in the worker runs events for different tasks and projects in parallel (up to 8
  at a time); events for the same task still run in order.

## [0.9.1] - 2026-10-08

Patch release: security fixes from a code review, Azure OpenAI for the AI assistant, and a proxy fix for
restarted API containers.

### Security
- **Single sign-on account linking:** a first sign-in links to an existing account only when the IdP marks
  the standard `email` claim verified (members, guests, admins) or, for members and guests, when the
  provider is set to **Link existing accounts by email** (needs allowed domains). Owners never auto-link.
  Anyone can link a provider from **Account → Single sign-on**. Before, any matching email was linked,
  which allowed account takeover through an IdP that does not verify addresses.
- **SCIM** can no longer change owner or admin accounts (email, active, externalId), change the email of
  accounts it did not provision, or reactivate accounts an admin deactivated. Email changes end sessions.
- **Client addresses** are taken only from the web container (`GLASSHAUS_TRUSTED_PROXIES`); spoofed
  `X-Forwarded-For` headers no longer affect login throttling, rate limits or the audit log. Rate limits
  also count per client address.
- **Request size:** the 10 MB cap now applies to chunked uploads too.
- **Email-to-task** connects only to addresses that pass the webhook checks (no loopback, link-local or
  metadata; private ranges with `GLASSHAUS_WEBHOOK_ALLOW_PRIVATE`), reports errors generically, and is
  limited to organization admins.
- **Secrets:** the api, worker and mcp containers no longer receive the database owner, Redis or first-owner
  passwords.

### Changed
- The direct API port (8471) now listens on `127.0.0.1` by default (`GLASSHAUS_API_BIND_ADDRESS`). Use the
  web port (`http://host:8470/api`) for API clients, or set `GLASSHAUS_API_BIND_ADDRESS=0.0.0.0`.
- Behind another reverse proxy, set `GLASSHAUS_UPSTREAM_PROXY` to its address or CIDR.

### Added
- **Azure OpenAI** for the AI assistant through the `openai` provider: `GLASSHAUS_AI_AUTH_HEADER=api-key`,
  optional `GLASSHAUS_AI_API_VERSION` for classic deployment URLs, and an automatic retry with
  `max_completion_tokens` for models that refuse `max_tokens`. See `docs/ai.md`.

### Fixed
- The web container now re-resolves the API's address, so `/api` keeps working when the `api` container
  is recreated on its own (for example `docker compose up -d` after an `.env` change). Before, `/api`
  requests failed until `web` was restarted too.
- End-to-end shortcut test waits for the task drawer to close (raced on slower CI runners).

## [0.9.0] - 2026-10-08

Phase 8 — optional in-app AI, polish, accessibility and end-to-end tests.

### Added
- **AI assistant (optional, off by default):** written status updates, task drafting (proposals you add
  one by one), risk flags with evidence, and plain-language task search. Provider-agnostic: Claude via the
  Anthropic SDK (`claude-opus-5-5` by default, structured outputs, server-side refusal fallbacks), any
  OpenAI-compatible server such as Ollama or LM Studio, or a fake provider for demos and tests. Needs a
  server provider and an admin switch with per-feature settings; rate limited per person and audited
  without content. REST `/api/v1/ai/*`, MCP tools `ai_status`, `ai_status_report`, `ai_draft_tasks`,
  `ai_flag_risks`, `ai_search_tasks`. See `docs/ai.md`.
- **Command palette** (Ctrl K / ⌘ K): pages, projects, task search by key or title, and *Ask* with the
  assistant.
- **Keyboard shortcuts** (`?` for help, `/`, `c`, `g` sequences) and an accessible dialog component.
- **Installable app:** service worker with an offline app shell (static files only) and a richer
  manifest.
- **End-to-end tests** with Playwright (`e2e/`, `make test-e2e`, CI job): project and task flows, all
  layouts, the palette, the assistant, PWA, and axe WCAG 2.1 AA scans of every screen in light and dark
  themes and on a phone viewport. `docs/accessibility.md` covers the manual checks.

### Fixed
- Dark-mode contrast of secondary text, out-of-month calendar days, the page background under wide
  content, sideways scrolling on narrow screens, and keyboard access to scrolling regions (board, table,
  timeline, wide tables).

## [0.8.0] - 2026-10-08

Phase 7 — governance, single sign-on, provisioning, integrations, hardening and performance.

### Added
- **Admin console** for owners and admins: people (add, role, deactivate/reactivate, password reset,
  sign out everywhere), single sign-on, provisioning, integrations, audit log, data & retention.
- **Single sign-on** with OpenID Connect (PKCE, nonce, signed ID tokens) and SAML 2.0 (signed responses or
  assertions, replay protection), just-in-time accounts, allowed domains and optional SSO enforcement
  (owners keep password sign-in). Sign-in page shows the organization's providers.
- **SCIM 2.0** provisioning at `/scim/v2` (Users, Groups as workspaces, filtering, PATCH) with revocable
  tokens.
- **Integrations:** Slack, Microsoft Teams and HMAC-signed webhooks with event selection, project scope,
  retries with backoff and a delivery log; GitHub and GitLab linking (`fixes KEY-12` completes on merge);
  email-to-task over IMAP; personal iCalendar feeds for Google, Outlook/Microsoft 365 and Apple calendars.
- **Full audit log** of every domain change, sign-in (success and failure), SSO, provisioning, export and
  MCP call, with filters and paging; **retention** settings with a nightly purge; **organization export**
  (zip of JSON Lines, secrets excluded).
- MCP tools `manage_users`, `get_org_settings`, `update_org_settings` and `manage_integrations`
  (destructive actions preview first).
- `scripts/bench.py` latency benchmark; docs for SSO/SCIM, integrations and the ASVS L2 baseline.

### Changed
- Third-party secrets are encrypted at rest with a key derived from `GLASSHAUS_SECRET_KEY`.
- The event consumer handles new events before retrying failed ones, so a retry backlog never delays
  live work.

### Security
- Security headers (`nosniff`, `DENY`, strict API CSP, `no-store`, HSTS on HTTPS), a 10 MB request cap and
  a per-principal REST/SCIM rate limit (`GLASSHAUS_API_RATE_LIMIT_PER_MINUTE`).
- Login throttling per account regardless of client address; common, repetitive and name-based passwords
  are refused.
- Deactivating a person ends their sessions immediately.

## [0.7.0] - 2026-10-08

Phase 6 — MCP server, OAuth 2.1 and AI assistant integrations.

### Added
- MCP server with 53 tools covering projects, tasks, bulk changes, statuses, custom fields, comments,
  views, dependencies and schedules, baselines, automations (including run-now and retries), recurring
  tasks, templates, time and timers, timesheets, workload, reports, status-summary data, dashboards,
  portfolios, OKRs and the audit log. Destructive tools return a dry-run preview unless `confirm=true`.
- MCP resources for projects, project reports and status, tasks, saved views and dashboards, and prompt
  templates for a weekly status, risk review, sprint planning and a stand-up digest.
- OAuth 2.1 for MCP clients: dynamic client registration, PKCE, RFC 8414/9728 discovery, a consent page
  in the web app, rotating refresh tokens with reuse detection, revocation, and **Account → Connected
  apps**. Personal API tokens also work, and can now be created under **Account → API tokens**.
- Per-tool scope checks mirroring RBAC, a per-user rate limit and an audit log of every MCP call
  (`GET /api/v1/audit-log`).
- `GET /api/v1/projects/{id}/status-summary` and `POST /api/v1/automation-rules/{id}/run`.
- Tested configuration examples for GitHub Copilot (VS Code), Copilot Studio, Microsoft 365 Copilot
  (declarative agent with MCP plugin, plus an OpenAPI 3.0 API plugin fallback), Claude Desktop, Claude
  Code and generic clients; an MCP conformance suite; and `examples/agent.py`.

### Fixed
- Read-only API tokens could create or change portfolios, objectives, key results, check-ins and
  dashboards; those writes now require the matching token scope.

## [0.6.0] - 2026-10-08

Phase 5 — time tracking, workload, reporting, dashboards, portfolios and OKRs.

### Added
- Time tracking: log time on tasks (billable flag, notes), a one-click timer shown in the header,
  per-person weekly timesheets (admins can view anyone's), a person × project time report and CSV
  export.
- Capacity per person (hours per working day, working weekdays) and a workload view comparing planned
  remaining work (estimate − logged, spread over task dates) with capacity per week or day,
  highlighting overload, undated, overdue and unestimated work.
- Project reports: burn-up, weekly throughput, status mix, lead time (median and 85th percentile),
  estimate vs actual, open work by assignee, health rating, and CSV export of tasks.
- Dashboards with widgets (my tasks, my time, team time by project, workload, project status, burn-up,
  throughput, portfolio, objective); private or shared.
- Portfolios rolling up project progress, overdue work, baseline slip and health.
- OKRs: objectives per period with weighted key results measured by a number or by task completion in a
  project (optionally one tag), check-ins with confidence, and alignment to parent objectives.
- Charts are accessible (keyboard readout, data tables, colour-blind-safe palette in light and dark).
- Demo data includes logged time, a portfolio, an objective and a shared dashboard.

## [0.5.0] - 2026-10-08

Phase 4 — automation engine and templates.

### Added
- Automation rules per project: trigger (task created/updated, status changed, comment added, due soon,
  daily/weekly/monthly schedule in any time zone) → conditions (priority, status, assignee, tags, title, days
  until due, subtask, custom fields) → actions (set status/priority/due date/custom field, assign/unassign,
  add/remove tags, create subtask, post comment, notify people, call a webhook). Text supports placeholders
  such as `{{task.key}}`.
- Exactly-once runs per event or occurrence, atomic actions, a run log with errors and one-click retry (only
  failed webhooks are resent when the actions succeeded), dry run against any task, and loop prevention.
- Signed outbound webhooks (`X-Glasshaus-Signature`, HMAC-SHA256) with SSRF protection; private networks are
  opt-in via `GLASSHAUS_WEBHOOK_ALLOW_PRIVATE` for homelab targets.
- Recurring tasks on daily, weekly or monthly schedules.
- Project templates: save a project's statuses, fields, shared views, tasks (relative dates), dependencies,
  rules and recurring tasks; start new projects from them.
- Web UI: project settings tabs for automations (rule builder, dry run, run log, retry), recurring tasks and
  templates; "Start from" template choice when creating a project; automation-made comments and changes are
  labelled "Automation".
- Demo data includes rules, a recurring review and a "Website launch" template.

### Changed
- `make dev-deps` uses its own Compose project (`glasshaus-dev`), so it never touches a stack running from
  another directory on the same host, and Makefile targets read `.env` correctly.

## [0.4.0] - 2026-10-08

Phase 3 — dependencies, timeline/Gantt, critical path, calendar.

### Added
- Task dependencies: finish-to-start, start-to-start, finish-to-finish and start-to-finish, with lag or lead in
  days; cycles and duplicates are rejected.
- Critical path calculation (early/late dates, slack, critical tasks, project finish).
- Auto-rescheduling (opt-in per project): changing dates or adding dependencies pushes dependent tasks later,
  keeping their durations; otherwise a preview-then-apply reschedule fixes violations on demand.
- Baselines: snapshot planned dates and compare per task and for the project finish.
- Slip warnings: overdue tasks, violated dependencies, tasks and the project finish behind the latest baseline.
- Calendar-window task filter (`scheduled_from` / `scheduled_to`).
- Web UI: timeline (Gantt) with dependency arrows, critical-path highlighting, baseline ghost bars, today line,
  day/week zoom, drag to move or resize and arrow keys for keyboard users; month calendar; start date and a
  dependency editor in the task drawer; auto-schedule toggle, baseline save, dependency check and warnings.
- Demo data includes a dependency chain and an "Initial plan" baseline per project.

### Changed
- Migration template generates modern typing syntax.
- The web app loads layouts, the task drawer, settings and account pages on demand (initial bundle 298 kB,
  down from 504 kB); busy calendar days expand with "+N more".

## [0.3.0] - 2026-10-08

Phase 2 — views, custom fields, comments, activity feed.

### Added
- Typed custom fields per project (text, number, date, single/multi select, person, checkbox, URL) with
  validation, required fields, filtering (`cf=`), sorting (`sort_field=`), and safe clean-up when options or
  fields are removed.
- Comments in markdown with @mentions (`@[Name](user:<id>)` or `@email`), editing by the author and moderation
  by project admins.
- In-app notifications for mentions, assignments and comments on your tasks, produced by idempotent event
  consumers (Redis Streams consumer group with retry and dead-lettering) that later phases reuse.
- Activity feed for tasks, projects or everything you can see, built from the domain-event log.
- Saved views (list, board, table; personal or shared) holding filters, grouping, sorting and columns; run a view
  through the API.
- Live updates over WebSocket (`/api/v1/ws`): identifiers only, filtered by project visibility, origin-checked.
- Web UI: list, board (drag and drop between and within columns) and virtualized table views; toolbar for search,
  priority, grouping, sorting and completed tasks; saved-view picker and save; task drawer with field editing,
  markdown description, comments with an @mention picker and activity; project settings for custom fields;
  notifications menu.
- Demo data includes custom fields, comments with mentions and shared views.
- Account page with a change-password form (signs you out everywhere, then back to sign-in).

### Changed
- Domain events record their project (`project_id`); existing events are backfilled.
- Response schemas in the OpenAPI document mark always-present fields as required, so generated clients are
  accurate.

## [0.2.1] - 2026-10-07

### Security
- Container images apply OS security updates at build time (`apk upgrade` / `apt-get upgrade`); the web image
  had 42 fixable HIGH findings from its nginx base (curl, expat, libuuid, pcre2, OpenSSL, c-ares, libxml2).
  `UPGRADE_OS_PACKAGES=false` exists only for networks that block the package mirrors.

### Changed
- CI scans both container images on every pull request with the same Trivy gate as the release workflow.

## [0.2.0] - 2026-10-07

Phase 1 — data model, authentication, RBAC, core task and project API.

### Added
- Domain model: organizations (tenants), users, workspaces and members, projects and members, configurable
  workflow statuses per project, tasks (subtasks, priority, assignee, dates, estimate, tags, ordering, soft
  delete, optimistic concurrency), API tokens, refresh sessions, domain-event outbox.
- Service layer (`ServiceContext` + per-module services) shared by every adapter.
- Authentication: email/password sign-in (argon2id), short-lived JWT access cookie, rotating refresh token,
  double-submit CSRF protection, login rate limiting, personal API tokens with scopes.
- Authorization: organization, workspace and project roles intersected with token scopes; invisible
  resources return 404.
- Tenant isolation with PostgreSQL row-level security (default deny) and a least-privilege `glasshaus_app`
  database role created by `migrate`; the API refuses to start in production as a role that bypasses RLS.
- REST API `/api/v1` (auth, users, tokens, workspaces, projects, members, statuses, tasks incl. search,
  filters, sorting, cursor pagination, bulk update, dry-run delete, restore, `If-Match`), RFC 9457 errors,
  stable operation IDs; OpenAPI 3.1 committed at `docs/openapi.json` with drift tests.
- Domain events relayed to a Redis stream and per-tenant pub/sub; worker sweep for unrelayed events.
- Web UI: sign-in, project navigation, create workspace/project, task list with quick add, status and
  priority changes; typed API client generated from OpenAPI.
- First owner account bootstrapped from `GLASSHAUS_ADMIN_EMAIL` / `GLASSHAUS_ADMIN_PASSWORD`; deterministic
  demo data generated through the service layer (`make demo`).
- Feature → REST → event → MCP coverage matrix.

### Changed
- `GLASSHAUS_SECRET_KEY` must be at least 32 characters in production.
- `setup.sh` and `update.sh` generate any missing secrets (new: `POSTGRES_APP_PASSWORD`, `GLASSHAUS_ADMIN_PASSWORD`).

## [0.1.0] - 2026-10-07

Phase 0 — scaffold.

### Added
- Monorepo layout: `backend/` (FastAPI, SQLAlchemy 2 async, Alembic, arq worker, MCP server) and
  `frontend/` (React 19, TypeScript, Vite, Tailwind CSS 4, TanStack Query).
- Docker Compose stack: `api`, `web`, `worker`, `mcp`, `postgres`, `redis`, one-shot `migrate`, scheduled `backup`.
  Non-root, read-only containers with healthchecks; host ports 8470 (web), 8471 (API), 8472 (MCP).
- Health (`/healthz`, `/readyz`), version (`/api/v1/version`), Prometheus metrics (`/metrics`),
  structured JSON logging, optional OpenTelemetry tracing.
- MCP server skeleton (official Python SDK 2.x, Streamable HTTP at `/mcp`, stdio for local use) with a
  `server_info` tool.
- Multi-tenant foundation: `tenants` table and `TenantScoped` mixin; idempotent seed and demo-data generator.
- `setup.sh` (idempotent installer), `update.sh` (backup, upgrade, health check, automatic rollback),
  backup/restore scripts, version bump and consistency checks.
- Makefile, pre-commit hooks (ruff, eslint, prettier, shellcheck, gitleaks), GitHub Actions for lint, test,
  smoke test, dependency/filesystem/image scanning and multi-arch image publishing on tags.
- Dark mode, skip link and version display in the web shell.

[Unreleased]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.24.0...HEAD
[0.24.0]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.23.0...v0.24.0
[0.23.0]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.22.0...v0.23.0
[0.22.0]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.21.1...v0.22.0
[0.21.1]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.21.0...v0.21.1
[0.21.0]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.20.1...v0.21.0
[0.20.1]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.20.0...v0.20.1
[0.20.0]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.19.0...v0.20.0
[0.19.0]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.18.0...v0.19.0
[0.18.0]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.17.0...v0.18.0
[0.17.0]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.16.0...v0.17.0
[0.16.0]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.15.0...v0.16.0
[0.15.0]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.14.0...v0.15.0
[0.14.0]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.13.0...v0.14.0
[0.13.0]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.12.0...v0.13.0
[0.12.0]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.11.1...v0.12.0
[0.11.1]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.11.0...v0.11.1
[0.11.0]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.9.3...v0.10.0
[0.9.3]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.9.2...v0.9.3
[0.9.2]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.9.1...v0.9.2
[0.9.1]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/parabyte-ca/project-glasshaus/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/parabyte-ca/project-glasshaus/releases/tag/v0.1.0
