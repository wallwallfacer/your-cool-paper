/* papers.cool local - client state.
 *
 * URL hash protocol:
 *   #stared=<id>,<id>&include=<csv>&exclude=<csv>&highlight=<csv>&filter=0|1
 */
(() => {
  const BP = (typeof window !== 'undefined' && window.BASE_PATH) || '';
  const State = {
    stared: new Set(),
    include: [],
    exclude: [],
    highlight: [],
    filter: false,
    lang: 'zh',
  };

  const LS_STARS = 'papers_cool_stars';
  const LS_LANG  = 'papers_cool_lang';

  // ---- Hash helpers --------------------------------------------------------
  function parseHash() {
    const h = location.hash.replace(/^#/, '');
    const out = {};
    if (!h) return out;
    h.split('&').forEach(kv => {
      const [k, v] = kv.split('=');
      if (k) out[decodeURIComponent(k)] = decodeURIComponent(v || '');
    });
    return out;
  }
  function writeHash() {
    const parts = [];
    if (State.stared.size)  parts.push('stared='   + Array.from(State.stared).join(','));
    if (State.include.length)   parts.push('include='   + State.include.join(','));
    if (State.exclude.length)   parts.push('exclude='   + State.exclude.join(','));
    if (State.highlight.length) parts.push('highlight=' + State.highlight.join(','));
    if (State.filter)           parts.push('filter=1');
    const newHash = parts.length ? '#' + parts.join('&') : '';
    if (newHash !== location.hash) history.replaceState(null, '', location.pathname + location.search + newHash);
  }
  function csv(s) { return (s || '').split(',').map(x => x.trim()).filter(Boolean); }

  // ---- Storage -------------------------------------------------------------
  function loadStars() {
    try { return new Set(JSON.parse(localStorage.getItem(LS_STARS) || '[]')); } catch { return new Set(); }
  }
  function saveStars() {
    localStorage.setItem(LS_STARS, JSON.stringify(Array.from(State.stared)));
  }

  // ---- Init from URL/localStorage -----------------------------------------
  function initState() {
    State.stared    = loadStars();
    State.lang      = localStorage.getItem(LS_LANG) || (window.PAPERS_COOL && window.PAPERS_COOL.defaultLang) || 'zh';

    const h = parseHash();
    if (h.stared)    h.stared.split(',').filter(Boolean).forEach(id => State.stared.add(id));
    if (h.include)   State.include   = csv(h.include);
    if (h.exclude)   State.exclude   = csv(h.exclude);
    if (h.highlight) State.highlight = csv(h.highlight);
    if (h.filter === '1') State.filter = true;

    // Hydrate panel inputs
    const inc = document.getElementById('f-include');
    const exc = document.getElementById('f-exclude');
    const hi  = document.getElementById('f-highlight');
    const fl  = document.getElementById('f-filter-on');
    const lng = document.getElementById('set-ai-lang');
    if (inc) inc.value = State.include.join(', ');
    if (exc) exc.value = State.exclude.join(', ');
    if (hi)  hi.value  = State.highlight.join(', ');
    if (fl)  fl.checked = State.filter;
    if (lng) lng.value  = State.lang;
  }

  // ---- Star management -----------------------------------------------------
  function toggleStar(id, force) {
    const want = (force === undefined) ? !State.stared.has(id) : force;
    if (want) State.stared.add(id); else State.stared.delete(id);
    saveStars(); writeHash(); refreshStarUI();
  }
  function autoStar(id) { if (!State.stared.has(id)) toggleStar(id, true); }

  function refreshStarUI() {
    document.querySelectorAll('.paper-card').forEach(card => {
      const id  = card.dataset.id;
      const btn = card.querySelector('.btn-star');
      const on  = State.stared.has(id);
      card.classList.toggle('starred', on);
      if (btn) { btn.classList.toggle('active', on); btn.textContent = on ? '★' : '☆'; }
    });
    const c = document.getElementById('star-count');
    if (c) c.textContent = State.stared.size ? String(State.stared.size) : '';
    const slc = document.getElementById('star-list-count');
    if (slc) slc.textContent = String(State.stared.size);
    const list = document.getElementById('star-list');
    if (list) {
      list.innerHTML = '';
      Array.from(State.stared).forEach(id => {
        const li = document.createElement('li');
        const a  = document.createElement('a');
        a.href = `${BP}/arxiv/${id}`;
        a.textContent = id;
        const rm = document.createElement('button');
        rm.textContent = '×';
        rm.onclick = () => toggleStar(id, false);
        li.appendChild(a); li.appendChild(rm);
        list.appendChild(li);
      });
    }
  }

  // ---- Filter / highlight -------------------------------------------------
  function applyFilter() {
    const inc = State.include.map(s => s.toLowerCase());
    const exc = State.exclude.map(s => s.toLowerCase());
    document.querySelectorAll('.paper-card').forEach(card => {
      const haystack = card.textContent.toLowerCase();
      const hitInc = inc.length === 0 || inc.some(s => haystack.includes(s));
      const hitExc = exc.length > 0 && exc.some(s => haystack.includes(s));
      const hide = State.filter && (!hitInc || hitExc);
      card.classList.toggle('hidden', hide);
    });
    applyHighlight();
  }
  function applyHighlight() {
    document.querySelectorAll('.paper-card').forEach(card => {
      ['.paper-title a', '.authors', '.abstract'].forEach(sel => {
        const el = card.querySelector(sel);
        if (!el) return;
        if (!el.dataset.raw) el.dataset.raw = el.textContent;
        let text = el.dataset.raw;
        if (State.highlight.length === 0) { el.textContent = text; return; }
        const re = new RegExp(
          '(' + State.highlight.map(escRe).join('|') + ')',
          'gi'
        );
        el.innerHTML = escapeHTML(text).replace(re, '<mark>$1</mark>');
      });
    });
  }
  function escRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
  function escapeHTML(s) {
    return s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  // ---- Time -> local -------------------------------------------------------
  function localizeTimes() {
    document.querySelectorAll('.pub-time').forEach(el => {
      const utc = el.dataset.utc;
      if (!utc) return;
      const d = new Date(utc);
      if (isNaN(d)) return;
      el.textContent = d.toLocaleString();
      el.title = utc;
    });
  }

  // ---- PDF -----------------------------------------------------------------
  function togglePDF(card) {
    const pane = card.querySelector('.pdf-pane');
    if (!pane) return;
    if (!pane.hidden) { pane.hidden = true; pane.innerHTML = ''; return; }
    const pdf = card.dataset.pdf;
    pane.innerHTML = `<iframe src="${pdf}" loading="lazy" allow="fullscreen"></iframe>`;
    pane.hidden = false;
    autoStar(card.dataset.id);
  }

  // ---- AI streaming --------------------------------------------------------
  async function translateCardAbstract(card, lang, opts = {}) {
    const absEl = card.querySelector('.abstract');
    if (!absEl) return;
    if (absEl.dataset.translatedLang === lang && !opts.force) return;
    const original = absEl.dataset.originalText || absEl.textContent;
    absEl.dataset.originalText = original;
    absEl.dataset.translating = '1';
    try {
      const u = `${BP}/api/abstract/${encodeURIComponent(card.dataset.id)}?lang=${lang}${opts.force ? '&force=1' : ''}`;
      const r = await fetch(u);
      if (!r.ok) throw new Error('http ' + r.status);
      const j = await r.json();
      if (j.abstract) {
        absEl.textContent = j.abstract;
        absEl.dataset.translatedLang = lang;
        if (window.MathJax && window.MathJax.typesetPromise) {
          window.MathJax.typesetPromise([absEl]).catch(() => {});
        }
      }
    } catch (_) {
      // leave original abstract in place on error
    } finally {
      absEl.dataset.translating = '';
    }
  }

  async function streamAI(card, opts = {}) {
    const pane    = card.querySelector('.ai-pane');
    const content = pane.querySelector('.ai-content');
    const langSel = pane.querySelector('.ai-lang');
    const lang    = (opts.lang || langSel.value || State.lang || 'zh');
    langSel.value = lang;
    pane.hidden = false;
    autoStar(card.dataset.id);

    if (pane.dataset.loading === '1') return;
    pane.dataset.loading = '1';

    // Replace the card abstract with a translation before streaming the FAQ.
    await translateCardAbstract(card, lang, { force: !!opts.force });

    let url = `${BP}/api/ai/${encodeURIComponent(card.dataset.id)}?lang=${lang}`;
    if (opts.force) url += '&force=1';
    content.innerHTML = '<em class="dim">Loading…</em>';
    let acc = '';

    try {
      const r = await fetch(url);
      if (!r.ok) throw new Error('http ' + r.status);
      const reader = r.body.getReader();
      const decoder = new TextDecoder();
      content.innerHTML = '';
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        acc += decoder.decode(value, { stream: true });
        try {
          content.innerHTML = window.marked ? marked.parse(acc) : escapeHTML(acc);
        } catch { content.textContent = acc; }
      }
      if (window.MathJax && window.MathJax.typesetPromise) {
        window.MathJax.typesetPromise([content]).catch(() => {});
      }
    } catch (e) {
      content.innerHTML += `<p class="dim">[error: ${e.message}]</p>`;
    } finally {
      pane.dataset.loading = '';
    }
  }
  function toggleAIPane(card) {
    const pane = card.querySelector('.ai-pane');
    const content = pane.querySelector('.ai-content');
    if (!pane.hidden && content.textContent.trim()) {
      pane.hidden = true; return;
    }
    if (!content.textContent.trim()) streamAI(card);
    else pane.hidden = false;
  }

  // ---- REL -----------------------------------------------------------------
  async function showRelated(card) {
    const pane = card.querySelector('.rel-pane');
    if (!pane.hidden) { pane.hidden = true; return; }
    pane.hidden = false;
    pane.innerHTML = '<em class="dim">Loading related…</em>';
    try {
      const r = await fetch(`${BP}/api/related/${encodeURIComponent(card.dataset.id)}`);
      const j = await r.json();
      const items = (j.suggestions || []).map(p =>
        `<li><a href="${BP}/arxiv/${p.arxiv_id}">${escapeHTML(p.title)}</a> <span class="dim">${p.arxiv_id}</span></li>`
      ).join('');
      pane.innerHTML = `
        <strong>Local matches (FTS5 on title):</strong>
        <ul>${items || '<li class="dim">none</li>'}</ul>
        <a href="${j.arxiv_similar_url}" target="_blank">arXiv recent list ↗</a>
      `;
    } catch (e) {
      pane.innerHTML = `<span class="dim">REL error: ${e.message}</span>`;
    }
  }

  // ---- Copy ----------------------------------------------------------------
  function copyPaper(card) {
    const id = card.dataset.id;
    const title = card.querySelector('.paper-title a').textContent.trim();
    const authors = card.querySelector('.authors').textContent.trim();
    const abstract = (card.querySelector('.abstract').dataset.raw || card.querySelector('.abstract').textContent).trim();
    const text = `${title}\n${authors}\nhttps://arxiv.org/abs/${id}\n\n${abstract}`;
    const sel = window.getSelection();
    const saved = sel.rangeCount ? sel.getRangeAt(0).cloneRange() : null;
    navigator.clipboard.writeText(text).then(() => {
      flash(card.querySelector('.btn-copy'), 'Copied');
      if (saved) { sel.removeAllRanges(); sel.addRange(saved); }
    }).catch(e => alert('Copy failed: ' + e.message));
    autoStar(id);
  }
  function flash(btn, msg) {
    if (!btn) return;
    const old = btn.textContent;
    btn.textContent = msg; btn.classList.add('active');
    setTimeout(() => { btn.textContent = old; btn.classList.remove('active'); }, 1200);
  }

  // ---- Wire up -------------------------------------------------------------
  function wireCards() {
    document.querySelectorAll('.paper-card').forEach(card => {
      card.addEventListener('click', e => {
        const t = e.target.closest('[data-action]');
        if (!t) return;
        const action = t.dataset.action;
        if (action === 'pdf')   togglePDF(card);
        if (action === 'ai')    toggleAIPane(card);
        if (action === 'rel')   showRelated(card);
        if (action === 'copy')  copyPaper(card);
        if (action === 'star')  toggleStar(card.dataset.id);
      });

      const aiPane = card.querySelector('.ai-pane');
      if (aiPane) {
        aiPane.querySelector('.ai-collapse').onclick = () => { aiPane.hidden = true; };
        aiPane.querySelector('.ai-regen').onclick = () => streamAI(card, { force: true });
        aiPane.querySelector('.ai-lang').onchange = e => {
          State.lang = e.target.value;
          localStorage.setItem(LS_LANG, State.lang);
        };
      }
    });
  }
  function wirePanels() {
    document.querySelectorAll('.bar-btn[data-panel]').forEach(btn => {
      btn.onclick = () => {
        const id = btn.dataset.panel;
        document.querySelectorAll('.panel').forEach(p => {
          if (p.id === id) p.hidden = !p.hidden;
          else p.hidden = true;
        });
        document.querySelectorAll('.bar-btn[data-panel]').forEach(b => b.classList.toggle('active', !document.getElementById(b.dataset.panel).hidden && b===btn));
      };
    });

    document.getElementById('apply-filter')?.addEventListener('click', () => {
      State.include   = csv(document.getElementById('f-include').value);
      State.exclude   = csv(document.getElementById('f-exclude').value);
      State.highlight = csv(document.getElementById('f-highlight').value);
      State.filter    = document.getElementById('f-filter-on').checked;
      writeHash(); applyFilter();
    });
    document.getElementById('clear-filter')?.addEventListener('click', () => {
      ['f-include','f-exclude','f-highlight'].forEach(id => document.getElementById(id).value='');
      document.getElementById('f-filter-on').checked = false;
      State.include = State.exclude = State.highlight = []; State.filter = false;
      writeHash(); applyFilter();
    });
    document.getElementById('export-stars')?.addEventListener('click', () => {
      writeHash();
      const url = location.href;
      navigator.clipboard.writeText(url).then(() => alert('Star URL copied:\n' + url));
    });
    document.getElementById('clear-stars')?.addEventListener('click', () => {
      if (!confirm('Clear all stars?')) return;
      State.stared.clear(); saveStars(); writeHash(); refreshStarUI();
    });
    document.getElementById('set-ai-lang')?.addEventListener('change', e => {
      State.lang = e.target.value; localStorage.setItem(LS_LANG, State.lang);
    });

    document.getElementById('scroll-top')?.addEventListener('click', () => window.scrollTo({top:0, behavior:'smooth'}));
    document.getElementById('scroll-bottom')?.addEventListener('click', () => window.scrollTo({top:document.body.scrollHeight, behavior:'smooth'}));

    // Live substring search via the include field
    document.getElementById('f-include')?.addEventListener('input', e => {
      State.include = csv(e.target.value);
      writeHash(); applyFilter();
    });
    document.getElementById('f-exclude')?.addEventListener('input', e => {
      State.exclude = csv(e.target.value);
      writeHash(); applyFilter();
    });
    document.getElementById('f-highlight')?.addEventListener('input', e => {
      State.highlight = csv(e.target.value);
      writeHash(); applyHighlight();
    });
    document.getElementById('f-filter-on')?.addEventListener('change', e => {
      State.filter = e.target.checked; writeHash(); applyFilter();
    });
  }

  // ---- Auto abstract translation (viewport-driven) ------------------------
  function startAbstractAutoTranslate() {
    const lang = State.lang || 'zh';
    if (lang === 'en') return; // source language; nothing to translate
    if (typeof IntersectionObserver === 'undefined') return;

    const queue = [];
    let active = 0;
    const PARALLEL = 4;

    const pump = () => {
      while (active < PARALLEL && queue.length) {
        const card = queue.shift();
        active++;
        translateCardAbstract(card, lang).catch(() => {}).finally(() => {
          active--;
          pump();
        });
      }
    };

    const seen = new WeakSet();
    const obs = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        const card = e.target;
        obs.unobserve(card);
        if (seen.has(card)) continue;
        seen.add(card);
        const a = card.querySelector('.abstract');
        if (!a || a.dataset.translatedLang === lang) continue;
        queue.push(card);
        pump();
      }
    }, { rootMargin: '300px' });

    document.querySelectorAll('.paper-card').forEach((card) => {
      const a = card.querySelector('.abstract');
      if (!a || a.dataset.translatedLang === lang) return;
      obs.observe(card);
    });
  }

  // Boot
  document.addEventListener('DOMContentLoaded', () => {
    initState();
    refreshStarUI();
    wireCards();
    wirePanels();
    localizeTimes();
    applyFilter();
    startAbstractAutoTranslate();
  });
})();
