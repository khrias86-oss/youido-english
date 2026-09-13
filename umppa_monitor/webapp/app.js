/* 키즈카페 빈자리 웹앱.
 *
 * data.json (감시 엔진이 10분마다 갱신) 을 읽어 당월 달력을 그리고,
 * 사용자가 고른 요일·날짜·회차를 감시 조건(prefs)으로 저장한다.
 * 조건은 대상(키즈카페/프로그램)별로 따로 보관해 개별 판단한다.
 */
(() => {
  'use strict';

  const CFG = Object.assign({ dataUrl: './data.json', apiBase: '', sourceUrl: '' }, window.UMPPA_CONFIG || {});
  const WD = ['월', '화', '수', '목', '금', '토', '일'];
  const LS_PREFS = 'umppa.prefs.v1';
  const LS_PIN = 'umppa.pin.v1';

  let DATA = null;
  let prefs = null;
  let savedJson = '';
  let activeKey = null;
  let viewMonth = '';
  let selDate = null;

  // ---------------------------------------------------------------- helpers
  const $ = (sel, root = document) => root.querySelector(sel);
  const pad = (n) => String(n).padStart(2, '0');
  const monthOf = (iso) => iso.slice(0, 7);
  /** 0=월 … 6=일 (파이썬 weekday 와 동일) */
  const wdOf = (iso) => {
    const [y, m, d] = iso.split('-').map(Number);
    return (new Date(y, m - 1, d).getDay() + 6) % 7;
  };
  const todayIso = () => {
    const d = new Date();
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  };

  function el(tag, cls, txt) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (txt != null) n.textContent = txt;
    return n;
  }
  function btn(cls, txt, onClick) {
    const b = el('button', cls, txt);
    b.type = 'button';
    if (onClick) b.addEventListener('click', onClick);
    return b;
  }
  function since(ts) {
    if (!ts) return '아직 확인 전';
    const m = Math.floor((Date.now() / 1000 - ts) / 60);
    if (m < 1) return '방금 확인';
    if (m < 60) return `${m}분 전 확인`;
    const h = Math.floor(m / 60);
    return h < 24 ? `${h}시간 전 확인` : `${Math.floor(h / 24)}일 전 확인`;
  }
  const fmtDate = (iso) => {
    const [, m, d] = iso.split('-').map(Number);
    return `${m}/${d}(${WD[wdOf(iso)]})`;
  };

  // ------------------------------------------------------------- prefs 모델
  function targetPrefs(key) {
    if (!prefs.targets) prefs.targets = {};
    if (!prefs.targets[key]) {
      prefs.targets[key] = { enabled: true, weekdays: [], dates: [], sessions: [], min_remaining: 1 };
    }
    const p = prefs.targets[key];
    for (const f of ['weekdays', 'dates', 'sessions']) if (!Array.isArray(p[f])) p[f] = [];
    if (typeof p.min_remaining !== 'number') p.min_remaining = 1;
    return p;
  }
  function toggleIn(arr, v) {
    const i = arr.indexOf(v);
    if (i >= 0) arr.splice(i, 1); else arr.push(v);
  }
  const isDirty = () => JSON.stringify(prefs) !== savedJson;

  const activeTarget = () => (DATA.targets || []).find((t) => t.key === activeKey) || null;

  // ------------------------------------------------------------------ 로드
  async function load() {
    const icon = $('#reload');
    icon.classList.add('spin');
    try {
      const res = await fetch(`${CFG.dataUrl}${CFG.dataUrl.includes('?') ? '&' : '?'}t=${Date.now()}`, { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      DATA = await res.json();
    } catch (e) {
      $('#main').innerHTML = '';
      const c = el('div', 'card');
      c.appendChild(el('h2', null, '현황을 불러오지 못했습니다'));
      c.appendChild(el('p', 'card-sub', String(e.message || e)));
      c.appendChild(btn('btn block', '다시 시도', load));
      $('#main').appendChild(c);
      return;
    } finally {
      icon.classList.remove('spin');
    }

    prefs = adoptPrefs(DATA.prefs);
    savedJson = JSON.stringify(prefs);
    const targets = DATA.targets || [];
    if (!activeKey || !targets.some((t) => t.key === activeKey)) {
      activeKey = (targets.find((t) => t.open_count > 0) || targets[0] || {}).key || null;
    }
    resetMonth();
    render();
  }

  /** 서버 조건을 기준으로 하되, 아직 서버에 못 보낸 로컬 변경이 더 새로우면 그것을 쓴다. */
  function adoptPrefs(base) {
    const server = JSON.parse(JSON.stringify(base || { targets: {}, programs: [] }));
    try {
      const local = JSON.parse(localStorage.getItem(LS_PREFS) || 'null');
      if (local && (!CFG.apiBase || (local.updated_at || 0) > (server.updated_at || 0))) return local;
    } catch (_) { /* 저장소 접근 불가 시 서버 값 사용 */ }
    return server;
  }

  function resetMonth() {
    const t = activeTarget();
    const months = monthList(t);
    const cur = monthOf(todayIso());
    viewMonth = months.includes(cur) ? cur : (months[0] || cur);
    selDate = null;
  }

  function monthList(t) {
    if (!t || !t.days) return [];
    return [...new Set(Object.keys(t.days).map(monthOf))].sort();
  }

  // ---------------------------------------------------------------- 렌더링
  function render() {
    const main = $('#main');
    main.innerHTML = '';
    if (!DATA) return;

    $('#freshness').textContent = freshnessText();
    main.appendChild(renderTabs());

    const t = activeTarget();
    if (!t) {
      main.appendChild(card('감시 대상이 없습니다', '아래에서 프로그램을 고르거나 config.yaml 에 대상을 추가하세요.'));
    } else if (t.kind === 'kidscafe') {
      main.appendChild(renderCalendar(t));
      main.appendChild(renderWeekdaySummary(t));
      if (selDate) main.appendChild(renderDay(t));
      main.appendChild(renderPrefs(t));
    } else {
      main.appendChild(renderProgramTarget(t));
      main.appendChild(renderPrefs(t));
    }
    if ((DATA.programs || []).length) main.appendChild(renderProgramPicker());
    main.appendChild(renderFooter());
    updateSaveBar();
  }

  function freshnessText() {
    const ts = Math.max(0, ...(DATA.targets || []).map((t) => t.checked_at || 0));
    const every = Math.round((DATA.interval_sec || 600) / 60);
    return `${since(ts)} · ${every}분마다 확인`;
  }

  function card(title, sub) {
    const c = el('div', 'card');
    if (title) c.appendChild(el('h2', null, title));
    if (sub) c.appendChild(el('p', 'card-sub', sub));
    return c;
  }

  function renderTabs() {
    const wrap = el('div', 'tabs');
    wrap.setAttribute('role', 'tablist');
    for (const t of DATA.targets || []) {
      const p = prefs.targets && prefs.targets[t.key];
      const on = !p || p.enabled !== false;
      const b = btn(`tab${on ? '' : ' off'}`, null, () => {
        activeKey = t.key;
        resetMonth();
        render();
      });
      b.setAttribute('role', 'tab');
      b.setAttribute('aria-selected', String(t.key === activeKey));
      b.appendChild(el('span', null, t.name || t.key));
      b.appendChild(el('span', 'count', String(t.open_count || 0)));
      wrap.appendChild(b);
    }
    return wrap;
  }

  // ---- 달력 -------------------------------------------------------------
  function heatClass(day) {
    if (!day || !day.open) return 'h0';
    const s = day.seats || 0;
    if (s >= 50) return 'h4';
    if (s >= 25) return 'h3';
    if (s >= 10) return 'h2';
    return 'h1';
  }

  function renderCalendar(t) {
    const c = el('div', 'card');
    const months = monthList(t);
    const idx = months.indexOf(viewMonth);

    const nav = el('div', 'month-nav');
    const [yy, mm] = viewMonth.split('-').map(Number);
    nav.appendChild(el('h2', null, `${yy}년 ${mm}월`));
    const nb = el('div', 'nav-btns');
    const prev = btn(null, '‹', () => { viewMonth = months[idx - 1]; selDate = null; render(); });
    const next = btn(null, '›', () => { viewMonth = months[idx + 1]; selDate = null; render(); });
    prev.disabled = idx <= 0;
    next.disabled = idx < 0 || idx >= months.length - 1;
    nb.appendChild(prev); nb.appendChild(next);
    nav.appendChild(nb);
    c.appendChild(nav);

    const tp = targetPrefs(t.key);
    const grid = el('div', 'cal');
    for (let w = 0; w < 7; w++) {
      const h = btn('cal-head', WD[w], () => { toggleIn(tp.weekdays, w); render(); });
      h.dataset.wd = String(w);
      h.setAttribute('aria-pressed', String(tp.weekdays.includes(w)));
      h.title = `${WD[w]}요일 감시 켜기/끄기`;
      grid.appendChild(h);
    }

    const first = new Date(yy, mm - 1, 1);
    const lead = (first.getDay() + 6) % 7;
    const total = new Date(yy, mm, 0).getDate();
    for (let i = 0; i < lead; i++) grid.appendChild(el('div', 'cell blank'));

    const today = todayIso();
    for (let d = 1; d <= total; d++) {
      const iso = `${viewMonth}-${pad(d)}`;
      const day = (t.days || {})[iso];
      const picked = tp.weekdays.includes(wdOf(iso)) || tp.dates.includes(iso);
      const cell = btn(`cell ${heatClass(day)}`, null, () => {
        selDate = selDate === iso ? null : iso;
        render();
        if (selDate) requestAnimationFrame(() => $('#day-card') && $('#day-card').scrollIntoView({ behavior: 'smooth', block: 'nearest' }));
      });
      if (iso < today) cell.classList.add('past');
      if (iso === today) cell.classList.add('today');
      if (picked) cell.classList.add('picked');
      cell.setAttribute('aria-selected', String(iso === selDate));
      cell.setAttribute('aria-label', `${fmtDate(iso)} ${day && day.open ? `빈자리 ${day.seats || day.open}` : '빈자리 없음'}`);
      cell.appendChild(el('span', 'dnum', String(d)));
      if (day && day.open) cell.appendChild(el('span', 'seats', String(day.seats || day.open)));
      else if (day) cell.appendChild(el('span', 'dot'));
      grid.appendChild(cell);
    }
    c.appendChild(grid);

    const lg = el('div', 'cal-legend');
    lg.appendChild(el('span', null, '적음'));
    for (const k of ['h1', 'h2', 'h3', 'h4']) {
      const i = el('i');
      i.style.background = `var(--${k}-bg)`;
      lg.appendChild(i);
    }
    lg.appendChild(el('span', null, '많음 · 숫자는 잔여 인원'));
    c.appendChild(lg);
    return c;
  }

  function renderWeekdaySummary(t) {
    const [wy, wm] = viewMonth.split('-').map(Number);
    const c = card('요일별 빈자리', `${wy}년 ${wm}월 합계 · 요일을 누르면 감시 조건에 넣고 뺍니다`);
    const tp = targetPrefs(t.key);
    const totals = Array.from({ length: 7 }, () => 0);
    for (const [iso, day] of Object.entries(t.days || {})) {
      if (monthOf(iso) !== viewMonth) continue;
      totals[wdOf(iso)] += day.seats || day.open || 0;
    }
    const grid = el('div', 'wd-summary');
    for (let w = 0; w < 7; w++) {
      const cell = btn(`wd-cell${tp.weekdays.includes(w) ? ' on' : ''}`, null, () => { toggleIn(tp.weekdays, w); render(); });
      cell.appendChild(el('div', 'wd', WD[w]));
      cell.appendChild(el('div', `v${totals[w] ? '' : ' zero'}`, totals[w] ? String(totals[w]) : '–'));
      grid.appendChild(cell);
    }
    c.appendChild(grid);
    return c;
  }

  // ---- 날짜 상세 --------------------------------------------------------
  function renderDay(t) {
    const c = el('div', 'card');
    c.id = 'day-card';
    const day = (t.days || {})[selDate];
    const tp = targetPrefs(t.key);

    const head = el('div', 'day-head');
    head.appendChild(el('span', 'd', fmtDate(selDate)));
    head.appendChild(el('span', 'n', day && day.open ? `열린 회차 ${day.open}개 · ${day.seats}석` : '빈자리 없음'));
    c.appendChild(head);

    if (!day || !day.slots.length) {
      c.appendChild(el('div', 'empty', '이 날짜의 회차 정보가 없습니다 (휴관일이거나 아직 열리지 않음)'));
      return c;
    }
    for (const s of day.slots) {
      const on = tp.sessions.includes(s.session);
      const row = btn('session', null, () => { toggleIn(tp.sessions, s.session); render(); });
      row.setAttribute('aria-pressed', String(on));
      const box = el('span', 'box', '✓');
      row.appendChild(box);
      row.appendChild(el('span', 'label', s.session));
      if (s.remaining != null) row.appendChild(el('span', 'meta', `잔여 ${s.remaining}${s.capacity != null ? `/${s.capacity}` : ''}`));
      const label = { open: '가능', full: '마감', closed: '불가' }[s.status] || '?';
      row.appendChild(el('span', `pill ${s.status === 'open' ? 'open' : s.status === 'full' ? 'full' : 'closed'}`, label));
      c.appendChild(row);
    }

    const actions = el('div', 'row-actions');
    const pinned = tp.dates.includes(selDate);
    actions.appendChild(btn('btn ghost', pinned ? '이 날짜 감시 해제' : '이 날짜만 감시', () => {
      toggleIn(tp.dates, selDate);
      render();
    }));
    const link = el('a', 'btn ghost', '예약 페이지 열기');
    link.href = t.url; link.target = '_blank'; link.rel = 'noopener';
    actions.appendChild(link);
    c.appendChild(actions);
    return c;
  }

  function renderProgramTarget(t) {
    const c = card(t.name || t.key, t.checked_at ? since(t.checked_at) : '아직 확인 전');
    const rows = [...(t.undated || []), ...Object.entries(t.days || {}).flatMap(([iso, d]) => d.slots.map((s) => ({ ...s, date: iso })))];
    if (!rows.length) {
      c.appendChild(el('div', 'empty', '아직 수집된 회차가 없습니다.'));
    } else {
      const tp = targetPrefs(t.key);
      for (const s of rows) {
        const row = btn('session', null, () => { toggleIn(tp.sessions, s.session); render(); });
        row.setAttribute('aria-pressed', String(tp.sessions.includes(s.session)));
        row.appendChild(el('span', 'box', '✓'));
        const lab = el('span', 'label', s.session);
        if (s.date) lab.appendChild(el('span', 'meta', ` · ${fmtDate(s.date)}`));
        row.appendChild(lab);
        if (s.remaining != null) row.appendChild(el('span', 'meta', `잔여 ${s.remaining}`));
        row.appendChild(el('span', `pill ${s.status === 'open' ? 'open' : s.status === 'full' ? 'full' : 'closed'}`,
          { open: '가능', full: '마감', closed: '불가' }[s.status] || '?'));
        c.appendChild(row);
      }
    }
    const link = el('a', 'btn ghost block', '예약 페이지 열기');
    link.href = t.url; link.target = '_blank'; link.rel = 'noopener';
    link.style.marginTop = '12px';
    c.appendChild(link);
    return c;
  }

  // ---- 감시 조건 --------------------------------------------------------
  function renderPrefs(t) {
    const tp = targetPrefs(t.key);
    const c = card('내 감시 조건', `${t.name || t.key} 에만 적용됩니다`);

    const onOff = el('div', 'field');
    const lw = el('div');
    lw.appendChild(el('label', null, '이 대상 감시'));
    lw.appendChild(el('div', 'hint', tp.enabled ? '조건에 맞는 빈자리가 생기면 알립니다' : '알림을 보내지 않습니다'));
    onOff.appendChild(lw);
    const sw = btn('switch', null, () => { tp.enabled = !tp.enabled; render(); });
    sw.setAttribute('role', 'switch');
    sw.setAttribute('aria-checked', String(!!tp.enabled));
    sw.setAttribute('aria-label', '이 대상 감시');
    onOff.appendChild(sw);
    c.appendChild(onOff);

    c.appendChild(chipField('요일', '비우면 모든 요일', WD.map((w, i) => ({
      label: w, on: tp.weekdays.includes(i), onClick: () => { toggleIn(tp.weekdays, i); render(); },
    })), tp.weekdays.length ? () => { tp.weekdays = []; render(); } : null));

    if (tp.sessions.length) {
      c.appendChild(chipField('회차', '달력에서 회차를 눌러 추가합니다', tp.sessions.map((s) => ({
        label: `${s} ✕`, on: true, onClick: () => { toggleIn(tp.sessions, s); render(); },
      })), () => { tp.sessions = []; render(); }));
    }
    if (tp.dates.length) {
      c.appendChild(chipField('지정 날짜', '이 날짜만 감시합니다', tp.dates.slice().sort().map((d) => ({
        label: `${fmtDate(d)} ✕`, on: true, onClick: () => { toggleIn(tp.dates, d); render(); },
      })), () => { tp.dates = []; render(); }));
    }

    const minf = el('div', 'field');
    const ml = el('div');
    ml.appendChild(el('label', null, '최소 잔여 인원'));
    ml.appendChild(el('div', 'hint', '이 인원 이상 남았을 때만 알림'));
    minf.appendChild(ml);
    const st = el('div', 'stepper');
    st.appendChild(btn(null, '−', () => { tp.min_remaining = Math.max(1, tp.min_remaining - 1); render(); }));
    st.appendChild(el('span', null, `${tp.min_remaining}명`));
    st.appendChild(btn(null, '+', () => { tp.min_remaining = Math.min(99, tp.min_remaining + 1); render(); }));
    minf.appendChild(st);
    c.appendChild(minf);

    const wd = tp.weekdays.length ? tp.weekdays.slice().sort().map((i) => WD[i]).join('·') : '모든 요일';
    const se = tp.sessions.length ? `${tp.sessions.length}개 회차` : '모든 회차';
    const dt = tp.dates.length ? ` · 지정 날짜 ${tp.dates.length}일` : '';
    const line = el('div', 'summary-line');
    line.innerHTML = `<b>${wd}</b> 의 <b>${se}</b> 에 <b>${tp.min_remaining}명</b> 이상 빈자리가 생기면 알림${dt}`;
    c.appendChild(line);
    return c;
  }

  function chipField(title, hint, items, onClear) {
    const f = el('div', 'field');
    f.style.display = 'block';
    const h = el('div');
    h.appendChild(el('label', null, title));
    h.appendChild(el('div', 'hint', hint));
    f.appendChild(h);
    const row = el('div', 'chips');
    for (const it of items) {
      const b = btn('chip', it.label, it.onClick);
      b.setAttribute('aria-pressed', String(!!it.on));
      row.appendChild(b);
    }
    if (onClear) row.appendChild(btn('chip clear', '전체 해제', onClear));
    f.appendChild(row);
    return f;
  }

  // ---- 프로그램 선택 ----------------------------------------------------
  function renderProgramPicker() {
    const c = card('프로그램 감시 대상', '고른 프로그램은 다음 확인부터 키즈카페와 별도로 판단합니다');
    if (!prefs.programs) prefs.programs = [];
    for (const p of DATA.programs) {
      const on = prefs.programs.includes(p.id);
      const row = btn('session prog', null, () => { toggleIn(prefs.programs, p.id); render(); });
      row.setAttribute('aria-pressed', String(on));
      row.appendChild(el('span', 'box', '✓'));
      const lab = el('span', 'label');
      lab.appendChild(el('span', 'nm', p.name || `프로그램 ${p.id}`));
      const sub = [p.status, p.period].filter(Boolean).join(' · ');
      if (sub) lab.appendChild(el('span', 'sub', sub));
      row.appendChild(lab);
      if (on) row.appendChild(el('span', 'pill open', '감시'));
      c.appendChild(row);
    }
    return c;
  }

  function renderFooter() {
    const c = el('div', 'card');
    const n = el('p', 'note');
    const parts = [`빈자리 확인은 ${Math.round((DATA.interval_sec || 600) / 60)}분마다 자동으로 돌아갑니다.`];
    if ((DATA.quiet_hours || []).length) parts.push(`야간(${DATA.quiet_hours.join(', ')})에는 쉽니다.`);
    parts.push(CFG.apiBase
      ? '저장한 조건은 다음 확인부터 알림에 반영됩니다.'
      : '지금은 조건이 이 브라우저에만 저장됩니다. 알림까지 반영하려면 저장 서버 연결이 필요합니다.');
    n.textContent = parts.join(' ');
    c.appendChild(n);
    if (CFG.sourceUrl) {
      const a = el('a', 'note', '실행 기록 보기');
      a.href = CFG.sourceUrl; a.target = '_blank'; a.rel = 'noopener';
      a.style.display = 'inline-block';
      a.style.marginTop = '8px';
      c.appendChild(a);
    }
    return c;
  }

  // ------------------------------------------------------------------ 저장
  function updateSaveBar() {
    const bar = $('#savebar');
    const dirty = isDirty();
    bar.hidden = !dirty;
    if (dirty) {
      $('#savebar-text').className = 'savebar-text';
      $('#savebar-text').textContent = '변경한 조건이 있습니다';
      $('#save').disabled = false;
    }
  }

  function setMsg(text, kind) {
    const t = $('#savebar-text');
    t.textContent = text;
    t.className = `savebar-text${kind ? ` ${kind}` : ''}`;
    $('#savebar').hidden = false;
  }

  async function save() {
    const payload = JSON.parse(JSON.stringify(prefs));
    payload.updated_at = Date.now() / 1000;
    $('#save').disabled = true;
    try { localStorage.setItem(LS_PREFS, JSON.stringify(payload)); } catch (_) { /* 저장소 불가 */ }

    if (!CFG.apiBase) {
      prefs = payload;
      savedJson = JSON.stringify(prefs);
      setMsg('이 기기에 저장했습니다 (알림 반영은 서버 연결 필요)', 'ok');
      return;
    }
    try {
      const res = await fetch(`${CFG.apiBase.replace(/\/$/, '')}/api/prefs`, {
        method: 'PUT',
        headers: Object.assign({ 'content-type': 'application/json' }, pinHeader()),
        body: JSON.stringify(payload),
      });
      if (res.status === 401) {
        const pin = window.prompt('저장 비밀번호(PIN)를 입력하세요');
        if (pin) { try { localStorage.setItem(LS_PIN, pin); } catch (_) { /* noop */ } return save(); }
        setMsg('저장하려면 PIN 이 필요합니다', 'err');
        $('#save').disabled = false;
        return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      prefs = payload;
      savedJson = JSON.stringify(prefs);
      setMsg('저장했습니다 · 다음 확인부터 반영됩니다', 'ok');
    } catch (e) {
      setMsg(`저장 실패: ${e.message || e} (이 기기에는 저장됨)`, 'err');
      $('#save').disabled = false;
    }
  }

  function pinHeader() {
    try {
      const pin = localStorage.getItem(LS_PIN);
      return pin ? { 'x-umppa-pin': pin } : {};
    } catch (_) { return {}; }
  }

  // ------------------------------------------------------------------ 시작
  $('#reload').addEventListener('click', load);
  $('#save').addEventListener('click', save);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && DATA && !isDirty()) load();
  });
  load();
})();
