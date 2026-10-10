# Project assistant (virtual project manager)

The project assistant acts like a junior project manager assigned to a project. Every working morning it
writes a **stand-up digest** for everyone on the project, and once a week a **status draft** for the
project's admins to edit and send. With the digest it also **suggests** follow-ups, new due dates and
owners, and it turns meeting notes into proposed tasks. **By default it changes nothing by itself:** every
suggestion waits in an approval queue until a project editor or admin approves it. Organizations can let
projects have its follow-up comments posted automatically, with a daily limit and undo.

## Turning it on

Project admins open the project and choose **Project assistant** (next to **Report**). **Turn on** with:

| Setting | Default | Notes |
| --- | --- | --- |
| Daily stand-up digest | On, 08:00, weekdays only | Goes to everyone on the project |
| Weekly status draft | On, Friday 14:00 | Goes to the project's admins only |
| Time zone | Your browser's | Both schedules use it |
| Stale after | 5 days | In-progress tasks with no update for this long are listed as stale |
| Deliver by | Notification | Also **Email** (needs outgoing email) and a **Slack or Teams** channel (digest only) |

**Write a digest now** and **Write a weekly draft now** write one straight away; it is stored on the
Digests page and nobody is notified. Everyone on the project can read past digests and drafts there
(kept for 180 days).

"Everyone on the project" means the project's members plus the members of its workspace; "admins" are
project admins plus workspace admins. Deactivated people are skipped.

## What a digest contains

Always (computed by Glasshaus, no AI needed):

- health, percent complete, open and overdue counts;
- **Overdue** tasks with how many days late, **Due today**, **Due soon** (next 3 days; 7 for the weekly
  draft);
- **No update for N+ days**: in-progress tasks nobody has touched;
- **Unassigned and due soon**;
- **Done since the last digest** (or this week, for the draft);
- schedule warnings (dependency and baseline problems).

When an organization admin ticks **Project assistant** under **Admin → AI**, the model adds:

- for the digest, a two-to-four-sentence summary and up to five **Focus today** suggestions (task keys it
  names are checked against the data and dropped if unknown);
- for the weekly draft, a headline, two or three paragraphs, highlights and concerns, with **Copy draft as
  text** to paste into an email or chat.

What is sent to the model: the project key and name, today's date, health numbers, and the key, title,
status, due date, owner's name and days late/stale of the listed tasks (up to 20 per list) and schedule
warnings. Never emails, descriptions or comments. Task titles are wrapped as untrusted data, as for the
other AI features. If the model is off or fails, the brief still goes out with the facts and says why
there is no write-up.

## Suggestions and the approval queue

With each digest (scheduled or **Write a digest now**), the assistant fills the **Suggestions** list on the
Digests page. Turn this off with **Suggest follow-ups, new dates and owners** in the settings.

| Suggestion | Made by the rules (no AI needed) | With AI write-ups allowed |
| --- | --- | --- |
| **Follow-up comment** | On overdue work ("this was due Oct 6. What's a realistic new date…?") and in-progress work with no update for the stale threshold, addressed to the owner | A more specific, friendly note; the owner is always mentioned by Glasshaus, never by the model |
| **New due date** | Work 7+ days overdue that has not started: one week from today | A realistic date for clearly slipping work (must be in the next year and after the start date) |
| **New owner** | Unassigned work due within a week (or overdue): the project editor with the fewest open tasks | The person it judges best placed, from the project's editors and admins |
| **New task** | From **Turn meeting notes or an email into tasks**: lines starting with `- [ ]`, `TODO:`, `Action:` or `AI:` | Real action items from free-form notes, with priority and, when the notes say so, a date and owner |

What it never does: suggest the same thing twice while one is waiting, suggest something again within 7
days of a decision or after expiring, or keep more than 30 waiting. Unapproved suggestions expire after
7 days (notes-based tasks stay until decided, up to 50 at a time). Text the AI writes is kept plain: links
and images are removed and nobody is @-mentioned by the model. The digest says how many are waiting.

**Approving.** Project **editors and admins** see **Approve** and **Dismiss** on each suggestion and can edit
it first (the comment text, the date, the owner, or the new task's title, priority, due date and owner).
Viewers can read the queue. On approval:

- the change is made by the **Project assistant (AI)** account, so the task history shows the AI did it;
- comments and new tasks end with *Suggested by the project assistant, approved by <name>*;
- the approval is recorded in the audit log under the approver's name (`assistant.suggestion_approved`);
- if the task changed since the suggestion was made (another due date or owner, closed or deleted),
  nothing is applied and the suggestion is **set aside**; it shows under **Show recent decisions**.

The assistant gets editor rights only for the one change a person approved, inside that request; it stays
a Viewer otherwise.

## The assistant's account

Each organization has one **Project assistant (AI)** account, created the first time a project turns the
assistant on. It:

- is added to that project as a **Viewer** (and removed when the assistant is turned off), so it reads
  exactly what a viewer would and nothing in other projects; it makes a change only when a person approves
  a suggestion;
- cannot sign in (no password, no single sign-on, an address on the reserved `.invalid` domain), is not
  listed under people or provisioned through SCIM, cannot be given another role or assigned tasks;
- appears in the project's **People** list as *Project assistant (AI)*, and its AI requests are in the
  audit log under that name (`ai.assistant`).

## Trusted actions: follow-ups without approval

By default every suggestion waits for a person. Two switches let the assistant post its **follow-up
comments** by itself; both must be on:

1. **Organization ceiling.** An organization admin ticks **Post follow-up comments** under **Admin → AI
   assistant → What the project assistant may do without approval**. Turning it off stops automatic
   follow-ups in every project at once, whatever the projects chose.
2. **Project choice.** A project admin ticks **Post follow-up comments without approval** in the
   project's assistant settings, and sets **At most per day** (default 10, up to 50).

Then, with each digest, the day's waiting follow-ups are posted straight away, oldest first, until the limit
is reached (in the project's time zone; undone ones still count). The rest, and follow-ups proposed on
earlier days, stay in the queue for a person. Safeguards:

- **The person affected is told.** The task's owner is mentioned, so they get a notification (and a phone
  push where turned on). The comment says it was posted automatically and how to undo it.
- **Undo for 7 days.** Automatic follow-ups are listed under **Done on its own** on the Digests page;
  project editors and admins can **Undo**, which deletes the comment. An undone follow-up is not suggested
  again for 7 days. Follow-ups a person approved can be undone the same way.
- **Audited.** Each automatic comment is recorded as `assistant.action_automatic` under the assistant
  account, and each undo as `assistant.action_undone` under the person who undid it.
- **Only follow-ups.** New due dates, owners and tasks from notes always wait for approval. A follow-up on
  a task that was closed or deleted in the meantime is left for a person to look at.

API: `GET/PUT/DELETE /api/v1/projects/{id}/assistant`, `POST /api/v1/projects/{id}/assistant/run`,
`GET /api/v1/projects/{id}/assistant/briefs`, `GET /api/v1/assistant/briefs/{id}`,
`GET /api/v1/projects/{id}/assistant/suggestions` (`?decided=true` for recent decisions),
`POST /api/v1/projects/{id}/assistant/suggestions/{sid}/approve` (optional edits) and `/dismiss`,
`POST /api/v1/projects/{id}/assistant/notes`,
`POST /api/v1/projects/{id}/assistant/suggestions/{sid}/undo`. The organization ceiling is
`assistant_trusted` in `PATCH /api/v1/admin/settings`; the project choice is `trusted` and
`auto_daily_cap` in `PUT /api/v1/projects/{id}/assistant`.
