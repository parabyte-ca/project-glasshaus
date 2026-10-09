# Project assistant (virtual project manager)

The project assistant acts like a junior project manager assigned to a project. Every working morning it
writes a **stand-up digest** for everyone on the project, and once a week a **status draft** for the
project's admins to edit and send. With the digest it also **suggests** follow-ups, new due dates and
owners, and it turns meeting notes into proposed tasks. **It changes nothing by itself:** every suggestion
waits in an approval queue until a project editor or admin approves it.

## Turning it on

Project admins open the project and choose **Digests** (next to **Report**). **Turn on** with:

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

When an organization admin ticks **Project assistant** under **Admin → AI assistant**, the model adds:

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
days of a decision, or keep more than 30 waiting. Unapproved suggestions expire after 7 days (notes-based
tasks stay until decided). The digest says how many are waiting.

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

## Coming next

- **Phase 3, trusted actions:** admins choose which kinds of suggestion it may apply on its own (for
  example, follow-up comments), with everything else still waiting for approval.

API: `GET/PUT/DELETE /api/v1/projects/{id}/assistant`, `POST /api/v1/projects/{id}/assistant/run`,
`GET /api/v1/projects/{id}/assistant/briefs`, `GET /api/v1/assistant/briefs/{id}`,
`GET /api/v1/projects/{id}/assistant/suggestions` (`?decided=true` for recent decisions),
`POST /api/v1/projects/{id}/assistant/suggestions/{sid}/approve` (optional edits) and `/dismiss`,
`POST /api/v1/projects/{id}/assistant/notes`.
