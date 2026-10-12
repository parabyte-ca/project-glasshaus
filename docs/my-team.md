# My team

**My team** (`/team`) shows managers the people who report to them, as your organization's directory
says. It appears in the menu, on the home page and in the command palette (`g y`) for anyone with at least
one direct report.

For each person:

- **Workload:** open, overdue, due this week and in progress.
- **Time:** hours logged this week (against what they have available in a week, from Workload
  capacity) and last week.
- **Projects:** the projects with their open work, each with the project's health (from its overdue
  work).
- **Recent activity:** tasks finished in the last 7 days (the latest three listed) and in-progress tasks
  with no update for 5 days or more.

**See tasks** opens that person's open work, or what they finished in the last 30 days, with links to the
tasks. **Include everyone below me** adds their reports' reports, and so on down.

## What managers can see

Set in **Admin → Provisioning → What managers see on My team**:

| Setting | Managers see |
| --- | --- |
| **Only in projects the manager can open** (default) | Detail in projects the manager can open; elsewhere, only counts ("1 more in projects you can't open"). |
| **Their reports' work in every project** | Full detail everywhere, including projects the manager is not a member of. Choosing it asks for confirmation. |

Guests (contractors, partners) who manage someone always get the first setting. Either way, every time a manager opens someone's task list it is recorded in the audit log as
`team.tasks_viewed`, with who was viewed. Opening a task itself still needs access to its project.

## Where managers come from

Reporting lines are not edited in Glasshaus; they come from your identity provider.

1. **SCIM** (recommended). Microsoft Entra ID's default SCIM mapping already sends each person's manager,
   job title and department (the SCIM enterprise extension). Turn on provisioning as in
   [sso-scim.md](sso-scim.md) and managers follow along. Okta and others work the same way when the
   `manager` attribute is mapped.
2. **Microsoft Graph sync**, for people SCIM does not cover (or if you sign in with SSO but do not
   provision). In Entra ID:
   1. **App registrations → New registration** (single tenant, no redirect URI).
   2. **API permissions → Add → Microsoft Graph → Application permissions → `User.Read.All`**, then
      **Grant admin consent**.
   3. **Certificates & secrets → New client secret**; copy the value.
   4. In Glasshaus, **Admin → Provisioning → Managers from Microsoft Entra ID**: enter the directory
      (tenant) ID or primary domain, the application (client) ID and the secret, then **Save**,
      **Sync now**, and tick **Sync every night**.

   People are matched by email (their mail or user principal name). The sync runs nightly at 02:37 UTC.
   It also fills in job titles and departments. Someone whose manager came from SCIM is left alone (SCIM
   wins). The secret is encrypted at rest; only `login.microsoftonline.com` and `graph.microsoft.com` are
   called.

A loop (someone made their own manager's manager) is refused and logged; the rest of the change applies.
Deactivated people drop off My team.

## API and MCP

- `GET /api/v1/team?everyone=true|false`, `GET /api/v1/team/{person_id}/tasks?done=true|false`
- `GET/PUT /api/v1/admin/directory-sync`, `POST /api/v1/admin/directory-sync/run` (org admins)
- `manager_visibility` in `PATCH /api/v1/admin/settings`
- `GET /api/v1/users/me` includes `direct_reports`; users include `manager_id`, `job_title` and
  `department`.
- MCP: `my_team` ("how is my team doing this week?").
