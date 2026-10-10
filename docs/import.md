# Importing tasks

Bring work into a project from a **CSV** or **Excel (.xlsx)** file: a spreadsheet you keep, or an export
from another tool such as **Nimble**. Open the project and choose **Import** (project editors and
admins), or type "import" in the command palette.

## Steps

1. **Exported from:** *A spreadsheet* or *Nimble*. This only changes which column names are recognised
   automatically.
2. **File:** pick the `.csv` or `.xlsx` file. For Excel files with several sheets, pick the sheet. The
   first row must be the column names. At most 5,000 rows per file.
3. **Columns:** each column shows an example value and what it will be imported as. Glasshaus guesses
   from the column names; change any choice, or pick *Don't import*.

   | Import as | Notes |
   | --- | --- |
   | ID | The item's id in the other tool. With it, importing again updates the same tasks. |
   | Title | Required. |
   | Description | Plain text or Markdown. |
   | Status, Priority | Each value in the file is matched to one of the project's statuses or priorities (below). |
   | Owner | Matched to a person by email address, or by exact name when it is unique. |
   | Start date, Due date | `2026-10-15`, `15/10/2026`, `Oct 15, 2026` or Excel dates. |
   | Estimate | Hours (`2.5`) or `1h 30m`. |
   | Tags | Separated by commas or semicolons. |
   | Parent ID | The ID of the parent item; makes the task a subtask. |
   | Comment | Each column chosen as a comment adds one comment. |
   | Link | Web addresses (several per cell are fine), listed under **Links** in the description. Files themselves aren't copied. |
   | Custom fields | The project's custom fields; select options are matched by their label. |

4. **Dates:** when a file writes dates like `03/04/2026`, choose whether that is day/month or
   month/day (Glasshaus picks it when a date such as `15/10/2026` makes it clear).
5. **Statuses and priorities:** each different value in the file is listed with the status or priority
   it will become. Values like *Closed* or *Major* are matched automatically.
6. **Check** runs the whole import without changing anything and shows what would happen: how many tasks
   are new, updated or unchanged, rows with problems, and people who couldn't be matched.
7. **Import** does it. All rows go in together; rows with problems are skipped and listed.

## Importing again

With an **ID** column, Glasshaus remembers which task each item became (per project and per *Exported
from* choice). Importing the same or a newer file again:

- updates the tasks whose rows changed, and adds new rows as new tasks;
- changes only the fields the file has columns for, so edits made in Glasshaus to other fields stay;
- adds each comment once;
- skips items whose task was deleted in Glasshaus.

This lets a team keep working in the old tool for a while and import again before switching over.
Without an ID column, every import adds the tasks again.

## People

Owners are matched by **email address** (or exact, unique name) to people who can open the project.
Anyone not found, or without access to the project, is listed after the check; their tasks are left
unassigned. Add them (Admin › People) or to the project, then import the file again: their tasks get
assigned.

## What an import doesn't do

- It doesn't notify anyone, run automation rules or post to Slack, Teams or webhooks for each task. The
  activity log and audit log record one *project imported* entry with the counts.
- Imported comments are written by the person who imported them.
- Attachments are not copied; their links are kept.

## Nimble

In Nimble, open the work items list, choose **Export**, export all field content and save it as `.xlsx`
or `.csv`. Choose *Nimble* under **Exported from**. Nimble's work item id becomes the ID, and its lane or
state becomes the status. Check the column choices: Nimble's exports vary with each workspace's forms.

A direct connection to Nimble's REST API (no export needed) is planned.

## API

`POST /api/v1/projects/{project_id}/import` takes the rows already mapped to fields (the web app reads
the file in the browser). Set `dry_run` to check. See the OpenAPI document for the request format.
