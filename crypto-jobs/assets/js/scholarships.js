// scholarships filter — runs entirely in the browser.
// Filters scholarships & fellowships by level / region / status / focus /
// upcoming-deadline / free text, and annotates each card with how soon its
// deadline falls (for real ISO dates; "rolling"/"annual" are left as-is).

(function () {
  const levelSel = document.getElementById('s-level');
  if (!levelSel) return;

  const cards = Array.from(document.querySelectorAll('.cards .card'));
  const regionSel = document.getElementById('s-region');
  const statusSel = document.getElementById('s-status');
  const searchInp = document.getElementById('s-search');
  const soonChk = document.getElementById('s-soon');
  const focusCbs = Array.from(document.querySelectorAll('.focus-cb'));
  const visibleCount = document.getElementById('s-visible-count');
  const totalCount = document.getElementById('s-total-count');

  totalCount.textContent = cards.length;

  const SOON_DAYS = 60;     // "deadline soon" window for the toggle + badge
  const NEW_DAYS = 3;       // reuse the site-wide NEW window
  const DAY = 86400000;
  const now = Date.now();

  // ---- Annotate each card: NEW badge (recently added) + deadline countdown.
  cards.forEach(card => {
    // NEW badge — same rule as the positions page.
    const added = Date.parse(card.dataset.added);
    const addedAge = (now - added) / DAY;
    const isNew = !Number.isNaN(added) && addedAge >= 0 && addedAge <= NEW_DAYS;
    card.classList.toggle('is-new', isNew);
    const newBadge = card.querySelector('.badge-new');
    if (newBadge) newBadge.hidden = !isNew;

    // Deadline handling — only ISO dates (YYYY-MM-DD) get a countdown.
    const raw = (card.dataset.deadline || '').trim();
    const isDate = /^\d{4}-\d{2}-\d{2}$/.test(raw);
    const soonBadge = card.querySelector('.badge-soon');
    if (isDate) {
      const due = Date.parse(raw + 'T23:59:59');
      const daysLeft = Math.ceil((due - now) / DAY);
      card.dataset.daysLeft = String(daysLeft);
      if (daysLeft < 0) {
        card.dataset.deadlineState = 'past';
        if (soonBadge) { soonBadge.hidden = false; soonBadge.textContent = 'passed'; soonBadge.classList.add('is-past'); }
      } else if (daysLeft <= SOON_DAYS) {
        card.dataset.deadlineState = 'soon';
        if (soonBadge) { soonBadge.hidden = false; soonBadge.textContent = daysLeft + 'd left'; }
      } else {
        card.dataset.deadlineState = 'future';
      }
    } else {
      // rolling / annual — no fixed countdown.
      card.dataset.deadlineState = raw.toLowerCase() || 'none';
    }
  });

  function apply() {
    const level = levelSel.value;
    const region = regionSel.value;
    const status = statusSel.value;
    const q = searchInp.value.trim().toLowerCase();
    const soonOnly = soonChk.checked;
    const focuses = focusCbs.filter(cb => cb.checked).map(cb => cb.value);

    let shown = 0;
    cards.forEach(card => {
      const matchesLevel = !level || card.dataset.level === level;
      const matchesRegion = !region || card.dataset.region === region;
      const matchesStatus = !status || card.dataset.status === status;
      const cardFocus = (card.dataset.focus || '').split(' ');
      const matchesFocus = focuses.length === 0 || focuses.every(f => cardFocus.includes(f));
      const matchesQ = !q || card.dataset.search.includes(q);
      const matchesSoon = !soonOnly || card.dataset.deadlineState === 'soon';

      const visible = matchesLevel && matchesRegion && matchesStatus && matchesFocus && matchesQ && matchesSoon;
      card.hidden = !visible;
      if (visible) shown++;
    });
    visibleCount.textContent = shown;

    // sync URL hash so filtered views are shareable
    const params = new URLSearchParams();
    if (level) params.set('level', level);
    if (region) params.set('region', region);
    if (status) params.set('status', status);
    if (q) params.set('q', q);
    if (soonOnly) params.set('soon', '1');
    if (focuses.length) params.set('focus', focuses.join(','));
    history.replaceState(null, '', params.toString() ? '#' + params.toString() : location.pathname);
  }

  function restore() {
    if (!location.hash) return;
    const params = new URLSearchParams(location.hash.slice(1));
    if (params.has('level')) levelSel.value = params.get('level');
    if (params.has('region')) regionSel.value = params.get('region');
    if (params.has('status')) statusSel.value = params.get('status');
    if (params.has('q')) searchInp.value = params.get('q');
    if (params.has('soon')) soonChk.checked = params.get('soon') === '1';
    if (params.has('focus')) {
      const set = new Set(params.get('focus').split(','));
      focusCbs.forEach(cb => { cb.checked = set.has(cb.value); });
    }
  }

  [levelSel, regionSel, statusSel].forEach(s => s.addEventListener('change', apply));
  searchInp.addEventListener('input', apply);
  soonChk.addEventListener('change', apply);
  focusCbs.forEach(cb => cb.addEventListener('change', apply));

  restore();
  apply();
})();
