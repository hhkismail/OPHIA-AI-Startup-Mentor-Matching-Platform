"""
label_app.py — blind labelling of startup-mentor pairs.

  streamlit run ophia-nlp/label_app.py

Shows one pair at a time with the AI's score and reasoning HIDDEN, so the
labels aren't anchored to what the AI said. Every click is saved straight to
output/human_labels.json; close the tab any time and resume later.
Then run: python ophia-nlp/eval_human.py report
"""

import html
import os
import sys
from pathlib import Path

import streamlit as st

import eval_human as eh

# `streamlit run label_app.py -- validation` labels the held-out batch
_default = eh.VALIDATION_PATH if "validation" in sys.argv[1:] else eh.SAMPLE_PATH
SAMPLE_PATH = Path(os.getenv("OPHIA_LABEL_SAMPLE", _default))
LABELS_PATH = Path(os.getenv("OPHIA_LABELS_PATH", eh.LABELS_PATH))

st.set_page_config(page_title="OPHIA — Label pairs", layout="wide")

if not SAMPLE_PATH.exists():
    st.error("No sample yet. Run `python ophia-nlp/eval_human.py build` first.")
    st.stop()

sample = eh.json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
labels = eh.load_labels(LABELS_PATH)
remaining = [p for p in sample if eh.pair_key(p) not in labels]

st.title("Label mentor matches")
st.caption("Would you approve this mentor for this startup? Judge from the profiles only — "
           "the AI's score is hidden on purpose.")
st.progress(len(labels.keys() & {eh.pair_key(p) for p in sample}) / len(sample),
            text=f"{len(sample) - len(remaining)} of {len(sample)} labelled")

with st.sidebar:
    labeller = st.text_input("Your name", value=st.session_state.get("labeller", ""), key="labeller")
    with st.expander("How to label"):
        st.markdown(
            "- **Good** — you'd approve it: the mentor clearly fits this startup's industry and needs\n"
            "- **OK** — acceptable if nothing better: relevant but generic, or a partial fit\n"
            "- **Bad** — you'd reject it: wrong industry, or skills that don't help this startup\n\n"
            "Go with your first reaction; a short note helps when you're unsure.")
    if labels:
        if st.button("↩ Undo last label", key="undo"):
            last = max(labels, key=lambda k: labels[k]["at"])
            del labels[last]
            tmp = LABELS_PATH.with_suffix(".tmp")
            tmp.write_text(eh.json.dumps(labels, indent=1, ensure_ascii=False), encoding="utf-8")
            tmp.replace(LABELS_PATH)
            st.rerun()

if not remaining:
    next_step = "validate" if SAMPLE_PATH == eh.VALIDATION_PATH else "report"
    st.success(f"All {len(sample)} pairs labelled — thank you! "
               f"Now run `python ophia-nlp/eval_human.py {next_step}`.")
    st.stop()

pair = remaining[0]
s, m = pair["startup"], pair["mentor"]
esc = html.escape

left, right = st.columns(2, gap="large")
with left:
    st.subheader(f"🚀 {pair['startup_name']}")
    st.markdown(f"**{esc(s.get('description') or '')}**")
    if s.get("long_description"):
        st.write(s["long_description"])
    st.caption(" · ".join(filter(None, [", ".join(s.get("industry_tags") or []), s.get("country"),
                                        f"batch {s['batch']}" if s.get("batch") else None])))
with right:
    st.subheader(f"👤 {pair['mentor_name']}")
    st.markdown(f"**{esc(m.get('title') or '')}**")
    st.write(m.get("bio") or "")
    expertise = list(dict.fromkeys((m.get("skills") or []) + (m.get("industry_tags") or [])))
    st.caption(" · ".join(filter(None, [", ".join(expertise),
                                        f"{m['availability_hours']}h/month" if m.get("availability_hours") else None])))

st.divider()
key = eh.pair_key(pair)
note = st.text_input("Note (optional)", key=f"note_{key}", placeholder="e.g. right industry, wrong stage")
cols = st.columns([1, 1, 1, 3])
for col, (label, text) in zip(cols, [("good", "✅ Good"), ("ok", "➖ OK"), ("bad", "❌ Bad")]):
    if col.button(text, key=f"{label}_{key}", use_container_width=True):
        eh.save_label(key, label, note=note, labeller=labeller, path=LABELS_PATH)
        st.rerun()
