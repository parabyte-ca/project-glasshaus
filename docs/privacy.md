# Privacy and compliance

Glasshaus is self-hosted: the organization that runs it is the controller of the personal data in it and
decides what is turned on. This page lists what Glasshaus stores, where data can go, how long it is kept,
and the tools for people's rights (access, erasure) and for audits. People can read a short version in
the app under **About, privacy and source code** (footer).

## What is stored

| Data | Where | Kept |
| --- | --- | --- |
| Profile: name, email, role, working hours; from a directory: job title, department, manager | `users` | Until erased |
| Work: tasks, comments, time entries, goals, reports, dashboards | project tables | Until deleted; deleted tasks are purged after the *Deleted tasks* setting (tasks with logged time are kept) |
| Activity history: what changed, when, by whom | `domain_events` | *Activity history* setting, **2 years by default** |
| Notifications | `notifications` | *Notifications* setting (90 days by default) |
| Sign-ins: time, IP address, browser | `auth_sessions` | Deleted 90 days after the session ends |
| Audit log: administrative, security and AI actions, every domain event | `audit_log` | *Audit log* setting (365 days by default, at least 30) |
| Sign-in links to identity providers, API tokens (hashed), connected apps, push devices | their tables | Until revoked or erased |

Comment text is **not** copied into the activity history or the audit log: only the comment's id, author
and mentions. Deleting a comment removes its text everywhere. (Before 0.22 events carried the text; the
0.22 migration removed it from past events and audit entries.)

Colleagues see each other's name, email, role and working hours (for assignment and workload). When
someone last signed in is shown to organization admins only.

## Where data can go

Nothing leaves the server unless an admin turns it on:

| Recipient | What it receives | Turned on by |
| --- | --- | --- |
| AI provider (Anthropic or OpenAI) | The project text a feature needs, per request; see [ai.md](ai.md) | `GLASSHAUS_AI_PROVIDER` and Admin → AI |
| Slack, Microsoft Teams | Event summaries, comment text for comment events, scheduled report posts | Admin → Integrations |
| Webhooks | Event payloads (tasks, changes; comment metadata without text) | Admin → Integrations |
| Email (your SMTP server) | Report emails, alerts, backup warnings | `GLASSHAUS_SMTP_*` |
| Browser push services (Google, Mozilla, Apple) | Encrypted notification text; the service cannot read it | Each person, per device |
| GitHub (release check) | Nothing about your server or people: a daily request for the latest release's version and notes | `GLASSHAUS_UPDATE_CHECK` (on by default) |
| Microsoft Entra ID / identity provider | Sign-in and provisioning requests; the Graph sync reads people and managers | Admin → Single sign-on, Provisioning |

Keep a list of the ones you use as your subprocessor register.

## People's rights

- **Access / portability.** Everyone can download their own data from **Account → Download my data**: a
  zip with one JSON Lines file per table holding every row that refers to them (profile, work assigned to
  or created by them, comments, time, sessions, notifications, settings), plus the audit entries and
  activity they caused. Passwords, token hashes and device keys are left out. Admins can download anyone's
  data from **Admin → People → Download data** (a subject access request). Both are audited
  (`user.exported`).
- **Erasure.** **Admin → People → Erase…** (owners for owners; typing the person's email confirms it)
  anonymises the person: their name and email become "Former user", and their sign-ins, tokens, connected
  apps, devices, identity-provider links, calendar feeds, notifications, report subscriptions and the text
  of their comments are deleted. Their tasks, time and history stay, attributed to "Former user", so
  reports and the organization's records stay correct. Events about the account itself lose their
  details. An erased person cannot sign in, be reactivated or be changed by SCIM; if they come back, add
  them as a new person. Audited as `user.erased`.
- **What erasure keeps.** The audit log is the record of what happened and cannot be changed; its entries
  name the person only by an id (now "Former user") and expire with the audit retention. Text other
  people wrote about the person (for example "@Pat" in someone else's comment) is not rewritten. Backups
  taken before the erasure still hold the old data until they expire (`GLASSHAUS_BACKUP_RETENTION_DAYS`).

## Audit log integrity

Each organization's audit entries are numbered without gaps and sealed in a hash chain: every entry
stores `sha256(previous entry's hash + its own fields)`. A database trigger does this, so the
application cannot skip it, and the database refuses changes and deletions from the application's role.
Old entries leave only through the retention function, which first records the purge (how many entries,
up to when) in the chain.

**Admin → Audit log → Check integrity** recomputes the chain and reports any entry that was changed,
removed or inserted, even by someone with direct database access. It shows the latest seal (the newest
entry's hash): keep a copy elsewhere (a ticket, an email) and later checks prove that nothing before it
changed. Changing a retention setting is audited with the old and new values.

## Backups

Backups are encrypted with [age](https://age-encryption.org) and each has a SHA-256 checksum. See
[Backup and restore](../README.md#backup-and-restore). The key (`GLASSHAUS_BACKUP_KEY` in `.env`) is
generated by `setup.sh`/`update.sh`; store a copy outside the server, because encrypted backups cannot
be restored without it.

## Source code and licences

Glasshaus is licensed under the AGPL-3.0. People using a server can find its source from the footer
(**About, privacy and source code**), `GET /api/v1/version` (`source`) and the MCP `server_info` tool. If
you run a modified version, set `GLASSHAUS_SOURCE_URL` to where your changes are published. The same page
lists the third-party packages in the server (`GET /api/v1/licenses`) and the web app (`/licenses.json`)
with their licences.
