"""Scroll-triggered 3D animations for KPI cards, section headings, and chart blocks.

Injects CSS + IntersectionObserver into Streamlit's parent DOM. Targets natural
Streamlit data-testid selectors plus .kc/.shd classes. Idempotent — re-running is a no-op.
"""

import streamlit as st

_INJECTOR = """<!DOCTYPE html>
<html>
<body>
<script>
(function() {
  const STYLE_ID = 'scroll-anim-styles';
  const FLAG = '__scrollAnimInit';
  let parentDoc;
  try { parentDoc = window.parent.document; }
  catch (e) { parentDoc = document; }

  if (!parentDoc.getElementById(STYLE_ID)) {
    const style = parentDoc.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      [data-testid="stIFrame"]:not([data-chat-overlay]),
      [data-testid="stIframe"]:not([data-chat-overlay]) {
        opacity: 0;
        transform: perspective(1200px) rotateX(35deg) translateY(50px);
        transform-origin: center bottom;
        transition: opacity 0.95s cubic-bezier(0.2, 0, 0, 1),
                    transform 0.95s cubic-bezier(0.2, 0, 0, 1);
        will-change: transform, opacity;
      }
      [data-testid="stIFrame"]:not([data-chat-overlay]).animate-visible,
      [data-testid="stIframe"]:not([data-chat-overlay]).animate-visible {
        opacity: 1;
        transform: perspective(1200px) rotateX(0) translateY(0);
      }

      [data-testid="stPlotlyChart"] {
        opacity: 0;
        transform: perspective(1300px) rotateX(24deg) translateY(48px) scale(0.97);
        transform-origin: center bottom;
        transition: opacity 1.05s cubic-bezier(0.2, 0, 0, 1),
                    transform 1.05s cubic-bezier(0.2, 0, 0, 1);
        will-change: transform, opacity;
      }
      [data-testid="stPlotlyChart"].animate-visible {
        opacity: 1;
        transform: none;
      }

      [data-testid="stHorizontalBlock"] > [data-testid="column"]:nth-child(1) [data-testid="stPlotlyChart"] {
        transform: perspective(1300px) rotateY(-28deg) translateX(-24px);
      }
      [data-testid="stHorizontalBlock"] > [data-testid="column"]:nth-child(1) [data-testid="stPlotlyChart"].animate-visible {
        transform: none;
      }
      [data-testid="stHorizontalBlock"] > [data-testid="column"]:last-child [data-testid="stPlotlyChart"] {
        transform: perspective(1300px) rotateY(28deg) translateX(24px);
      }
      [data-testid="stHorizontalBlock"] > [data-testid="column"]:last-child [data-testid="stPlotlyChart"].animate-visible {
        transform: none;
      }

      [data-testid="stHorizontalBlock"] > [data-testid="column"]:nth-child(2) [data-testid="stPlotlyChart"],
      [data-testid="stHorizontalBlock"] > [data-testid="column"]:nth-child(2) [data-testid="stIFrame"]:not([data-chat-overlay]) {
        transition-delay: 0.15s;
      }

      [data-testid="stPlotlyChart"].animate-visible {
        transition-property: transform, opacity, box-shadow;
      }
      [data-testid="stPlotlyChart"].animate-visible:hover {
        transform: perspective(1300px) rotateX(-3deg) translateY(-4px);
      }

      .section-heading, .shd {
        opacity: 0;
        transform: translateY(16px);
        transition: opacity 0.7s cubic-bezier(0.2, 0, 0, 1),
                    transform 0.7s cubic-bezier(0.2, 0, 0, 1);
      }
      .section-heading.animate-visible, .shd.animate-visible {
        opacity: 1;
        transform: none;
      }

      @media (prefers-reduced-motion: reduce) {
        [data-testid="stIFrame"]:not([data-chat-overlay]),
        [data-testid="stIframe"]:not([data-chat-overlay]),
        [data-testid="stPlotlyChart"],
        .section-heading, .shd, .kc {
          opacity: 1 !important;
          transform: none !important;
          transition: none !important;
        }
      }
    `;
    parentDoc.head.appendChild(style);
  }

  if (!window.parent[FLAG]) {
    window.parent[FLAG] = true;

    const observer = new (window.parent.IntersectionObserver || IntersectionObserver)(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          const el = entry.target;
          if (el.classList.contains('kc')) {
            el.classList.add('vis');
          } else {
            el.classList.add('animate-visible');
          }
          observer.unobserve(el);
        });
      },
      { threshold: 0.15, rootMargin: '0px 0px -8% 0px' }
    );

    const SELECTOR =
      '[data-testid="stIFrame"]:not([data-chat-overlay]), [data-testid="stIframe"]:not([data-chat-overlay]), ' +
      '[data-testid="stPlotlyChart"], .section-heading, .shd, .kc';

    // Count-up animation for .kc elements
    function _fmtKc(num, fmt, pre, suf) {
      let s = fmt === 'int'  ? Math.round(num).toLocaleString()
            : fmt === 'dec1' ? num.toFixed(1)
            :                  num.toFixed(2);
      return pre + s + suf;
    }
    function runCountUp(el) {
      const target = parseFloat(el.dataset.t) || 0;
      const valEl  = el.querySelector('.kc-val');
      if (!valEl) return;
      const pre = el.dataset.p || '', suf = el.dataset.s || '', fmt = el.dataset.f || 'int';
      const T = 1400, start = performance.now();
      function tick(now) {
        const p    = Math.min((now - start) / T, 1);
        const ease = 1 - Math.pow(1 - p, 3);
        valEl.textContent = _fmtKc(ease * target, fmt, pre, suf);
        if (p < 1) requestAnimationFrame(tick);
      }
      requestAnimationFrame(tick);
    }

    const kcMO = new (window.parent.MutationObserver || MutationObserver)((mutations) => {
      mutations.forEach((m) => {
        if (m.attributeName === 'class') {
          const el = m.target;
          if (el.classList.contains('kc') && el.classList.contains('vis') && !el.dataset.counted) {
            el.dataset.counted = '1';
            runCountUp(el);
          }
        }
      });
    });

    function watchKc() {
      parentDoc.querySelectorAll('.kc').forEach((el) => {
        if (el.dataset.kcWatched) return;
        el.dataset.kcWatched = '1';
        kcMO.observe(el, { attributes: true, attributeFilter: ['class'] });
      });
    }
    watchKc();

    function watchAll() {
      parentDoc.querySelectorAll(SELECTOR).forEach((el) => {
        if (el.dataset.scrollObserved) return;
        el.dataset.scrollObserved = '1';
        observer.observe(el);
      });
    }
    watchAll();

    const mo = new (window.parent.MutationObserver || MutationObserver)(() => {
      watchAll();
      watchKc();
    });
    mo.observe(parentDoc.body, { childList: true, subtree: true });

    window.parent.__scrollAnimObserver = observer;
    window.parent.__scrollAnimMutation = mo;
  }
})();
</script>
</body>
</html>
"""


def inject_scroll_animations() -> None:
    """Inject scroll-triggered animations targeting the parent Streamlit DOM."""
    st.iframe(_INJECTOR, height=1)
