# Feature → API → MCP coverage matrix

Every capability is implemented once in the service layer and exposed through REST, domain events
(the source for webhooks) and MCP. MCP tools land in Phase 6; the "MCP tool" column names the tool that
will wrap each service function, and the Phase 6 conformance suite verifies this table.

| Capability | Service function | REST | Domain event(s) | MCP tool | Since |
| --- | --- | --- | --- | --- | --- |
| Server version / health | — | `GET /api/v1/version`, `/healthz`, `/readyz` | — | `server_info` ✅ | 0.1 |
| Sign in / refresh / sign out | `identity.login`, `refresh`, `logout` | `POST /api/v1/auth/{login,refresh,logout}` | — | n/a (OAuth 2.1, Phase 6) | 0.2 |
| Change password | `identity.change_password` | `POST /api/v1/auth/password` | `user.password_changed` | n/a (interactive only) | 0.2 |
| Current user | `identity.get_me` | `GET /api/v1/users/me` | — | `whoami` | 0.2 |
| List / create / update users | `identity.list_users`, `create_user`, `update_user` | `GET/POST /api/v1/users`, `PATCH /api/v1/users/{id}` | `user.created`, `user.updated` | `list_users` | 0.2 |
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
| Live updates | `realtime.to_client` (ids only, visibility-filtered) | `WS /api/v1/ws` | all events | MCP resource subscriptions (Phase 6) | 0.3 |
| Task dependencies (FS/SS/FF/SF, lag/lead) | `scheduling.list_dependencies`, `task_dependencies`, `create_dependency`, `update_dependency`, `delete_dependency` | `GET /api/v1/projects/{id}/dependencies`, `GET /api/v1/tasks/{ref}/dependencies`, `POST /api/v1/dependencies`, `PATCH/DELETE /api/v1/dependencies/{id}` | `dependency.created`, `dependency.updated`, `dependency.deleted` | `manage_dependencies` | 0.4 |
| Critical path | `scheduling.get_schedule` | `GET /api/v1/projects/{id}/schedule` | — | `get_schedule` | 0.4 |
| Auto-rescheduling | `scheduling.propagate_from` (on date/dependency changes when `auto_schedule`), `reschedule` | `PATCH /api/v1/projects/{id}` (`auto_schedule`), `POST /api/v1/projects/{id}/reschedule?dry_run=` | `task.updated` (`reason: auto_schedule`/`reschedule`) | `reschedule_project` (confirm) | 0.4 |
| Baselines and variance | `scheduling.list_baselines`, `create_baseline`, `delete_baseline`, `baseline_variance` | `GET/POST /api/v1/projects/{id}/baselines`, `GET /api/v1/baselines/{id}/variance`, `DELETE /api/v1/baselines/{id}` | `baseline.created`, `baseline.deleted` | `manage_baselines` | 0.4 |
| Slip warnings | `scheduling.schedule_warnings` | `GET /api/v1/projects/{id}/schedule/warnings` | — | `get_schedule` (warnings) | 0.4 |
| Calendar window | `tasks.list_tasks` (`scheduled_from`, `scheduled_to`) | `GET /api/v1/tasks?scheduled_from=&scheduled_to=` | — | `search_tasks` | 0.4 |
