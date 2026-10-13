import { initGraphRenderer, rendererEndpoint } from './renderer.js';
import { smokePingURL, intervalLabel, epochValue, croppedRange, navigatorImageURL } from './core.js';

const root = document.documentElement;
const byId = id => document.getElementById(id);
const pageURL = smokePingURL(location.href, location.href);
const sidebar = byId('sidebar');
const menuButton = byId('atlas-menu-button');
const closeMenuButton = byId('atlas-menu-close');
const backdrop = byId('atlas-backdrop');
const mobile = matchMedia('(max-width: 760px)');
const overview = byId('atlas-overview');
const details = byId('atlas-details');
const status = byId('atlas-page-status');
const dialog = byId('atlas-graph-dialog');
const appearance = byId('atlas-theme');
const refreshCheckbox = byId('atlas-auto-refresh');
const navigatorImage = document.querySelector('#atlas-details #zoom');
const loadedAt = new Date().toLocaleTimeString([], { hour:'2-digit', minute:'2-digit' });
const step = Number(document.body.dataset.step);
const refreshInterval = Number.isFinite(step) && step >= 1 ? step : 0;
let menuOpen = false;
let refreshTimer;
let cropper;

function readPreference(key, fallback) {
  try { return localStorage.getItem(key) ?? fallback; } catch (_) { return fallback; }
}
function savePreference(key, value) {
  try { localStorage.setItem(key, value); } catch (_) { /* Preferences still work without storage. */ }
}
appearance.value = root.dataset.theme || 'system';
appearance.addEventListener('change', () => {
  root.dataset.theme = appearance.value;
  savePreference('smokeping-atlas-appearance', appearance.value);
});

function setMenu(open, returnFocus = false) {
  menuOpen = mobile.matches && open;
  root.dataset.menuOpen = String(menuOpen);
  menuButton.setAttribute('aria-expanded', String(menuOpen));
  menuButton.setAttribute('aria-label', menuOpen ? 'Close target navigation' : 'Open target navigation');
  sidebar.inert = mobile.matches && !menuOpen;
  if (mobile.matches) sidebar.setAttribute('aria-hidden', String(!menuOpen));
  else sidebar.removeAttribute('aria-hidden');
  backdrop.hidden = !menuOpen;
  if (menuOpen) closeMenuButton.focus();
  else if (returnFocus) menuButton.focus();
  updateRefresh();
}
menuButton.addEventListener('click', () => setMenu(!menuOpen, menuOpen));
closeMenuButton.addEventListener('click', () => setMenu(false, true));
backdrop.addEventListener('click', () => setMenu(false, true));
mobile.addEventListener('change', () => setMenu(false));
sidebar.addEventListener('keydown', event => {
  if (!menuOpen) return;
  if (event.key === 'Escape') { event.preventDefault(); setMenu(false, true); return; }
  if (event.key !== 'Tab') return;
  const focusable = [...sidebar.querySelectorAll('a[href],button,input,select')].filter(el => !el.disabled && el.getClientRects().length);
  const first = focusable[0], last = focusable.at(-1);
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
});

// Build breadcrumbs only from native links that SmokePing actually rendered.
const homeURL = new URL(pageURL.pathname, pageURL);
const hierarchy = pageURL.searchParams.get('hierarchy');
if (hierarchy && hierarchy !== '0') homeURL.searchParams.set('hierarchy', hierarchy);
document.querySelectorAll('[data-home]').forEach(link => { link.href = homeURL.href; });
if (!pageURL.searchParams.get('target')) document.querySelector('.atlas-home').setAttribute('aria-current', 'page');
document.querySelectorAll('#atlas-targets .menulinkactive').forEach(link => link.setAttribute('aria-current', 'page'));
const breadcrumb = byId('atlas-breadcrumb');
const home = document.createElement('a');
home.href = homeURL.href;
home.textContent = 'Network';
breadcrumb.append(home);
const currentTarget = pageURL.searchParams.get('target') || '';
const links = [...document.querySelectorAll('#atlas-targets .menu a[href]')];
const path = currentTarget.split('~')[0].split('.').filter(Boolean);
path.forEach((_, index) => {
  const target = path.slice(0, index + 1).join('.');
  const link = links.find(link => smokePingURL(link.href, pageURL).searchParams.get('target') === target);
  if (!link) return;
  const separator = document.createElement('span');
  separator.className = 'atlas-breadcrumb-separator';
  separator.textContent = '›';
  separator.setAttribute('aria-hidden', 'true');
  const item = document.createElement(index === path.length - 1 ? 'span' : 'a');
  item.textContent = link.textContent;
  if (item.tagName === 'A') item.href = link.href;
  else item.setAttribute('aria-current', 'page');
  breadcrumb.append(separator, item);
});
if (!byId('atlas-title').textContent.trim()) {
  const nativeTitle = overview.querySelector('h1');
  byId('atlas-title').textContent = nativeTitle?.textContent || 'SmokePing charts';
  nativeTitle?.remove();
}

// Preserve the native hierarchy/filter form, including its CGI action and parameters.
const hierarchyForm = document.querySelector('#atlas-targets form');
if (hierarchyForm) {
  const submit = document.createElement('button');
  submit.type = 'submit';
  submit.className = 'atlas-button';
  submit.textContent = 'Apply filter';
  hierarchyForm.append(submit);
}

function fullSizeButton(image, heading, title) {
  if (!dialog.showModal) return;
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'atlas-button atlas-graph-button';
  button.textContent = 'Full size';
  button.setAttribute('aria-label', `View ${title} graph at full size`);
  button.addEventListener('click', () => {
    byId('atlas-dialog-title').textContent = title;
    const fullImage = byId('atlas-dialog-image');
    fullImage.src = image.currentSrc || image.src;
    fullImage.alt = image.alt;
    fullImage.closest('.atlas-dialog-canvas').classList.toggle('atlas-native-surface', !image.closest('.atlas-rendered-surface'));
    // Native-size pixels; no loss-color transforms or image filtering.
    if (image.naturalWidth) fullImage.width = image.naturalWidth;
    dialog.showModal();
    updateRefresh();
  });
  heading.append(button);
}
dialog.addEventListener('close', updateRefresh);
dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });

let graphIndex = 0;
document.querySelectorAll('#atlas-overview .panel,#atlas-details .panel').forEach(panel => {
  const image = panel.querySelector('img');
  if (!image) return; // Keep native waiting/error messages visible.
  graphIndex += 1;
  panel.id = `atlas-graph-${graphIndex}`;
  let heading = panel.querySelector('.panel-heading');
  if (!heading) {
    heading = document.createElement('div');
    heading.className = 'panel-heading';
    const title = document.createElement('h2');
    const graphLink = image.closest('a[href]');
    const graphTarget = graphLink ? smokePingURL(graphLink.href, pageURL).searchParams.get('target') : currentTarget;
    title.textContent = links.find(link => smokePingURL(link.href, pageURL).searchParams.get('target') === graphTarget)?.textContent || byId('atlas-title').textContent || 'Latency graph';
    heading.append(title);
    panel.prepend(heading);
  }
  const title = heading.querySelector('h2')?.textContent.trim() || 'Latency graph';
  image.alt = `${title}. SmokePing latency distribution and packet-loss graph; statistics and units are printed in the image.`;
  if (image.id === 'zoom') return;
  image.classList.add('atlas-graph-image');
  const keepNativeResolution = () => { if (image.naturalWidth && !image.closest('.atlas-rendered-surface')) image.style.maxWidth = `min(100%, ${image.naturalWidth}px)`; };
  image.addEventListener('load', () => {
    keepNativeResolution();
    panel.querySelector('.atlas-graph-error')?.remove();
    panel.querySelector('.atlas-graph-button')?.removeAttribute('disabled');
  });
  keepNativeResolution();
  image.loading = panel.closest('#atlas-details') ? 'lazy' : 'eager';
  const graphLink = image.closest('a');
  const surface = document.createElement('div');
  surface.className = 'atlas-graph-surface';
  const graphElement = graphLink || image;
  graphElement.before(surface);
  surface.append(graphElement);
  if (panel.closest('#atlas-overview') && graphLink && heading.querySelector('h2')) {
    const titleElement = heading.querySelector('h2');
    const titleLink = document.createElement('a');
    titleLink.href = graphLink.href;
    titleLink.textContent = titleElement.textContent;
    titleElement.replaceChildren(titleLink);
  }
  fullSizeButton(image, heading, title);
  const showGraphError = () => {
    if (panel.querySelector('.atlas-graph-error')) return;
    const error = document.createElement('p');
    error.className = 'atlas-graph-error';
    error.setAttribute('role', 'status');
    error.textContent = 'This graph could not be loaded. Check the SmokePing image-cache URL and permissions.';
    surface.after(error);
    heading.querySelector('.atlas-graph-button')?.setAttribute('disabled', '');
  };
  image.addEventListener('error', showGraphError);
  if (image.hasAttribute('src') && image.complete && !image.naturalWidth) showGraphError();
});

const overviewPanels = [...overview.querySelectorAll(':scope > .panel')].filter(panel => panel.querySelector('img'));
if (overviewPanels.length) {
  byId('atlas-overview-toolbar').hidden = false;
  byId('atlas-target-count').textContent = `/ ${overviewPanels.length} graphs`;
  byId('atlas-search-control').hidden = false;
  root.dataset.hasSearch = 'true';
  byId('atlas-search').addEventListener('input', event => {
    const query = event.target.value.trim().toLocaleLowerCase();
    let visible = 0;
    overviewPanels.forEach(panel => {
      const match = panel.querySelector('h2').textContent.toLocaleLowerCase().includes(query);
      panel.hidden = !match;
      if (match) visible += 1;
    });
    byId('atlas-target-count').textContent = `/ ${visible} of ${overviewPanels.length} graphs`;
    byId('atlas-no-matches').hidden = visible > 0;
    updateRefresh();
  });
}
byId('atlas-empty-view').hidden = Boolean(overview.textContent.trim() || details.textContent.trim() || overview.querySelector('img') || details.querySelector('img'));

const rangeLinks = byId('atlas-ranges');
const detailedPanels = [...details.querySelectorAll(':scope > .panel')];
if (!navigatorImage && detailedPanels.length > 1) {
  detailedPanels.forEach(panel => {
    const heading = panel.querySelector('h2');
    if (!heading) return;
    const anchor = document.createElement('a');
    anchor.href = `#${panel.id}`;
    anchor.textContent = heading.textContent;
    rangeLinks.append(anchor);
  });
  rangeLinks.hidden = !rangeLinks.childElementCount;
}

// Refresh complete CGI pages; never invent a data API or probe timestamps.
refreshCheckbox.checked = readPreference('smokeping-atlas-refresh', 'on') !== 'off' && !navigatorImage && refreshInterval > 0;
refreshCheckbox.disabled = Boolean(navigatorImage) || refreshInterval === 0;
function refreshPaused() {
  const editing = document.activeElement?.matches('input,select,textarea');
  return document.hidden || menuOpen || dialog.open || editing || Boolean(byId('atlas-search').value);
}
function updateRefresh() {
  clearTimeout(refreshTimer);
  const prefix = `Page loaded ${loadedAt}`;
  if (navigatorImage) { status.textContent = `${prefix} · Auto refresh paused in graph navigator`; return; }
  if (!refreshCheckbox.checked || !refreshInterval) { status.textContent = `${prefix} · Auto refresh off`; return; }
  const paused = refreshPaused();
  status.textContent = `${prefix} · Refresh every ${intervalLabel(refreshInterval)}${paused ? ' · Paused while interacting' : ''}`;
  if (!paused) refreshTimer = setTimeout(() => { if (refreshPaused()) updateRefresh(); else location.reload(); }, refreshInterval * 1000);
}
refreshCheckbox.addEventListener('change', () => { savePreference('smokeping-atlas-refresh', refreshCheckbox.checked ? 'on' : 'off'); updateRefresh(); });
byId('atlas-refresh-now').addEventListener('click', () => location.reload());
document.addEventListener('visibilitychange', updateRefresh);
document.addEventListener('focusin', updateRefresh);
document.addEventListener('focusout', () => setTimeout(updateRefresh, 0));
setMenu(false);

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = src;
    script.onload = resolve;
    script.onerror = () => reject(new Error(`Could not load ${src}`));
    document.head.append(script);
  });
}

async function setupNavigator() {
  if (!navigatorImage) return;
  const form = document.querySelector('#range_form');
  if (!form) return;
  const panel = navigatorImage.closest('.panel-body');
  const surface = document.createElement('div');
  surface.className = 'atlas-navigator-scroll';
  surface.setAttribute('aria-label', 'Full-resolution graph. Scroll horizontally to inspect it.');
  navigatorImage.before(surface);
  surface.append(navigatorImage);
  const hint = document.createElement('p');
  hint.className = 'atlas-navigator-hint';
  hint.textContent = 'Use the time-range fields to zoom. The graph keeps its original resolution.';
  panel.prepend(hint);
  const startField = form.elements.namedItem('start');
  const endField = form.elements.namedItem('end');
  const submit = form.querySelector('input[type="submit"],button[type="submit"]');
  if (startField && endField && submit) {
    const hiddenFields = [...form.querySelectorAll('input[type="hidden"]')];
    const fields = document.createElement('div');
    fields.className = 'atlas-form-fields';
    [['Start', startField], ['End', endField]].forEach(([text, input]) => {
      const label = document.createElement('label');
      label.append(document.createTextNode(text), input);
      fields.append(label);
    });
    fields.append(submit);
    form.replaceChildren(...hiddenFields, fields);
  }
  if (rendererEndpoint()) return;
  const themeScript = new URL(import.meta.url);
  // The Ubuntu package's existing library symlinks live beside /atlas/, under /js/.
  const libraries = new URL('../js/', themeScript);
  let start = epochValue(form.elements.namedItem('epoch_start')?.value ?? startField?.value);
  let end = epochValue(form.elements.namedItem('epoch_end')?.value ?? endField?.value);
  try {
    for (const path of ['prototype/prototype.js','scriptaculous/builder.js','scriptaculous/effects.js','scriptaculous/dragdrop.js','cropper/cropper.js']) await loadScript(new URL(path, libraries).href);
    if (!navigatorImage.complete) await new Promise(resolve => { navigatorImage.addEventListener('load', resolve, { once:true }); navigatorImage.addEventListener('error', resolve, { once:true }); });
    if (!window.Cropper?.Img || !navigatorImage.naturalWidth) throw new Error('Navigator libraries or graph are unavailable');
    cropper = new window.Cropper.Img('zoom', {
      minHeight:navigatorImage.height, maxHeight:navigatorImage.height,
      onEndCrop(coords) {
        const range = croppedRange(coords, navigatorImage.width, start, end);
        if (!range) return;
        start = range.start;
        end = range.end;
        navigatorImage.src = navigatorImageURL(form.action || pageURL.href, form.elements.namedItem('target')?.value || currentTarget, form.elements.namedItem('hierarchy')?.value || hierarchy, range, pageURL);
        [['epoch_start',start],['epoch_end',end],['start',start],['end',end]].forEach(([name,value]) => { const input=form.elements.namedItem(name); if (input) input.value=String(value); });
      }
    });
    navigatorImage.addEventListener('load', () => cropper?.setParams());
    hint.textContent = 'Drag across the graph to zoom, or enter a start and end time. On a phone, use the time-range fields.';
  } catch (_) {
    hint.textContent = 'Use the time-range fields to zoom. Drag-to-zoom is unavailable; check the graph image and the existing SmokePing js/ assets.';
  }
}
setupNavigator();
initGraphRenderer(pageURL);
