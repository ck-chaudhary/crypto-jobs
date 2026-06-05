// crypto-jobs filter — runs entirely in the browser.
// Filters by type / region / status / area / "new" / free text search.

(function () {
  // "Data last updated" marker lives in the layout on every page.
  const lastUpdated = document.getElementById('last-updated');

  // Everything below is specific to the positions page. Bail on other pages,
  // but still stamp the shared header with today's date there.
  const typeSel = document.getElementById('f-type');
  if (!typeSel) {
    if (lastUpdated) lastUpdated.textContent = new Date().toISOString().slice(0, 10);
    return;
  }

  const cards = Array.from(document.querySelectorAll('.cards .card'));
  const regionSel = document.getElementById('f-region');
  const statusSel = document.getElementById('f-status');
  const searchInp = document.getElementById('f-search');
  const newChk = document.getElementById('f-new');
  const areaCbs = Array.from(document.querySelectorAll('.area-cb'));
  const visibleCount = document.getElementById('visible-count');
  const totalCount = document.getElementById('total-count');

  totalCount.textContent = cards.length;

  // ---- Mark cards added within the last 3 days as NEW, and measure data
  //      freshness from the `added` dates the scraper stamps on each job. ----
  const NEW_DAYS = 3;
  const FRESH_DAYS = 7;
  const now = Date.now();
  let newestAdded = 0;
  let recentCount = 0;
  cards.forEach(card => {
    const added = Date.parse(card.dataset.added);
    const ageDays = (now - added) / 86400000;
    const isNew = !Number.isNaN(added) && ageDays >= 0 && ageDays <= NEW_DAYS;
    card.classList.toggle('is-new', isNew);
    const badge = card.querySelector('.badge-new');
    if (badge) badge.hidden = !isNew;
    if (!Number.isNaN(added)) {
      if (added > newestAdded) newestAdded = added;
      if (ageDays >= 0 && ageDays <= FRESH_DAYS) recentCount++;
    }
  });

  // "Data last updated" reflects the newest job actually added — not the
  // browser clock — so a stale board shows its real age instead of "today".
  if (lastUpdated) {
    lastUpdated.textContent = newestAdded
      ? new Date(newestAdded).toISOString().slice(0, 10)
      : new Date().toISOString().slice(0, 10);
  }

  // Inline freshness hint shown next to the Refresh button.
  const freshness = document.getElementById('data-freshness');
  if (freshness) {
    freshness.textContent = recentCount > 0
      ? ` · 🆕 ${recentCount} added in the last ${FRESH_DAYS} days`
      : ` · no new jobs in the last ${FRESH_DAYS} days`;
    freshness.classList.toggle('is-stale', recentCount === 0);
  }

  function apply() {
    const type = typeSel.value;
    const region = regionSel.value;
    const status = statusSel.value;
    const q = searchInp.value.trim().toLowerCase();
    const newOnly = newChk.checked;
    const areas = areaCbs.filter(cb => cb.checked).map(cb => cb.value);

    let shown = 0;
    cards.forEach(card => {
      const matchesType = !type || card.dataset.type === type;
      const matchesRegion = !region || card.dataset.region === region;
      const matchesStatus = !status || card.dataset.status === status;
      const cardAreas = (card.dataset.area || '').split(' ');
      const matchesArea = areas.length === 0 || areas.every(a => cardAreas.includes(a));
      const matchesQ = !q || card.dataset.search.includes(q);
      const matchesNew = !newOnly || card.classList.contains('is-new');

      const visible = matchesType && matchesRegion && matchesStatus && matchesArea && matchesQ && matchesNew;
      card.hidden = !visible;
      if (visible) shown++;
    });
    visibleCount.textContent = shown;

    // sync URL hash so filters are shareable
    const params = new URLSearchParams();
    if (type) params.set('type', type);
    if (region) params.set('region', region);
    if (status) params.set('status', status);
    if (q) params.set('q', q);
    if (newOnly) params.set('new', '1');
    if (areas.length) params.set('areas', areas.join(','));
    history.replaceState(null, '', params.toString() ? '#' + params.toString() : location.pathname);
  }

  // restore from hash
  function restore() {
    if (!location.hash) return;
    const params = new URLSearchParams(location.hash.slice(1));
    if (params.has('type')) typeSel.value = params.get('type');
    if (params.has('region')) regionSel.value = params.get('region');
    if (params.has('status')) statusSel.value = params.get('status');
    if (params.has('q')) searchInp.value = params.get('q');
    if (params.has('new')) newChk.checked = params.get('new') === '1';
    if (params.has('areas')) {
      const set = new Set(params.get('areas').split(','));
      areaCbs.forEach(cb => { cb.checked = set.has(cb.value); });
    }
  }

  // wire up
  [typeSel, regionSel, statusSel].forEach(s => s.addEventListener('change', apply));
  searchInp.addEventListener('input', apply);
  newChk.addEventListener('change', apply);
  areaCbs.forEach(cb => cb.addEventListener('change', apply));

  restore();
  apply();
})();
