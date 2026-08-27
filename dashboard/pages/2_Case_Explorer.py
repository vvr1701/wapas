"""Screen 2 — Case explorer: filterable table -> per-case timeline rendered
purely from the audit log (FR-10.3)."""

import streamlit as st

from dashboard import data

st.set_page_config(page_title="Wapas · Case explorer", page_icon="🪃", layout="wide")
st.title("Case explorer")

with data.session() as db:
    col1, col2 = st.columns(2)
    state = col1.selectbox(
        "State",
        [None, "RECOVERED", "ESCALATED", "STOPPED", "EXHAUSTED", "PROMISE_PENDING"],
        format_func=lambda v: v or "All",
    )
    category = col2.selectbox(
        "Category", [None, "L1", "L2", "L3"], format_func=lambda v: v or "All"
    )
    cases = data.list_cases(db, state=state, category=category)
    st.caption(f"{len(cases)} cases")
    st.dataframe(cases, hide_index=True, use_container_width=True, height=320)

    case_id = st.number_input(
        "Case id for timeline", min_value=1, value=cases[0]["case_id"] if cases else 1
    )
    st.subheader(f"Timeline — case {case_id} (rendered from the audit log only)")
    for entry in data.case_timeline(db, int(case_id)):
        rule = f" · rule `{entry['rule_id']}`" if entry["rule_id"] else ""
        st.markdown(f"**{entry['ts']}** · {entry['actor']} · `{entry['event']}`{rule}")
        rationale = entry["detail"].get("rationale")
        if rationale:
            st.caption(rationale)  # FR-4.2: shown verbatim
        else:
            st.caption(str(entry["detail"]))
