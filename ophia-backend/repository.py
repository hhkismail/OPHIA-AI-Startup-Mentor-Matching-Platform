"""
repository.py — storage for startups, mentors, matches and workspaces.

Two implementations of the same interface:
  FirestoreRepository  — production; multi-document changes run in transactions
  InMemoryRepository   — tests (and local experiments); same rules, a lock
                         instead of transactions

Every state change goes through state_machine.py, so both enforce the same
lifecycle. Approving is idempotent: approving an approved match returns its
existing workspace instead of creating a second one.
"""

import copy
import datetime
import re
import threading
import uuid
from typing import Callable, Optional, Protocol

import state_machine as sm

MILESTONES = [
    (30, "Establish goals, align on tech stack, first check-in"),
    (60, "Mid-term review — progress audit and course correction"),
    (90, "Final evaluation and programme completion sign-off"),
]


class NotFound(KeyError):
    pass


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def match_id(startup_name: str, mentor_name: str) -> str:
    """Deterministic, so suggesting the same pair twice can't create two matches."""
    return f"{_slug(startup_name)}__{_slug(mentor_name)}"


def new_match(result: dict) -> dict:
    """A pending match document from an ai_engine result (+ display fields)."""
    return {**result, "match_id": match_id(result["startup_name"], result["mentor_name"]),
            "status": sm.MatchStatus.PENDING.value, "created_at": _now(),
            "decided_at": None, "reject_reason": None, "workspace_id": None}


def new_workspace(match: dict) -> dict:
    start = datetime.datetime.now(datetime.timezone.utc)
    return {
        "match_id": match["match_id"],
        "startup_name": match["startup_name"],
        "mentor_name": match["mentor_name"],
        "synergy_score": match["synergy"],
        "workspace_name": f"Project {match['startup_name']} × {match['mentor_name']}",
        "status": sm.WorkspaceStatus.ACTIVE.value,
        "active": True,
        "lifecycle_start": start.isoformat(),
        "lifecycle_end": (start + datetime.timedelta(days=90)).isoformat(),
        "milestones": [{"day": d, "objective": o, "completed": False} for d, o in MILESTONES],
        "provisioning_status": sm.ProvisioningStatus.QUEUED.value,
        "provisioning_errors": [],
        "drive_folder_id": None,
        "drive_folder_url": None,
        "milestone_doc_created": False,
        "calendar_event_id": None,
        "intro_email_sent": False,
    }


def normalize_workspace(doc: dict) -> dict:
    """Upgrades workspaces stored before the state machine existed."""
    doc = dict(doc)
    doc["status"] = sm.parse_workspace_status(doc.get("status", "active")).value
    doc.setdefault("provisioning_status", sm.ProvisioningStatus.QUEUED.value
                   if not doc.get("drive_folder_url") else sm.ProvisioningStatus.SUCCEEDED.value)
    doc.setdefault("provisioning_errors", [])
    # Older code only saved the folder URL once its milestone doc existed
    doc.setdefault("milestone_doc_created", bool(doc.get("drive_folder_url")))
    return doc


def _approve(match: dict, workspace_id: str) -> tuple[dict, dict]:
    """Shared approve logic: returns (updated match, new workspace)."""
    sm.transition_match(match["status"], sm.MatchStatus.APPROVED)
    workspace = new_workspace(match)
    updated = dict(match, status=sm.MatchStatus.APPROVED.value, decided_at=_now(), workspace_id=workspace_id)
    return updated, workspace


def _reject(match: dict, reason: Optional[str]) -> dict:
    sm.transition_match(match["status"], sm.MatchStatus.REJECTED)
    return dict(match, status=sm.MatchStatus.REJECTED.value, decided_at=_now(), reject_reason=reason)


class Repository(Protocol):
    def active_startups(self) -> list[dict]: ...
    def available_mentors(self) -> list[dict]: ...
    def all_startups(self) -> list[dict]: ...
    def all_mentors(self) -> list[dict]: ...
    def matches(self, status: Optional[str] = None) -> list[dict]: ...
    def add_matches(self, matches: list[dict]) -> None: ...
    def delete_pending_matches(self) -> int: ...
    def approve_match(self, match_id: str) -> tuple[dict, bool]: ...
    def reject_match(self, match_id: str, reason: Optional[str] = None) -> dict: ...
    def workspaces(self) -> list[dict]: ...
    def get_workspace(self, workspace_id: str) -> dict: ...
    def update_workspace(self, workspace_id: str, change: Callable[[dict], dict]) -> dict: ...


# ── In-memory ────────────────────────────────────────────────────────────────

class InMemoryRepository:
    def __init__(self, startups=(), mentors=()):
        self._lock = threading.RLock()
        self._startups = [dict(s) for s in startups]
        self._mentors = [dict(m) for m in mentors]
        self._matches: dict[str, dict] = {}
        self._workspaces: dict[str, dict] = {}

    def active_startups(self):
        return [copy.deepcopy(s) for s in self._startups if s.get("is_active", True)]

    def available_mentors(self):
        return [copy.deepcopy(m) for m in self._mentors if m.get("status", "Available") == "Available"]

    def all_startups(self):
        return copy.deepcopy(self._startups)

    def all_mentors(self):
        return copy.deepcopy(self._mentors)

    def matches(self, status=None):
        with self._lock:
            return [copy.deepcopy(m) for m in self._matches.values() if status in (None, m["status"])]

    def add_matches(self, matches):
        with self._lock:
            for m in matches:
                self._matches.setdefault(m["match_id"], copy.deepcopy(m))

    def delete_pending_matches(self):
        with self._lock:
            pending = [k for k, m in self._matches.items() if m["status"] == sm.MatchStatus.PENDING.value]
            for k in pending:
                del self._matches[k]
            return len(pending)

    def _match(self, match_id):
        if match_id not in self._matches:
            raise NotFound(f"No match '{match_id}'")
        return self._matches[match_id]

    def approve_match(self, match_id):
        with self._lock:
            match = self._match(match_id)
            if match["status"] == sm.MatchStatus.APPROVED.value:
                return self.get_workspace(match["workspace_id"]), False
            workspace_id = uuid.uuid4().hex
            updated, workspace = _approve(match, workspace_id)
            self._workspaces[workspace_id] = dict(workspace, doc_id=workspace_id)
            self._matches[match_id] = updated
            return copy.deepcopy(self._workspaces[workspace_id]), True

    def reject_match(self, match_id, reason=None):
        with self._lock:
            updated = _reject(self._match(match_id), reason)
            self._matches[match_id] = updated
            return copy.deepcopy(updated)

    def workspaces(self):
        with self._lock:
            return [normalize_workspace(w) for w in self._workspaces.values()]

    def get_workspace(self, workspace_id):
        with self._lock:
            if workspace_id not in self._workspaces:
                raise NotFound(f"No workspace '{workspace_id}'")
            return normalize_workspace(self._workspaces[workspace_id])

    def update_workspace(self, workspace_id, change):
        with self._lock:
            current = self.get_workspace(workspace_id)
            updated = dict(current, **change(copy.deepcopy(current)))
            self._workspaces[workspace_id] = updated
            return copy.deepcopy(updated)


# ── Firestore ────────────────────────────────────────────────────────────────

class FirestoreRepository:
    """Startups/mentors come from ophia-data/database.py; matches and
    workspaces live in the 'matches' and 'active_entities' collections."""

    def __init__(self, database_module):
        self.database = database_module

    @property
    def _db(self):
        return self.database.get_db()

    def active_startups(self):
        return self.database.get_active_startups()

    def available_mentors(self):
        return self.database.get_available_mentors()

    def all_startups(self):
        return self.database.get_all_startups()

    def all_mentors(self):
        return self.database.get_all_mentors()

    def matches(self, status=None):
        query = self._db.collection("matches")
        if status:
            query = query.where("status", "==", status)
        return [d.to_dict() for d in query.stream()]

    def add_matches(self, matches):
        from google.api_core.exceptions import AlreadyExists
        for m in matches:
            try:
                # create() refuses to overwrite, so a decided match is never reset to pending
                self._db.collection("matches").document(m["match_id"]).create(m)
            except AlreadyExists:
                pass

    def delete_pending_matches(self):
        docs = list(self._db.collection("matches").where("status", "==", "pending").stream())
        batch = self._db.batch()
        for d in docs:
            batch.delete(d.reference)
        batch.commit()
        return len(docs)

    def _run_transaction(self, fn):
        from firebase_admin import firestore
        return firestore.transactional(fn)(self._db.transaction())

    def approve_match(self, match_id):
        db = self._db

        def txn(transaction):
            match_ref = db.collection("matches").document(match_id)
            snap = match_ref.get(transaction=transaction)
            if not snap.exists:
                raise NotFound(f"No match '{match_id}'")
            match = snap.to_dict()
            if match["status"] == sm.MatchStatus.APPROVED.value:
                ws = db.collection("active_entities").document(match["workspace_id"]).get(transaction=transaction)
                return normalize_workspace(dict(ws.to_dict(), doc_id=ws.id)), False
            ws_ref = db.collection("active_entities").document()
            updated, workspace = _approve(match, ws_ref.id)
            transaction.set(ws_ref, workspace)
            transaction.set(match_ref, updated)
            return dict(workspace, doc_id=ws_ref.id), True

        return self._run_transaction(txn)

    def reject_match(self, match_id, reason=None):
        db = self._db

        def txn(transaction):
            ref = db.collection("matches").document(match_id)
            snap = ref.get(transaction=transaction)
            if not snap.exists:
                raise NotFound(f"No match '{match_id}'")
            updated = _reject(snap.to_dict(), reason)
            transaction.set(ref, updated)
            return updated

        return self._run_transaction(txn)

    def workspaces(self):
        return [normalize_workspace(dict(d.to_dict(), doc_id=d.id))
                for d in self._db.collection("active_entities").stream()]

    def get_workspace(self, workspace_id):
        snap = self._db.collection("active_entities").document(workspace_id).get()
        if not snap.exists:
            raise NotFound(f"No workspace '{workspace_id}'")
        return normalize_workspace(dict(snap.to_dict(), doc_id=snap.id))

    def update_workspace(self, workspace_id, change):
        db = self._db

        def txn(transaction):
            ref = db.collection("active_entities").document(workspace_id)
            snap = ref.get(transaction=transaction)
            if not snap.exists:
                raise NotFound(f"No workspace '{workspace_id}'")
            current = normalize_workspace(dict(snap.to_dict(), doc_id=snap.id))
            changes = change(copy.deepcopy(current))
            transaction.update(ref, changes)
            return dict(current, **changes)

        return self._run_transaction(txn)
