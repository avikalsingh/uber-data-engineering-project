"""Central design system for the Streamlit dashboard."""

COLORS = {
    "bg_dark": "#060608",
    "bg_panel": "#0c0c10",
    "bg_card": "#111116",
    "bg_hover": "#16161c",
    "bg_input": "#0c0c10",
    "bg_elevated": "#111116",
    "accent_cyan": "#00e5c3",
    "accent_blue": "#00b8ff",
    "accent_gold": "#ffb800",
    "accent_red": "#ff4466",
    "accent_purple": "#a855f7",
    "status_success": "#00e5c3",
    "status_warning": "#ffb800",
    "status_danger": "#ff4444",
    "status_info": "#00b8ff",
    "text_primary": "#d8e4f0",
    "text_secondary": "#4a5a6e",
    "text_tertiary": "#222e3c",
    "text_muted": "rgba(216,228,240,0.3)",
    "border_primary": "rgba(0,229,195,0.18)",
    "border_secondary": "rgba(255,255,255,0.08)",
    "border_subtle": "rgba(255,255,255,0.04)",
}

SPACING = {
    "xs": "4px",
    "sm": "8px",
    "md": "16px",
    "lg": "24px",
    "xl": "32px",
    "2xl": "40px",
}

FONTS = {
    "sans": "'IBM Plex Mono', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    "mono": "'IBM Plex Mono', monospace",
    "display": "'Press Start 2P', 'IBM Plex Mono', monospace",
}

SHADOWS = {
    "sm": "0 4px 14px rgba(0,0,0,0.25)",
    "md": "0 10px 32px rgba(0,0,0,0.32)",
    "lg": "0 22px 70px rgba(0,0,0,0.42)",
    "glow_cyan": "0 0 24px rgba(0,229,195,0.12)",
    "glow_blue": "0 0 24px rgba(0,184,255,0.11)",
}

BORDER_RADIUS = {
    "sm": "4px",
    "md": "6px",
    "lg": "8px",
}

CHART_COLORS = [
    COLORS["accent_cyan"],
    COLORS["accent_blue"],
    COLORS["accent_gold"],
    COLORS["accent_red"],
    COLORS["accent_purple"],
]


def inject_design_system() -> None:
    import streamlit as st

    st.markdown(
        f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;700&family=Press+Start+2P&display=swap');

:root {{
    --bg-dark: {COLORS['bg_dark']};
    --bg-panel: {COLORS['bg_panel']};
    --bg-card: {COLORS['bg_card']};
    --bg-hover: {COLORS['bg_hover']};
    --accent-cyan: {COLORS['accent_cyan']};
    --accent-blue: {COLORS['accent_blue']};
    --accent-gold: {COLORS['accent_gold']};
    --accent-red: {COLORS['accent_red']};
    --text-primary: {COLORS['text_primary']};
    --text-secondary: {COLORS['text_secondary']};
    --text-tertiary: {COLORS['text_tertiary']};
    --text-muted: {COLORS['text_muted']};
    --border-primary: {COLORS['border_primary']};
    --border-secondary: {COLORS['border_secondary']};
    --font-sans: {FONTS['sans']};
    --font-mono: {FONTS['mono']};
    --font-display: {FONTS['display']};
    /* Short-form aliases matching mission-control.html */
    --a: {COLORS['accent_cyan']};
    --bg: {COLORS['bg_dark']};
    --bg2: {COLORS['bg_panel']};
    --bg3: {COLORS['bg_card']};
    --bg4: {COLORS['bg_hover']};
    --b: rgba(0,229,195,0.12);
    --t: {COLORS['text_primary']};
    --t2: {COLORS['text_secondary']};
    --t3: {COLORS['text_tertiary']};
}}

*, *::before, *::after {{
    box-sizing: border-box;
}}

html, body, [data-testid="stAppViewContainer"] {{
    background: var(--bg) !important;
    font-family: var(--font-mono);
}}

[data-testid="stAppViewContainer"] {{
    background:
        radial-gradient(circle at 15% 0%, rgba(0,229,195,0.07), transparent 28%),
        radial-gradient(circle at 85% 8%, rgba(0,184,255,0.06), transparent 30%),
        linear-gradient(rgba(0,229,195,0.02) 1px, transparent 1px),
        linear-gradient(90deg, rgba(0,229,195,0.015) 1px, transparent 1px),
        var(--bg) !important;
    background-size: auto, auto, 42px 42px, 42px 42px !important;
}}

[data-testid="stSidebar"], [data-testid="collapsedControl"], footer {{
    display: none !important;
}}

header[data-testid="stHeader"] {{
    background: transparent !important;
}}

.block-container {{
    padding: 0 !important;
    max-width: 100% !important;
}}

:focus-visible {{
    outline: 2px solid var(--accent-cyan) !important;
    outline-offset: 2px !important;
}}

.app-section {{
    padding: 0 2rem 1.15rem;
}}


.metric-card, .status-card {{
    background: linear-gradient(135deg, rgba(17,26,33,0.96), rgba(8,12,16,0.72));
    border: 1px solid var(--border-primary);
    border-radius: {BORDER_RADIUS['md']};
    box-shadow: {SHADOWS['sm']};
}}

.mission-header {{
    position: sticky;
    top: 0;
    z-index: 999;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 22px;
    padding: 16px 24px;
    border-bottom: 1px solid rgba(0,229,195,0.14);
    background: rgba(6,6,8,0.88);
    backdrop-filter: blur(16px);
    box-shadow: 0 12px 34px rgba(0,0,0,0.28);
}}

.mission-brand {{
    display: flex;
    align-items: center;
    gap: 16px;
    min-width: 0;
}}

.mission-logo {{
    width: 38px;
    height: 38px;
    display: grid;
    place-items: center;
    border: 1px solid rgba(0,229,195,0.32);
    border-radius: {BORDER_RADIUS['md']};
    color: var(--a);
    background: rgba(0,229,195,0.08);
    box-shadow: var(--glow-cyan, {SHADOWS['glow_cyan']});
    font-family: var(--font-mono);
    font-weight: 700;
}}

.mission-kicker {{
    font-family: var(--font-mono);
    font-size: 0.56rem;
    color: var(--text-muted);
    letter-spacing: 0.18em;
    text-transform: uppercase;
}}

.mission-title {{
    margin-top: 6px;
    font-family: var(--font-display);
    font-size: 0.95rem;
    font-weight: 400;
    color: var(--text-primary);
    letter-spacing: 0.03em;
    line-height: 1.4;
    text-shadow: 0 0 18px rgba(0,229,195,0.25);
}}

.mission-subtitle {{
    font-family: var(--font-mono);
    font-size: 0.58rem;
    color: var(--text-tertiary);
    white-space: nowrap;
}}

.mission-status {{
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 10px;
    flex-wrap: wrap;
}}

.mission-chip {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    min-height: 32px;
    padding: 7px 10px;
    border: 1px solid rgba(255,255,255,0.09);
    border-radius: {BORDER_RADIUS['sm']};
    background: rgba(255,255,255,0.035);
    font-family: var(--font-mono);
    font-size: 0.62rem;
    color: var(--text-secondary);
    letter-spacing: 0.07em;
    text-transform: uppercase;
}}

.status-dot {{
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: currentColor;
    box-shadow: 0 0 10px currentColor;
}}

.is-live {{
    color: var(--accent-cyan);
}}

.is-warning {{
    color: var(--accent-gold);
}}

.is-danger {{
    color: var(--accent-red);
}}

.section-heading {{
    display: flex;
    align-items: baseline;
    gap: 12px;
    padding: 1.2rem 2rem 0.65rem;
    border-top: 1px solid rgba(255,255,255,0.045);
}}

.section-heading-label {{
    font-family: var(--font-mono);
    font-size: 0.66rem;
    color: var(--accent-cyan);
    letter-spacing: 0.16em;
    text-transform: uppercase;
}}

.section-heading-sub {{
    font-family: var(--font-mono);
    font-size: 0.58rem;
    color: var(--text-muted);
    letter-spacing: 0.07em;
}}

.ai-panel {{
    position: relative;
    overflow: hidden;
    padding: 20px 20px 16px;
    background: linear-gradient(135deg, rgba(0,229,195,0.055) 0%, rgba(12,12,16,0.92) 48%);
    border: 1px solid rgba(0,229,195,0.22);
    border-top: none;
    border-radius: 0 0 {BORDER_RADIUS['sm']} {BORDER_RADIUS['sm']};
}}

.ai-panel::before {{
    content: "";
    position: absolute;
    inset: 0 0 auto;
    height: 2px;
    background: linear-gradient(90deg, var(--accent-cyan) 0%, rgba(0,229,195,0.15) 100%);
}}

.ai-title {{
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 18px;
    margin-bottom: 14px;
    padding-bottom: 14px;
    border-bottom: 1px solid rgba(0,229,195,0.10);
}}

.ai-title-kicker {{
    font-family: var(--font-mono);
    font-size: 0.58rem;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: var(--accent-cyan);
    margin-bottom: 8px;
}}

.ai-title-main {{
    font-family: var(--font-mono);
    font-size: clamp(1.55rem, 2.4vw, 2.4rem);
    font-weight: 700;
    line-height: 1.05;
    color: var(--text-primary);
}}

.ai-title-sub {{
    max-width: 380px;
    font-family: var(--font-mono);
    font-size: 0.63rem;
    line-height: 1.65;
    color: var(--text-secondary);
    text-align: right;
    padding-top: 4px;
    flex-shrink: 0;
}}

.ai-layer-strip {{
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 6px;
    margin-bottom: 0;
}}

.ai-layer-pill {{
    border: 1px solid rgba(0,229,195,0.16);
    background: rgba(0,229,195,0.03);
    padding: 8px 10px;
    border-radius: {BORDER_RADIUS['sm']};
    font-family: var(--font-mono);
    font-size: 0.54rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--text-secondary);
}}

.ai-layer-pill strong {{
    display: block;
    margin-bottom: 2px;
    color: var(--accent-cyan);
    font-size: 0.58rem;
}}

.metric-card {{
    min-height: 168px;
    padding: 18px 16px 16px;
    position: relative;
    overflow: hidden;
    transition: transform 180ms ease, border-color 180ms ease, box-shadow 180ms ease;
}}

.metric-card:hover {{
    border-color: rgba(0,229,195,0.38);
    box-shadow: {SHADOWS['glow_cyan']};
    transform: translateY(-2px);
}}

.metric-card::before {{
    content: "";
    position: absolute;
    inset: 0 auto 0 0;
    width: 2px;
    background: var(--metric-accent, var(--accent-cyan));
    opacity: 0.72;
}}

.responsive-table-note {{
    color: var(--text-muted);
    font-family: var(--font-mono);
    font-size: 0.62rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}}

.table-shell {{
    border: 1px solid rgba(0,229,195,0.16);
    border-radius: {BORDER_RADIUS['md']};
    background: linear-gradient(135deg, rgba(17,26,33,0.88), rgba(8,12,16,0.66));
    box-shadow: {SHADOWS['sm']};
    overflow: hidden;
}}

.table-shell-header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 12px 14px;
    border-bottom: 1px solid rgba(255,255,255,0.06);
}}

.table-shell-title {{
    font-family: var(--font-mono);
    font-size: 0.65rem;
    color: var(--text-secondary);
    letter-spacing: 0.12em;
    text-transform: uppercase;
}}

.table-shell-count {{
    font-family: var(--font-mono);
    font-size: 0.58rem;
    color: var(--accent-cyan);
    letter-spacing: 0.10em;
    text-transform: uppercase;
}}

.empty-state {{
    border: 1px dashed rgba(0,229,195,0.20);
    background: rgba(0,229,195,0.035);
    border-radius: {BORDER_RADIUS['md']};
    padding: 18px;
    font-family: var(--font-mono);
    color: var(--text-secondary);
    font-size: 0.68rem;
}}

.stTabs [data-baseweb="tab-list"] {{
    background: rgba(0,0,0,0.16) !important;
    border-bottom: 1px solid rgba(0,229,195,0.15);
    gap: 0;
    padding: 0 2rem;
}}

.stTabs [data-baseweb="tab"] {{
    font-family: var(--font-mono) !important;
    font-size: 0.74rem !important;
    letter-spacing: 0.12em !important;
    text-transform: uppercase !important;
    color: rgba(255,255,255,0.46) !important;
    padding: 0.95rem 1.5rem !important;
    border-bottom: 2px solid transparent !important;
    background: transparent !important;
}}

.stTabs [aria-selected="true"] {{
    color: var(--accent-cyan) !important;
    border-bottom: 2px solid var(--accent-cyan) !important;
    background: rgba(0,229,195,0.04) !important;
}}

.stTabs [data-baseweb="tab-panel"] {{
    padding: 0 !important;
    background: transparent !important;
}}

.stDataFrame thead tr th {{
    background: rgba(0,229,195,0.05) !important;
    color: rgba(255,255,255,0.58) !important;
    font-family: var(--font-mono) !important;
    font-size: 0.64rem !important;
    letter-spacing: 0.08em !important;
    text-transform: uppercase !important;
    border-bottom: 1px solid rgba(0,229,195,0.15) !important;
}}

.stDataFrame tbody tr td {{
    color: rgba(255,255,255,0.82) !important;
    font-family: var(--font-mono) !important;
    font-size: 0.74rem !important;
    border-bottom: 1px solid rgba(255,255,255,0.04) !important;
}}

.stDataFrame tbody tr:hover td {{
    background: rgba(0,229,195,0.04) !important;
}}

button[kind="primary"] {{
    background: linear-gradient(135deg, var(--accent-cyan), var(--accent-blue)) !important;
    color: var(--bg-dark) !important;
    font-family: var(--font-mono) !important;
    font-size: 0.7rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.1em !important;
    text-transform: uppercase !important;
    border: none !important;
    border-radius: {BORDER_RADIUS['sm']} !important;
    padding: 0.62rem 1.35rem !important;
    box-shadow: 0 0 18px rgba(0,229,195,0.12) !important;
}}

button[kind="secondary"] {{
    background: rgba(255,255,255,0.025) !important;
    color: rgba(255,255,255,0.68) !important;
    font-family: var(--font-mono) !important;
    font-size: 0.68rem !important;
    letter-spacing: 0.09em !important;
    text-transform: uppercase !important;
    border: 1px solid rgba(255,255,255,0.16) !important;
    border-radius: {BORDER_RADIUS['sm']} !important;
}}

.stSelectbox label, .stNumberInput label, .stTextInput label, .stToggle label {{
    font-family: var(--font-mono) !important;
    font-size: 0.64rem !important;
    color: rgba(255,255,255,0.44) !important;
    letter-spacing: 0.09em !important;
    text-transform: uppercase !important;
}}

[data-testid="stNumberInputContainer"] input,
[data-baseweb="select"],
[data-testid="stTextInput"] input {{
    background: rgba(255,255,255,0.04) !important;
    border: 1px solid rgba(255,255,255,0.10) !important;
    color: white !important;
    font-family: var(--font-mono) !important;
    border-radius: {BORDER_RADIUS['sm']} !important;
}}

.stSuccess {{ background: rgba(0,229,195,0.08) !important; border: 1px solid rgba(0,229,195,0.3) !important; border-radius: {BORDER_RADIUS['sm']} !important; }}
.stError   {{ background: rgba(255,68,102,0.08) !important; border: 1px solid rgba(255,68,102,0.3) !important; border-radius: {BORDER_RADIUS['sm']} !important; }}
.stWarning {{ background: rgba(255,184,0,0.08) !important; border: 1px solid rgba(255,184,0,0.3) !important; border-radius: {BORDER_RADIUS['sm']} !important; }}
.stInfo    {{ background: rgba(0,184,255,0.08) !important; border: 1px solid rgba(0,184,255,0.3) !important; border-radius: {BORDER_RADIUS['sm']} !important; }}
.stProgress > div > div {{ background: var(--accent-cyan) !important; }}

@keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.42; }} }}
@keyframes scan {{ 0% {{ transform: translateX(-120%); }} 100% {{ transform: translateX(420%); }} }}

@media (max-width: 900px) {{
    .app-section {{ padding: 0 1rem 1rem; }}
    .mission-header {{ align-items: flex-start; flex-direction: column; padding: 14px 16px; }}
    .mission-status {{ justify-content: flex-start; }}
    .mission-subtitle {{ white-space: normal; }}
    .section-heading {{ padding: 1rem 1rem 0.55rem; flex-direction: column; gap: 4px; }}
    .ai-panel {{ padding: 16px 12px; }}
    .ai-title {{ display: block; }}
    .ai-title-main {{ font-size: 1.8rem; }}
    .ai-title-sub {{ margin-top: 12px; text-align: left; }}
    .ai-layer-strip {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    .metric-card {{ min-height: 150px; }}
    .stTabs [data-baseweb="tab"] {{ padding: 0.8rem 0.75rem !important; }}
    [data-testid="column"] {{ width: 100% !important; flex: 1 1 100% !important; }}
    .shd {{ padding: 1rem 1rem .55rem; flex-direction: column; gap: 4px; }}
}}

/* ══ KPI Grid (mission-control.html pattern) ══ */
.kpi-grid {{
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  border-top: 1px solid var(--b);
  border-bottom: 1px solid var(--b);
  perspective: 1600px;
}}
.kc {{
  padding: 14px 14px 12px;
  border-right: 1px solid var(--b);
  position: relative;
  overflow: hidden;
  background: var(--bg2);
  opacity: 0;
  transform: perspective(800px) rotateX(65deg) translateY(28px);
  transition: opacity .85s cubic-bezier(.2,0,0,1),
              transform .85s cubic-bezier(.2,0,0,1);
}}
.kc:last-child {{ border-right: none; }}
.kc.vis {{
  opacity: 1;
  transform: perspective(800px) rotateX(0) translateY(0);
}}
.kc:nth-child(1) {{ transition-delay: 0s; }}
.kc:nth-child(2) {{ transition-delay: .07s; }}
.kc:nth-child(3) {{ transition-delay: .14s; }}
.kc:nth-child(4) {{ transition-delay: .21s; }}
.kc:nth-child(5) {{ transition-delay: .28s; }}
.kc:nth-child(6) {{ transition-delay: .35s; }}
.kc:nth-child(7) {{ transition-delay: .42s; }}
.kc-top  {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 6px; margin-bottom: 4px; }}
.kc-lbl  {{ font-size: .58rem; color: var(--t2); letter-spacing: .12em; text-transform: uppercase; line-height: 1.3; }}
.kc-badge {{ font-size: .52rem; color: var(--a); border: 1px solid rgba(0,229,195,.3); padding: 2px 5px; border-radius: 3px; letter-spacing: .08em; white-space: nowrap; flex-shrink: 0; }}
.kc-agg  {{ font-size: .52rem; color: var(--t3); letter-spacing: .06em; margin-bottom: 10px; }}
.kc-val  {{ display: block; font-size: clamp(1.45rem, 2.2vw, 2.1rem); font-weight: 700; color: var(--t); line-height: 1; letter-spacing: -.01em; margin-bottom: 6px; }}
.kc-sub  {{ display: block; font-size: .55rem; color: var(--t2); letter-spacing: .10em; text-transform: uppercase; }}

/* ══ Section headings (.shd) ══ */
.shd {{
  display: flex;
  align-items: baseline;
  gap: 12px;
  padding: 1.2rem 2rem .65rem;
  border-top: 1px solid rgba(255,255,255,.045);
}}
.s-eye {{ font-size: .66rem; color: var(--a); letter-spacing: .16em; text-transform: uppercase; }}
.s-cmt {{ font-size: .58rem; color: var(--t2); letter-spacing: .06em; }}

@media (max-width: 900px) {{
  .kpi-grid {{ grid-template-columns: repeat(4, 1fr); }}
  .kc:nth-child(4n) {{ border-right: none; }}
}}
</style>
""",
        unsafe_allow_html=True,
    )


def render_app_header(eventhub_live: bool, ai_ready: bool) -> None:
    import streamlit as st

    eventhub_class = "is-live" if eventhub_live else "is-danger"
    eventhub_label = "EventHub Live" if eventhub_live else "EventHub Offline"
    ai_class = "is-live" if ai_ready else "is-warning"
    ai_label = "AI Ready" if ai_ready else "AI Disabled"
    st.markdown(
        f"""
<div class="mission-header">
    <div class="mission-brand">
        <div class="mission-logo">UB</div>
        <div>
            <div class="mission-kicker">Uber AI</div>
            <div class="mission-title">Neural Ops</div>
        </div>
        <div class="mission-subtitle">AI Agents · Delta Lake · DLT Pipeline · Azure EventHub</div>
    </div>
    <div class="mission-status">
        <div class="mission-chip {eventhub_class}"><span class="status-dot"></span>{eventhub_label}</div>
        <div class="mission-chip {ai_class}"><span class="status-dot"></span>{ai_label}</div>
        <div class="mission-chip is-live"><span class="status-dot"></span>Databricks SQL</div>
    </div>
</div>
""",
        unsafe_allow_html=True,
    )
