"""Screen 5 — Eval results: 3-arm comparison, promises, cost, exception list,
run manifest."""

import streamlit as st

from dashboard import data

st.set_page_config(page_title="Wapas · Eval results", page_icon="🪃", layout="wide")
st.title("Evaluation — three arms, one world")

m = data.load_metrics()
st.caption(f"Attribution rule: {m['attribution']['rule']}")

arms = m["arms"]
st.dataframe(
    [
        {
            "Arm": name,
            "Recovered raw ₹": f"{a['recovered_raw_inr']:,}",
            "Recovered adj ₹": f"{a.get('recovered_adj_inr', '—'):,}"
            if isinstance(a.get("recovered_adj_inr"), int | float)
            else "—",
            "Recovery rate": f"{a['recovery_rate']:.1%}",
            "Payments": a["payments"],
            "Contacts": a["contacts_made"],
            "Opt-outs": a.get("opt_outs", 0),
        }
        for name, a in arms.items()
    ],
    hide_index=True,
    use_container_width=True,
)

c1, c2, c3 = st.columns(3)
c1.metric("Lift (absolute)", f"{m['headline']['lift']['absolute']:.1%}")
c2.metric("Lift (relative)", f"{m['headline']['lift']['relative']:+.0%}")
c3.metric(
    "Cost per recovered ₹",
    f"₹{m['cost']['cost_per_recovered_inr']:.4f}" if m["cost"]["cost_per_recovered_inr"] else "—",
    help=f"(LLM ${m['cost']['llm_cost_usd']} + comms est ₹{m['cost']['comms_cost_est_inr']}) "
    f"/ adjusted recovery",
)

st.subheader("Promises (voice)")
p = m["promises"]
st.write(
    f"Made **{p['made']}** · kept **{p['kept']}** ({p['kept_rate']:.0%}) · "
    f"₹{p['inr_via_promises']:,} recovered via promises"
)
with data.session() as db:
    st.dataframe(data.promises_list(db), hide_index=True, use_container_width=True)

st.subheader("Honest exception list")
st.markdown(data.exceptions_table())

st.subheader("Run manifest")
st.json(data.load_manifest())
