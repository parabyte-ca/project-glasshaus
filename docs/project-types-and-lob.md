# Project types and lines of business (planned)

Status: roadmap row 34, design draft. The wording under "When to use" is a first draft to be corrected by the people who know the work.

## The idea

Every project gets one **Type**. Every Type belongs to one **Line of business (LOB)**.

| | Type | LOB |
| --- | --- | --- |
| Question it answers | "What kind of work is this?" | "Where does this work roll up in reports?" |
| Who sees it | Everyone on the project, in the project header, pickers and filters | Reports, dashboards and the portfolio view |
| Who sets it | Whoever creates the project, from a short list | Nobody per project: it follows from the Type |
| Who manages the lists | Admins and owners | Admins and owners |

People only ever choose a Type. The LOB comes along with it, so reporting stays consistent and nobody has to know the reporting structure to start a project.

## Starting list

All ten rows are one Type to one LOB today. The model allows several Types under one LOB later (for example two kinds of training under one training LOB).

| Type | LOB | Who can pick it |
| --- | --- | --- |
| External Technical Training | Training and Professional Development | Everyone |
| In-House Technical Training | Training and Professional Development | Everyone |
| GHS Process Improvements | GHS Process Improvement | Everyone |
| Internal Projects | Internal Projects | Everyone |
| Internal IT Work for GHS | GHS Internal IT | Everyone |
| Process Improvements | Process Improvements | Everyone |
| R&D | R&D | Developers only |
| Management | Management | Managers only |
| GHS Internal Security | GHS Internal Security | Everyone |
| Non-billable work | Non-billable, company events, leave | Everyone |

"Developers only" and "Managers only" are an **audience** on the Type: people outside the audience do not see it in the picker. Admins and owners always see every Type.

## When to use each (first draft)

This is the part people will consult most, so it lives next to the picker, not in a manual.

| Type | Use it when | Not when | Examples |
| --- | --- | --- | --- |
| External Technical Training | Someone attends training run by an outside provider | The session is delivered by our own staff | A vendor certification course; a conference workshop |
| In-House Technical Training | Our own staff prepare or deliver the training | An outside provider runs it | A lunch-and-learn on a new tool; onboarding curriculum for new hires |
| GHS Process Improvements | Improving how GHS itself works internally | The change is for a client or product process | Streamlining expense approvals; a new internal handover checklist |
| Process Improvements | Improving a process outside GHS's own internal operations | It is purely an internal GHS process | A better intake process for a team's work requests |
| Internal Projects | Internal work that is not IT, security, training or a process change | A more specific Type fits | An office move; a team offsite plan |
| Internal IT Work for GHS | IT work for GHS's own systems and people | It is security-focused | A laptop refresh; a file-share migration |
| GHS Internal Security | Security work on GHS's own environment | The work is general IT | A policy review; a vulnerability clean-up; an access audit |
| R&D | Building or exploring something new (developers) | It is routine upkeep | A prototype of a new integration |
| Management | Management activities (managers) | Delivery work a team member would do | Budget planning; performance review cycle |
| Non-billable work | Anything that cannot be billed, including company events and leave | It could be billed to a client or covered by a more specific Type | A company event; planned leave; an all-hands |

Two pairs need a clear line, and I would settle them with the team before launch:
- **GHS Process Improvements vs Process Improvements.** Suggested line: the first is about GHS's own internal operations, the second is anything else.
- **Internal IT Work vs GHS Internal Security.** Suggested line: if the main goal is protecting something, it is Security; otherwise IT.

## How it should look

1. **Picking a Type.** A single dropdown on New project and in project settings, grouped by LOB, each option with a one-line description. A "Which one do I pick?" link opens a side panel with the table above, filtered to the Types the person can use. The panel also shows the three or four most common mix-ups.
2. **Seeing it.** The Type appears as a small label in the project header and on project cards, and as a filter on the Home and Portfolio pages. The LOB is not shown to team members.
3. **Reporting.** The report builder and dashboards gain a "Line of business" field to group, filter and total by (hours, tasks, projects). Type stays available as a finer breakdown, with LOB as the roll-up. A ready-made "Hours by LOB" tile and report ship with it.
4. **Managing the lists.** An admin page (Admin → Project types) for admins and owners to add, rename, retire and reorder Types and LOBs, set each Type's audience, and edit its guidance text and examples. Retiring a Type hides it from pickers but keeps it on existing projects and in reports. Every change is recorded in the audit log.
5. **Guidance is data, not documentation.** The "use when / not when / examples" text is stored with each Type, so admins can improve it without a release, and the same text feeds the picker, the help panel and the AI assistant.

## Rolling it out to existing projects

- Existing projects start as **Unclassified** so nothing is guessed silently.
- The assistant can propose a Type for each from its name and description. Suggestions go in the existing approval queue, and nothing changes until someone approves.
- A report shows how many projects are still Unclassified. After the team has caught up, an admin setting can make Type required on new projects (the default from the start for new projects).
- Import and the planned plan-to-project import (row 31) map to Type by name, and prompt when it is missing.

## Open questions

1. Is a project ever in two LOBs (for example half training, half internal)? The design says no: one Type, one LOB. Splitting work across LOBs would be done with separate projects.
2. How should "Developers only" and "Managers only" be decided: a role, a group, or a flag on the person? The Azure AD manager hierarchy already identifies managers.
3. Should a Type be changeable after work has been logged? Suggested: yes for admins and the project owner, with the change recorded, and reports use the current Type.
4. Do any Types carry a billable or non-billable meaning that should drive timesheets? Today it is only a label.
5. Should LOB totals feed the planned ADP view (row 32)?
