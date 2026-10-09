# Project assistant (virtual project manager)

The project assistant acts like a junior project manager assigned to a project. In this first phase it
**only reads**: every working morning it writes a **stand-up digest** for everyone on the project, and once
a week a **status draft** for the project's admins to edit and send. It never changes tasks, comments or
settings.

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

## The assistant's account

Each organization has one **Project assistant (AI)** account, created the first time a project turns the
assistant on. It:

- is added to that project as a **Viewer** (and removed when the assistant is turned off), so it reads
  exactly what a viewer would and nothing in other projects;
- cannot sign in (no password, no single sign-on, an address on the reserved `.invalid` domain), is not
  listed under people or provisioned through SCIM, cannot be given another role or assigned tasks;
- appears in the project's **People** list as *Project assistant (AI)*, and its AI requests are in the
  audit log under that name (`ai.assistant`).

## Coming next

- **Phase 2, approval queue:** suggested follow-up comments, reassignments and date changes, applied only
  when a person approves them.
- **Phase 3, trusted actions:** admins choose which kinds of action it may take on its own.

API: `GET/PUT/DELETE /api/v1/projects/{id}/assistant`, `POST /api/v1/projects/{id}/assistant/run`,
`GET /api/v1/projects/{id}/assistant/briefs`, `GET /api/v1/assistant/briefs/{id}`.
