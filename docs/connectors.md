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
