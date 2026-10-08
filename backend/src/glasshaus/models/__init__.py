"""ORM models. Every module's models are imported here so Alembic autogenerate sees them."""

from glasshaus.automation.models import AutomationRule, AutomationRun, ProjectTemplate, RecurringTask
from glasshaus.collab.models import Comment, Notification
from glasshaus.core.models import DomainEventRecord
from glasshaus.core.orm import RLS_TABLES, Base, TenantScoped, TimestampMixin
from glasshaus.fields.models import CustomField
from glasshaus.identity.models import ApiToken, AuthSession, User, Workspace, WorkspaceMember
from glasshaus.models.tenant import Tenant
from glasshaus.projects.models import Project, ProjectMember, ProjectStatus
from glasshaus.scheduling.models import Baseline, BaselineTask, TaskDependency
from glasshaus.tasks.models import Task
from glasshaus.views.models import SavedView

__all__ = [
    "RLS_TABLES",
    "ApiToken",
    "AuthSession",
    "AutomationRule",
    "AutomationRun",
    "Base",
    "Baseline",
    "BaselineTask",
    "Comment",
    "CustomField",
    "DomainEventRecord",
    "Notification",
    "Project",
    "ProjectMember",
    "ProjectStatus",
    "ProjectTemplate",
    "RecurringTask",
    "SavedView",
    "Task",
    "TaskDependency",
    "Tenant",
    "TenantScoped",
    "TimestampMixin",
    "User",
    "Workspace",
    "WorkspaceMember",
]
