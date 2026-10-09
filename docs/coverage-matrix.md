# Feature → API → MCP coverage matrix

Every capability is implemented once in the service layer and exposed through REST, domain events
(the source for webhooks) and MCP. Each MCP tool is a thin adapter over the same service function, so
RBAC, validation and events are identical. `tests/test_mcp_tools.py::test_coverage_matrix_matches_server`
checks that every tool named here exists and that every registered tool is listed.

MCP resources (read-only): `glasshaus://projects`, `glasshaus://projects/{key}`,
`glasshaus://projects/{key}/report`, `glasshaus://projects/{key}/status`, `glasshaus://tasks/{ref}`,
`glasshaus://views/{view_id}`, `glasshaus://dashboards/{dashboard_id}`.
MCP prompts: `weekly_status`, `risk_review`, `sprint_planning`, `standup_digest`.

| Capability | Service function | REST | Domain event(s) | MCP tool | Since |
| --- | --- | --- | --- | --- | --- |
| Server version / health | — | `GET /api/v1/version`, `/healthz`, `/readyz` | — | `server_info` | 0.1 |
| Sign in / refresh / sign out | `identity.login`, `refresh`, `logout` | `POST /api/v1/auth/{login,refresh,logout}` | — | n/a (MCP clients use OAuth 2.1 or an API token) | 0.2 |
| Change password | `identity.change_password` | `POST /api/v1/auth/password` | `user.password_changed` | n/a (interactive only) | 0.2 |
| Current user | `identity.get_me` | `GET /api/v1/users/me` | — | `whoami` | 0.2 |
| List / create / update users | `identity.list_users`, `create_user`, `update_user` | `GET/POST /api/v1/users`, `PATCH /api/v1/users/{id}` | `user.created`, `user.updated` | `list_users`, `manage_users` | 0.2 |
| API tokens | `identity.create_api_token`, `list_api_tokens`, `revoke_api_token` | `GET/POST /api/v1/tokens`, `DELETE /api/v1/tokens/{id}` | `api_token.created`, `api_token.revoked` | n/a (credentials) | 0.2 |
| Workspaces | `identity.list_workspaces`, `get_workspace`, `create_workspace`, `update_workspace` | `GET/POST /api/v1/workspaces`, `GET/PATCH /api/v1/workspaces/{id}` | `workspace.created`, `workspace.updated` | `list_workspaces` | 0.2 |
| Workspace members | `identity.list_workspace_members`, `set_workspace_member`, `remove_workspace_member` | `GET/PUT /api/v1/workspaces/{id}/members`, `DELETE …/members/{user_id}` | `workspace.member_set`, `workspace.member_removed` | `set_workspace_member` | 0.2 |
| Projects | `projects.list_projects`, `get_project`, `get_project_by_key`, `create_project`, `update_project` | `GET/POST /api/v1/projects`, `GET/PATCH /api/v1/projects/{id}`, `GET /api/v1/projects/by-key/{key}` | `project.created`, `project.updated` | `search_projects`, `get_project`, `create_project`, `update_project` | 0.2 |
| Delete project (dry-run first) | `projects.delete_project` | `DELETE /api/v1/projects/{id}?dry_run=` | `project.deleted` | `delete_project` (confirm) | 0.2 |
| Project members | `projects.list_project_members`, `set_project_member`, `remove_project_member` | `GET/PUT /api/v1/projects/{id}/members`, `DELETE …/members/{user_id}` | `project.member_set`, `project.member_removed` | `set_project_member` | 0.2 |
| Workflow statuses | `projects.list_statuses`, `create_status`, `update_status`, `delete_status` | `GET/POST /api/v1/projects/{id}/statuses`, `PATCH/DELETE …/statuses/{status_id}` | `status.created`, `status.updated`, `status.deleted` | `manage_statuses` | 0.2 |
| Search / list tasks | `tasks.list_tasks` | `GET /api/v1/tasks` | — | `search_tasks` | 0.2 |
| Get task (id or `KEY-123`) | `tasks.get_task`, `resolve_ref` | `GET /api/v1/tasks/{ref}` | — | `get_task` | 0.2 |
| Create task | `tasks.create_task` | `POST /api/v1/tasks` | `task.created` | `create_task` | 0.2 |
| Update task / change status | `tasks.update_task` | `PATCH /api/v1/tasks/{ref}` (`If-Match`) | `task.updated` | `update_task`, `change_status` | 0.2 |
| Bulk update | `tasks.bulk_update` | `POST /api/v1/tasks/bulk-update` | `task.updated` (each) | `bulk_update_tasks` | 0.2 |
| Delete tasks (dry-run first) | `tasks.delete_tasks` | `POST /api/v1/tasks/bulk-delete?dry_run=`, `DELETE /api/v1/tasks/{ref}` | `task.deleted` | `delete_tasks` (confirm) | 0.2 |
| Restore task | `tasks.restore_task` | `POST /api/v1/tasks/{ref}/restore` | `task.restored` | `restore_task` | 0.2 |
| My permissions on a task | `tasks.can` | `GET /api/v1/tasks/{ref}/permissions` | — | `get_task` (included) | 0.2 |
| Custom fields (define) | `fields.list_fields`, `create_field`, `update_field`, `delete_field` | `GET/POST /api/v1/projects/{id}/fields`, `PATCH/DELETE …/fields/{field_id}` | `field.created`, `field.updated`, `field.deleted` | `manage_custom_fields` | 0.3 |
| Custom field values | `tasks.create_task` / `update_task` (`custom_fields`) | `POST /api/v1/tasks`, `PATCH /api/v1/tasks/{ref}` | `task.created`, `task.updated` | `create_task`, `update_task` | 0.3 |
| Filter / sort by custom field | `tasks.list_tasks` (`cf`, `sort_field`) | `GET /api/v1/tasks?cf=<id>=<value>&sort_field=<id>` | — | `search_tasks` | 0.3 |
| Comments with @mentions | `collab.list_comments`, `create_comment`, `update_comment`, `delete_comment` | `GET/POST /api/v1/tasks/{ref}/comments`, `PATCH/DELETE /api/v1/comments/{id}` | `comment.created`, `comment.updated`, `comment.deleted` | `post_comment`, `list_comments` | 0.3 |
| Notifications (in-app) | `collab.list_notifications`, `unread_count`, `mark_read`; created by event consumers | `GET /api/v1/notifications`, `GET …/unread-count`, `POST …/read` | consumes `comment.*`, `task.created`, `task.updated` | `list_notifications` | 0.3 |
| Activity feed | `collab.activity` | `GET /api/v1/activity?task=&project_id=` | (reads the event log) | `get_activity` | 0.3 |
| Saved views | `views.list_views`, `create_view`, `get_view`, `update_view`, `delete_view` | `GET/POST /api/v1/projects/{id}/views`, `GET/PATCH/DELETE /api/v1/views/{id}` | `view.created`, `view.updated`, `view.deleted` (shared views) | `list_views`, resource `glasshaus://views/{id}` | 0.3 |
| Run a saved view | `views.run_view` | `GET /api/v1/views/{id}/tasks` | — | `run_view` | 0.3 |
| Live updates | `realtime.to_client` (ids only, visibility-filtered) | `WS /api/v1/ws` | all events | n/a (poll `get_activity`; resource subscriptions are not yet offered) | 0.3 |
| Task dependencies (FS/SS/FF/SF, lag/lead) | `scheduling.list_dependencies`, `task_dependencies`, `create_dependency`, `update_dependency`, `delete_dependency` | `GET /api/v1/projects/{id}/dependencies`, `GET /api/v1/tasks/{ref}/dependencies`, `POST /api/v1/dependencies`, `PATCH/DELETE /api/v1/dependencies/{id}` | `dependency.created`, `dependency.updated`, `dependency.deleted` | `manage_dependencies` | 0.4 |
| Critical path | `scheduling.get_schedule` | `GET /api/v1/projects/{id}/schedule` | — | `get_schedule` | 0.4 |
| Auto-rescheduling | `scheduling.propagate_from` (on date/dependency changes when `auto_schedule`), `reschedule` | `PATCH /api/v1/projects/{id}` (`auto_schedule`), `POST /api/v1/projects/{id}/reschedule?dry_run=` | `task.updated` (`reason: auto_schedule`/`reschedule`) | `reschedule_project` (confirm) | 0.4 |
| Baselines and variance | `scheduling.list_baselines`, `create_baseline`, `delete_baseline`, `baseline_variance` | `GET/POST /api/v1/projects/{id}/baselines`, `GET /api/v1/baselines/{id}/variance`, `DELETE /api/v1/baselines/{id}` | `baseline.created`, `baseline.deleted` | `manage_baselines` | 0.4 |
| Slip warnings | `scheduling.schedule_warnings` | `GET /api/v1/projects/{id}/schedule/warnings` | — | `get_schedule` (warnings) | 0.4 |
| Calendar window | `tasks.list_tasks` (`scheduled_from`, `scheduled_to`) | `GET /api/v1/tasks?scheduled_from=&scheduled_to=` | — | `search_tasks` | 0.4 |
| Automation rules | `automation.list_rules`, `get_rule`, `create_rule`, `update_rule`, `delete_rule`, `rotate_secret` | `GET/POST /api/v1/projects/{id}/automation-rules`, `GET/PATCH/DELETE /api/v1/automation-rules/{id}`, `POST …/{id}/rotate-secret` | rules react to `task.created`, `task.updated`, `comment.created`; their changes emit normal events (`actor.method = automation`) | `manage_automations` | 0.5 |
| Dry-run a rule | `automation.test_rule` | `POST /api/v1/projects/{id}/automation-rules/test` | — | `test_automation` | 0.5 |
| Run log and retry | `automation.list_runs`, `retry_run` | `GET /api/v1/projects/{id}/automation-runs`, `POST /api/v1/automation-runs/{id}/retry` | — | `list_automation_runs` (also retries) | 0.5 |
| Due-soon and scheduled rules | `automation.handlers.run_due_soon_rules`, `run_scheduled_rules` (worker cron) | — | — | n/a (runs in the worker) | 0.5 |
| Outbound webhooks (signed) | `automation.webhooks.send` (rule action) | — | — | n/a (rule action) | 0.5 |
| Recurring tasks | `automation.list_recurring`, `create_recurring`, `update_recurring`, `delete_recurring`; `run_recurring_tasks` (cron) | `GET/POST /api/v1/projects/{id}/recurring-tasks`, `PATCH/DELETE /api/v1/recurring-tasks/{id}` | `task.created` (per occurrence) | `manage_recurring_tasks` | 0.5 |
| Project templates | `templates.list_templates`, `get_template`, `create_template`, `delete_template`, `instantiate` | `GET/POST /api/v1/project-templates`, `GET/DELETE /api/v1/project-templates/{id}`, `POST …/{id}/instantiate` | `project.created`, `task.created`, … | `create_project_from_template` | 0.5 |
| Time entries | `timetracking.log_time`, `list_entries`, `update_entry`, `delete_entry` | `GET/POST /api/v1/time-entries`, `PATCH/DELETE /api/v1/time-entries/{id}` | `time.logged`, `time.updated`, `time.deleted` | `log_time`, `list_time_entries` | 0.6 |
| Timer | `timetracking.get_timer`, `start_timer`, `stop_timer`, `discard_timer` | `GET/POST/DELETE /api/v1/timer`, `POST /api/v1/timer/stop` | `time.logged` (on stop) | `start_timer`, `stop_timer` | 0.6 |
| Timesheets (per person) | `timetracking.timesheet` | `GET /api/v1/timesheets?user_id=&date_from=&date_to=` | — | `get_timesheet` | 0.6 |
| Time report and CSV export | `timetracking.time_report`, `export_csv` | `GET /api/v1/reports/time`, `GET /api/v1/time-entries/export` | — | `time_report` | 0.6 |
| Workload and capacity | `insights.workload`; capacity via `identity.update_user` | `GET /api/v1/workload`, `PATCH /api/v1/users/{id}` (`capacity_minutes`, `working_days`) | `user.updated` | `get_workload` | 0.6 |
| Project report and health | `insights.project_report`, `get_project_health` | `GET /api/v1/projects/{id}/report`, `GET /api/v1/projects/{id}/health` | — | `project_report` | 0.6 |
| Task export (CSV) | `insights.export_tasks_csv` | `GET /api/v1/projects/{id}/tasks/export` | — | n/a (file download) | 0.6 |
| Dashboards | `insights.list_dashboards`, `get_dashboard`, `create_dashboard`, `update_dashboard`, `delete_dashboard` | `GET/POST /api/v1/dashboards`, `GET/PATCH/DELETE /api/v1/dashboards/{id}` | — | `list_dashboards` | 0.6 |
| Custom reports (saved, run, CSV) | `reports.list_reports`, `get_report`, `create_report`, `update_report`, `delete_report`, `engine.run` | `GET/POST /api/v1/reports`, `GET/PATCH/DELETE /api/v1/reports/{id}`, `POST /api/v1/reports/run`, `POST /api/v1/reports/{id}/run`, `GET /api/v1/reports/{id}/export` | — | `list_reports`; `run_report`; `manage_reports` (delete confirms) | 0.13 |
| Portfolios | `goals.list_portfolios`, `get_portfolio`, `create_portfolio`, `update_portfolio`, `delete_portfolio` | `GET/POST /api/v1/portfolios`, `GET/PATCH/DELETE /api/v1/portfolios/{id}` | — | `get_portfolio` | 0.6 |
| OKRs | `goals.list_objectives`, `get_objective`, `create_objective`, `update_objective`, `delete_objective`, `add_key_result`, `update_key_result`, `delete_key_result` | `GET/POST /api/v1/objectives`, `GET/PATCH/DELETE /api/v1/objectives/{id}`, `POST …/{id}/key-results`, `PATCH/DELETE /api/v1/key-results/{id}` | — | `list_objectives`, `manage_objectives` | 0.6 |
| OKR check-ins | `goals.check_in`, `list_check_ins` | `GET/POST /api/v1/key-results/{id}/check-ins` | — | `check_in_key_result` | 0.6 |
| Run a rule now | `automation.run_rule_now` | `POST /api/v1/automation-rules/{id}/run` | the rule's actions' events | `run_automation` | 0.7 |
| Status summary data | `insights.status_summary` | `GET /api/v1/projects/{id}/status-summary` | — | `status_summary`, resource `glasshaus://projects/{key}/status` | 0.7 |
| Project templates (list) | `templates.list_templates` | `GET /api/v1/project-templates` | — | `list_project_templates` | 0.7 |
| OAuth consent (MCP clients) | `oauth.get_consent`, `decide` | `GET/POST /api/v1/oauth/requests/{id}`; MCP server `/authorize`, `/token`, `/register`, `/revoke` | — | n/a (the OAuth flow itself) | 0.7 |
| Connected apps | `oauth.list_connected_apps`, `revoke_app` | `GET /api/v1/oauth/apps`, `DELETE /api/v1/oauth/apps/{id}` | — | n/a (credentials) | 0.7 |
| Audit log (every MCP call) | `audit.record`, `list_entries` | `GET /api/v1/audit-log` | — | `get_audit_log` | 0.7 |
| Deactivate / reactivate people (ends sessions) | `identity.update_user` (`is_active`), `governance.revoke_user_sessions` | `PATCH /api/v1/users/{id}` | `user.updated` | `manage_users` (confirm) | 0.8 |
| Admin password reset, sign out everywhere | `governance.reset_password`, `sign_out_everywhere` | `POST /api/v1/admin/users/{id}/password`, `POST …/sessions/revoke` | `user.password_reset`, `user.signed_out` | n/a (credentials) | 0.8 |
| Retention settings and purge | `governance.get_settings`, `update_settings`, `apply_retention` (worker, nightly) | `GET/PATCH /api/v1/admin/settings` | `org.settings_updated` | `get_org_settings`, `update_org_settings` (confirm) | 0.8 |
| Organization data export | `governance.export_organization` | `GET /api/v1/admin/export` (zip) | `org.exported` | n/a (file download, browser session only) | 0.8 |
| Full audit trail | `audit.handlers.record_event` (every domain event), `audit.record_raw` (sign-ins, SSO, provisioning) | `GET /api/v1/audit-log?action=&actor_id=&outcome=&before=` | consumes all events | `get_audit_log` | 0.8 |
| Single sign-on (OIDC, SAML) | `sso.service.*`, `sso.oidc`, `sso.saml` | `GET/POST/PATCH/DELETE /api/v1/admin/sso-providers`, `/api/v1/auth/sso/…` | `sso.provider_*` | n/a (credentials, browser flow) | 0.8 |
| SCIM 2.0 provisioning | `scim.service.*` | `/scim/v2/Users`, `/scim/v2/Groups`; tokens `GET/POST/DELETE /api/v1/admin/scim-tokens` | `user.*`, `workspace.*`, `scim.token_*` | n/a (machine provisioning) | 0.8 |
| Integrations: Slack, Teams, signed webhooks | `integrations.service.*`, `integrations.delivery` (event consumer, retries) | `GET/POST/PATCH/DELETE /api/v1/integrations`, `POST …/{id}/test`, `GET …/{id}/deliveries` | `integration.*`; sends subscribed events | `manage_integrations` (create in the app: secrets) | 0.8 |
| Integrations: GitHub / GitLab | `integrations.service.handle_inbound` | `POST /api/v1/integrations/{id}/inbound` (signed) | `comment.created`, `task.updated` | `manage_integrations` | 0.8 |
| Email-to-task (IMAP) | `integrations.email.poll_all` (worker, every 2 min) | configured via `/api/v1/integrations` | `task.created` | `manage_integrations` | 0.8 |
| Calendar feed (Google, Microsoft 365, Apple) | `integrations.service.calendar_ics`, `reset_calendar_feed` | `GET/POST/DELETE /api/v1/calendar-feed`, `GET /api/v1/calendar/{token}.ics` | — | n/a (secret URL) | 0.8 |
| AI assistant status and switch | `ai.get_status`; `governance.update_settings` (`ai_enabled`, `ai_features`) | `GET /api/v1/ai/status`; `PATCH /api/v1/admin/settings` | `org.settings_updated` | `ai_status`; `update_org_settings` (confirm) | 0.9 |
| AI status update (written from the status summary) | `ai.status_report` | `POST /api/v1/ai/projects/{id}/status-report` | — (audited as `ai.summaries`) | `ai_status_report` | 0.9 |
| AI task drafting (proposals only) | `ai.draft_tasks` | `POST /api/v1/ai/projects/{id}/draft-tasks` | — (audited as `ai.drafting`) | `ai_draft_tasks` (then `create_task`) | 0.9 |
| AI risk flags | `ai.flag_risks` | `POST /api/v1/ai/projects/{id}/risks` | — (audited as `ai.risks`) | `ai_flag_risks` | 0.9 |
| Natural-language task search | `ai.search` (question → `TaskQuery` → `tasks.list_tasks`) | `POST /api/v1/ai/search` | — (audited as `ai.search`) | `ai_search_tasks` | 0.9 |
| Questions about reports (question → report definition or saved report → run → answer) | `ai.ask_reports` | `POST /api/v1/ai/reports` | — (audited as `ai.reports`) | `ai_ask_reports` | 0.13 |
