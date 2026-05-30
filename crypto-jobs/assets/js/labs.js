// labs filter — runs entirely in the browser.
// Filters the cryptography groups directory by region / area / free text.

(function () {
  const regionSel = document.getElementById('l-region');
  if (!regionSel) return;

  const cards = Array.from(document.querySelectorAll('.cards .card'));
  const searchInp = document.getElementById('l-search');
  const areaCbs = Array.from(document.querySelectorAll('.larea-cb'));
  const visibleCount = document.getElementById('l-visible-count');
  const totalCount = document.getElementById('l-total-count');

  totalCount.textContent = cards.length;

  function apply() {
    const region = regionSel.value;
    const q = searchInp.value.trim().toLowerCase();
    const areas = areaCbs.filter(cb => cb.checked).map(cb => cb.value);

    let shown = 0;
    cards.forEach(card => {
      const matchesRegion = !region || card.dataset.region === region;
      const cardAreas = (card.dataset.area || '').split(' ');
      const matchesArea = areas.length === 0 || areas.every(a => cardAreas.includes(a));
      const matchesQ = !q || card.dataset.search.includes(q);

      const visible = matchesRegion && matchesArea && matchesQ;
      card.hidden = !visible;
      if (visible) shown++;
    });
    visibleCount.textContent = shown;

    // sync URL hash so filters are shareable
    const params = new URLSearchParams();
    if (region) params.set('region', region);
    if (q) params.set('q', q);
    if (areas.length) params.set('areas', areas.join(','));
    history.replaceState(null, '', params.toString() ? '#' + params.toString() : location.pathname);
  }

  function restore() {
    if (!location.hash) return;
    const params = new URLSearchParams(location.hash.slice(1));
    if (params.has('region')) regionSel.value = params.get('region');
    if (params.has('q')) searchInp.value = params.get('q');
    if (params.has('areas')) {
      const set = new Set(params.get('areas').split(','));
      areaCbs.forEach(cb => { cb.checked = set.has(cb.value); });
    }
  }

  regionSel.addEventListener('change', apply);
  searchInp.addEventListener('input', apply);
  areaCbs.forEach(cb => cb.addEventListener('change', apply));

  restore();
  apply();
})();
