"""Screen 1 — Command center (FR-12.1). Run: make dashboard"""

import streamlit as st

from dashboard import data

st.set_page_config(page_title="Wapas · Command center", page_icon="🪃", layout="wide")
st.title("🪃 Wapas — Revenue Recovery Command Center")
st.caption("Every number on this screen traces to a `results/metrics.json` key. Seed 42 eval run.")

k = data.kpis()
c1, c2, c3, c4 = st.columns(4)
c1.metric("₹ at risk", f"₹{k['at_risk_inr']:,}")
c2.metric("₹ recovered (raw)", f"₹{k['recovered_raw_c_inr']:,}")
c3.metric(
    "₹ recovered (adjusted)",
    f"₹{k['recovered_adj_c_inr']:,.0f}",
    help="raw − natural_rate × at-risk of touched cases (arm-A adjustment)",
)
c4.metric("Lift vs baseline", f"{k['lift_relative']:+.0%}")

c5, c6, c7, c8 = st.columns(4)
c5.metric("Stops honored", f"{k['stops_honored']:.0%}")
c6.metric("Promises kept", f"{k['promises_kept_rate']:.0%}")
c7.metric("Natural recovery rate", f"{k['natural_rate']:.1%}")
c8.metric("Honest exceptions", k["exceptions_count"])

with data.session() as db:
    left, right = st.columns(2)
    with left:
        st.subheader("Recovery by category")
        st.dataframe(
            [
                {
                    "Category": r["category"],
                    "Cases": r["cases"],
                    "At risk ₹": f"{r['at_risk_inr']:,}",
                    "Recovered ₹": f"{r['recovered_inr']:,}",
                    "Rate": f"{r['rate']:.0%}",
                }
                for r in data.recovery_by_category(db)
            ],
            hide_index=True,
            use_container_width=True,
        )
    with right:
        st.subheader("Cases by final state")
        st.bar_chart(data.cases_by_state(db))

st.divider()
m = data.load_manifest()
st.caption(
    f"Run manifest: seed {m['seed']} · batch {m['batch_hash'][:12]}… · "
    f"world {m['world_hash'][:12]}… (equal across arms: {m['world_hash_equal_across_arms']}) · "
    f"policy {m['policy_version_hash'][:12]}… · {m['audit_chain']}"
)
