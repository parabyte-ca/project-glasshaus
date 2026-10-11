"""MCP tools: dependencies and schedules, automations, recurring tasks, templates, time tracking,
workload, reports and status summaries, dashboards, portfolios and OKRs."""

import uuid
from datetime import date
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from glasshaus.core.context import ServiceContext
from glasshaus.core.errors import InvalidInput
from glasshaus.core.rbac import Scope
from glasshaus.mcp_server.runtime import UNTRUSTED, invoke
from glasshaus.mcp_server.tools_core import (
    DESTRUCTIVE,
    READ,
    WRITE,
    Confirm,
    ProjectRef,
    TaskRef,
    project_id,
    user_id,
)

DepType = Literal["fs", "ss", "ff", "sf"]


def register(server: MCPServer) -> None:
    # ------------------------------------------------------------------ dependencies and schedule

    @server.tool(name="manage_dependencies", title="Manage task dependencies", annotations=WRITE)
    async def manage_dependencies(
        action: Literal["list", "add", "update", "remove"],
        task: Annotated[TaskRef | None, Field(description="list: the task whose links to show.")] = None,
        project: Annotated[ProjectRef | None, Field(description="list: every link in a project.")] = None,
        predecessor: Annotated[str | None, Field(description="add: the task that must happen first.")] = None,
        successor: Annotated[str | None, Field(description="add: the task that waits for it.")] = None,
        type: Annotated[DepType, Field(description="fs = finish-to-start (default), ss, ff, sf.")] = "fs",  # noqa: A002
        lag_days: Annotated[int, Field(ge=-365, le=365, description="Gap in days; negative = lead.")] = 0,
        dependency_id: Annotated[uuid.UUID | None, Field(description="update/remove: the link id.")] = None,
    ) -> dict[str, Any]:
        """List, add, change or remove dependencies (FS/SS/FF/SF with lag). Cycles are refused; with
        auto-scheduling on, successors move later automatically and the moves are returned."""
        from glasshaus.scheduling import service as scheduling
        from glasshaus.scheduling.schemas import DependencyCreate, DependencyUpdate

        async def run(ctx: ServiceContext) -> Any:
            if action == "list":
                if task:
                    return await scheduling.task_dependencies(ctx, task)
                if project:
                    return {
                        "dependencies": await scheduling.list_dependencies(
                            ctx, await project_id(ctx, project)
                        )
                    }
                raise InvalidInput("list needs task or project")
            if action == "add":
                if not predecessor or not successor:
                    raise InvalidInput("add needs predecessor and successor")
                data = DependencyCreate(
                    predecessor=predecessor, successor=successor, type=type, lag_days=lag_days
                )
                return await scheduling.create_dependency(ctx, data)
            if dependency_id is None:
                raise InvalidInput(f"{action} needs dependency_id")
            if action == "update":
                return await scheduling.update_dependency(
                    ctx,
                    dependency_id,
                    DependencyUpdate(type=type, lag_days=lag_days),
                )
            await scheduling.delete_dependency(ctx, dependency_id)
            return {"removed": str(dependency_id)}

        scope = Scope.READ if action == "list" else Scope.TASKS_WRITE
        args = {"action": action, "predecessor": predecessor, "successor": successor, "task": task}
        return await invoke("manage_dependencies", scope, args, run)

    @server.tool(name="get_schedule", title="Get schedule and critical path", annotations=READ)
    async def get_schedule(project: ProjectRef) -> dict[str, Any]:
        """Early/late dates, slack, the critical path, project finish and schedule warnings."""
        from glasshaus.scheduling import service as scheduling

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            pid = await project_id(ctx, project)
            return {
                "schedule": await scheduling.get_schedule(ctx, pid),
                "warnings": await scheduling.schedule_warnings(ctx, pid),
            }

        return await invoke("get_schedule", Scope.READ, {"project": project}, run, target=project)

    @server.tool(name="reschedule_project", title="Reschedule project", annotations=DESTRUCTIVE)
    async def reschedule_project(project: ProjectRef, confirm: Confirm = False) -> dict[str, Any]:
        """Move tasks later so every dependency holds. Without confirm=true, returns the planned moves."""
        from glasshaus.scheduling import service as scheduling

        async def run(ctx: ServiceContext) -> Any:
            return await scheduling.reschedule(ctx, await project_id(ctx, project), dry_run=not confirm)

        return await invoke(
            "reschedule_project",
            Scope.TASKS_WRITE,
            {"project": project, "confirm": confirm},
            run,
            target=project,
        )

    @server.tool(name="manage_baselines", title="Manage baselines", annotations=WRITE)
    async def manage_baselines(
        project: ProjectRef,
        action: Literal["list", "create", "variance", "delete"] = "list",
        name: str | None = None,
        baseline_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Snapshot planned dates (create), compare against one (variance), list or delete baselines."""
        from glasshaus.scheduling import service as scheduling
        from glasshaus.scheduling.schemas import BaselineCreate

        async def run(ctx: ServiceContext) -> Any:
            pid = await project_id(ctx, project)
            if action == "create":
                return await scheduling.create_baseline(ctx, pid, BaselineCreate(name=name or "Baseline"))
            if action in ("variance", "delete"):
                if baseline_id is None:
                    raise InvalidInput(f"{action} needs baseline_id")
                if action == "variance":
                    return await scheduling.baseline_variance(ctx, baseline_id)
                await scheduling.delete_baseline(ctx, baseline_id)
            return {"baselines": await scheduling.list_baselines(ctx, pid)}

        scope = Scope.READ if action in ("list", "variance") else Scope.PROJECTS_WRITE
        return await invoke("manage_baselines", scope, {"project": project, "action": action}, run)

    # ------------------------------------------------------------------ automations

    @server.tool(name="manage_automations", title="Manage automation rules", annotations=WRITE)
    async def manage_automations(
        project: ProjectRef,
        action: Literal["list", "create", "update", "enable", "disable", "delete"] = "list",
        rule_id: uuid.UUID | None = None,
        rule: Annotated[
            dict[str, Any] | None,
            Field(
                description=(
                    "create/update: {name, trigger:{type, ...}, conditions:[{field, op, value}], "
                    "actions:[{type, ...}]}. Triggers: task_created, task_updated, status_changed "
                    "(to_category), comment_created, due_soon (days_before), scheduled (schedule). "
                    "Actions: set_status, set_priority, assign, "
                    "unassign, set_due_date, add_tags, remove_tags, set_custom_field, create_subtask, "
                    "post_comment, notify, webhook. See GET /api/v1/openapi.json RuleCreate for the schema."
                )
            ),
        ] = None,
        confirm: Annotated[bool, Field(description="delete: true to delete.")] = False,
    ) -> dict[str, Any]:
        """List, create, change, enable/disable or delete a project's automation rules (project admins)."""
        from glasshaus.automation import service as automation
        from glasshaus.automation.schemas import RuleCreate, RuleUpdate

        async def run(ctx: ServiceContext) -> Any:
            pid = await project_id(ctx, project)
            if action == "list":
                return {"rules": await automation.list_rules(ctx, pid)}
            if action == "create":
                if rule is None:
                    raise InvalidInput("create needs rule")
                return {"rule": await automation.create_rule(ctx, pid, RuleCreate.model_validate(rule))}
            if rule_id is None:
                raise InvalidInput(f"{action} needs rule_id")
            if action == "delete":
                if not confirm:
                    current = await automation.get_rule(ctx, rule_id)
                    return {"preview": True, "would_delete": current.name}
                await automation.delete_rule(ctx, rule_id)
                return {"deleted": str(rule_id)}
            patch = RuleUpdate.model_validate(rule or {})
            if action in ("enable", "disable"):
                patch = RuleUpdate(enabled=action == "enable")
            return {"rule": await automation.update_rule(ctx, rule_id, patch)}

        scope = Scope.READ if action == "list" else Scope.PROJECTS_WRITE
        return await invoke(
            "manage_automations", scope, {"project": project, "action": action, "rule": rule}, run
        )

    @server.tool(name="test_automation", title="Dry-run an automation", annotations=READ)
    async def test_automation(project: ProjectRef, rule: dict[str, Any], task: TaskRef) -> dict[str, Any]:
        """Check whether a rule's conditions match a task and list what it would do. Changes nothing."""
        from glasshaus.automation import service as automation
        from glasshaus.automation.schemas import RuleTestRequest

        async def run(ctx: ServiceContext) -> Any:
            req = RuleTestRequest.model_validate({"rule": rule, "task": task})
            return await automation.test_rule(ctx, await project_id(ctx, project), req)

        return await invoke("test_automation", Scope.READ, {"project": project, "task": task}, run)

    @server.tool(name="run_automation", title="Run an automation now", annotations=WRITE)
    async def run_automation(rule_id: uuid.UUID, task: TaskRef | None = None) -> dict[str, Any]:
        """Trigger a rule immediately (optionally on one task). Conditions still apply."""
        from glasshaus.automation import service as automation

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            result = await automation.run_rule_now(ctx, rule_id, task)
            return {"run": result, "matched": result is not None}

        return await invoke(
            "run_automation", Scope.PROJECTS_WRITE, {"rule_id": str(rule_id), "task": task}, run
        )

    @server.tool(name="list_automation_runs", title="Automation run log", annotations=READ)
    async def list_automation_runs(
        project: ProjectRef,
        rule_id: uuid.UUID | None = None,
        status: Literal["success", "failed", "skipped"] | None = None,
        limit: int = 30,
        retry_run_id: Annotated[uuid.UUID | None, Field(description="Retry this failed run first.")] = None,
    ) -> dict[str, Any]:
        """Recent automation runs with results and errors; optionally retry a failed run."""
        from glasshaus.automation import service as automation
        from glasshaus.automation.schemas import RunStatus

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            out: dict[str, Any] = {}
            if retry_run_id:
                out["retried"] = await automation.retry_run(ctx, retry_run_id)
            out["runs"] = await automation.list_runs(
                ctx,
                await project_id(ctx, project),
                rule_id=rule_id,
                status=RunStatus(status) if status else None,
                limit=limit,
            )
            return out

        scope = Scope.PROJECTS_WRITE if retry_run_id else Scope.READ
        return await invoke("list_automation_runs", scope, {"project": project}, run)

    @server.tool(name="manage_recurring_tasks", title="Manage recurring tasks", annotations=WRITE)
    async def manage_recurring_tasks(
        project: ProjectRef,
        action: Literal["list", "create", "pause", "resume", "delete"] = "list",
        recurring_id: uuid.UUID | None = None,
        title: str | None = None,
        frequency: Literal["daily", "weekly", "monthly"] = "weekly",
        weekday: Annotated[int | None, Field(ge=0, le=6, description="weekly: 0 = Monday.")] = 0,
        day: Annotated[int | None, Field(ge=1, le=28, description="monthly: day of month.")] = None,
        hour: Annotated[int, Field(ge=0, le=23)] = 9,
        timezone: str = "UTC",
        due_in_days: int | None = None,
        assignee: str | None = None,
    ) -> dict[str, Any]:
        """List or schedule tasks that are created automatically every day, week or month."""
        from glasshaus.automation import service as automation
        from glasshaus.automation.schemas import RecurringCreate, RecurringUpdate

        async def run(ctx: ServiceContext) -> Any:
            pid = await project_id(ctx, project)
            if action == "create":
                if not title:
                    raise InvalidInput("create needs title")
                schedule: dict[str, Any] = {"frequency": frequency, "hour": hour, "timezone": timezone}
                if frequency == "weekly":
                    schedule["weekday"] = weekday if weekday is not None else 0
                if frequency == "monthly":
                    schedule["day"] = day or 1
                body = {
                    "template": {
                        "title": title,
                        "due_in_days": due_in_days,
                        "assignee_id": await user_id(ctx, assignee),
                    },
                    "schedule": schedule,
                }
                await automation.create_recurring(ctx, pid, RecurringCreate.model_validate(body))
            elif action in ("pause", "resume", "delete"):
                if recurring_id is None:
                    raise InvalidInput(f"{action} needs recurring_id")
                if action == "delete":
                    await automation.delete_recurring(ctx, recurring_id)
                else:
                    await automation.update_recurring(
                        ctx, recurring_id, RecurringUpdate(enabled=action == "resume")
                    )
            return {"recurring": await automation.list_recurring(ctx, pid)}

        scope = Scope.READ if action == "list" else Scope.PROJECTS_WRITE
        return await invoke("manage_recurring_tasks", scope, {"project": project, "action": action}, run)

    @server.tool(name="list_project_templates", title="List project templates", annotations=READ)
    async def list_project_templates() -> dict[str, Any]:
        """Saved project templates (statuses, fields, views, tasks, automations)."""
        from glasshaus.automation import templates

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            return {"templates": await templates.list_templates(ctx)}

        return await invoke("list_project_templates", Scope.READ, {}, run)

    @server.tool(name="create_project_from_template", title="Create project from template", annotations=WRITE)
    async def create_project_from_template(
        template_id: uuid.UUID,
        workspace_id: uuid.UUID,
        key: str,
        name: str,
        start_date: Annotated[
            date | None, Field(description="Task dates shift to start here (default today).")
        ] = None,
    ) -> dict[str, Any]:
        """Start a new project from a template."""
        from glasshaus.automation import templates
        from glasshaus.automation.schemas import TemplateInstantiate

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            data = TemplateInstantiate(
                workspace_id=workspace_id, key=key.upper(), name=name, start_date=start_date
            )
            return {"project": await templates.instantiate(ctx, template_id, data)}

        return await invoke(
            "create_project_from_template", Scope.PROJECTS_WRITE, {"key": key}, run, target=key
        )

    # ------------------------------------------------------------------ time tracking

    @server.tool(name="log_time", title="Log time", annotations=WRITE)
    async def log_time(
        task: TaskRef,
        minutes: Annotated[int | None, Field(ge=1, le=1440)] = None,
        duration: Annotated[
            str | None, Field(description="Alternative to minutes: '1h 30m', '1.5h', '45m'.")
        ] = None,
        spent_on: Annotated[date | None, Field(description="Default today (UTC).")] = None,
        note: str = "",
        billable: bool = False,
    ) -> dict[str, Any]:
        """Record time you spent on a task."""
        from glasshaus.timetracking import service as timetracking
        from glasshaus.timetracking.schemas import TimeEntryCreate

        total = minutes if minutes is not None else _parse_duration(duration)

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            if total is None:
                raise InvalidInput("give minutes or a duration like '1h 30m'")
            data = TimeEntryCreate(task=task, minutes=total, spent_on=spent_on, note=note, billable=billable)
            return {"entry": await timetracking.log_time(ctx, data)}

        return await invoke("log_time", Scope.TASKS_WRITE, {"task": task, "minutes": total}, run, target=task)

    @server.tool(name="list_time_entries", title="List time entries", annotations=READ)
    async def list_time_entries(
        user: Annotated[str | None, Field(description="'me', id or email.")] = None,
        project: ProjectRef | None = None,
        task: TaskRef | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Time entries you can see, newest first."""
        from glasshaus.timetracking import service as timetracking

        async def run(ctx: ServiceContext) -> Any:
            return await timetracking.list_entries(
                ctx,
                user_id=await user_id(ctx, user),
                project_id=await project_id(ctx, project) if project else None,
                task=task,
                date_from=date_from,
                date_to=date_to,
                limit=limit,
            )

        return await invoke("list_time_entries", Scope.READ, {"user": user, "project": project}, run)

    @server.tool(name="start_timer", title="Start timer", annotations=WRITE)
    async def start_timer(task: TaskRef, note: str = "") -> dict[str, Any]:
        """Start your timer on a task (one running timer per person)."""
        from glasshaus.timetracking import service as timetracking
        from glasshaus.timetracking.schemas import TimerStart

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            return {"timer": await timetracking.start_timer(ctx, TimerStart(task=task, note=note))}

        return await invoke("start_timer", Scope.TASKS_WRITE, {"task": task}, run, target=task)

    @server.tool(name="stop_timer", title="Stop timer", annotations=WRITE)
    async def stop_timer(billable: bool = False, note: str | None = None) -> dict[str, Any]:
        """Stop your running timer and log the elapsed time."""
        from glasshaus.timetracking import service as timetracking
        from glasshaus.timetracking.schemas import TimerStop

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            return {"entry": await timetracking.stop_timer(ctx, TimerStop(billable=billable, note=note))}

        return await invoke("stop_timer", Scope.TASKS_WRITE, {}, run)

    @server.tool(name="get_timesheet", title="Get timesheet", annotations=READ)
    async def get_timesheet(
        user: Annotated[str | None, Field(description="'me' (default), id or email.")] = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> dict[str, Any]:
        """A person's time per task and day (default: you, last 7 days)."""
        from glasshaus.timetracking import service as timetracking

        async def run(ctx: ServiceContext) -> Any:
            return await timetracking.timesheet(ctx, await user_id(ctx, user), date_from, date_to)

        return await invoke("get_timesheet", Scope.READ, {"user": user}, run)

    @server.tool(name="time_report", title="Time report", annotations=READ)
    async def time_report(
        date_from: date | None = None,
        date_to: date | None = None,
        project: ProjectRef | None = None,
        user: str | None = None,
    ) -> dict[str, Any]:
        """Minutes per person and project for a range (default: last 30 days)."""
        from glasshaus.timetracking import service as timetracking

        async def run(ctx: ServiceContext) -> Any:
            return await timetracking.time_report(
                ctx,
                date_from=date_from,
                date_to=date_to,
                project_id=await project_id(ctx, project) if project else None,
                user_id=await user_id(ctx, user),
            )

        return await invoke("time_report", Scope.READ, {"project": project}, run)

    # ------------------------------------------------------------------ workload and reports

    @server.tool(name="get_workload", title="Get workload", annotations=READ)
    async def get_workload(
        project: ProjectRef | None = None,
        workspace_id: uuid.UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        bucket: Literal["week", "day"] = "week",
    ) -> dict[str, Any]:
        """Planned remaining work vs capacity per person (default: 4 weeks from this Monday)."""
        from glasshaus.insights import service as insights

        async def run(ctx: ServiceContext) -> Any:
            return await insights.workload(
                ctx,
                date_from=date_from,
                date_to=date_to,
                project_id=await project_id(ctx, project) if project else None,
                workspace_id=workspace_id,
                bucket=bucket,
            )

        return await invoke("get_workload", Scope.READ, {"project": project}, run)

    @server.tool(name="project_report", title="Project report", annotations=READ)
    async def project_report(
        project: ProjectRef, date_from: date | None = None, date_to: date | None = None
    ) -> dict[str, Any]:
        """Status mix, burn-up, throughput, lead time, estimate vs actual (default: last 30 days)."""
        from glasshaus.insights import service as insights

        async def run(ctx: ServiceContext) -> Any:
            pid = await project_id(ctx, project)
            return await insights.project_report(ctx, pid, date_from=date_from, date_to=date_to)

        return await invoke("project_report", Scope.READ, {"project": project}, run, target=project)

    @server.tool(
        name="status_summary",
        title="Status summary data",
        annotations=READ,
        description=(
            "Facts for a status update on a project: health, what was completed in the last `days`, "
            "what is in progress, overdue and due soon, schedule warnings and time logged. Write the "
            "summary from these facts. " + UNTRUSTED
        ),
    )
    async def status_summary(
        project: ProjectRef, days: Annotated[int, Field(ge=1, le=90)] = 7
    ) -> dict[str, Any]:
        from glasshaus.insights import service as insights

        async def run(ctx: ServiceContext) -> Any:
            return await insights.status_summary(ctx, await project_id(ctx, project), days=days)

        return await invoke(
            "status_summary", Scope.READ, {"project": project, "days": days}, run, target=project
        )

    # ------------------------------------------------------------------ dashboards, portfolios, OKRs

    @server.tool(name="list_dashboards", title="List dashboards", annotations=READ)
    async def list_dashboards() -> dict[str, Any]:
        """Your dashboards and shared ones (widget layouts; read data with the report tools)."""
        from glasshaus.insights import service as insights

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            return {"dashboards": await insights.list_dashboards(ctx)}

        return await invoke("list_dashboards", Scope.READ, {}, run)

    # ------------------------------------------------------------------ custom reports

    report_help = (
        "A definition is {source: 'tasks'|'time', group_by: up to 2 of [tasks: project, status, "
        "status_category, priority, assignee, reporter, tag, due_week, due_month, created_week, "
        "created_month, completed_week, completed_month, cf:<select field id>; time: project, person, "
        "task, day, week, month, billable], measures: up to 6 of [tasks: count, open, done, overdue, "
        "estimate_hours, avg_age_days, avg_cycle_days, on_time_pct; time: hours, billable_hours, entries, "
        "people], filters: {project_ids, people, status_categories, priorities, tags, billable, date: "
        "{field: created|completed|due|spent, preset: last_7_days|last_30_days|last_90_days|this_month|"
        "last_month|this_quarter|this_year|next_30_days|custom, date_from, date_to}}, chart: "
        "table|bar|line|kpi, sort: {by: 'label' or a measure, descending}, limit (1-500)}."
    )

    @server.tool(name="list_reports", title="List saved reports", annotations=READ)
    async def list_reports() -> dict[str, Any]:
        """Your saved reports and those shared with you, with their definitions. Run one with
        `run_report`."""
        from glasshaus.reports import service as reports

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            return {"reports": await reports.list_reports(ctx)}

        return await invoke("list_reports", Scope.READ, {}, run)

    @server.tool(
        name="run_report",
        title="Run a report",
        annotations=READ,
        description=(
            "Run a saved report (report_id) or a report definition, with your access: you only get numbers "
            "for projects and time you can see. Optional date_preset and projects override a saved report's "
            "own range and projects (like dashboard filters). " + report_help + " " + UNTRUSTED
        ),
    )
    async def run_report(
        report_id: Annotated[uuid.UUID | None, Field(description="A saved report.")] = None,
        definition: Annotated[
            dict[str, Any] | None, Field(description="A report definition, when not using report_id.")
        ] = None,
        date_preset: Annotated[
            Literal[
                "last_7_days",
                "last_30_days",
                "last_90_days",
                "this_month",
                "last_month",
                "this_quarter",
                "this_year",
                "next_30_days",
            ]
            | None,
            Field(description="Saved reports: replace the report's date range."),
        ] = None,
        projects: Annotated[
            list[ProjectRef] | None, Field(description="Saved reports: limit to these projects.")
        ] = None,
    ) -> dict[str, Any]:
        from glasshaus.reports import service as reports
        from glasshaus.reports.schemas import DateFilter, ReportDefinition, ReportOverrides

        async def run(ctx: ServiceContext) -> Any:
            if (report_id is None) == (definition is None):
                raise InvalidInput("give either report_id or definition")
            if report_id is not None:
                overrides = None
                if date_preset or projects:
                    overrides = ReportOverrides(
                        date=DateFilter(preset=date_preset) if date_preset else None,
                        project_ids=[await project_id(ctx, p) for p in projects or []],
                    )
                return await reports.run_report(ctx, report_id, overrides)
            try:
                parsed = ReportDefinition.model_validate(definition)
            except ValueError as exc:
                raise InvalidInput(f"invalid report definition: {exc}") from None
            return await reports.run_definition(ctx, parsed)

        return await invoke(
            "run_report",
            Scope.READ,
            {"report_id": str(report_id) if report_id else None, "date_preset": date_preset},
            run,
        )

    @server.tool(
        name="manage_reports",
        title="Save, change or delete a report",
        annotations=WRITE,
        description=(
            "Save a report definition for later (and for dashboards), change one you own, or delete it "
            "(previews unless confirm=true). Check a definition with `run_report` first. " + report_help
        ),
    )
    async def manage_reports(
        action: Literal["create", "update", "delete"],
        report_id: Annotated[uuid.UUID | None, Field(description="update/delete: the report.")] = None,
        name: Annotated[str | None, Field(max_length=100)] = None,
        description: Annotated[str | None, Field(max_length=500)] = None,
        shared: Annotated[bool | None, Field(description="Visible to everyone in the organization.")] = None,
        definition: dict[str, Any] | None = None,
        confirm: Confirm = False,
    ) -> dict[str, Any]:
        from glasshaus.reports import service as reports
        from glasshaus.reports.schemas import ReportDefinition, SavedReportCreate, SavedReportUpdate

        async def run(ctx: ServiceContext) -> Any:
            try:
                parsed = ReportDefinition.model_validate(definition) if definition is not None else None
            except ValueError as exc:
                raise InvalidInput(f"invalid report definition: {exc}") from None
            if action == "create":
                if not name or parsed is None:
                    raise InvalidInput("create needs name and definition")
                return await reports.create_report(
                    ctx,
                    SavedReportCreate(
                        name=name, description=description or "", shared=bool(shared), definition=parsed
                    ),
                )
            if report_id is None:
                raise InvalidInput(f"{action} needs report_id")
            if action == "delete":
                current = await reports.get_report(ctx, report_id)
                if not confirm:
                    return {"preview": True, "would_delete": current.name}
                await reports.delete_report(ctx, report_id)
                return {"deleted": str(report_id)}
            return await reports.update_report(
                ctx,
                report_id,
                SavedReportUpdate(name=name, description=description, shared=shared, definition=parsed),
            )

        return await invoke(
            "manage_reports",
            Scope.TASKS_WRITE,
            {"action": action, "report_id": str(report_id) if report_id else None, "confirm": confirm},
            run,
        )

    @server.tool(name="get_portfolio", title="Get portfolio", annotations=READ)
    async def get_portfolio(portfolio_id: uuid.UUID | None = None) -> dict[str, Any]:
        """A portfolio with each project's health, or the list of portfolios when no id is given."""
        from glasshaus.goals import service as goals

        async def run(ctx: ServiceContext) -> Any:
            if portfolio_id is None:
                return {"portfolios": await goals.list_portfolios(ctx)}
            return await goals.get_portfolio(ctx, portfolio_id)

        return await invoke("get_portfolio", Scope.READ, {"portfolio_id": str(portfolio_id)}, run)

    @server.tool(name="list_objectives", title="List objectives (OKRs)", annotations=READ)
    async def list_objectives(
        period: Annotated[str | None, Field(description="e.g. 2026-Q4; all periods when omitted.")] = None,
    ) -> dict[str, Any]:
        """Objectives with key results, progress and confidence."""
        from glasshaus.goals import service as goals

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            return {"objectives": await goals.list_objectives(ctx, period=period)}

        return await invoke("list_objectives", Scope.READ, {"period": period}, run)

    @server.tool(name="manage_objectives", title="Create an objective", annotations=WRITE)
    async def manage_objectives(
        title: str,
        period: Annotated[str, Field(description="e.g. 2026-Q4, 2026-H1 or 2026.")],
        key_results: Annotated[
            list[dict[str, Any]],
            Field(
                description=(
                    "Each: {title, kind: metric|tasks, start_value, target_value, unit} or "
                    "{title, kind: tasks, project_id, tag?}."
                )
            ),
        ],
        description: str = "",
        parent_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Create an objective with key results (you become its owner)."""
        from glasshaus.goals import service as goals
        from glasshaus.goals.schemas import ObjectiveCreate

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            data = ObjectiveCreate.model_validate(
                {
                    "title": title,
                    "period": period,
                    "description": description,
                    "parent_id": parent_id,
                    "key_results": key_results,
                }
            )
            return {"objective": await goals.create_objective(ctx, data)}

        return await invoke(
            "manage_objectives", Scope.PROJECTS_WRITE, {"title": title, "period": period}, run
        )

    @server.tool(name="check_in_key_result", title="Check in on a key result", annotations=WRITE)
    async def check_in_key_result(
        key_result_id: uuid.UUID,
        confidence: Literal["on_track", "at_risk", "off_track"],
        value: Annotated[
            float | None, Field(description="New value (number-based key results only).")
        ] = None,
        note: str = "",
    ) -> dict[str, Any]:
        """Record progress and confidence on a key result (objective owners)."""
        from glasshaus.goals import service as goals
        from glasshaus.goals.schemas import CheckInCreate

        async def run(ctx: ServiceContext) -> dict[str, Any]:
            data = CheckInCreate(value=value, confidence=confidence, note=note)
            return {"check_in": await goals.check_in(ctx, key_result_id, data)}

        return await invoke(
            "check_in_key_result", Scope.TASKS_WRITE, {"key_result_id": str(key_result_id)}, run
        )


def _parse_duration(text: str | None) -> int | None:
    """'1h 30m', '1.5h', '90m', '90' or '1:30' -> minutes."""
    import re

    if not text:
        return None
    s = text.strip().lower()
    if m := re.fullmatch(r"(\d+):([0-5]\d)", s):
        return int(m.group(1)) * 60 + int(m.group(2))
    if s.isdigit():
        return int(s)
    m = re.fullmatch(r"(?:(\d+(?:\.\d+)?)\s*h)?\s*(?:(\d+)\s*m)?", s)
    if not m or not (m.group(1) or m.group(2)):
        return None
    total = round(float(m.group(1) or 0) * 60 + int(m.group(2) or 0))
    return total or None
