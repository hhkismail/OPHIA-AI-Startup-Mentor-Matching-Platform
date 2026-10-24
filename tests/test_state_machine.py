"""Lifecycle rules, checked exhaustively: every (from, to) pair is either allowed or raises."""

import itertools

import pytest

import state_machine as sm

ALLOWED_MATCH = {("pending", "approved"), ("pending", "rejected")}
ALLOWED_WORKSPACE = {("active", "completed"), ("active", "cancelled")}
ALLOWED_PROVISIONING = {("queued", t) for t in ("succeeded", "partial", "skipped", "failed")} | \
                       {(f, "queued") for f in ("partial", "skipped", "failed")}


@pytest.mark.parametrize("enum, fn, allowed", [
    (sm.MatchStatus, sm.transition_match, ALLOWED_MATCH),
    (sm.WorkspaceStatus, sm.transition_workspace, ALLOWED_WORKSPACE),
    (sm.ProvisioningStatus, sm.transition_provisioning, ALLOWED_PROVISIONING),
])
def test_every_transition(enum, fn, allowed):
    for src, dst in itertools.product([s.value for s in enum], repeat=2):
        if (src, dst) in allowed:
            assert fn(src, dst) == enum(dst)
        else:
            with pytest.raises(sm.InvalidTransition):
                fn(src, dst)


def test_error_message_names_allowed_moves():
    with pytest.raises(sm.InvalidTransition, match="from 'approved' to 'rejected'.*final state"):
        sm.transition_match("approved", "rejected")


def test_unknown_status_is_rejected():
    with pytest.raises(ValueError):
        sm.transition_match("maybe", "approved")


def test_legacy_in_progress_workspaces_count_as_active():
    assert sm.parse_workspace_status("In Progress") == sm.WorkspaceStatus.ACTIVE
    assert sm.transition_workspace("In Progress", "cancelled") == sm.WorkspaceStatus.CANCELLED


@pytest.mark.parametrize("email, drive, cal, expected", [
    (True, "url", "ev", "succeeded"),
    (True, None, "ev", "partial"),
    (False, None, None, "failed"),
])
def test_provisioning_outcome(email, drive, cal, expected):
    assert sm.provisioning_outcome(email, drive, cal).value == expected


def milestones(*done):
    return [{"day": d, "objective": "o", "completed": d in done} for d in (30, 60, 90)]


def test_milestones_complete_in_order():
    ms, status = sm.complete_milestone("active", milestones(), 30)
    assert [m["completed"] for m in ms] == [True, False, False]
    assert status == sm.WorkspaceStatus.ACTIVE


def test_cannot_skip_a_milestone():
    with pytest.raises(sm.InvalidTransition, match="day-30 milestone first"):
        sm.complete_milestone("active", milestones(), 60)


def test_last_milestone_completes_the_workspace():
    ms, status = sm.complete_milestone("active", milestones(30, 60), 90)
    assert all(m["completed"] for m in ms)
    assert status == sm.WorkspaceStatus.COMPLETED


def test_completing_a_done_milestone_is_a_no_op():
    ms, status = sm.complete_milestone("active", milestones(30), 30)
    assert ms == milestones(30) and status == sm.WorkspaceStatus.ACTIVE


@pytest.mark.parametrize("status", ["completed", "cancelled"])
def test_milestones_frozen_once_workspace_closed(status):
    with pytest.raises(sm.InvalidTransition, match="only change while the workspace is active"):
        sm.complete_milestone(status, milestones(), 30)


def test_unknown_milestone_day():
    with pytest.raises(sm.InvalidTransition, match="no day-45 milestone"):
        sm.complete_milestone("active", milestones(), 45)


def test_complete_milestone_does_not_mutate_input():
    original = milestones()
    sm.complete_milestone("active", original, 30)
    assert original == milestones()
