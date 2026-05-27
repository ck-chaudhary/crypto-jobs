// crypto-jobs filter — runs entirely in the browser.
// Filters by type / region / status / area / free text search.

(function () {
  const cards = Array.from(document.querySelectorAll('.cards .card'));
  const typeSel = document.getElementById('f-type');
  const regionSel = document.getElementById('f-region');
  const statusSel = document.getElementById('f-status');
  const searchInp = document.getElementById('f-search');
  const areaCbs = Array.from(document.querySelectorAll('.area-cb'));
  const visibleCount = document.getElementById('visible-count');
  const totalCount = document.getElementById('total-count');
  const lastUpdated = document.getElementById('last-updated');

  totalCount.textContent = cards.length;

  function apply() {
    const type = typeSel.value;
    const region = regionSel.value;
    const status = statusSel.value;
    const q = searchInp.value.trim().toLowerCase();
    const areas = areaCbs.filter(cb => cb.checked).map(cb => cb.value);

    let shown = 0;
    cards.forEach(card => {
      const matchesType = !type || card.dataset.type === type;
      const matchesRegion = !region || card.dataset.region === region;
      const matchesStatus = !status || card.dataset.status === status;
      const cardAreas = (card.dataset.area || '').split(' ');
      const matchesArea = areas.length === 0 || areas.every(a => cardAreas.includes(a));
      const matchesQ = !q || card.dataset.search.includes(q);

      const visible = matchesType && matchesRegion && matchesStatus && matchesArea && matchesQ;
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
    if (params.has('areas')) {
      const set = new Set(params.get('areas').split(','));
      areaCbs.forEach(cb => { cb.checked = set.has(cb.value); });
    }
  }

  // wire up
  [typeSel, regionSel, statusSel].forEach(s => s.addEventListener('change', apply));
  searchInp.addEventListener('input', apply);
  areaCbs.forEach(cb => cb.addEventListener('change', apply));

  restore();
  apply();

  // last-updated marker — built into the page at deploy time would be ideal,
  // but we can read the file mtime from a meta tag if you choose to inject it.
  // For now, show today.
  if (lastUpdated) {
    const d = new Date();
    lastUpdated.textContent = d.toISOString().slice(0, 10);
  }
})();
