"""Agentic AI popup chat — ReAct agent with Databricks tools, triggered via a floating FAB button.

Trigger mechanism: a visually-hidden Streamlit checkbox is injected into the page.
The FAB's click handler does a native DOM .click() on that checkbox element, which
React picks up immediately (no synthetic-event tricks needed), causing a Streamlit
rerun with the new checkbox value, which opens the @st.dialog.
"""

import streamlit as st

from react_agent_service import answer_with_react_agent, is_react_agent_configured
from supervisor_service import (
    answer_with_full_report,
    answer_with_supervisor,
    is_supervisor_configured,
    run_step,
    synthesize_city_report,
)


# Unique label used to locate the hidden checkbox in the DOM.
_TRIGGER_LABEL = "⚡​agent"  # ⚡<zero-width-space>agent — visually minimal, unique


_FAB_INJECTOR = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body>
<script>
(function () {
  var FAB_ID   = 'uber-agent-fab';
  var STYLE_ID = 'uber-agent-fab-styles';
  var LABEL    = '⚡​agent';   /* must match _TRIGGER_LABEL in Python */
  var pd;
  try { pd = window.parent.document; }
  catch (e) { return; }

  /* idempotent */
  if (pd.getElementById(FAB_ID)) return;

  if (!pd.getElementById(STYLE_ID)) {
    var sty = pd.createElement('style');
    sty.id = STYLE_ID;
    sty.textContent = `
      @keyframes ua-fab-pop {
        0%   { opacity:0; transform:scale(.5) translateY(8px) }
        70%  { opacity:1; transform:scale(1.07) translateY(-2px) }
        100% { opacity:1; transform:scale(1) }
      }
      #uber-agent-fab {
        position: fixed; bottom: 90px; right: 28px;
        width: 52px; height: 52px; border-radius: 50%;
        background: linear-gradient(135deg, #7c3aed, #6366f1);
        border: none; cursor: pointer; color: #fff;
        display: grid; place-items: center;
        box-shadow: 0 0 28px rgba(124,58,237,.4), 0 8px 24px rgba(0,0,0,.32);
        animation: ua-fab-pop .55s 1.05s cubic-bezier(.34,1.56,.64,1) both;
        transition: transform .18s ease, box-shadow .18s ease;
        z-index: 99998;
        font-family: inherit;
      }
      #uber-agent-fab:hover {
        transform: scale(1.09);
        box-shadow: 0 0 44px rgba(124,58,237,.6), 0 10px 32px rgba(0,0,0,.4);
      }
      #uber-agent-fab svg { width: 22px; height: 22px; pointer-events: none; }
      #ua-tooltip {
        position: fixed; bottom: 100px; right: 88px;
        background: rgba(12,12,16,.92); border: 1px solid rgba(124,58,237,.3);
        color: rgba(216,228,240,.8); font-size: .58rem; letter-spacing: .08em;
        padding: 5px 10px; border-radius: 6px; pointer-events: none;
        opacity: 0; transition: opacity .18s; white-space: nowrap;
        font-family: 'IBM Plex Mono', ui-monospace, monospace; z-index: 99998;
      }
      #uber-agent-fab:hover + #ua-tooltip { opacity: 1; }
    `;
    pd.head.appendChild(sty);
  }

  var fab = pd.createElement('button');
  fab.id = FAB_ID;
  fab.setAttribute('aria-label', 'Open AI Agent');
  fab.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M12 2L2 7l10 5 10-5-10-5z"/>
    <path d="M2 17l10 5 10-5"/>
    <path d="M2 12l10 5 10-5"/>
  </svg>`;

  var tip = pd.createElement('div');
  tip.id = 'ua-tooltip';
  tip.textContent = 'AI Agent';

  pd.body.appendChild(fab);
  pd.body.appendChild(tip);

  fab.addEventListener('click', function () {
    /* Find the hidden Streamlit checkbox by its aria-label and native-click it.
       A native .click() is picked up by React immediately and causes a Streamlit
       rerun — no synthetic event tricks needed. */
    var chk = pd.querySelector('input[type="checkbox"][aria-label="' + LABEL + '"]');
    if (chk) {
      chk.click();
    } else {
      console.warn('[uber-agent-fab] trigger checkbox not found in DOM');
    }
  });
})();
</script>
</body></html>
"""

# CSS injected once to visually hide the trigger checkbox while keeping it in the DOM.
_HIDE_CHECKBOX_CSS = (
    "<style>"
    "[data-testid='stCheckbox']:has(input[aria-label='⚡​agent'])"
    "{ position:fixed!important; top:-9999px!important; left:-9999px!important;"
    " width:1px!important; height:1px!important; overflow:hidden!important; }"
    "</style>"
)


# Agent badge definitions shared by both dialog modes
_AGENT_BADGES = [
    ("Gold", "KPIs &amp; executive metrics"),
    ("Silver", "Enriched ride signals"),
    ("ML", "Demand &amp; surge forecasts"),
    ("Context", "Market reference data"),
]

_AGENT_BADGE_HTML = (
    '<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px;">'
    + "".join(
        f'<div style="font-size:.65rem;font-weight:700;letter-spacing:.1em;'
        f'text-transform:uppercase;color:#a78bfa;padding:4px 10px;'
        f'border:1px solid rgba(124,58,237,.28);border-radius:4px;">'
        f'<strong>{t[0]}</strong>&nbsp;&nbsp;{t[1]}</div>'
        for t in _AGENT_BADGES
    )
    + "</div>"
)

_EXAMPLES = [
    "What's the total revenue in New York?",
    "Which are the top 5 cities by revenue?",
    "Give me a silver-layer deep dive for Chicago",
    "Compare surge pricing between New York and Los Angeles",
    "Predict demand for Dallas over the next 3 hours",
    "What is the surge pressure in Las Vegas?",
    "Add market context for San Diego",
    "Show me demand metrics for Chicago",
    "What are peak surge hours?",
    "Show me the KPI dashboard",
]


def _render_agents_called(agents: list[str]) -> str:
    """Render a compact routing badge string for the metadata panel."""
    label_map = {
        "gold_agent": "Gold",
        "silver_agent": "Silver",
        "ml_agent": "ML",
        "context_agent": "Context",
        "supervisor": "Supervisor",
    }
    return " → ".join(label_map.get(a, a) for a in agents)


@st.dialog("AI Operations Analyst", width="large")
def _agent_dialog() -> None:
    supervisor_ready = is_supervisor_configured()
    react_ready = is_react_agent_configured()

    st.markdown(_AGENT_BADGE_HTML, unsafe_allow_html=True)

    tab_chat, tab_report = st.tabs(["💬  Chat", "📊  Full City Report"])

    # ------------------------------------------------------------------ #
    # Tab 1 — Chat (Supervisor or ReAct)
    # ------------------------------------------------------------------ #
    with tab_chat:
        col_mode, _ = st.columns([2, 3])
        with col_mode:
            mode = st.radio(
                "Agent mode",
                ["Supervisor", "ReAct"],
                horizontal=True,
                key="agent_popup_mode",
                help="Supervisor: LangGraph multi-agent routing. ReAct: single flat-tool agent.",
                label_visibility="collapsed",
            )

        use_supervisor = mode == "Supervisor"

        if use_supervisor and not supervisor_ready:
            st.info("Configure GEMINI_API_KEY and Databricks credentials to enable the Supervisor.")
        elif not use_supervisor and not react_ready:
            st.info("Configure GEMINI_API_KEY and Databricks credentials to enable the ReAct agent.")
        else:
            history_key = "supervisor_history" if use_supervisor else "react_agent_history"
            if history_key not in st.session_state:
                st.session_state[history_key] = []

            col_ex, col_use, col_clear = st.columns([5, 1.2, 1.2])
            with col_ex:
                selected = st.selectbox(
                    "Example questions", [""] + _EXAMPLES,
                    key="agent_popup_example", label_visibility="collapsed",
                )
            with col_use:
                use_clicked = st.button(
                    "Use Example", type="secondary",
                    use_container_width=True, key="agent_popup_use",
                )
            with col_clear:
                if st.button(
                    "Clear Chat", type="secondary",
                    use_container_width=True, key="agent_popup_clear",
                ):
                    st.session_state[history_key] = []
                    st.rerun()

            if use_clicked and selected:
                st.session_state.agent_popup_prefill = selected

            chat_area = st.container(height=320, border=False)
            with chat_area:
                history = st.session_state[history_key]
                if not history:
                    hint = (
                        "Supervisor routes your question across Gold, Silver, ML, and Context agents."
                        if use_supervisor
                        else "Ask about revenue, demand, surge pressure, or market context."
                    )
                    st.markdown(
                        f'<div style="text-align:center;padding:40px 24px;'
                        f'color:rgba(216,228,240,.35);font-size:.75rem;">{hint}</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    for msg in history[-14:]:
                        with st.chat_message(msg["role"]):
                            st.markdown(msg["content"])
                            if msg["role"] == "assistant" and msg.get("metadata"):
                                meta = msg["metadata"]
                                routed = meta.get("agents_called", [])
                                label = (
                                    f"Routed via: {_render_agents_called(routed)}"
                                    if routed and use_supervisor
                                    else "Execution details"
                                )
                                with st.expander(label):
                                    st.json(meta)

            prefill = st.session_state.pop("agent_popup_prefill", "")
            placeholder = (
                "Ask a question — supervisor routes to the right agent…"
                if use_supervisor
                else "Ask about revenue, demand, surge, forecasts…"
            )
            question = st.chat_input(placeholder=placeholder, key="agent_popup_input")
            if not question and prefill:
                question = prefill

            if question and question.strip():
                q = question.strip()
                st.session_state[history_key].append({"role": "user", "content": q})
                history = st.session_state[history_key]
                with chat_area:
                    with st.chat_message("user"):
                        st.markdown(q)
                    with st.chat_message("assistant"):
                        spin = (
                            "Supervisor routing to sub-agents…"
                            if use_supervisor
                            else "Routing to curated tools…"
                        )
                        with st.spinner(spin):
                            result = (
                                answer_with_supervisor(q, history[:-1])
                                if use_supervisor
                                else answer_with_react_agent(q, history[:-1])
                            )
                        if result["ok"]:
                            st.markdown(result["answer"])
                        else:
                            st.warning(result["answer"])
                        if result.get("metadata"):
                            routed = result["metadata"].get("agents_called", [])
                            label = (
                                f"Routed via: {_render_agents_called(routed)}"
                                if routed and use_supervisor
                                else "Execution details"
                            )
                            with st.expander(label):
                                st.json(result["metadata"])
                st.session_state[history_key].append(
                    {
                        "role": "assistant",
                        "content": result["answer"],
                        "metadata": result.get("metadata", {}),
                    }
                )
                st.rerun()

    # ------------------------------------------------------------------ #
    # Tab 2 — Full City Report (sequential orchestration)
    # ------------------------------------------------------------------ #
    with tab_report:
        if not supervisor_ready:
            st.info("Configure GEMINI_API_KEY and Databricks credentials to generate city reports.")
        else:
            st.markdown(
                '<p style="font-size:.72rem;color:rgba(216,228,240,.5);margin-bottom:8px;">'
                "Runs Gold → Silver → ML → Context agents sequentially, then synthesizes a "
                "full city report. Takes ~30–60 seconds."
                "</p>",
                unsafe_allow_html=True,
            )

            col_city, col_btn = st.columns([3, 1])
            with col_city:
                city_input = st.text_input(
                    "City",
                    placeholder="e.g. New York, Chicago, Las Vegas",
                    key="report_city_input",
                    label_visibility="collapsed",
                )
            with col_btn:
                generate = st.button(
                    "Generate", type="primary",
                    use_container_width=True, key="report_generate_btn",
                )

            if st.button(
                "Clear report", type="secondary",
                use_container_width=False, key="report_clear_btn",
            ):
                st.session_state.pop("full_report_result", None)
                st.rerun()

            # Run sequential orchestration with live step progress
            if generate and city_input.strip():
                city = city_input.strip()
                sections: dict[str, str] = {}
                started = __import__("time").time()

                _STEPS = [
                    ("gold",    "Gold layer — KPIs & revenue"),
                    ("silver",  "Silver layer — operational deep dive"),
                    ("ml",      "ML forecasts — demand & surge"),
                    ("context", "Context — market archetype & RAG"),
                ]

                with st.status(
                    f"Generating full report for **{city}**…", expanded=True
                ) as status_widget:
                    for step_key, step_label in _STEPS:
                        st.write(f"Querying {step_label}…")
                        sections[step_key] = run_step(step_key, city)
                        st.write(f"✓ {step_label} complete")

                    st.write("Synthesizing final report…")
                    report_text = synthesize_city_report(city, sections)
                    elapsed = round(__import__("time").time() - started, 1)
                    status_widget.update(
                        label=f"Report for {city} ready — {elapsed}s",
                        state="complete",
                        expanded=False,
                    )

                st.session_state.full_report_result = {
                    "city": city,
                    "report": report_text,
                    "elapsed": elapsed,
                }

            # Render cached report
            cached = st.session_state.get("full_report_result")
            if cached:
                st.divider()
                st.markdown(cached["report"])
                with st.expander("Report metadata"):
                    st.json({
                        "city": cached["city"],
                        "mode": "Sequential Full-City Report",
                        "agents_called": ["gold_agent", "silver_agent", "ml_agent", "context_agent", "synthesizer"],
                        "execution_time_seconds": cached.get("elapsed"),
                    })


def _on_agent_trigger_change() -> None:
    """on_change is the one place Streamlit lets us reset the widget's own key."""
    if st.session_state.get("agent_chat_trigger"):
        st.session_state.agent_chat_trigger = False
        st.session_state._open_agent_dialog = True


def render_agentic_popup_chat() -> None:
    # 1. Inject the floating purple FAB into the parent document
    st.iframe(_FAB_INJECTOR, height=1)

    # 2. CSS to keep the checkbox off-screen while it remains in the DOM
    st.markdown(_HIDE_CHECKBOX_CSS, unsafe_allow_html=True)

    # 3. Hidden checkbox — FAB JS calls .click() on this; on_change captures the
    #    edge and immediately resets the widget so the next click works again.
    st.checkbox(
        _TRIGGER_LABEL,
        key="agent_chat_trigger",
        label_visibility="collapsed",   # collapsed > hidden — no reserved space
        on_change=_on_agent_trigger_change,
    )

    if st.session_state.pop("_open_agent_dialog", False):
        try:
            _agent_dialog()
        except AttributeError:
            st.info("Upgrade Streamlit to ≥ 1.36 to use the AI Agent popup.")