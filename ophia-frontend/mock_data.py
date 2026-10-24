# mock_data.py
# Sample data for demo mode (no backend). Nothing here was computed: the
# matches are hand-written examples in the same shape the live API returns,
# and approving them saves nothing and sends nothing.

from datetime import datetime, timedelta

# ═══════════════════════════════════════════════════════════════════════
# PENDING MATCHES (hand-written examples)
# ═══════════════════════════════════════════════════════════════════════

def _match(key, startup, desc, batch, country, mentor, title, synergy, grades, pct, insight, tags):
    domain, need, market = grades
    return {
        "key": key, "startup": startup, "startup_desc": desc, "startup_batch": batch,
        "startup_country": country, "mentor": mentor, "mentor_title": title,
        "synergy": synergy, "insight": insight, "tags": tags,
        "score_detail": f"Domain {domain}/5 · Need {need}/5 · Market {market}/5 · "
                        f"Closer than {pct}% of pairs (demo)",
    }


PENDING_MATCHES = [
    _match("demo_match_1", "DataShield", "AI-powered fraud detection and cybersecurity for fintech platforms.",
           "W23", "Malaysia", "Ehtisham Raza", "AI Security Architect & Serial Founder",
           96, (5, 5, 5), 99,
           "Ehtisham has built fraud-detection systems for Southeast Asian fintechs, which is exactly "
           "DataShield's product. He can help them harden their models for enterprise bank customers.",
           ["Fraud Detection", "AI Security", "Fintech"]),
    _match("demo_match_2", "GreenLedger", "ESG compliance and carbon tracking platform for Southeast Asian enterprises.",
           "S23", "Singapore", "Leong Lai Fong", "RegTech Advisor & Former Central Bank Regulatory Lead",
           86, (4, 5, 4), 95,
           "Her regulatory background maps directly onto GreenLedger's compliance product. The gap is "
           "climate science: she knows reporting rules, not carbon measurement.",
           ["RegTech", "ESG Compliance"]),
    _match("demo_match_3", "MediCore AI", "Clinical ML platform predicting patient outcomes from electronic health records.",
           "W23", "Malaysia", "Weiyuan Liu", "Clinical ML Research Lead",
           91, (5, 4, 5), 97,
           "Both work on predictive clinical models from patient records. Weiyuan can help MediCore "
           "design validation studies that hospitals will accept.",
           ["Health AI", "Clinical Data"]),
    _match("demo_match_4", "SupplySync", "B2B supply chain automation platform for SMEs in Southeast Asia.",
           "S22", "Malaysia", "Faiz Hassan", "B2B SaaS Growth Lead",
           72, (3, 4, 4), 81,
           "Faiz knows B2B SaaS sales into ASEAN SMEs, which is SupplySync's go-to-market. He has no "
           "supply-chain operations background, so he is a sales mentor rather than a product one.",
           ["B2B SaaS", "SME Sales"]),
    _match("demo_match_5", "LeafGrid", "Clean energy marketplace connecting solar panel owners with grid operators.",
           "W24", "Indonesia", "Sarah Chen", "Climate Tech Investor",
           64, (4, 3, 2), 74,
           "Sarah invests in climate marketplaces, so she understands LeafGrid's model. Her portfolio is "
           "in Singapore, not Indonesia, and she is an investor rather than an operator.",
           ["Climate Tech", "Marketplaces"]),
]


# ═══════════════════════════════════════════════════════════════════════
# INITIAL ACTIVE WORKSPACES (already approved before demo)
# ═══════════════════════════════════════════════════════════════════════

def _milestones(done_through: int) -> list[dict]:
    return [{"day": d, "label": label, "done": d <= done_through} for d, label in (
        (30, "Establish goals, align on tech stack, first check-in"),
        (60, "Mid-term review — progress audit and course correction"),
        (90, "Final evaluation and programme completion sign-off"),
    )]


INITIAL_WORKSPACES = [
    {
        "doc_id": "demo_ws_1",
        "name": "Project NeuralPay × Yuda Adi Pratama",
        "startup": "NeuralPay",
        "mentor": "Yuda Adi Pratama",
        "status": "Active",
        "day": 45,
        "synergy": 89,
        "milestones": _milestones(done_through=30),
    },
    {
        "doc_id": "demo_ws_2",
        "name": "Project AgriSense × Dr. Poo Kuan Hoong",
        "startup": "AgriSense",
        "mentor": "Dr. Poo Kuan Hoong",
        "status": "Active",
        "day": 62,
        "synergy": 84,
        "milestones": _milestones(done_through=60),
    },
]



# ═══════════════════════════════════════════════════════════════════════
# MENTOR DIRECTORY
# ═══════════════════════════════════════════════════════════════════════

MENTORS = [
    {
        "name": "Ehtisham Raza",
        "title": "AI Security Architect & Serial Founder",
        "expertise": ["Fraud Detection", "AI Architecture", "Security Protocols"],
        "bio": "15 years building AI-powered fraud detection systems for fintech companies across Southeast Asia. Has scaled 3 startups to Series B.",
        "status": "Active",
        "partnerships": 3,
        "availability_hours": 8,
        "country": "Malaysia",
    },
    {
        "name": "Leong Lai Fong",
        "title": "RegTech Advisor & Former Bank Negara Lead",
        "expertise": ["RegTech", "ESG Compliance", "Automation"],
        "bio": "Former regulatory advisor with deep expertise in ESG compliance frameworks and RegTech automation across ASEAN financial markets.",
        "status": "Active",
        "partnerships": 2,
        "availability_hours": 6,
        "country": "Malaysia",
    },
    {
        "name": "Weiyuan Liu",
        "title": "Clinical ML Research Lead",
        "expertise": ["Health AI", "ML Diagnostics", "Clinical Data"],
        "bio": "AI researcher turned investor. Background in predictive diagnostics, clinical machine learning models, and health data infrastructure.",
        "status": "Active",
        "partnerships": 4,
        "availability_hours": 5,
        "country": "Singapore",
    },
    {
        "name": "Faiz Hassan",
        "title": "B2B SaaS Growth Lead",
        "expertise": ["B2B", "SaaS", "Developer Tools", "Cloud Infrastructure"],
        "bio": "Ecosystem builder with deep expertise in B2B SaaS scaling and cloud infrastructure for Southeast Asian markets.",
        "status": "Available",
        "partnerships": 1,
        "availability_hours": 10,
        "country": "Malaysia",
    },
    {
        "name": "Sarah Chen",
        "title": "Climate Tech Investor",
        "expertise": ["Climate Tech", "Sustainability", "ESG", "Green Energy"],
        "bio": "Deep tech investor with expertise in climate tech, sustainability metrics, and green energy startup scaling across ASEAN.",
        "status": "Available",
        "partnerships": 0,
        "availability_hours": 4,
        "country": "Singapore",
    },
    {
        "name": "Vriraj Singh",
        "title": "Senior AI Infrastructure Scientist",
        "expertise": ["Fraud Detection", "AI Architecture", "Security Protocols"],
        "bio": "Senior AI scientist with a track record in building enterprise-grade machine learning infrastructure and adversarial AI systems.",
        "status": "Active",
        "partnerships": 3,
        "availability_hours": 6,
        "country": "India",
    },
    {
        "name": "Saurabh Mishra",
        "title": "RegTech & Compliance Director",
        "expertise": ["RegTech", "ESG Compliance", "Automation", "Policy"],
        "bio": "Director-level compliance expert with regulatory experience across India, Singapore, and Malaysia's central banking frameworks.",
        "status": "Active",
        "partnerships": 2,
        "availability_hours": 8,
        "country": "Singapore",
    },
    {
        "name": "Esther Tan",
        "title": "Health AI Product Strategist",
        "expertise": ["Health AI", "ML Diagnostics", "Clinical Data", "MedTech"],
        "bio": "Product strategist who has launched three clinical AI products into regulated healthcare markets in ASEAN and Australia.",
        "status": "Active",
        "partnerships": 4,
        "availability_hours": 5,
        "country": "Malaysia",
    },
    {
        "name": "Dr. L. Wong",
        "title": "Blockchain & DeFi Architect",
        "expertise": ["DeFi", "Smart Contracts", "Web3 Security", "Blockchain"],
        "bio": "Former academic turned blockchain architect. Advised on DeFi protocol design for 5 fintech startups with combined TVL of $200M.",
        "status": "Available",
        "partnerships": 1,
        "availability_hours": 6,
        "country": "Hong Kong",
    },
    {
        "name": "Dr. Poo Kuan Hoong",
        "title": "Sustainability & ESG Strategist",
        "expertise": ["ESG Reporting", "Carbon Markets", "Sustainability", "Policy"],
        "bio": "ESG strategist with 20 years in sustainability consulting. Helped 12 companies achieve carbon neutrality certification in ASEAN.",
        "status": "Active",
        "partnerships": 2,
        "availability_hours": 7,
        "country": "Malaysia",
    },
    {
        "name": "Hernando Cruz",
        "title": "Cybersecurity & Zero-Trust Architect",
        "expertise": ["Zero-Trust", "Penetration Testing", "Cloud Security"],
        "bio": "Zero-trust architect who has designed security frameworks for 3 unicorn startups. Previously red-teamed for a Fortune 500 financial institution.",
        "status": "Available",
        "partnerships": 0,
        "availability_hours": 8,
        "country": "Philippines",
    },
    {
        "name": "Razif Kamaruddin",
        "title": "ML Infrastructure Lead, ex-Google Brain",
        "expertise": ["AI/ML", "NLP", "LLM Deployment", "Deep Learning"],
        "bio": "CTO background in machine learning infrastructure and LLM deployment at enterprise scale. Previously contributed to Google Brain research teams.",
        "status": "Available",
        "partnerships": 0,
        "availability_hours": 6,
        "country": "Malaysia",
    },
]


# ═══════════════════════════════════════════════════════════════════════
# MOCK WORKSPACE GENERATION
# (Called when approve button is clicked)
# ═══════════════════════════════════════════════════════════════════════

def generate_workspace_entity(startup: str, mentor: str, synergy: int) -> dict:
    """A local-only workspace for demo mode, same shape as api_client._to_workspace.
    Nothing is saved, emailed or scheduled."""
    now = datetime.now()
    return {
        "doc_id": f"demo_ws_{now.timestamp()}",
        "name": f"Project {startup} × {mentor}",
        "startup": startup,
        "mentor": mentor,
        "status": "Active",
        "day": 0,
        "synergy": synergy,
        "drive_url": "Demo mode — no folder created",
        "calendar_id": "Demo mode — no invite sent",
        "created_at": now.strftime("%d %b %Y, %H:%M"),
        "lifecycle_end": (now + timedelta(days=90)).strftime("%d %b %Y"),
        "email_status": "Demo mode — no email sent",
        "milestones": _milestones(done_through=0),
    }
