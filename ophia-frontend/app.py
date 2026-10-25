# app.py
# OPHIA — admin dashboard.
#
# Data source, chosen once per session:
#   live      OPHIA_API_URL is set: the FastAPI backend (changes are saved)
#   snapshot  ophia-frontend/snapshot.json: real exported output, the public demo
#   mock      built-in sample data (mock_data.py)
# In snapshot and mock mode every action works but only inside the browser
# session: nothing is saved and nothing reaches Google Cloud.

import html

import streamlit as st

import api_client
import evaluation_page
import ui
from mock_data import INITIAL_WORKSPACES, MENTORS, PENDING_MATCHES, generate_workspace_entity

st.set_page_config(page_title="OPHIA · Mentor matching", layout="wide")

st.markdown(ui.CSS, unsafe_allow_html=True)


# ── State ────────────────────────────────────────────────────────────────────

def mock_stats() -> dict:
    startups = {m["startup"] for m in PENDING_MATCHES} | {w["startup"] for w in INITIAL_WORKSPACES}
    return {"startups": len(startups),
            "mentors": sum(m["status"] == "Available" for m in MENTORS)}


def init_state():
    defaults = {
        "page": "dashboard",
        "workspaces": INITIAL_WORKSPACES.copy(),
        "pending_matches": PENDING_MATCHES.copy(),
        "mentors": MENTORS,
        "stats": mock_stats(),
        "last_approved_details": [],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # Load once per session (generating matches calls Gemini)
    if "data_source" not in st.session_state:
        st.session_state.data_source = "mock"
        if api_client.enabled():
            with st.spinner("Loading matches from the OPHIA backend…"):
                matches = api_client.fetch_pending_matches()
                workspaces = api_client.fetch_workspaces()
                mentors = api_client.fetch_mentors()
                stats = api_client.fetch_stats()
            if None not in (matches, workspaces, mentors, stats):
                st.session_state.pending_matches = matches
                st.session_state.workspaces = workspaces
                st.session_state.mentors = mentors
                st.session_state.stats = stats
                st.session_state.data_source = "live"
        elif (snapshot := api_client.load_snapshot()) is not None:
            for key in ("pending_matches", "workspaces", "mentors", "stats"):
                st.session_state[key] = snapshot[key]
            st.session_state.snapshot_date = snapshot["exported_at"]
            st.session_state.data_source = "snapshot"


init_state()


def live() -> bool:
    return st.session_state.data_source == "live"


def read_only() -> bool:
    """Live data without an admin key: the backend would refuse every change."""
    return live() and not api_client.API_KEY


def plain(text) -> str:
    """API text is HTML-escaped; native widgets need it unescaped."""
    return html.unescape(str(text or ""))


# ── Actions ──────────────────────────────────────────────────────────────────

def approve_matches(selected: list):
    """Creates a 90-day workspace per match (saved in live mode, session-only otherwise)."""
    if live():
        with st.spinner("Saving workspaces and queuing intro email, Drive folder and kick-off…"):
            created = api_client.approve(selected)
        if created is None:
            st.error(f"Approval failed. {api_client.last_error or ''}")
            return
        # Re-read rather than append: approval is idempotent, so a workspace
        # may already exist (e.g. approved from another tab)
        st.session_state.workspaces = api_client.fetch_workspaces() or st.session_state.workspaces
    else:
        created = [generate_workspace_entity(m["startup"], m["mentor"], m["synergy"]) for m in selected]
        st.session_state.workspaces.extend(created)

    st.session_state.last_approved_details = created
    keys = {m["key"] for m in selected}
    st.session_state.pending_matches = [m for m in st.session_state.pending_matches if m["key"] not in keys]
    st.rerun()


def reject_match(match: dict):
    if live() and not api_client.reject(match):
        st.error(f"Reject failed. {api_client.last_error or ''}")
        return
    st.session_state.pending_matches = [m for m in st.session_state.pending_matches if m["key"] != match["key"]]
    st.rerun()


def complete_milestone(index: int, day: int):
    """Live: the backend enforces order and completes the workspace after day 90.
    Otherwise the same rules are applied locally."""
    ws = st.session_state.workspaces[index]
    if live():
        updated = api_client.complete_milestone(ws["doc_id"], day)
        if updated is None:
            st.error(f"Could not update milestone. {api_client.last_error or ''}")
            return
    else:
        milestones = [dict(m, done=m["done"] or m["day"] == day) for m in ws["milestones"]]
        updated = dict(ws, milestones=milestones,
                       status="Completed" if all(m["done"] for m in milestones) else ws["status"])
    st.session_state.workspaces[index] = updated
    st.rerun()


# ── Layout ───────────────────────────────────────────────────────────────────

PAGES = [("dashboard", "Matches", "nav_dash"), ("mentors", "Mentors", "nav_mentors"),
         ("evaluation", "Evaluation", "nav_eval")]
SOURCE_LABEL = {"live": "Live data", "snapshot": "Snapshot", "mock": "Demo data"}


def render_header():
    left, right = st.columns([3, 2], vertical_alignment="center")
    with left:
        st.markdown('<div class="o-bar"><div class="o-logo">O</div><div><div class="o-name">OPHIA</div>'
                    '<div class="o-tag">Mentor matching for startup accelerator programmes</div></div></div>',
                    unsafe_allow_html=True)
    with right:
        cols = st.columns(len(PAGES) + 1, vertical_alignment="center")
        for col, (page, label, key) in zip(cols, PAGES):
            if col.button(label, key=key, use_container_width=True,
                          type="primary" if st.session_state.page == page else "tertiary"):
                st.session_state.page = page
                st.rerun()
        cols[-1].caption(SOURCE_LABEL[st.session_state.data_source])

    source = st.session_state.data_source
    if source == "snapshot":
        st.info(f"Read-only snapshot of real OPHIA output, exported {st.session_state.snapshot_date}. "
                "Startups are from the public YC dataset; mentors are AI-generated. You can approve, "
                "reject and complete milestones: changes stay in this browser tab and nothing is saved.")
    elif source == "mock":
        if api_client.enabled():
            st.warning(f"Backend unreachable, showing demo data. {api_client.last_error or ''}")
        else:
            st.caption("Demo mode: sample data, nothing is saved. "
                       "Set OPHIA_API_URL in .env to use the live backend.")
    elif read_only():
        st.caption("Read-only: showing live data. Set OPHIA_API_KEY in .env to approve, "
                   "reject and update workspaces.")


def render_match(match: dict):
    with st.container(border=True):
        pick, startup, arrow, mentor, score = st.columns([0.3, 3.2, 0.3, 3.2, 1.1], vertical_alignment="center")
        pick.checkbox(f"Select {plain(match['startup'])}", key=match["key"], label_visibility="collapsed",
                      disabled=read_only())
        startup.markdown(ui.person(match["startup"], match.get("startup_desc", "")), unsafe_allow_html=True)
        arrow.markdown('<div style="color:#8C959F;text-align:center">→</div>', unsafe_allow_html=True)
        mentor.markdown(ui.person(match["mentor"], match.get("mentor_title", "")), unsafe_allow_html=True)
        score.markdown(ui.score_badge(match["synergy"]), unsafe_allow_html=True)

        body, action = st.columns([6.5, 1.1], vertical_alignment="bottom")
        with body:
            st.write(plain(match["insight"]))
            st.markdown(ui.grade_meters(match.get("grades")) + ui.chips(match.get("tags", [])),
                        unsafe_allow_html=True)
        if action.button("Reject", key=f"reject_{match['key']}", disabled=read_only(),
                         use_container_width=True):
            reject_match(match)


def render_workspace(i: int, ws: dict):
    with st.container(border=True):
        st.markdown(ui.person(ws["startup"], f"with {plain(ws['mentor'])}"), unsafe_allow_html=True)
        st.caption(f"{ws['status']} · day {ws.get('day', 0)} of 90 · match score {ws['synergy']}")
        milestones = ws.get("milestones", [])
        if milestones:
            done = sum(m["done"] for m in milestones)
            st.progress(done / len(milestones), text=f"Milestones {done}/{len(milestones)}")
            nxt = next((m for m in milestones if not m["done"]), None)
            if nxt and ws["status"] in ("Active", "In Progress"):
                if st.button(f"Mark day {nxt['day']} done", key=f"ms_{ws.get('doc_id', i)}_{nxt['day']}",
                             disabled=read_only(), use_container_width=True):
                    complete_milestone(i, nxt["day"])


def render_dashboard():
    stats = st.session_state.stats
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Startups", stats["startups"])
    m2.metric("Mentors available", stats["mentors"])
    m3.metric("Suggested matches", len(st.session_state.pending_matches))
    m4.metric("Active workspaces", sum(w["status"] in ("Active", "In Progress") for w in st.session_state.workspaces))

    left, right = st.columns([7, 3], gap="large")
    with left:
        head, action = st.columns([3, 2], vertical_alignment="bottom")
        head.subheader("Suggested matches")
        approve_clicked = action.button("Approve selected", key="approve_btn", type="primary",
                                        disabled=read_only(), use_container_width=True)
        st.caption("Ranked by embedding similarity, graded by Gemini on domain, need and market fit, "
                   "and assigned so no mentor exceeds their monthly hours.")
        if approve_clicked:
            selected = [m for m in st.session_state.pending_matches if st.session_state.get(m["key"])]
            if selected:
                approve_matches(selected)
            else:
                st.warning("Please select at least one match before approving.")

        for ws in st.session_state.last_approved_details:
            st.success(f"Workspace created: {plain(ws['startup'])} × {plain(ws['mentor'])} "
                       f"({ws['created_at']} → {ws['lifecycle_end']}). Email: {plain(ws['email_status'])} · "
                       f"Drive: {plain(ws['drive_url'])} · Kick-off: {plain(ws['calendar_id'])}")

        if not st.session_state.pending_matches:
            st.info("No suggested matches waiting for a decision.")
        for match in st.session_state.pending_matches:
            render_match(match)

    with right:
        st.subheader("Workspaces")
        if not st.session_state.workspaces:
            st.caption("Approved matches become 90-day workspaces with milestones at days 30, 60 and 90.")
        for i, ws in enumerate(st.session_state.workspaces):
            render_workspace(i, ws)


def render_mentors():
    mentors = st.session_state.mentors
    st.subheader("Mentors")
    st.caption(f"{len(mentors)} mentors · {sum(m['status'] == 'Available' for m in mentors)} available. "
               "Capacity is monthly hours ÷ 3 hours per mentorship.")

    search, expertise, order = st.columns([2.2, 2.2, 1.2])
    query = search.text_input("Search", placeholder="Name, title, bio or expertise", key="mentor_search",
                              label_visibility="collapsed").strip().lower()
    all_tags = sorted({plain(t) for m in mentors for t in m["expertise"]}, key=str.lower)
    wanted = expertise.multiselect("Expertise", all_tags, key="mentor_filter", placeholder="Filter by expertise",
                                   label_visibility="collapsed")
    sort = order.selectbox("Sort", ["Name", "Most hours", "Available first"], key="mentor_sort",
                           label_visibility="collapsed")

    def matches(m):
        text = [plain(v).lower() for v in [m["name"], m["title"], m.get("bio", ""), *m["expertise"]]]
        tags = {plain(t) for t in m["expertise"]}
        return (not query or any(query in t for t in text)) and (not wanted or tags & set(wanted))

    shown = [m for m in mentors if matches(m)]
    key = {"Name": lambda m: plain(m["name"]).lower(),
           "Most hours": lambda m: -m.get("availability_hours", 0),
           "Available first": lambda m: (m["status"] != "Available", plain(m["name"]).lower())}[sort]
    shown.sort(key=key)

    if not shown:
        st.info("No mentors match your search.")
        return
    st.caption(f"Showing {len(shown)}")
    for row in range(0, len(shown), 3):
        cols = st.columns(3)
        for col, m in zip(cols, shown[row:row + 3]):
            col.markdown(ui.mentor_card(m), unsafe_allow_html=True)


# ── Router ───────────────────────────────────────────────────────────────────

render_header()
if st.session_state.page == "mentors":
    render_mentors()
elif st.session_state.page == "evaluation":
    evaluation_page.render()
else:
    render_dashboard()
