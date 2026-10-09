"""First-run guidance: product tour, getting-started checklist and feature tips."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from glasshaus.core.schemas import Schema

TourState = Literal["completed", "skipped"]
ChecklistState = Literal["open", "minimized", "dismissed"]
BEACON = r"^[a-z0-9-]{1,40}$"


class Milestones(Schema):
    """Derived from what the person has actually done, so they tick themselves."""

    created_work: bool = Field(description="Created a project or a task.")
    added_collaborator: bool = Field(
        description="Assigned a task to someone else or added a member to a project they created."
    )
    set_due_date: bool = Field(description="Created a task with a due date.")
    toured: bool = Field(description="Finished the product tour.")


class OnboardingRead(Schema):
    tour: TourState | None = Field(description="null until the tour is finished or skipped.")
    tour_finished_at: datetime | None
    checklist: ChecklistState
    dismissed_tips: list[str]
    milestones: Milestones


class OnboardingUpdate(Schema):
    tour: TourState | None = None
    checklist: ChecklistState | None = None
    dismiss_tip: str | None = Field(None, pattern=BEACON, description="Hide this feature tip for good.")
    reset: bool = Field(False, description="Start over: show the tour, checklist and tips again.")
