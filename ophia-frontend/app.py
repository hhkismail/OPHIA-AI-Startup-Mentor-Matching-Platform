# app.py
# OPHIA — Admin dashboard
# Uses the live backend when OPHIA_API_URL is set in the repo-root .env;
# otherwise (or if the backend is down) runs on the mock data in mock_data.py.

import streamlit as st
import time
import random
import api_client
from mock_data import (
    PENDING_MATCHES,
    INITIAL_WORKSPACES,
    INITIAL_CHECKINS,
    MENTORS,
    SYNERGY_TREND,
    PIPELINE_STEPS,
    generate_workspace_entity,
)

st.set_page_config(page_title="OPHIA — Ophia Orchestrator", layout="wide")


# ══════════════════════════════════════════════════════════════════════
# SESSION STATE INITIALISATION
# ══════════════════════════════════════════════════════════════════════
def init_state():
    defaults = {
        "page": "dashboard",
        "approved": False,
        "contact_submitted": False,
        "propose_submitted": None,
        "approve_running": False,
        "approve_done": False,
        "approved_entities": [],          # stores newly approved workspace dicts
        "workspaces": INITIAL_WORKSPACES.copy(),
        "checkins": INITIAL_CHECKINS.copy(),
        "pending_matches": PENDING_MATCHES.copy(),
        "rejected_keys": [],              # keys of rejected matches
        "last_approved_details": [],      # shown in the success card
        "pending_proposed": [],           # mentor proposals from mentors page
        "total_startups": 124,
        "total_mentors": 45,
        "active_programmes": 8,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # Load live data once per session (generating matches calls Gemini)
    if "data_source" not in st.session_state:
        st.session_state.data_source = "mock"
        if api_client.enabled():
            with st.spinner("Loading live matches from the OPHIA backend…"):
                matches = api_client.fetch_pending_matches()
                workspaces = api_client.fetch_workspaces()
            if matches is not None and workspaces is not None:
                st.session_state.pending_matches = matches
                st.session_state.workspaces = workspaces
                st.session_state.checkins = []
                st.session_state.data_source = "live"

init_state()


# ══════════════════════════════════════════════════════════════════════
# GLOBAL CSS
# ══════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;700;800&family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap');

html, body, [class*="css"] { font-family: 'Plus Jakarta Sans', sans-serif !important; }

.stApp {
    background: radial-gradient(circle at 90% 10%, #f2f4e8 0%, #f8f9f3 55%, #ffffff 100%) !important;
    color: #1c2b24 !important;
}

#MainMenu, footer, header, .stDeployButton { visibility: hidden; display: none; }

.block-container {
    padding: 0 2.5rem 3rem 2.5rem !important;
    max-width: 100% !important;
}

/* ── TOPBAR ── */
.topbar-wrapper {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1.1rem 0 0.9rem 0;
    border-bottom: 1px solid rgba(28,43,36,0.1);
    margin-bottom: 1.5rem;
}
div[data-testid="stHorizontalBlock"] div.stButton > button {
    background: transparent !important;
    color: #5d6e65 !important;
    border: none !important;
    box-shadow: none !important;
    padding: 0px !important;
    font-size: 0.88rem !important;
    font-weight: 400 !important;
    font-family: 'Plus Jakarta Sans', sans-serif !important;
    border-radius: 0px !important;
    width: auto !important;
    transition: color 0.2s;
}
div[data-testid="stHorizontalBlock"] div.stButton > button:hover {
    color: #0b2416 !important;
    background: transparent !important;
}
div.nav-btn-active > button {
    color: #0b2416 !important;
    font-weight: 700 !important;
    border-bottom: 2px solid #0b2416 !important;
}
div.brand-btn-box > button {
    font-family: 'Playfair Display', serif !important;
    font-size: 1.55rem !important;
    font-weight: 800 !important;
    color: #0b2416 !important;
    letter-spacing: -0.3px !important;
}

/* ── PILLS ── */
.pill-outline {
    border: 1px solid rgba(11,36,22,0.3);
    border-radius: 50px; padding: 5px 14px;
    font-size: 0.8rem; font-weight: 500; color: #1c2b24; white-space: nowrap;
}
.pill-solid {
    border-radius: 50px; padding: 5px 14px;
    font-size: 0.8rem; font-weight: 600; color: #fff; background: #0b2416; white-space: nowrap;
}

/* ── HERO ── */
.page-eyebrow {
    font-size: 0.68rem; text-transform: uppercase;
    letter-spacing: 2px; color: #7a8c82; font-weight: 600; margin: 1.4rem 0 0.25rem;
}
.page-title {
    font-family: 'Playfair Display', serif !important;
    font-size: 2.8rem !important; font-weight: 700 !important;
    color: #0b2416 !important; margin: 0 0 1.5rem !important; line-height: 1.1 !important;
}

/* ── METRICS ── */
.metric-box {
    border: 1px solid rgba(11,36,22,0.18); border-radius: 14px;
    padding: 1.1rem 1.3rem; background: #ffffff !important;
    display: flex; align-items: center; gap: 1rem;
    transition: border-color 0.2s, box-shadow 0.2s;
}
.metric-box:hover {
    border-color: rgba(46,204,113,0.5);
    box-shadow: 0 4px 20px rgba(46,204,113,0.08);
}
.metric-icon-wrap {
    width: 44px; height: 44px; background: #eef4ef;
    border-radius: 12px; display: flex; align-items: center;
    justify-content: center; font-size: 1.3rem; flex-shrink: 0;
}
.metric-num { font-size: 1.9rem; font-weight: 700; color: #0b2416; line-height: 1; }
.metric-lbl { font-size: 0.78rem; color: #5d6e65; margin-top: 3px; }

/* ── SECTION TITLE ── */
.section-title {
    font-family: 'Playfair Display', serif !important;
    font-size: 1.55rem !important; font-weight: 700 !important;
    color: #0b2416 !important; margin: 0 !important; padding-top: 4px !important;
}

/* ── ACTION BUTTONS ── */
div.action-btn-container > button {
    background: #ffffff !important; color: #0b2416 !important;
    border: 1.5px solid #2ecc71 !important; border-radius: 50px !important;
    padding: 0.6rem 1.6rem !important; font-weight: 600 !important;
    font-size: 0.83rem !important; box-shadow: 0 0 14px rgba(46,204,113,0.22) !important;
    transition: all 0.25s !important; white-space: nowrap !important; width: 100% !important;
}
div.action-btn-container > button:hover {
    background: #2ecc71 !important; color: #ffffff !important;
    box-shadow: 0 0 24px rgba(46,204,113,0.4) !important;
}
div.green-cta-btn > button {
    background: #2ecc71 !important; color: #ffffff !important;
    border: 1.5px solid #2ecc71 !important;
    box-shadow: 0 0 20px rgba(46,204,113,0.4) !important;
}
div.green-cta-btn > button:hover {
    background: #27ae60 !important; border-color: #27ae60 !important;
    box-shadow: 0 0 28px rgba(39,174,96,0.55) !important;
}
div.reject-btn-container > button {
    background: #ffffff !important; color: #c0392b !important;
    border: 1.5px solid rgba(192,57,43,0.35) !important;
    border-radius: 50px !important; padding: 0.45rem 1.2rem !important;
    font-weight: 600 !important; font-size: 0.78rem !important;
    box-shadow: none !important; width: 100% !important;
}
div.reject-btn-container > button:hover {
    background: rgba(192,57,43,0.06) !important;
    border-color: #c0392b !important;
}

/* ── TAGS ── */
.tags-row { display: flex; gap: 0.4rem; flex-wrap: wrap; margin: 0.4rem 0 0.8rem; }
.tag-pill {
    border: 1px solid rgba(28,43,36,0.16); border-radius: 50px;
    padding: 2px 11px; font-size: 0.71rem; color: #43534c;
    background: transparent; white-space: nowrap;
}

/* ── MATCH CARDS ── */
.match-card {
    border: 1px solid rgba(11,36,22,0.16); border-radius: 16px;
    padding: 1.1rem 1.3rem 0.9rem; background: #ffffff !important;
    margin-bottom: 0.9rem; transition: border-color 0.2s, box-shadow 0.2s;
}
.match-card:hover {
    border-color: #2ecc71; box-shadow: 0 4px 22px rgba(46,204,113,0.1);
}
.entity-role { font-size: 0.7rem; color: #7a8c82; letter-spacing: 0.3px; }
.entity-name { font-size: 1.05rem; font-weight: 700; color: #0b2416; }
.synergy-circle {
    border: 2px solid #2ecc71; border-radius: 50%;
    width: 62px; height: 62px;
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    font-weight: 700; font-size: 1rem; color: #0b2416;
    background: radial-gradient(circle, rgba(46,204,113,0.1) 0%, transparent 70%);
    box-shadow: 0 0 12px rgba(46,204,113,0.18); margin: auto;
}
.synergy-sub {
    font-size: 0.5rem; text-transform: uppercase;
    letter-spacing: 0.5px; color: #5d6e65;
}
.synergy-badge {
    background: #2ecc71; color: #0b2416; font-weight: 700;
    font-size: 0.75rem; padding: 5px 13px; border-radius: 50px; white-space: nowrap;
}
.insight-text { font-size: 0.8rem; color: #5d6e65; margin: 0.5rem 0; line-height: 1.5; }
.insight-text strong { color: #1c2b24; font-weight: 600; }

/* ── SIDEBAR CARDS ── */
.sb-card {
    border: 1px solid rgba(11,36,22,0.12); border-radius: 14px;
    padding: 1rem 1.1rem; background: #ffffff !important; margin-bottom: 0.75rem;
}
.sb-section-label {
    font-size: 0.68rem; text-transform: uppercase;
    letter-spacing: 1.5px; color: #7a8c82; font-weight: 600; margin-bottom: 0.5rem;
    display: flex; align-items: center; gap: 0.35rem;
}
.sb-entry-name { font-size: 0.85rem; font-weight: 600; color: #0b2416; }
.sb-entry-sub  { font-size: 0.74rem; color: #7a8c82; }
.sb-dot {
    width: 7px; height: 7px; border-radius: 50%; background: #2ecc71;
    display: inline-block; margin-right: 6px; box-shadow: 0 0 5px rgba(46,204,113,0.5);
}

/* ── MENTORS PAGE ── */
.mentor-metric-banner { display: flex; gap: 1.5rem; align-items: center; margin: 0.6rem 0 1.8rem; flex-wrap: wrap; }
.mentor-metric-chip {
    border: 1px solid rgba(11,36,22,0.2); border-radius: 50px; padding: 6px 18px;
    font-size: 0.82rem; font-weight: 600; color: #0b2416; background: #ffffff !important;
    display: flex; align-items: center; gap: 0.5rem;
}
.mentor-metric-sep { color: rgba(11,36,22,0.2); font-size: 1.2rem; }
.mentor-row {
    border: 1px solid rgba(11,36,22,0.13); border-radius: 14px;
    padding: 1rem 1.3rem; background: #ffffff !important; margin-bottom: 0.65rem;
    transition: border-color 0.2s, box-shadow 0.2s;
}
.mentor-row:hover { border-color: #2ecc71; box-shadow: 0 3px 18px rgba(46,204,113,0.1); }
.mentor-name { font-size: 1rem; font-weight: 700; color: #0b2416; }
.mentor-title { font-size: 0.78rem; color: #7a8c82; margin-top: 2px; }
.mentor-status-active {
    display: inline-block; background: rgba(46,204,113,0.12); color: #0b7a3e;
    border-radius: 50px; padding: 2px 10px; font-size: 0.68rem; font-weight: 600; margin-top: 4px;
}
.mentor-status-available {
    display: inline-block; background: rgba(11,36,22,0.06); color: #5d6e65;
    border-radius: 50px; padding: 2px 10px; font-size: 0.68rem; font-weight: 600; margin-top: 4px;
}
.mentor-col-header {
    font-size: 0.68rem; text-transform: uppercase; letter-spacing: 1.5px;
    color: #7a8c82; font-weight: 600; padding: 0 0 0.6rem;
    border-bottom: 1px solid rgba(11,36,22,0.08); margin-bottom: 0.5rem;
}

/* ── PIPELINE ANIMATION ── */
.pipeline-step {
    display: flex; align-items: center; gap: 0.8rem;
    padding: 0.55rem 0.8rem; border-radius: 10px;
    background: rgba(46,204,113,0.05); margin-bottom: 0.4rem;
    border: 1px solid rgba(46,204,113,0.15);
    font-size: 0.82rem; color: #0b2416;
}
.pipeline-icon { font-size: 1.1rem; width: 28px; text-align: center; }

/* ── WORKSPACE ENTITY CARD ── */
.entity-card {
    background: #0b2416; border: 1.5px solid #2ecc71; border-radius: 16px;
    padding: 1.2rem 1.4rem; margin: 0.6rem 0;
    box-shadow: 0 0 28px rgba(46,204,113,0.18);
}
.entity-card-title { font-size: 1rem; font-weight: 700; color: #2ecc71; margin-bottom: 0.6rem; }
.entity-card-row { display: flex; gap: 0.6rem; align-items: flex-start; margin-bottom: 0.35rem; }
.entity-card-label { font-size: 0.7rem; color: #7ab898; width: 90px; flex-shrink: 0; font-weight: 600; }
.entity-card-value { font-size: 0.78rem; color: #d0e8d8; word-break: break-all; }

/* ── CONTACT PAGE ── */
.contact-card {
    border: 1px solid rgba(11,36,22,0.13); border-radius: 14px;
    padding: 1.2rem 1.4rem; background: #ffffff !important; margin-bottom: 0.85rem;
}
.contact-card-label {
    font-size: 0.67rem; text-transform: uppercase; letter-spacing: 1.5px;
    color: #7a8c82; font-weight: 600; margin-bottom: 0.55rem;
}
.contact-card-title { font-size: 0.9rem; font-weight: 700; color: #0b2416; margin-bottom: 3px; }
.contact-card-value { font-size: 0.82rem; color: #5d6e65; line-height: 1.6; }
.contact-card-highlight { font-size: 0.82rem; color: #0b2416; font-weight: 600; }
.contact-form-label {
    font-size: 0.72rem; text-transform: uppercase; letter-spacing: 1.2px;
    color: #7a8c82; font-weight: 600; margin-bottom: 0.4rem; margin-top: 1.1rem;
}
.triage-dot {
    width: 8px; height: 8px; border-radius: 50%; background: #2ecc71;
    display: inline-block; margin-right: 6px;
    box-shadow: 0 0 6px rgba(46,204,113,0.6); vertical-align: middle;
}

/* ── INPUT FIELDS ── */
.stTextInput div div input, .stTextArea div div textarea {
    background-color: #ffffff !important; color: #0b2416 !important;
    border: 1.5px solid rgba(11, 36, 22, 0.25) !important;
    border-radius: 8px !important; padding: 0.65rem 1.1rem !important;
    font-family: 'Plus Jakarta Sans', sans-serif !important; opacity: 1 !important; box-shadow: none !important;
}
.stTextInput div div input:focus, .stTextArea div div textarea:focus {
    border-color: #2ecc71 !important; background-color: #ffffff !important;
    box-shadow: 0 0 0 3px rgba(46, 204, 113, 0.15) !important;
}
.stTextInput div div input::placeholder, .stTextArea div div textarea::placeholder {
    color: #7a8c82 !important; opacity: 0.85 !important;
}
.stTextInput > label, .stTextArea > label { display: none !important; }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════
# TOPBAR
# ══════════════════════════════════════════════════════════════════════
def render_topbar(current_page):
    st.markdown('<div class="topbar-wrapper">', unsafe_allow_html=True)
    c_left, c_right = st.columns([6, 4])

    with c_left:
        sub_l, sub_d, sub_m, sub_c = st.columns([1.5, 1.2, 1.2, 3.1])

        with sub_l:
            st.markdown('<div class="brand-btn-box">', unsafe_allow_html=True)
            if st.button("OPHIA", key="nav_brand"):
                st.session_state.page = "dashboard"
                st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

        with sub_d:
            cls = "nav-btn-active" if current_page == "dashboard" else ""
            st.markdown(f'<div class="{cls}">', unsafe_allow_html=True)
            if st.button("Dashboard", key="nav_dash"):
                st.session_state.page = "dashboard"
                st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

        with sub_m:
            cls = "nav-btn-active" if current_page == "mentors" else ""
            st.markdown(f'<div class="{cls}">', unsafe_allow_html=True)
            if st.button("Mentors", key="nav_mentors"):
                st.session_state.page = "mentors"
                st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

        with sub_c:
            cls = "nav-btn-active" if current_page == "contact" else ""
            st.markdown(f'<div class="{cls}">', unsafe_allow_html=True)
            if st.button("Contact", key="nav_contact"):
                st.session_state.page = "contact"
                st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

    with c_right:
        st.markdown('''
        <div style="display:flex; gap:0.7rem; align-items:center; justify-content:flex-end;">
            <div class="pill-outline">Admin: Vaza</div>
            <div style="position:relative; width:34px; height:34px;
                        border:1px solid rgba(28,43,36,0.22); border-radius:50%;
                        display:flex; align-items:center; justify-content:center;
                        cursor:pointer; font-size:0.95rem;">
                🔔
                <span style="position:absolute; top:6px; right:6px; width:6px; height:6px;
                             background:#2ecc71; border-radius:50%; border:1.5px solid #f8f9f3;
                             box-shadow:0 0 5px rgba(46,204,113,0.7);"></span>
            </div>
            <div class="pill-solid">Sign in ▾</div>
        </div>
        ''', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════
# APPROVE PIPELINE ANIMATION
# This is the money shot for the demo
# ══════════════════════════════════════════════════════════════════════
def run_approve_animation(selected_matches: list):
    """
    Shows a step-by-step pipeline animation simulating backend operations.
    Runs inside a container so it replaces itself with the success card.
    """
    anim_container = st.container()

    with anim_container:
        st.markdown("""
        <div style="background:#f8f9f3; border:1px solid rgba(11,36,22,0.12);
                    border-radius:16px; padding:1.2rem 1.4rem; margin-bottom:1rem;">
            <div style="font-size:0.78rem; font-weight:700; color:#0b2416; 
                        text-transform:uppercase; letter-spacing:1.5px; margin-bottom:0.8rem;">
                ⚙️ OPHIA Orchestration Engine — Running
            </div>
        """, unsafe_allow_html=True)

        progress_bar = st.progress(0)
        step_placeholder = st.empty()

        for icon, label, progress in PIPELINE_STEPS:
            step_placeholder.markdown(f"""
            <div class="pipeline-step">
                <span class="pipeline-icon">{icon}</span>
                <span>{label}</span>
            </div>
            """, unsafe_allow_html=True)
            progress_bar.progress(progress)
            time.sleep(0.55)

        st.markdown('</div>', unsafe_allow_html=True)

    # Small pause then clear the animation
    time.sleep(0.3)
    anim_container.empty()

    # Create workspace entities for each approved match
    if st.session_state.data_source == "live":
        new_entities = api_client.approve(selected_matches)
        if new_entities is None:
            st.error(f"Approval failed — nothing was created. {api_client.last_error or ''}")
            return
        st.session_state.workspaces.extend(new_entities)
    else:
        new_entities = []
        for match in selected_matches:
            entity = generate_workspace_entity(
                match["startup"], match["mentor"], match["synergy"]
            )
            new_entities.append(entity)
            st.session_state.workspaces.append(entity)

    st.session_state.last_approved_details = new_entities
    st.session_state.approve_done = True
    st.session_state.approved = True

    # Remove approved matches from pending
    approved_keys = [m["key"] for m in selected_matches]
    st.session_state.pending_matches = [
        m for m in st.session_state.pending_matches
        if m["key"] not in approved_keys
    ]

    st.rerun()


# ══════════════════════════════════════════════════════════════════════
# PAGE 1 — DASHBOARD
# ══════════════════════════════════════════════════════════════════════
def render_dashboard():
    st.markdown('<div class="page-eyebrow">Orchestrator Home</div>', unsafe_allow_html=True)
    st.markdown('<h1 class="page-title">Ophia Orchestrator</h1>', unsafe_allow_html=True)

    if st.session_state.data_source == "live":
        st.caption("🟢 Live data — matches from the OPHIA backend")
    elif api_client.enabled():
        st.warning(f"Backend unreachable — showing demo data. {api_client.last_error or ''}")
    else:
        st.caption("Demo mode — mock data (set OPHIA_API_URL in .env to use the backend)")

    # ── Metrics ──────────────────────────────────────────────────────
    m1, m2, m3, spacer = st.columns([3, 3, 3, 0.6])
    metrics = [
        (m1, "🚀", str(st.session_state.total_startups), "New Startups"),
        (m2, "👥", str(st.session_state.total_mentors),  "Mentors Available"),
        (m3, "📅", str(st.session_state.active_programmes), "Active Programmes"),
    ]
    for col, icon, num, label in metrics:
        with col:
            st.markdown(f"""
            <div class="metric-box">
                <div class="metric-icon-wrap">{icon}</div>
                <div>
                    <div class="metric-num">{num}</div>
                    <div class="metric-lbl">{label}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

    with spacer:
        st.markdown("""
        <div style="display:flex; justify-content:flex-end; align-items:center;
                    height:100%; padding-top:2px;">
            <div style="border:1px solid rgba(11,36,22,0.18); border-radius:10px;
                        padding:8px 10px; cursor:pointer; font-size:1.05rem; background:#ffffff;">
                📊
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    left_col, right_col = st.columns([7, 3], gap="large")

    # ── LEFT: PENDING AI LINKAGES ─────────────────────────────────────
    with left_col:

        # Header + Approve button
        hdr_l, hdr_r = st.columns([5, 5])
        with hdr_l:
            pending_count = len(st.session_state.pending_matches)
            st.markdown(
                f'<h2 class="section-title">⚡ Pending AI Linkages '
                f'<span style="font-size:0.9rem; font-weight:400; color:#7a8c82;">({pending_count})</span>'
                f'</h2>',
                unsafe_allow_html=True
            )

        with hdr_r:
            st.markdown('<div class="action-btn-container green-cta-btn">', unsafe_allow_html=True)
            approve_clicked = st.button(
                "Approve Selected & Generate Programmable Entities",
                key="approve_btn"
            )
            st.markdown('</div>', unsafe_allow_html=True)

        # Handle approve click
        if approve_clicked:
            selected = [
                m for m in st.session_state.pending_matches
                if st.session_state.get(m["key"], False)
            ]
            if selected:
                run_approve_animation(selected)
            else:
                st.markdown("""
                <div style="background:#fff8e6; border:1.5px solid #f0a500;
                            border-radius:14px; padding:0.85rem 1.3rem;
                            margin:0.8rem 0 0.5rem; display:flex;
                            align-items:center; gap:0.8rem;">
                    <div style="font-size:1.3rem;">⚠️</div>
                    <div style="font-size:0.85rem; font-weight:600; color:#7a4f00;">
                        Please select at least one match before approving.
                    </div>
                </div>
                """, unsafe_allow_html=True)

        # ── Success cards (shown after approval) ──────────────────────
        if st.session_state.approve_done and st.session_state.last_approved_details:
            for entity in st.session_state.last_approved_details:
                startup_slug = entity["startup"].lower().replace(" ", "-")
                st.markdown(f"""
                <div class="entity-card">
                    <div class="entity-card-title">✅ Programmable Entity Active — {entity['name']}</div>
                    <div class="entity-card-row">
                        <span class="entity-card-label">Match</span>
                        <span class="entity-card-value">{entity['startup']} → {entity['mentor']}</span>
                    </div>
                    <div class="entity-card-row">
                        <span class="entity-card-label">Synergy</span>
                        <span class="entity-card-value" style="color:#2ecc71; font-weight:700;">{entity['synergy']}%</span>
                    </div>
                    <div class="entity-card-row">
                        <span class="entity-card-label">📁 Drive</span>
                        <span class="entity-card-value">{entity['drive_url']}</span>
                    </div>
                    <div class="entity-card-row">
                        <span class="entity-card-label">📧 Email</span>
                        <span class="entity-card-value">Intro sent → {entity['email_sent_to']}</span>
                    </div>
                    <div class="entity-card-row">
                        <span class="entity-card-label">📅 Kickoff</span>
                        <span class="entity-card-value">Calendar event + Meet link generated</span>
                    </div>
                    <div class="entity-card-row">
                        <span class="entity-card-label">Timeline</span>
                        <span class="entity-card-value">
                            {entity['created_at']} → {entity['lifecycle_end']} (90 days)
                        </span>
                    </div>
                </div>
                """, unsafe_allow_html=True)

        # ── AI Match Tags header ──────────────────────────────────────
        all_tags = []
        for m in st.session_state.pending_matches:
            all_tags.extend(m["tags"])
        unique_tags = list(dict.fromkeys(all_tags))[:6]

        if unique_tags:
            tags_html = "".join(f'<span class="tag-pill">{t}</span>' for t in unique_tags)
            st.markdown(f"""
            <div style="font-size:0.78rem; font-weight:600; color:#5d6e65; margin:0.9rem 0 0.4rem;">
                AI match tags — active taxonomy clusters
            </div>
            <div class="tags-row">{tags_html}</div>
            """, unsafe_allow_html=True)

        # ── Match cards ───────────────────────────────────────────────
        if not st.session_state.pending_matches:
            st.markdown("""
            <div style="text-align:center; padding:2.5rem;
                        border:1px dashed rgba(11,36,22,0.15); border-radius:14px;
                        color:#7a8c82; font-size:0.9rem; margin-top:0.5rem;">
                🎉 All matches have been approved. No pending linkages.
            </div>
            """, unsafe_allow_html=True)
        else:
            for match in st.session_state.pending_matches:
                st.markdown('<div class="match-card">', unsafe_allow_html=True)

                c_chk, c_entity, c_synergy, c_badge = st.columns([0.45, 5.55, 2, 2])

                with c_chk:
                    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
                    st.checkbox(f"Select {match['startup']}", key=match["key"], label_visibility="collapsed")

                with c_entity:
                    st.markdown(f"""
                    <div style="display:flex; align-items:center; gap:0.6rem;
                                flex-wrap:wrap; margin-top:5px;">
                        <div>
                            <div class="entity-role">Startup — {match.get('startup_batch','')}</div>
                            <div class="entity-name">{match['startup']}</div>
                            <div style="font-size:0.7rem; color:#7a8c82; margin-top:2px;">
                                {match.get('startup_desc','')[:60]}...
                            </div>
                        </div>
                        <div style="color:#0b2416; font-size:1rem; margin-top:14px;
                                    letter-spacing:1px;">————&gt;</div>
                        <div>
                            <div class="entity-role">Mentor</div>
                            <div class="entity-name">{match['mentor']}</div>
                            <div style="font-size:0.7rem; color:#7a8c82; margin-top:2px;">
                                {match.get('mentor_title','')}
                            </div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                with c_synergy:
                    st.markdown(f"""
                    <div style="display:flex; justify-content:center; padding-top:3px;">
                        <div class="synergy-circle">
                            {match['synergy']}%
                            <div class="synergy-sub">Synergy</div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                with c_badge:
                    score_detail = match.get("score_detail") or (
                        f"Semantic: {match.get('semantic_score', 0):.2f} · "
                        f"Taxonomy: {match.get('taxonomy_score', 0):.2f}"
                    )
                    st.markdown(f"""
                    <div style="display:flex; flex-direction:column; align-items:flex-end;
                                justify-content:center; height:100%; gap:0.5rem; padding-top:5px;">
                        <span class="synergy-badge">{match['synergy']}% Synergy</span>
                        <div style="font-size:0.65rem; color:#7a8c82; text-align:right;">
                            {score_detail}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                st.markdown(f"""
                <div class="insight-text">
                    <strong>AI Insight:</strong> {match['insight']}
                </div>
                <div class="tags-row">
                    {''.join(f'<span class="tag-pill">{t}</span>' for t in match["tags"])}
                </div>
                """, unsafe_allow_html=True)

                # Reject button per card
                _, _, reject_col = st.columns([7, 1.5, 1.5])
                with reject_col:
                    st.markdown('<div class="reject-btn-container">', unsafe_allow_html=True)
                    if st.button("Reject ✕", key=f"reject_{match['key']}"):
                        st.session_state.pending_matches = [
                            m for m in st.session_state.pending_matches
                            if m["key"] != match["key"]
                        ]
                        st.session_state.rejected_keys.append(match["key"])
                        st.rerun()
                    st.markdown('</div>', unsafe_allow_html=True)

                st.markdown('</div>', unsafe_allow_html=True)

    # ── RIGHT: SIDEBAR ────────────────────────────────────────────────
    with right_col:
        st.markdown("""
        <div style="border-left:1px solid rgba(28,43,36,0.1); padding-left:1.4rem;">
        """, unsafe_allow_html=True)

        st.markdown("""
        <div style="font-family:'Playfair Display',serif; font-size:1.05rem;
                    font-weight:700; color:#0b2416; margin-bottom:0.2rem;">
            ⚙️ Active Programmable Entities
        </div>
        <div style="font-size:0.75rem; color:#7a8c82; margin-bottom:1.2rem;">(Live Tracking)</div>
        """, unsafe_allow_html=True)

        # Active Workspaces — dynamically updated
        st.markdown('<div class="sb-card"><div class="sb-section-label">📁 Active Workspaces</div>', unsafe_allow_html=True)
        for ws in st.session_state.workspaces:
            day_label = f"Day {ws.get('day', 0)} / 90" if ws.get('day', 0) > 0 else "Day 0 — Just started"
            st.markdown(f"""
            <div style="margin-bottom:0.6rem;">
                <div class="sb-entry-name"><span class="sb-dot"></span>{ws['name']}</div>
                <div class="sb-entry-sub" style="padding-left:13px;">
                    {ws['startup']} × {ws['mentor']}<br>
                    Status: {ws['status']} · {day_label}
                </div>
            </div>
            """, unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

        # Completed Check-ins
        st.markdown('<div class="sb-card"><div class="sb-section-label">✅ Completed 90-day Check-ins</div>', unsafe_allow_html=True)
        for ci in st.session_state.checkins:
            st.markdown(f"""
            <div style="margin-bottom:0.5rem;">
                <div class="sb-entry-name">{ci['name']}</div>
                <div class="sb-entry-sub">{ci['detail']}</div>
            </div>
            """, unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

        # Synergy trend sparkline
        st.markdown("""
        <div class="sb-card">
            <div class="sb-section-label">📈 Synergy Trend</div>
            <svg viewBox="0 0 280 52" width="100%" height="52" preserveAspectRatio="none">
                <path d="M0,44 Q25,28 50,36 T100,14 T155,38 T210,18 T280,24"
                      fill="none" stroke="#2ecc71" stroke-width="2"
                      stroke-linecap="round" stroke-linejoin="round"/>
                <path d="M0,44 Q25,28 50,36 T100,14 T155,38 T210,18 T280,24 L280,52 L0,52 Z"
                      fill="rgba(46,204,113,0.07)"/>
                <circle cx="100" cy="14" r="3" fill="#2ecc71"/>
                <circle cx="210" cy="18" r="3" fill="#2ecc71"/>
            </svg>
            <div style="font-size:0.7rem; color:#7a8c82; margin-top:0.3rem;">
                Match quality improving over time — feedback loop active
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Dynamic quick stats
        pending_n = len(st.session_state.pending_matches)
        workspace_n = len(st.session_state.workspaces)
        checkin_n = len(st.session_state.checkins)
        avg_synergy = int(sum(w["synergy"] for w in st.session_state.workspaces) / max(workspace_n, 1))

        st.markdown(f"""
        <div class="sb-card">
            <div class="sb-section-label">📊 Quick Stats</div>
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:0.6rem;">
                <div style="text-align:center; padding:0.5rem;
                            background:rgba(46,204,113,0.06); border-radius:10px;">
                    <div style="font-size:1.2rem; font-weight:700; color:#0b2416;">{pending_n}</div>
                    <div style="font-size:0.68rem; color:#7a8c82;">Pending</div>
                </div>
                <div style="text-align:center; padding:0.5rem;
                            background:rgba(46,204,113,0.06); border-radius:10px;">
                    <div style="font-size:1.2rem; font-weight:700; color:#0b2416;">{avg_synergy}%</div>
                    <div style="font-size:0.68rem; color:#7a8c82;">Avg Synergy</div>
                </div>
                <div style="text-align:center; padding:0.5rem;
                            background:rgba(46,204,113,0.06); border-radius:10px;">
                    <div style="font-size:1.2rem; font-weight:700; color:#0b2416;">{workspace_n}</div>
                    <div style="font-size:0.68rem; color:#7a8c82;">Workspaces</div>
                </div>
                <div style="text-align:center; padding:0.5rem;
                            background:rgba(46,204,113,0.06); border-radius:10px;">
                    <div style="font-size:1.2rem; font-weight:700; color:#0b2416;">{checkin_n}</div>
                    <div style="font-size:0.68rem; color:#7a8c82;">Check-ins</div>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════
# PAGE 2 — MENTORS DIRECTORY
# ══════════════════════════════════════════════════════════════════════
def render_mentors():
    st.markdown('<div class="page-eyebrow">Ecosystem Overview</div>', unsafe_allow_html=True)
    st.markdown('<h1 class="page-title">Ecosystem Mentors Directory</h1>', unsafe_allow_html=True)

    active_count = sum(1 for m in MENTORS if m["status"] == "Active")
    total_partnerships = sum(m["partnerships"] for m in MENTORS)

    st.markdown(f"""
    <div class="mentor-metric-banner">
        <div class="mentor-metric-chip">
            <span>👥</span>
            <span style="font-size:1rem; font-weight:700;">{len(MENTORS)}</span>
            <span style="font-size:0.8rem; color:#5d6e65; font-weight:400;">Total Mentors</span>
        </div>
        <div class="mentor-metric-sep">|</div>
        <div class="mentor-metric-chip">
            <span>🟢</span>
            <span style="font-size:1rem; font-weight:700;">{active_count}</span>
            <span style="font-size:0.8rem; color:#5d6e65; font-weight:400;">Active</span>
        </div>
        <div class="mentor-metric-sep">|</div>
        <div class="mentor-metric-chip">
            <span>🤝</span>
            <span style="font-size:1rem; font-weight:700;">{total_partnerships}</span>
            <span style="font-size:0.8rem; color:#5d6e65; font-weight:400;">Active Partnerships</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    search_query = st.text_input(
        "Search mentors",
        placeholder="🔍  Search by name, expertise, or title…",
        key="mentor_search",
        label_visibility="collapsed",
    )

    st.markdown("""
    <div style="display:flex; gap:0.5rem; flex-wrap:wrap; align-items:center; margin:0.8rem 0 1.4rem;">
        <span style="font-size:0.72rem; font-weight:600; color:#7a8c82;
                     text-transform:uppercase; letter-spacing:1.2px; margin-right:0.2rem;">
            Filters:
        </span>
        <span class="tag-pill" style="cursor:pointer;">'Security Protocols'</span>
        <span class="tag-pill" style="cursor:pointer;">'Machine Learning'</span>
        <span class="tag-pill" style="cursor:pointer;">'Fraud Detection'</span>
        <span class="tag-pill" style="cursor:pointer;">'ESG Compliance'</span>
        <span class="tag-pill" style="cursor:pointer;">'Health AI'</span>
        <span class="tag-pill" style="cursor:pointer;">'RegTech'</span>
        <span class="tag-pill" style="cursor:pointer;">'DeFi'</span>
    </div>
    """, unsafe_allow_html=True)

    h_name, h_expertise, h_action = st.columns([3, 5, 2])
    with h_name:
        st.markdown('<div class="mentor-col-header">Mentor</div>', unsafe_allow_html=True)
    with h_expertise:
        st.markdown('<div class="mentor-col-header">Core Expertise</div>', unsafe_allow_html=True)
    with h_action:
        st.markdown('<div class="mentor-col-header" style="text-align:right;">Action</div>', unsafe_allow_html=True)

    query = search_query.strip().lower()
    filtered = [
        m for m in MENTORS
        if not query
        or query in m["name"].lower()
        or query in m["title"].lower()
        or any(query in tag.lower() for tag in m["expertise"])
        or query in m.get("bio", "").lower()
    ]

    if not filtered:
        st.markdown("""
        <div style="text-align:center; padding:2.5rem; color:#7a8c82;
                    font-size:0.9rem; border:1px dashed rgba(11,36,22,0.15);
                    border-radius:14px; margin-top:0.5rem;">
            No mentors match your search. Try a different keyword.
        </div>
        """, unsafe_allow_html=True)
        return

    for i, mentor in enumerate(filtered):
        st.markdown('<div class="mentor-row">', unsafe_allow_html=True)
        col_name, col_expertise, col_action = st.columns([3, 5, 2])

        status_cls = "mentor-status-active" if mentor["status"] == "Active" else "mentor-status-available"

        with col_name:
            st.markdown(f"""
            <div style="padding:4px 0;">
                <div class="mentor-name">{mentor['name']}</div>
                <div class="mentor-title">{mentor['title']}</div>
                <div style="font-size:0.7rem; color:#7a8c82; margin-top:3px;">
                    {mentor.get('country', '')} · {mentor.get('availability_hours', 0)}h/month
                </div>
                <span class="{status_cls}">{mentor['status']}</span>
            </div>
            """, unsafe_allow_html=True)

        with col_expertise:
            tags_html = "".join(f'<span class="tag-pill">{tag}</span>' for tag in mentor["expertise"])
            st.markdown(f"""
            <div style="padding:8px 0;">
                <div class="tags-row">{tags_html}</div>
                <div style="font-size:0.72rem; color:#5d6e65; margin-top:4px; line-height:1.4;">
                    {mentor.get('bio', '')[:90]}…
                </div>
                <div style="font-size:0.7rem; color:#7a8c82; margin-top:4px;">
                    {mentor['partnerships']} active partnership{'s' if mentor['partnerships'] != 1 else ''}
                </div>
            </div>
            """, unsafe_allow_html=True)

        with col_action:
            st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
            st.markdown('<div class="action-btn-container">', unsafe_allow_html=True)
            if st.button("Propose Synergy Linkage", key=f"propose_{i}"):
                st.session_state.propose_submitted = mentor["name"]
                # Add to pending queue in session state
                st.session_state.pending_proposed.append(mentor["name"])
            st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('</div>', unsafe_allow_html=True)

    if st.session_state.propose_submitted:
        st.markdown(f"""
        <div style="background:#0b2416; border:1.5px solid #2ecc71;
                    border-radius:14px; padding:0.9rem 1.3rem;
                    margin-top:1rem; display:flex; align-items:center; gap:1rem;
                    box-shadow:0 0 20px rgba(46,204,113,0.18);">
            <div style="font-size:1.4rem;">🔗</div>
            <div>
                <div style="font-size:0.9rem; font-weight:700; color:#2ecc71;">
                    Synergy Linkage Proposed
                </div>
                <div style="font-size:0.78rem; color:#a8c4b0; margin-top:2px;">
                    Proposal for <strong style="color:#d0e8d8;">
                    {st.session_state.propose_submitted}</strong> has been queued.
                    Admin Vaza will review and approve via the dashboard.
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════
# PAGE 3 — CONTACT
# ══════════════════════════════════════════════════════════════════════
def render_contact():
    st.markdown('<div class="page-eyebrow">Get In Touch</div>', unsafe_allow_html=True)
    st.markdown('<h1 class="page-title">Connect with OPHIA Operations</h1>', unsafe_allow_html=True)

    left_col, right_col = st.columns([5, 5], gap="large")

    with left_col:
        st.markdown("""
        <div style="font-size:0.82rem; color:#5d6e65; line-height:1.7;
                    margin-bottom:1.4rem; max-width:420px;">
            Reach out to the OPHIA operations team for partnership enquiries,
            programme onboarding, or system triage. All requests are reviewed
            within one working day.
        </div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div class="contact-card">
            <div class="contact-card-label">🕐 Office Hours</div>
            <div class="contact-card-title">Operations Desk</div>
            <div class="contact-card-value">
                Monday – Friday &nbsp;·&nbsp; 09:00 – 18:00 MYT<br>
                Saturday &nbsp;·&nbsp; 10:00 – 14:00 MYT<br>
                <span style="color:#7a8c82; font-size:0.76rem;">Closed on Public Holidays</span>
            </div>
        </div>
        <div class="contact-card">
            <div class="contact-card-label">📧 Support Channels</div>
            <div style="display:flex; flex-direction:column; gap:0.55rem; margin-top:0.3rem;">
                <div>
                    <div class="contact-card-title">General Operations</div>
                    <div class="contact-card-highlight">ops@ophia.ai</div>
                </div>
                <div style="border-top:1px solid rgba(11,36,22,0.07); padding-top:0.55rem;">
                    <div class="contact-card-title">Partnership Enquiries</div>
                    <div class="contact-card-highlight">partnerships@ophia.ai</div>
                </div>
                <div style="border-top:1px solid rgba(11,36,22,0.07); padding-top:0.55rem;">
                    <div class="contact-card-title">Technical Support</div>
                    <div class="contact-card-highlight">support@ophia.ai</div>
                </div>
            </div>
        </div>
        <div class="contact-card">
            <div class="contact-card-label">⚙️ System Triage — Admin Sarah M.</div>
            <div style="display:flex; align-items:center; gap:0.5rem; margin-bottom:0.6rem;">
                <span class="triage-dot"></span>
                <span style="font-size:0.8rem; font-weight:600; color:#0b7a3e;">
                    All Systems Operational
                </span>
            </div>
            <div class="contact-card-value">
                Last triage check: <strong style="color:#1c2b24;">Today, 09:15 MYT</strong><br>
                Pending tickets: <strong style="color:#1c2b24;">2 open</strong> · 14 resolved this week<br>
                Response SLA: <strong style="color:#1c2b24;">&lt; 4 business hours</strong>
            </div>
        </div>
        """, unsafe_allow_html=True)

    with right_col:
        st.markdown("""
        <div style="border-left:1px solid rgba(28,43,36,0.1); padding-left:2rem;">
            <div style="font-family:'Playfair Display',serif; font-size:1.2rem;
                        font-weight:700; color:#0b2416; margin-bottom:0.25rem;">
                Send a Message
            </div>
            <div style="font-size:0.78rem; color:#7a8c82; margin-bottom:1.4rem;">
                Our team typically responds within one business day.
            </div>
        """, unsafe_allow_html=True)

        st.markdown('<div class="contact-form-label">Full Name</div>', unsafe_allow_html=True)
        contact_name = st.text_input("Name", placeholder="e.g. Ahmad Faris", key="contact_name", label_visibility="collapsed")

        st.markdown('<div class="contact-form-label">Email Address</div>', unsafe_allow_html=True)
        contact_email = st.text_input("Email", placeholder="e.g. ahmad@company.com", key="contact_email", label_visibility="collapsed")

        st.markdown('<div class="contact-form-label">Organisation</div>', unsafe_allow_html=True)
        contact_org = st.text_input("Org", placeholder="e.g. DataShield Ventures", key="contact_org", label_visibility="collapsed")

        st.markdown('<div class="contact-form-label">Subject</div>', unsafe_allow_html=True)
        contact_subject = st.text_input("Subject", placeholder="e.g. Partnership Enquiry — MediCore AI", key="contact_subject", label_visibility="collapsed")

        st.markdown('<div class="contact-form-label">Message</div>', unsafe_allow_html=True)
        contact_message = st.text_area(
            "Message",
            placeholder="Describe your enquiry in detail. Include any relevant programme codes or startup names.",
            height=140, key="contact_message", label_visibility="collapsed",
        )

        st.markdown("<div style='height:0.8rem'></div>", unsafe_allow_html=True)
        st.markdown('<div class="action-btn-container">', unsafe_allow_html=True)

        if st.button("Submit Message →", key="contact_submit"):
            if contact_name and contact_email and contact_message:
                st.session_state.contact_submitted = True
            else:
                st.markdown("""
                <div style="background:#fff8e6; border:1.5px solid #f0a500;
                            border-radius:12px; padding:0.75rem 1.1rem;
                            margin-top:0.5rem; font-size:0.82rem;
                            font-weight:600; color:#7a4f00;">
                    ⚠️ Please fill in your name, email, and message before submitting.
                </div>
                """, unsafe_allow_html=True)

        st.markdown('</div>', unsafe_allow_html=True)

        if st.session_state.contact_submitted:
            st.markdown(f"""
            <div style="background:#0b2416; border:1.5px solid #2ecc71;
                        border-radius:14px; padding:1rem 1.3rem; margin-top:0.8rem;
                        display:flex; align-items:center; gap:0.9rem;
                        box-shadow:0 0 22px rgba(46,204,113,0.2);">
                <div style="font-size:1.5rem;">✅</div>
                <div>
                    <div style="font-size:0.9rem; font-weight:700;
                                color:#2ecc71; margin-bottom:2px;">
                        Message Sent Successfully
                    </div>
                    <div style="font-size:0.77rem; color:#a8c4b0;">
                        Hi {contact_name or 'there'} — Admin Sarah M. will review
                        your enquiry within one business day.
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════
# ROUTER
# ══════════════════════════════════════════════════════════════════════
render_topbar(st.session_state.page)

if st.session_state.page == "mentors":
    render_mentors()
elif st.session_state.page == "contact":
    render_contact()
else:
    render_dashboard()