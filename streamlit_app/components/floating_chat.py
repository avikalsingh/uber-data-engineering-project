"""Floating chat popup — Claude/ChatGPT-style widget injected into the parent Streamlit DOM.

Injects CSS + HTML + JS directly into window.parent.document (same-origin via srcdoc iframe).
This avoids the fragile window.frameElement overlay approach entirely.
"""

import json
import os

import streamlit as st

from config_utils import get_secret


_SYSTEM_BASE = """You are an AI assistant for the Uber Real-Time Data Engineering Mission Control dashboard.

The dashboard monitors a live Uber-style ride-sharing platform built on:
- Azure EventHub (live ride event ingestion)
- Databricks Delta Lake with DLT pipelines (Bronze → Silver → Gold medallion architecture)
- Streamlit (this real-time analytics dashboard)

Answer questions about the pipeline, data architecture, KPIs, ride analytics, and operational insights.
Be concise and technical. 2–4 sentences unless detail is needed. Plain text only.
Always use the exact live figures provided below — never invent or estimate numbers."""


def _build_system_prompt(live_data: dict | None) -> str:
    if not live_data:
        return _SYSTEM_BASE + "\n\nNo live data is available right now."

    k = live_data.get("kpis") or {}
    cities = live_data.get("by_city") or []
    drivers = live_data.get("drivers") or []
    regions = live_data.get("by_region") or []
    vehicles = live_data.get("by_vehicle") or []

    def fmt(val, prefix="", suffix="", fallback="N/A"):
        return f"{prefix}{val}{suffix}" if val is not None else fallback

    city_lines = "\n".join(
        f"  {i+1}. {c.get('city','?')}: {c.get('total_rides','?')} rides, ${c.get('total_revenue','?')} revenue"
        for i, c in enumerate(cities[:10])
    ) or "  (no data)"

    driver_lines = "\n".join(
        f"  {i+1}. {d.get('driver_name','?')}: {d.get('total_rides','?')} rides, "
        f"${d.get('total_revenue','?')} revenue, {d.get('driver_rating','?')} rating"
        for i, d in enumerate(drivers[:5])
    ) or "  (no data)"

    region_lines = "\n".join(
        f"  {r.get('region','?')}: {r.get('total_rides','?')} rides, ${r.get('total_revenue','?')} revenue"
        for r in regions
    ) or "  (no data)"

    vehicle_lines = "\n".join(
        f"  {v.get('vehicle_type','?')}: {v.get('total_rides','?')} rides, avg fare ${v.get('avg_fare','?')}"
        for v in vehicles
    ) or "  (no data)"

    data_section = f"""

=== LIVE DASHBOARD DATA (current snapshot from Databricks Gold layer) ===

KPIs:
  Total rides:        {fmt(k.get('total_rides'))}
  Total revenue:      {fmt(k.get('total_revenue'), '$')}
  Avg fare:           {fmt(k.get('avg_fare'), '$')}
  Avg surge:          {fmt(k.get('avg_surge'), suffix='x')}
  Avg rating:         {fmt(k.get('avg_rating'), suffix='/5')}
  Avg distance:       {fmt(k.get('avg_distance'), suffix=' miles')}
  Cancellation rate:  {fmt(k.get('cancellation_rate'), suffix='%')}

Top cities by rides:
{city_lines}

Top drivers:
{driver_lines}

Revenue by region:
{region_lines}

Rides by vehicle type:
{vehicle_lines}
======================================================================="""

    return _SYSTEM_BASE + data_section


_INJECTOR_TEMPLATE = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body>
<script>
(function () {
  var ROOT_ID   = 'uber-chat-root';
  var STYLE_ID  = 'uber-chat-styles';
  var API_KEY   = __API_KEY__;
  var MODELS    = __MODELS__;   /* ordered fallback list */
  var SYSTEM    = __SYSTEM__;
  var activeModel = MODELS[0];

  /* ── Access parent document ── */
  var pd;
  try { pd = window.parent.document; }
  catch (e) { return; }

  /* ── Inject/refresh styles (always update so CSS changes take effect) ── */
  var sty = pd.getElementById(STYLE_ID);
  if (!sty) { sty = pd.createElement('style'); sty.id = STYLE_ID; pd.head.appendChild(sty); }
  sty.textContent = `
      @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;700&display=swap');

      #uber-chat-root *,
      #uber-chat-root *::before,
      #uber-chat-root *::after { box-sizing: border-box; }

      #uber-chat-root {
        position: fixed; inset: 0;
        pointer-events: none;
        z-index: 99999;
        font-family: 'IBM Plex Mono', ui-monospace, monospace;
      }

      /* Animations */
      @keyframes uc-fab-pop  { 0%{opacity:0;transform:scale(.5) translateY(8px)} 70%{opacity:1;transform:scale(1.07) translateY(-2px)} 100%{opacity:1;transform:scale(1)} }
      @keyframes uc-pulse    { 0%,100%{opacity:1} 50%{opacity:.3} }
      @keyframes uc-msg-in   { from{opacity:0;transform:translateY(6px)} to{opacity:1;transform:translateY(0)} }
      @keyframes uc-dot-b    { 0%,80%,100%{transform:translateY(0);opacity:.4} 40%{transform:translateY(-5px);opacity:1} }
      @keyframes uc-blink    { 50%{opacity:0} }

      /* FAB */
      #uc-fab {
        position: fixed; bottom: 28px; right: 28px;
        width: 52px; height: 52px; border-radius: 50%;
        background: linear-gradient(135deg, #00e5c3, #00b8ff);
        border: none; cursor: pointer; color: #060608;
        display: grid; place-items: center;
        box-shadow: 0 0 28px rgba(0,229,195,.38), 0 8px 24px rgba(0,0,0,.32);
        animation: uc-fab-pop .55s .8s cubic-bezier(.34,1.56,.64,1) both;
        transition: transform .18s ease, box-shadow .18s ease;
        pointer-events: all; z-index: 1;
      }
      #uc-fab:hover { transform: scale(1.09); box-shadow: 0 0 42px rgba(0,229,195,.54), 0 10px 32px rgba(0,0,0,.4); }
      #uc-fab svg   { width: 22px; height: 22px; pointer-events: none; }

      /* Backdrop */
      #uc-backdrop {
        position: fixed; inset: 0;
        background: rgba(0,0,0,.38);
        opacity: 0; pointer-events: none;
        transition: opacity .38s cubic-bezier(.4,0,.2,1);
        z-index: 0;
      }
      #uc-backdrop.uc-open { opacity: 1; pointer-events: all; }

      /* Panel */
      #uc-panel {
        position: fixed; top: 0; right: 0;
        width: 420px; max-width: 100vw; height: 100dvh;
        display: flex; flex-direction: column;
        background: #0c0c10;
        border-left: 1px solid rgba(0,229,195,.14);
        box-shadow: -8px 0 40px rgba(0,0,0,.5), 0 0 0 1px rgba(0,229,195,.05);
        overflow: hidden;
        transform: translateX(100%);
        transition: transform .38s cubic-bezier(.4,0,.2,1);
        pointer-events: none;
        z-index: 1;
      }
      #uc-panel.uc-open { transform: translateX(0); pointer-events: all; }

      /* Header */
      #uc-hdr {
        display: flex; align-items: center; gap: 8px;
        padding: 14px 16px;
        border-bottom: 1px solid rgba(255,255,255,.05);
        background: rgba(0,0,0,.3);
        flex-shrink: 0;
      }
      .uc-hdr-brand  { display: flex; align-items: center; gap: 10px; flex: 1; min-width: 0; }
      .uc-hdr-dot    {
        width: 8px; height: 8px; border-radius: 50%;
        background: #00e5c3; box-shadow: 0 0 10px #00e5c3;
        animation: uc-pulse 2s infinite; flex-shrink: 0;
      }
      .uc-hdr-title  { font-size: .78rem; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; color: #d8e4f0; }
      .uc-hdr-model  { font-size: .58rem; color: rgba(216,228,240,.32); letter-spacing: .1em; margin-top: 2px; }
      .uc-hdr-acts   { display: flex; gap: 4px; flex-shrink: 0; }
      .uc-icon-btn   {
        background: none; border: 1px solid transparent;
        color: rgba(255,255,255,.36); width: 28px; height: 28px;
        border-radius: 5px; cursor: pointer; font-size: .8rem;
        display: grid; place-items: center; transition: all .15s;
      }
      .uc-icon-btn:hover { color: rgba(255,255,255,.88); border-color: rgba(255,255,255,.12); }
      #uc-close { color: rgba(255,255,255,.5); }

      /* Messages */
      #uc-msgs {
        flex: 1; overflow-y: auto; overflow-x: hidden;
        padding: 20px 16px;
        display: flex; flex-direction: column; gap: 20px;
        scroll-behavior: smooth;
      }
      #uc-msgs::-webkit-scrollbar { width: 4px; }
      #uc-msgs::-webkit-scrollbar-thumb { background: rgba(255,255,255,.06); border-radius: 2px; }

      .uc-group      { display: flex; flex-direction: column; gap: 6px; animation: uc-msg-in .28s ease; width: 100%; min-width: 0; }
      .uc-group.user { align-items: flex-end; }
      .uc-group.ai   { align-items: flex-start; }
      .uc-label      { font-size: .6rem; letter-spacing: .14em; text-transform: uppercase; color: rgba(216,228,240,.28); padding: 0 4px; display: flex; align-items: center; gap: 6px; }
      .uc-label .uc-d { width: 5px; height: 5px; border-radius: 50%; background: #00e5c3; }
      .uc-bubble     { font-size: .88rem; line-height: 1.7; padding: 14px; word-break: break-word; overflow-wrap: anywhere; white-space: pre-wrap; max-width: 82%; box-sizing: border-box; overflow: hidden; }
      .uc-group.user .uc-bubble { background: rgba(0,229,195,.07); border: 1px solid rgba(0,229,195,.22); border-radius: 14px 14px 3px 14px; color: #d8e4f0; }
      .uc-group.ai   .uc-bubble { background: rgba(255,255,255,.032); border: 1px solid rgba(255,255,255,.055); border-radius: 3px 14px 14px 14px; color: #c8d8e8; }

      /* Typing dots */
      .uc-typing { display: flex; gap: 5px; padding: 12px 14px; background: rgba(255,255,255,.032); border: 1px solid rgba(255,255,255,.055); border-radius: 3px 14px 14px 14px; width: fit-content; }
      .uc-typing span { width: 6px; height: 6px; border-radius: 50%; background: #00e5c3; opacity: .4; animation: uc-dot-b 1.2s infinite; }
      .uc-typing span:nth-child(2) { animation-delay: .16s; }
      .uc-typing span:nth-child(3) { animation-delay: .32s; }

      /* Cursor */
      .uc-cursor { display: inline-block; width: 7px; height: .9em; background: #00e5c3; vertical-align: -2px; margin-left: 1px; animation: uc-blink 1s steps(2) infinite; }

      /* Empty state */
      #uc-empty { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; text-align: center; padding: 32px 24px; }
      .uc-empty-icon { width: 44px; height: 44px; border-radius: 50%; background: rgba(0,229,195,.08); border: 1px solid rgba(0,229,195,.22); display: grid; place-items: center; color: #00e5c3; font-size: 1.2rem; margin-bottom: 6px; }
      .uc-empty-title { font-size: .95rem; font-weight: 700; color: #d8e4f0; letter-spacing: .04em; }
      .uc-empty-sub   { font-size: .76rem; color: rgba(216,228,240,.35); line-height: 1.65; max-width: 260px; }

      /* Suggestions */
      #uc-sug { padding: 0 16px 12px; display: flex; flex-direction: column; gap: 6px; }
      .uc-sug-lbl { font-size: .6rem; letter-spacing: .14em; text-transform: uppercase; color: rgba(216,228,240,.24); }
      .uc-chips   { display: flex; flex-wrap: wrap; gap: 6px; }
      .uc-chip { font-size: .75rem; padding: 6px 12px; border-radius: 20px; background: rgba(255,255,255,.035); border: 1px solid rgba(255,255,255,.08); color: rgba(216,228,240,.58); cursor: pointer; letter-spacing: .02em; transition: all .15s; font-family: inherit; }
      .uc-chip:hover { color: #00e5c3; border-color: rgba(0,229,195,.32); background: rgba(0,229,195,.04); }

      /* Composer — 16px horizontal to match msgs and sug */
      #uc-composer { padding: 12px 16px 16px; border-top: 1px solid rgba(255,255,255,.05); background: rgba(0,0,0,.25); flex-shrink: 0; }
      .uc-comp-row { display: flex; gap: 8px; align-items: flex-end; background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.09); border-radius: 10px; padding: 8px 8px 8px 12px; transition: border-color .15s; }
      .uc-comp-row:focus-within { border-color: rgba(0,229,195,.42); }
      #uc-input { flex: 1; resize: none; background: none; border: none; outline: none; color: #d8e4f0; font-family: inherit; font-size: .88rem; line-height: 1.6; min-height: 22px; max-height: 120px; }
      #uc-input::placeholder { color: rgba(216,228,240,.22); }
      #uc-input:disabled { opacity: .4; }
      #uc-send { background: linear-gradient(135deg, #00e5c3, #00b8ff); border: none; border-radius: 7px; width: 32px; height: 32px; flex-shrink: 0; color: #060608; cursor: pointer; display: grid; place-items: center; transition: opacity .15s; }
      #uc-send:disabled { opacity: .3; cursor: not-allowed; }
      .uc-hint { margin-top: 7px; font-size: .58rem; letter-spacing: .08em; text-transform: uppercase; color: rgba(216,228,240,.2); display: flex; justify-content: space-between; }
    `;

  /* ── Idempotency: only inject HTML once ── */
  if (pd.getElementById(ROOT_ID)) return;

  /* ── Inject HTML into parent body ── */
  var root = pd.createElement('div');
  root.id = ROOT_ID;
  root.innerHTML = `
    <div id="uc-backdrop"></div>

    <button id="uc-fab" aria-label="Open AI chat">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
      </svg>
    </button>

    <div id="uc-panel">
      <div id="uc-hdr">
        <button class="uc-icon-btn" id="uc-close" title="Close chat">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
        <div class="uc-hdr-brand">
          <div class="uc-hdr-dot"></div>
          <div>
            <div class="uc-hdr-title">Uber DE · AI</div>
            <div class="uc-hdr-model" id="uc-model-lbl">gemini · mission control</div>
          </div>
        </div>
        <div class="uc-hdr-acts">
          <button class="uc-icon-btn" id="uc-new" title="New chat">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
            </svg>
          </button>
        </div>
      </div>

      <div id="uc-msgs"></div>

      <div id="uc-empty">
        <div class="uc-empty-icon">✦</div>
        <div class="uc-empty-title">Uber DE Assistant</div>
        <div class="uc-empty-sub">Ask about KPIs, pipeline health, surge, revenue, or the data platform architecture.</div>
      </div>

      <div id="uc-sug">
        <div class="uc-sug-lbl">Try asking</div>
        <div class="uc-chips" id="uc-chips"></div>
      </div>

      <div id="uc-composer">
        <div class="uc-comp-row">
          <textarea id="uc-input" rows="1" placeholder="Ask anything about the dashboard…"></textarea>
          <button id="uc-send" aria-label="Send">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round">
              <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
            </svg>
          </button>
        </div>
        <div class="uc-hint">
          <span>↵ send · ⇧↵ newline</span>
          <span id="uc-status">ready</span>
        </div>
      </div>
    </div>
  `;
  pd.body.appendChild(root);

  /* ── Wire up logic ── */
  var $fab      = pd.getElementById('uc-fab');
  var $backdrop = pd.getElementById('uc-backdrop');
  var $panel    = pd.getElementById('uc-panel');
  var $msgs     = pd.getElementById('uc-msgs');
  var $empty    = pd.getElementById('uc-empty');
  var $sug      = pd.getElementById('uc-sug');
  var $chips    = pd.getElementById('uc-chips');
  var $input    = pd.getElementById('uc-input');
  var $send     = pd.getElementById('uc-send');
  var $status   = pd.getElementById('uc-status');

  var history = [];
  var busy    = false;

  /* Set initial model label */
  pd.getElementById('uc-model-lbl').textContent = activeModel + ' · mission control';

  var SUGGESTIONS = [
    "What's the current revenue and avg fare?",
    "Which cities have the highest surge?",
    "How does the DLT pipeline work?",
    "Who are the top earning drivers?",
    "Explain the Bronze → Silver → Gold architecture",
    "What does the cancellation rate tell us?",
  ];

  /* Open / close */
  function setOpen(v) {
    $panel.classList.toggle('uc-open', v);
    $backdrop.classList.toggle('uc-open', v);
    if (v) setTimeout(function(){ $input.focus(); }, 300);
  }
  $fab.addEventListener('click',      function(){ setOpen(true); });
  $backdrop.addEventListener('click', function(){ setOpen(false); });
  pd.getElementById('uc-close').addEventListener('click', function(){ setOpen(false); });
  pd.getElementById('uc-new').addEventListener('click',   newChat);

  /* Suggestion chips */
  SUGGESTIONS.forEach(function(s) {
    var btn = pd.createElement('button');
    btn.className = 'uc-chip';
    btn.textContent = s;
    btn.addEventListener('click', function(){ sendMsg(s); });
    $chips.appendChild(btn);
  });

  /* Auto-resize input */
  $input.addEventListener('input', function() {
    $input.style.height = 'auto';
    $input.style.height = Math.min($input.scrollHeight, 120) + 'px';
  });
  $input.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMsg(); }
  });
  $send.addEventListener('click', function(){ sendMsg(); });

  function scroll() { $msgs.scrollTop = $msgs.scrollHeight; }

  /* Build message group */
  function addGroup(role) {
    $empty.style.display = 'none';
    $sug.style.display   = 'none';

    var g = pd.createElement('div');
    g.className = 'uc-group ' + role;
    var lbl = pd.createElement('div');
    lbl.className = 'uc-label';
    if (role === 'ai') lbl.innerHTML = '<span class="uc-d"></span>assistant';
    else               lbl.textContent = 'you';
    g.appendChild(lbl);
    $msgs.appendChild(g);
    scroll();
    return g;
  }

  function addBubble(group, text) {
    var b = pd.createElement('div');
    b.className = 'uc-bubble';
    b.textContent = text;
    group.appendChild(b);
    scroll();
    return b;
  }

  /* Typing indicator */
  function showTyping() {
    var g = addGroup('ai');
    var t = pd.createElement('div');
    t.className = 'uc-typing';
    t.innerHTML = '<span></span><span></span><span></span>';
    g.appendChild(t);
    scroll();
    return g;
  }

  /* Typewriter */
  function sleep(ms) { return new Promise(function(r){ setTimeout(r, ms); }); }

  async function typewrite(bubble, text) {
    var cursor = pd.createElement('span');
    cursor.className = 'uc-cursor';
    var CHUNK = 5, i = 0;
    bubble.textContent = '';
    bubble.appendChild(cursor);
    for (; i <= text.length; i += CHUNK) {
      bubble.textContent = text.slice(0, i);
      bubble.appendChild(cursor);
      scroll();
      await sleep(14);
    }
    cursor.remove();
    bubble.textContent = text;
    scroll();
  }

  /* Gemini API — tries each model in MODELS until one succeeds */
  async function callOneModel(model, contents) {
    var res = await fetch(
      'https://generativelanguage.googleapis.com/v1beta/models/' + model +
      ':generateContent?key=' + encodeURIComponent(API_KEY),
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          system_instruction: { parts: [{ text: SYSTEM }] },
          contents: contents,
          generationConfig: { temperature: 0.65, maxOutputTokens: 1024 }
        })
      }
    );
    if (!res.ok) {
      var e = await res.json().catch(function(){ return {}; });
      var msg = (e.error && e.error.message) || 'HTTP ' + res.status;
      /* quota / rate-limit errors should fall through to next model */
      var isQuota = res.status === 429 || res.status === 503 ||
                    msg.toLowerCase().indexOf('quota') !== -1 ||
                    msg.toLowerCase().indexOf('rate') !== -1;
      var err = new Error(msg);
      err.isQuota = isQuota;
      throw err;
    }
    var data = await res.json();
    var cand = data.candidates && data.candidates[0];
    if (cand && cand.content && cand.content.parts) {
      return cand.content.parts.map(function(p){ return p.text || ''; }).join('').trim() || '(empty response)';
    }
    return '(no response)';
  }

  async function callGemini(userText) {
    if (!API_KEY) return "Set GEMINI_API_KEY in your .env to enable AI responses.";

    var contents = history.slice(-16).map(function(m) {
      return { role: m.role === 'assistant' ? 'model' : 'user', parts: [{ text: m.content }] };
    });
    contents.push({ role: 'user', parts: [{ text: userText }] });

    var lastErr;
    for (var i = 0; i < MODELS.length; i++) {
      try {
        var reply = await callOneModel(MODELS[i], contents);
        /* update active model label if we switched */
        if (MODELS[i] !== activeModel) {
          activeModel = MODELS[i];
          pd.getElementById('uc-model-lbl').textContent = activeModel + ' · mission control';
        }
        return reply;
      } catch (err) {
        lastErr = err;
        if (!err.isQuota) break; /* non-quota error — don't bother trying other models */
      }
    }
    throw lastErr;
  }

  /* Send message */
  async function sendMsg(override) {
    var text = (override !== undefined ? override : $input.value).trim();
    if (!text || busy) return;
    busy = true; setBusy(true);
    $input.value = ''; $input.style.height = 'auto';

    addBubble(addGroup('user'), text);

    var typingGroup = showTyping();
    var reply;
    try { reply = await callGemini(text); }
    catch(err) { reply = 'Error: ' + (err.message || 'Could not reach Gemini.'); }

    typingGroup.remove();
    var aiGroup  = addGroup('ai');
    var aiBubble = pd.createElement('div');
    aiBubble.className = 'uc-bubble';
    aiGroup.appendChild(aiBubble);
    scroll();
    await typewrite(aiBubble, reply);

    history.push({ role: 'user',      content: text  });
    history.push({ role: 'assistant', content: reply });
    busy = false; setBusy(false);
  }

  function setBusy(v) {
    $input.disabled = v;
    $send.disabled  = v;
    $status.textContent = v ? 'thinking…' : 'ready';
  }

  function newChat() {
    history = [];
    $msgs.innerHTML = '';
    $empty.style.display = '';
    $sug.style.display   = '';
  }
})();
</script>
</body></html>
"""


_GEMINI_MODELS = [
    "gemini-2.5-flash",       # primary — best free tier
    "gemini-2.0-flash",       # fallback 1
    "gemini-2.0-flash-lite",  # fallback 2 — lightest 2.0
    "gemini-1.5-flash",       # fallback 3
    "gemini-1.5-flash-8b",    # fallback 4 — smallest, highest quota
]


def render_floating_chat(live_data: dict | None = None) -> None:
    api_key = (
        get_secret("GEMINI_API_KEY")
        or os.getenv("GEMINI_API_KEY", "")
        or os.getenv("GOOGLE_API_KEY", "")
        or ""
    )

    html = (
        _INJECTOR_TEMPLATE
        .replace("__API_KEY__", json.dumps(api_key))
        .replace("__MODELS__",  json.dumps(_GEMINI_MODELS))
        .replace("__SYSTEM__",  json.dumps(_build_system_prompt(live_data)))
    )

    st.iframe(html, height=1)
