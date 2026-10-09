"""ORM models. Every module's models are imported here so Alembic autogenerate sees them."""

from glasshaus.audit.models import AuditEntry
from glasshaus.automation.models import AutomationRule, AutomationRun, ProjectTemplate, RecurringTask
from glasshaus.collab.models import Comment, Notification
from glasshaus.core.models import DomainEventRecord
from glasshaus.core.orm import RLS_TABLES, Base, TenantScoped, TimestampMixin
from glasshaus.fields.models import CustomField
from glasshaus.goals.models import CheckIn, KeyResult, Objective, Portfolio, PortfolioProject
from glasshaus.governance.models import OrgSettings
from glasshaus.identity.models import ApiToken, AuthSession, User, Workspace, WorkspaceMember
from glasshaus.insights.models import Dashboard
from glasshaus.integrations.models import CalendarFeed, Integration, IntegrationDelivery
from glasshaus.models.tenant import Tenant
from glasshaus.oauth.models import OAuthClient, OAuthGrant, OAuthRequest
from glasshaus.projects.models import Project, ProjectMember, ProjectStatus
from glasshaus.reports.models import ReportSubscription, SavedReport
from glasshaus.scheduling.models import Baseline, BaselineTask, TaskDependency
from glasshaus.scim.models import ScimToken
from glasshaus.sso.models import IdentityProvider, UserIdentity
from glasshaus.tasks.models import Task
from glasshaus.timetracking.models import RunningTimer, TimeEntry
from glasshaus.views.models import SavedView

__all__ = [
    "RLS_TABLES",
    "ApiToken",
    "AuditEntry",
    "AuthSession",
    "AutomationRule",
    "AutomationRun",
    "Base",
    "Baseline",
    "BaselineTask",
    "CalendarFeed",
    "CheckIn",
    "Comment",
    "CustomField",
    "Dashboard",
    "DomainEventRecord",
    "IdentityProvider",
    "Integration",
    "IntegrationDelivery",
    "KeyResult",
    "Notification",
    "OAuthClient",
    "OAuthGrant",
    "OAuthRequest",
    "Objective",
    "OrgSettings",
    "Portfolio",
    "PortfolioProject",
    "Project",
    "ProjectMember",
    "ProjectStatus",
    "ProjectTemplate",
    "RecurringTask",
    "ReportSubscription",
    "RunningTimer",
    "SavedReport",
    "SavedView",
    "ScimToken",
    "Task",
    "TaskDependency",
    "Tenant",
    "TenantScoped",
    "TimeEntry",
    "TimestampMixin",
    "User",
    "UserIdentity",
    "Workspace",
    "WorkspaceMember",
]
