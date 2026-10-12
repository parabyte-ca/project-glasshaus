# Microsoft Teams & M365 Copilot Agent Guide

Project Glasshaus provides a Microsoft 365 Copilot declarative agent designed for Microsoft Teams and Microsoft 365. Powered by the Glasshaus Model Context Protocol (MCP) server, it allows team members, project managers, and executives to plan, track, and manage projects directly from conversational Teams chats and channels.

---

## Capabilities by Persona

The agent adapts to different project roles, providing tailored tools and responses.

### 1. Team Members: Daily Focus & Time Tracking
Team members can track time, inspect timesheets, and manage daily priorities without switching context into the web UI:

* **Active Timers**:
  * *"Start a timer on task WEB-12."*
  * *"Stop my active timer and add a note 'Refactored auth middleware'."*
* **Direct Time Logging**:
  * *"Log 1.5 hours to WEB-45 for code review."*
  * *"Log 45 minutes to CORE-10 with note 'Customer bug triage' dated yesterday."*
* **Timesheet & Hours Summary**:
  * *"What is my timesheet breakdown for this week?"*
  * *"How many hours have I logged so far this month?"*
* **Daily Priorities & Standup Prep**:
  * *"What tasks are assigned to me and due this week?"*
  * *"What is blocking my in-progress tasks?"*
  * *"Summarize what I completed yesterday and what I'm working on today for standup."*

### 2. Project Managers: Delivery, Scheduling & Capacity
Project managers gain conversational command over project schedules, critical paths, and team workloads:

* **Status Reports & Digests**:
  * *"Write this week's status update and risk summary for project WEB."*
  * *"What tasks in project CORE were completed this past week?"*
* **Critical Path & Schedule Impact**:
  * *"Which tasks in project WEB are on the critical path or overdue?"*
  * *"If task WEB-14 slips by 4 days, what downstream milestones and deliverables are impacted?"*
* **Workload & Capacity Balancing**:
  * *"Show team workload and capacity balance across active projects."*
  * *"Who on the team has bandwidth to take on a 20-hour task next sprint?"*
  * *"Are any team members currently over-allocated?"*
* **Meeting Action Items**:
  * *"Here are the meeting notes from today's sprint review: [paste notes]. Extract action items and draft tasks for project WEB."*

### 3. Executives & Leadership: Portfolio, OKRs & Burn
Executives and portfolio leads can inspect cross-cutting metrics and strategic progress:

* **Portfolio Health Rollup**:
  * *"Summarize portfolio health across all active projects."*
  * *"Which projects are marked Amber or Red, and what are their primary risk factors?"*
* **Strategic OKRs & Goal Tracking**:
  * *"What is our current progress toward Q3 strategic objectives?"*
  * *"List all key results associated with project MOBILE and their latest check-ins."*
* **Hours & Budget Burn Rate**:
  * *"Compare planned versus actual hours logged across Q3 initiatives."*
  * *"What is the burn rate and projected variance for project WEB?"*

---

## Security & Safety Guardrails

The Glasshaus Teams agent enforces strict security policies at the protocol and runtime levels:

1. **Role-Based Access Control (RBAC)**:
   The agent operates under the authenticated user's credentials and permissions. A user cannot view or modify projects, tasks, or financial reports that they cannot access in the Glasshaus web interface.
2. **Untrusted Content Isolation**:
   Task titles, descriptions, and user comments are treated strictly as untrusted data. The agent summarizes and displays them but never follows instructions embedded within them, mitigating prompt injection risks.
3. **Preview-First for Destructive Actions**:
   Destructive or modifying tools (`delete_tasks`, `delete_project`, `bulk_update_tasks`, `reschedule_project`) generate a dry-run preview first. The agent presents the proposed changes and requires explicit user confirmation before repeating the call with `confirm=true`.
4. **Full Auditability**:
   Every tool execution initiated through Microsoft Teams is recorded in the Glasshaus audit trail (`/api/v1/audit-log`) with the authenticated user ID, client identifier, timestamp, and parameter payload.

---

## Authentication & Identity

The agent integrates with Glasshaus using **OAuth 2.1** with PKCE:

* **Entra ID UPN Resolution**:
  When users interact with the agent in Microsoft Teams, Microsoft 365 Copilot passes the user's authenticated Entra ID identity (UPN / email). When directory sync (SCIM or Microsoft Graph) is enabled in Glasshaus, users are automatically matched to their Glasshaus accounts.
* **OAuth Registration**:
  Register an OAuth 2.0 application in the Teams Developer Portal pointing to the Glasshaus authorization server:
  * Authorization Endpoint: `https://mcp.glasshaus.example.com/authorize`
  * Token Endpoint: `https://mcp.glasshaus.example.com/token`
  * Discovery: `https://mcp.glasshaus.example.com/.well-known/oauth-authorization-server`

---

## Package & Deployment

The declarative agent is defined in [`docs/integrations/m365/`](m365/):

1. **Agent Manifest (`declarativeAgent.json`)**: Configures instructions, role guidelines, and starter prompts.
2. **MCP Plugin (`glasshaus-mcp-plugin.json`)**: Connects Copilot to the remote Glasshaus MCP server (`/mcp`) with dynamic tool discovery.
3. **Packaging with Teams Toolkit**:
   Create a Teams app package (`.zip`) containing:
   * `manifest.json` (Teams application manifest with Copilot declarative agent definition)
   * `declarativeAgent.json`
   * `glasshaus-mcp-plugin.json`
   * `color.png` (192x192 px app icon)
   * `outline.png` (32x32 px outline icon)
4. **Tenant Sideloading**:
   Upload the package in the Microsoft Teams Developer Portal or deploy via the Microsoft 365 Admin Center for organizational distribution.

---

## Roadmap: Teams Bot with Interactive Adaptive Cards (Phase 30)

As a planned follow-up (Roadmap Phase 30), Project Glasshaus will complement conversational Copilot interactions with a native Teams Bot powered by interactive Adaptive Cards:
* **One-Click Timers**: Interactive cards in 1:1 chats with direct *Start Timer* / *Stop Timer* action buttons.
* **Quick Log Inputs**: In-line text & dropdown inputs to log time against recent tasks without typing prompts.
* **Timesheet Approval Cards**: Channel cards summarizing weekly hours with one-click *Approve* or *Flag* actions for managers.
