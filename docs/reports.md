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

## API

| Call | Purpose |
|---|---|
| `POST /api/v1/reports/run` | Run a definition without saving it |
| `GET/POST /api/v1/reports`, `GET/PATCH/DELETE /api/v1/reports/{id}` | Saved reports |
| `POST /api/v1/reports/{id}/run` | Run a saved report; optional body `{"date": {"preset": "last_7_days"}, "project_ids": [...]}` |
| `GET /api/v1/reports/{id}/export` | CSV |

```bash
# Open and overdue tasks per assignee, as JSON
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"group_by":["assignee"],"measures":["open","overdue"],"sort":{"by":"overdue","descending":true}}' \
  http://localhost:8471/api/v1/reports/run
```

Definitions only use the names listed above; there is no free-form query language, so reports
cannot reach data the API would not otherwise show you.
