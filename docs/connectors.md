# Integrations

Configured under **Admin → Integrations** (org admins; project admins can add integrations for their own
project) or `GET/POST/PATCH/DELETE /api/v1/integrations`. Secrets (webhook URLs, signing secrets, mailbox
passwords) are encrypted at rest with a key derived from `GLASSHAUS_SECRET_KEY` and never returned; if you
change that key, re-enter them.

## Outbound: Slack, Microsoft Teams, signed webhooks

Pick the events to send (`task.created`, `task.completed`, `task.updated`, `comment.created`,
`task.deleted`, `dependency.created`, `time.logged`, …) and optionally limit to one project.

- **Slack:** an incoming-webhook URL. Messages show who did what with a link back; user text is escaped.
- **Microsoft Teams:** a Workflows webhook URL ("Post to a channel when a webhook request is received").
  Messages are Adaptive Cards.
- **Webhook:** any URL; the body is the domain event envelope (`id`, `type`, `project_id`, `actor`,
  `occurred_at`, `data`). Each request carries `X-Glasshaus-Event`, `X-Glasshaus-Delivery` and
  `X-Glasshaus-Signature: t=<unix>,v1=<hex HMAC-SHA256 of "<t>.<body>" with the signing secret>`.

Delivery is at-least-once with one attempt per event per integration, retried after 1, 5 and 15 minutes,
1 and 4 hours (4xx responses other than 429 are not retried). URLs that resolve to loopback, link-local or
cloud-metadata addresses are always refused; private networks only with `GLASSHAUS_WEBHOOK_ALLOW_PRIVATE=true`.
**Test** sends a sample message; **Deliveries** shows the log.

### Scheduled posts (Slack and Teams)

On a Slack or Teams integration, **Scheduled posts** sends a **saved report** (its table, up to 15
rows, with totals) or a **project's status** (health, open/done/overdue, and the overdue, due-soon
and recently completed tasks) daily, weekly or monthly. **Post now** sends one straight away.

- A post runs with the access of the person who set it up, at the time it is sent. Everyone in the
  channel sees it, so only people who manage the integration can add posts.
- A channel set up for one project only ever gets that project's numbers, even from a report that
  covers more.
- Posts end on their own when their report is deleted or no longer visible to that person, or the
  person is deactivated. They use the same delivery log and retries as other messages.

API: `GET/POST /api/v1/integrations/{id}/posts`, `DELETE /api/v1/integrations/{id}/posts/{post_id}`,
`POST /api/v1/integrations/{id}/posts/{post_id}/send`.

## Slack command: `/glasshaus`

Ask Glasshaus from Slack. Answers are **private to the person asking** (ephemeral) and use **their**
access, read-only.

| Command | Answer |
| --- | --- |
| `/glasshaus my` | Your open tasks, soonest due first |
| `/glasshaus WEB-12` | That task, with a link |
| `/glasshaus report Open work` | Runs your saved report (or a shared one) |
| `/glasshaus who has the most overdue work?` | With the AI assistant on: an answer from a report (*Questions about reports*) or the matching tasks (*Ask in plain words*) |
| `/glasshaus help` | This list |

Set-up (an organization admin):

1. In Slack, **Create an app** → *From scratch*. Under **OAuth & Permissions** add the bot scopes
   `commands`, `users:read` and `users:read.email`, then install it to the workspace and copy the
   **Bot User OAuth Token** (`xoxb-…`). Copy the **Signing Secret** from *Basic Information*.
2. In Glasshaus, **Admin → Integrations → Connect**, type *Slack command (/glasshaus)*, paste both.
   **Test** checks the token.
3. Back in Slack, **Slash Commands → Create New Command**: command `/glasshaus`, Request URL = the
   integration's **Request URL** (`https://<your server>/api/v1/integrations/<id>/slack`).

Glasshaus matches people by the email on their Slack profile; someone without an active Glasshaus
account with that email gets a "not linked" reply and no data. Slack workspace admins can change
profile emails, so only connect a workspace whose admins you trust as much as Glasshaus admins. Slack must be able to reach your server
over HTTPS (for a homelab, a reverse proxy or tunnel such as Cloudflare Tunnel that exposes only
`/api/v1/integrations/*/slack`). Every request is checked against the signing secret and must be less
than five minutes old.

For Microsoft Teams, ask through the Microsoft 365 Copilot agent or the Copilot Studio connector (see
[integrations/README.md](integrations/README.md#microsoft-365-copilot-declarative-agent)); a Teams
channel bot could not reply privately.

## Inbound: GitHub and GitLab

Create the integration for a project, then add a webhook in the repository:

- **GitHub:** Payload URL = the integration's payload URL, content type `application/json`, secret = the
  signing secret, events *Pushes* and *Pull requests*.
- **GitLab:** URL = the payload URL, secret token = the signing secret, triggers *Push* and *Merge request*.

Commits, pull requests and merge requests that mention a task key of that project (`WEB-12`, in the
message, title, body or branch name) add a comment linking them. `fixes WEB-12` / `closes` / `resolves`
completes the task when the pull/merge request is merged or the commit lands on the default branch.

## Email to task

An IMAP mailbox (TLS, port 993) polled every two minutes. Each unseen message becomes a task in the chosen
project: subject → title, plain-text body → description, with the sender noted. Limit senders to
addresses or `@domains`. Messages are marked as read afterwards. Use a dedicated mailbox.

## Calendars (Google, Microsoft 365 / Outlook, Apple)

Each person can create a private iCalendar link under **Account → Calendar feed** and subscribe to it
("From URL" in Google Calendar, "Subscribe from web" in Outlook). It lists their open tasks with due dates
as all-day events (start date to due date), up to a year ahead, and is re-checked against their current
permissions on every refresh. Creating a new link turns off the old one.
