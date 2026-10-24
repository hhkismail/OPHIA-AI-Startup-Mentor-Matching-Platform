"""
state_machine.py — the lifecycle rules for matches and workspaces.

Pure logic, no I/O: the backend asks these functions whether a change is
allowed before it writes anything, so every rule lives (and is tested) here.

Match (an AI-suggested startup-mentor pair):

    pending ──approve──► approved   (creates a workspace)
       └─────reject───► rejected   (never suggested again)

Workspace (a 90-day mentorship created on approval):

    active ──last milestone done──► completed
       └──────────cancel──────────► cancelled

Provisioning (intro email + Drive folder + Calendar kick-off for a workspace):

    queued ──► succeeded            all three steps worked
           ├─► partial              some steps failed     ─┐
           ├─► skipped              Google not connected  ─┼─retry─► queued
           └─► failed               nothing worked        ─┘
"""

from enum import Enum


class InvalidTransition(ValueError):
    """Raised when a requested state change breaks the lifecycle rules."""


class MatchStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class WorkspaceStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ProvisioningStatus(str, Enum):
    QUEUED = "queued"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    SKIPPED = "skipped"
    FAILED = "failed"


MATCH_TRANSITIONS = {
    MatchStatus.PENDING: {MatchStatus.APPROVED, MatchStatus.REJECTED},
    MatchStatus.APPROVED: set(),
    MatchStatus.REJECTED: set(),
}

WORKSPACE_TRANSITIONS = {
    WorkspaceStatus.ACTIVE: {WorkspaceStatus.COMPLETED, WorkspaceStatus.CANCELLED},
    WorkspaceStatus.COMPLETED: set(),
    WorkspaceStatus.CANCELLED: set(),
}

PROVISIONING_TRANSITIONS = {
    ProvisioningStatus.QUEUED: {ProvisioningStatus.SUCCEEDED, ProvisioningStatus.PARTIAL,
                                ProvisioningStatus.SKIPPED, ProvisioningStatus.FAILED},
    ProvisioningStatus.SUCCEEDED: set(),
    ProvisioningStatus.PARTIAL: {ProvisioningStatus.QUEUED},
    ProvisioningStatus.SKIPPED: {ProvisioningStatus.QUEUED},
    ProvisioningStatus.FAILED: {ProvisioningStatus.QUEUED},
}

# Workspaces created before this state machine existed used "In Progress"
_LEGACY_WORKSPACE_STATUS = {"In Progress": WorkspaceStatus.ACTIVE}


def _check(table: dict, current, target, kind: str):
    if target not in table[current]:
        allowed = ", ".join(sorted(s.value for s in table[current])) or "none (final state)"
        raise InvalidTransition(
            f"{kind} cannot go from '{current.value}' to '{target.value}' (allowed: {allowed})")
    return target


def transition_match(current, target) -> MatchStatus:
    return _check(MATCH_TRANSITIONS, MatchStatus(current), MatchStatus(target), "Match")


def transition_workspace(current, target) -> WorkspaceStatus:
    return _check(WORKSPACE_TRANSITIONS, parse_workspace_status(current),
                  WorkspaceStatus(target), "Workspace")


def transition_provisioning(current, target) -> ProvisioningStatus:
    return _check(PROVISIONING_TRANSITIONS, ProvisioningStatus(current),
                  ProvisioningStatus(target), "Provisioning")


def parse_workspace_status(value) -> WorkspaceStatus:
    return _LEGACY_WORKSPACE_STATUS.get(value) or WorkspaceStatus(value)


def provisioning_outcome(email_sent: bool, drive_url, calendar_event_id) -> ProvisioningStatus:
    """Classifies the result of the three Workspace automation steps."""
    done = sum(bool(x) for x in (email_sent, drive_url, calendar_event_id))
    if done == 3:
        return ProvisioningStatus.SUCCEEDED
    return ProvisioningStatus.PARTIAL if done else ProvisioningStatus.FAILED


def complete_milestone(status, milestones: list[dict], day: int) -> tuple[list[dict], WorkspaceStatus]:
    """
    Marks the milestone for `day` done. Milestones must be completed in order,
    only while the workspace is active; finishing the last one completes the
    workspace. Returns (new milestones, new workspace status). Idempotent:
    completing an already-completed milestone changes nothing.
    """
    status = parse_workspace_status(status)
    if status != WorkspaceStatus.ACTIVE:
        raise InvalidTransition(f"Milestones can only change while the workspace is active (it is '{status.value}')")

    ordered = sorted(milestones, key=lambda m: m["day"])
    index = next((i for i, m in enumerate(ordered) if m["day"] == day), None)
    if index is None:
        raise InvalidTransition(f"Workspace has no day-{day} milestone")
    if ordered[index]["completed"]:
        return ordered, status
    unfinished = [m["day"] for m in ordered[:index] if not m["completed"]]
    if unfinished:
        raise InvalidTransition(f"Complete the day-{unfinished[0]} milestone first")

    updated = [dict(m, completed=True) if i == index else dict(m) for i, m in enumerate(ordered)]
    if all(m["completed"] for m in updated):
        status = transition_workspace(status, WorkspaceStatus.COMPLETED)
    return updated, status
