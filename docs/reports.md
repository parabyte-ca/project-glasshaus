# Custom reports and dashboards

**Reports** (left navigation, or `g` then `r`) lets anyone build a report from tasks or logged time,
save it, share it and put it on a dashboard.

## Building a report

| Part | Choices |
|---|---|
| **Source** | Tasks, or logged time |
| **Group by** (up to two) | Tasks: project, status, status category, priority, assignee, reporter, tag, due / created / completed by week or month, and a project's single-select custom fields (filter to that one project first). Time: project, person, task, day, week, month, billable or not |
| **Measures** (up to six) | Tasks: number of tasks, open, done, overdue, estimate (hours), average age of open tasks, average time to complete, % completed on or before the due date. Time: hours, billable hours, entries, people |
| **Filters** | Projects, people (assignee or who logged time), date range (presets or custom; tasks by created, completed or due date), status, priority, tags, billable |
| **Show as** | Table, bar chart, line chart (first grouping along the axis, the second as up to six lines), or a single number |

The preview updates as you change things. **Download CSV** exports what you see; saved reports also
export at `GET /api/v1/reports/{id}/export` (up to 500 rows, spreadsheet formulas neutralised).
Four templates (overdue work by person, tasks completed per week, on-time delivery by project, hours
by project this month) are on the Reports page.

## Who sees what

A report holds a definition, not data. Every run uses the access of the person viewing it: tasks in
projects they can read, and time they may see (their own, or in projects they can read). A shared
report therefore shows each person their own numbers; sharing never exposes a project to someone
who isn't in it. Guests can build private reports but not share them. Only the owner or an
organization admin can change or delete a report; anyone it is shared with can **Save a copy**.

## On dashboards

- **Add to dashboard** on a saved report, or **Edit → Saved report or number** on a dashboard.
- A single-number report can have a **target** and whether higher or lower is good; the tile then says
  "On target" or "Off target" (with an icon, not colour alone).
- **Dashboard filters** (date range, project) apply to every report tile at once and stay in the
  address, so a filtered dashboard can be bookmarked or shared. "Each report's own" uses the report's
  saved filters.
- In **Edit** mode, drag tiles to reorder them (or use the arrow buttons), set each tile's width
  (narrow, wide, full) and give it a title.

## Report emails

On a saved report, **Email me this report** sends it to you daily, weekly or monthly at a time you
choose (in your time zone), with the table in the email and, if you like, the full report (up to 500
rows) as a CSV attachment. **Email me now** sends one straight away.

- Each email is run **as you, when it is sent**, so it shows only what you could see in the app at
  that moment. Subscribing to a shared report never shows you more than the owner's report would.
- Emails stop on their own when you are deactivated or can no longer see the report (it was deleted
  or unshared). If sending fails, the reason shows on the report and the next email is tried at its
  usual time.
- Emails go only to your own address; there is no way to send a report to someone else.

### Setting up email (administrators)

Email is off until the server has an SMTP server. Add these to `.env` and restart:

```bash
GLASSHAUS_SMTP_HOST=smtp.office365.com     # or smtp.gmail.com, or a relay on your network
GLASSHAUS_SMTP_PORT=587
GLASSHAUS_SMTP_SECURITY=starttls           # starttls (587), tls (465) or none (local relay)
GLASSHAUS_SMTP_USERNAME=reports@example.com
GLASSHAUS_SMTP_PASSWORD=…                  # an app password where the provider offers one
GLASSHAUS_SMTP_FROM=Glasshaus <reports@example.com>
```

The worker sends due emails once a minute. Office 365 needs SMTP AUTH turned on for the sending
mailbox; Gmail needs an app password.

## Alerts

**Alert me** on a saved report tells you when one of its totals goes above or below a number: for
example "Overdue goes above 5" or "% on time goes below 80". The report is checked on the schedule
you choose (daily, weekly or monthly, in your time zone), with your access. You get a notification
(and, if you tick it and email is set up, an email) when the alert goes off and again when the
number is back; never on every check. **Check now** runs a check straight away.

Alerts end on their own if you are deactivated or can no longer see the report. If the report is
changed so the measure is gone, the alert stays and says why it cannot check.

## Asking questions (AI assistant)

When the optional [AI assistant](ai.md) is on and an admin has ticked **Questions about reports**, the
Reports page has an **Ask a question** box (also **Ctrl K** → *Ask reports: …*), and each saved report
has **Ask about this report**.

1. The assistant picks one of your saved reports by name, or fills in a report definition from the
   same lists as the builder.
2. Glasshaus runs it with your access.
3. The assistant writes a short answer from that table. The table or chart is shown beside it, and
   **Open in the report builder** lets you adjust and save it.

MCP clients get the same through `list_reports`, `run_report`, `manage_reports` (create, update,
delete with a preview) and `ai_ask_reports`.

## API

| Call | Purpose |
|---|---|
| `POST /api/v1/reports/run` | Run a definition without saving it |
| `GET/POST /api/v1/reports`, `GET/PATCH/DELETE /api/v1/reports/{id}` | Saved reports |
| `POST /api/v1/reports/{id}/run` | Run a saved report; optional body `{"date": {"preset": "last_7_days"}, "project_ids": [...]}` |
| `GET /api/v1/reports/{id}/export` | CSV |
| `GET/PUT/DELETE /api/v1/reports/{id}/email` | Your email schedule for a report |
| `POST /api/v1/reports/{id}/email/send` | Email it to yourself now |
| `GET /api/v1/reports/subscriptions` | All your report emails |
| `GET/PUT/DELETE /api/v1/reports/{id}/alert`, `POST /api/v1/reports/{id}/alert/check` | Your alert on a report |
| `GET /api/v1/reports/alerts` | All your report alerts |
| `POST /api/v1/ai/reports` | Ask a question, `{"question": "...", "report_id": null}`; needs the AI assistant's `reports` feature |

```bash
# Open and overdue tasks per assignee, as JSON
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"group_by":["assignee"],"measures":["open","overdue"],"sort":{"by":"overdue","descending":true}}' \
  http://localhost:8471/api/v1/reports/run
```

Definitions only use the names listed above; there is no free-form query language, so reports
cannot reach data the API would not otherwise show you.
