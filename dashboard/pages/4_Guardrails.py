"""Screen 4 — Guardrails & compliance: stops honored, blocked actions with
reasons, opt-out registry, contact-window heatmap."""

import streamlit as st

from dashboard import data

st.set_page_config(page_title="Wapas · Guardrails", page_icon="🪃", layout="wide")
st.title("Guardrails & compliance")

with data.session() as db:
    g = data.guardrails_view(db)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Stops honored", f"{g['stops_honored']:.0%}")
    c2.metric("Actions after opt-out", g["actions_after_optout"])
    c3.metric("Opt-out registry size", g["opt_out_registry_size"])
    c4.metric("Actions cancelled by opt-out", g["cancelled_actions"])

    left, right = st.columns(2)
    with left:
        st.subheader("Blocked actions, by gate reason")
        st.caption("Blocked ≠ silent death: every block is audited and window blocks auto-replan.")
        st.bar_chart(g["blocked_by_reason"])
    with right:
        st.subheader("Customer contacts by IST hour")
        st.caption("Contact window 10:00–19:00 IST is code-enforced; the histogram proves it.")
        st.bar_chart(data.contact_hour_histogram(db))

    st.subheader("Escalation queue (context packets)")
    for e in data.escalation_queue(db)[:20]:
        summary = e["packet"]["case_summary"]
        with st.expander(
            f"#{e['escalation_id']} · case {e['case_id']} · {e['reason']} · "
            f"₹{summary['amount_due_inr']:,}"
        ):
            st.json(e["packet"])
