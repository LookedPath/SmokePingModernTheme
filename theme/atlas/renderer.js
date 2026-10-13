import { smokePingURL, epochValue, croppedRange, graphDataState } from './core.js';

export function nativeGraphURL(image) {
  return image.dataset?.atlasNativeSrc || image.src;
}

function useNativeGraph(image, source = nativeGraphURL(image)) {
  if (image.dataset?.atlasNativeSrcset) image.srcset = image.dataset.atlasNativeSrcset;
  if (source) image.src = source;
  image.closest('.atlas-graph-surface,.atlas-navigator-scroll')?.classList.add('atlas-native-surface');
}

function loadGraphImage(image, url, signal) {
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      image.removeEventListener('load', loaded);
      image.removeEventListener('error', failed);
      signal.removeEventListener('abort', cancelled);
    };
    const loaded = () => { cleanup(); resolve(); };
    const failed = () => { cleanup(); reject(new Error('Graph image is unavailable')); };
    const cancelled = () => { cleanup(); reject(new DOMException('Cancelled', 'AbortError')); };
    if (signal.aborted) { cancelled(); return; }
    image.addEventListener('load', loaded);
    image.addEventListener('error', failed);
    signal.addEventListener('abort', cancelled, {once:true});
    image.removeAttribute('srcset');
    // We are explicitly awaiting this image; off-screen lazy loading would
    // otherwise time out even though the renderer successfully supplied it.
    image.loading = 'eager';
    image.src = url;
  });
}

export function graphDescriptor(image, pageURL) {
  const form = image.id === 'zoom' ? document.querySelector('#range_form') : null;
  const link = image.closest('a[href]');
  const url = link ? smokePingURL(link.href, pageURL) : pageURL;
  // Alternate hierarchies and aggregate graphs retain SmokePing's native renderer.
  if (url.searchParams.get('hierarchy') && url.searchParams.get('hierarchy') !== '0') return null;
  let target = form?.elements.namedItem('target')?.value || url.searchParams.get('target');
  if (!target) return null;
  const filename = decodeURIComponent(new URL(nativeGraphURL(image), pageURL).pathname.split('/').at(-1));
  const slave = /~(.+)$/.exec(filename.replace(/_(?:last|now|\d+)_\d+\.png$/, '').replace(/_mini\.png$/, ''))?.[1];
  if (slave && !target.includes('~')) target += `~${slave}`;
  let start, end;
  if (form) {
    start = epochValue(form.elements.namedItem('epoch_start')?.value);
    end = epochValue(form.elements.namedItem('epoch_end')?.value);
    if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
  } else {
    const range = /_(last|now|\d+)_(\d+)\.png$/.exec(filename);
    if (range) { end = range[1] === 'last' ? 'now' : range[1]; start = `-${range[2]}s`; }
    else if (!filename.endsWith('_mini.png') && !filename.endsWith('-overview.png') && !filename.endsWith('-detail.png')) return null;
  }
  return { target, ...(start !== undefined ? {start, end} : {}) };
}

export function rendererEndpoint() {
  const value = document.querySelector('meta[name="atlas-renderer"]')?.content;
  if (!value) return null;
  const url = new URL(value, location.href);
  return url.origin === location.origin ? url : null;
}

export function initGraphRenderer(pageURL) {
  const endpoint = rendererEndpoint();
  if (!endpoint) {
    document.querySelectorAll('img[data-atlas-native-src]').forEach(image => useNativeGraph(image));
    return;
  }
  document.documentElement.dataset.atlasRendererStarted = 'true';
  const scheme = matchMedia('(prefers-color-scheme: dark)');
  const theme = () => document.documentElement.dataset.theme === 'system' ? (scheme.matches ? 'dark' : 'light') : document.documentElement.dataset.theme;
  const states = [];
  for (const image of document.querySelectorAll('#atlas-overview .panel img,#atlas-details .panel img')) {
    const descriptor = graphDescriptor(image, pageURL);
    if (!descriptor) { useNativeGraph(image); continue; }
    const panel = image.closest('.panel');
    const surface = image.closest('.atlas-graph-surface,.atlas-navigator-scroll') || image.parentElement;
    const metrics = document.createElement('div');
    metrics.className = 'atlas-graph-metrics';
    metrics.hidden = true;
    surface.after(metrics);
    const state = { image, panel, surface, descriptor, native:nativeGraphURL(image), nativeLoading:image.loading, metrics, generation:0, controller:null, metadata:null, size:0 };
    states.push(state);
    if (image.id === 'zoom') setupZoom(state);
  }

  function restore(state, message) {
    state.image.loading = state.nativeLoading;
    useNativeGraph(state.image, state.native);
    state.image.removeAttribute('width');
    state.image.removeAttribute('height');
    state.image.style.maxWidth = '';
    state.surface.classList.remove('atlas-rendered-surface');
    state.metadata = null;
    delete state.panel.dataset.graphDataState;
    state.metrics.hidden = false;
    state.metrics.textContent = message;
    const hint = state.panel.querySelector('.atlas-navigator-hint');
    if (hint) hint.textContent = 'Use the time-range fields to zoom. This graph is using SmokePing’s native renderer.';
    state.metrics.classList.add('atlas-renderer-fallback');
  }

  async function update(state, force = false) {
    const width = Math.max(240, Math.min(1600, Math.floor(state.surface.clientWidth - 24)));
    const bucket = Math.ceil(width / 80) * 80;
    if (!force && bucket === state.size) return;
    state.size = bucket;
    state.controller?.abort();
    state.controller = new AbortController();
    const generation = ++state.generation;
    const controller = state.controller;
    // Bound both metadata and image loading; a stalled endpoint must fall back.
    let timedOut = false;
    const timeout = setTimeout(() => {timedOut=true; controller.abort();}, 60000);
    if (!state.image.hasAttribute('src')) {
      state.metrics.hidden = false;
      state.metrics.textContent = 'Loading graph…';
      state.panel.querySelector('.atlas-graph-button')?.setAttribute('disabled', '');
    }
    const url = new URL(endpoint);
    const height = state.panel.closest('#atlas-overview') ? 160 : 240;
    for (const [key,value] of Object.entries({...state.descriptor, theme:theme(), width, height,
      scale:devicePixelRatio > 1 ? 2 : 1, format:'json'})) url.searchParams.set(key, value);
    try {
      const result = await fetch(url, {signal:controller.signal, credentials:'same-origin'});
      if (!result.ok) throw new Error('Renderer unavailable');
      const data = await result.json();
      const png = new URL(endpoint);
      png.search = data.image_query;
      if (generation !== state.generation) return;
      // Assign only the selected renderer PNG: no preliminary native download
      // and no second image request through an off-screen preloader.
      await loadGraphImage(state.image, png.href, controller.signal);
      if (generation !== state.generation) return;
      state.metadata = data;
      state.image.width = data.width;
      state.image.height = data.height;
      state.image.style.maxWidth = '100%';
      state.image.alt = `${data.title}. Latency distribution in milliseconds; packet loss is shown by colored lines. Times are UTC.`;
      state.surface.classList.remove('atlas-native-surface');
      state.surface.classList.add('atlas-rendered-surface');
      state.panel.querySelector('.atlas-graph-error')?.remove();
      state.panel.querySelector('.atlas-graph-button')?.removeAttribute('disabled');
      state.metrics.classList.remove('atlas-renderer-fallback');
      state.metrics.replaceChildren();
      const stats = data.statistics;
      const dataState = graphDataState(stats);
      state.panel.dataset.graphDataState = dataState;
      const labels = [['Last median',stats.median_ms,'ms'], ['Avg median',stats.average_ms,'ms'],
        ['Max median',stats.maximum_ms,'ms'], ['Avg loss',stats.loss_percent,'%']];
      for (const [label,value,unit] of labels) {
        const item = document.createElement('span');
        const text = document.createElement('span');
        text.textContent = label;
        const number = document.createElement('strong');
        const unavailable = unit === 'ms' && dataState === 'no_replies' ? 'No replies'
          : unit === 'ms' && dataState === 'no_latency' ? 'No latency' : 'No data';
        number.textContent = Number.isFinite(value) ? `${value.toFixed(2)} ${unit}` : unavailable;
        if (label === 'Last median') item.title = 'Last non-missing median in the selected range';
        item.append(text,number);
        state.metrics.append(item);
      }
      if (dataState !== 'latency') {
        const note = document.createElement('p');
        note.className = 'atlas-graph-data-note';
        note.setAttribute('role','status');
        note.textContent = {
          no_replies:'No replies recorded · 100% packet loss in the available measurements.',
          no_latency:'Probe measurements are present, but latency values are unavailable for this range.',
          no_data:'No latency or packet-loss measurements are available for this range.'
        }[dataState];
        state.metrics.append(note);
      }
      const legend = document.createElement('details');
      const summary = document.createElement('summary');
      summary.textContent = 'Packet-loss legend · UTC';
      legend.append(summary);
      legend.className = 'atlas-loss-legend';
      for (const entry of data.loss_legend) {
        const item = document.createElement('span');
        const swatch = document.createElement('i');
        swatch.style.backgroundColor = entry.color;
        item.append(swatch, document.createTextNode(entry.label));
        legend.append(item);
      }
      const note = document.createElement('small');
      note.textContent = 'Smoke: latency distribution. Shading: red = total loss; gray = missing data. Consolidated historical loss can be fractional.';
      legend.append(note);
      state.metrics.append(legend);
      state.metrics.hidden = false;
    } catch (error) {
      if (generation !== state.generation || (error.name === 'AbortError' && !timedOut)) return;
      restore(state, 'Native graph · Atlas renderer unavailable for this graph');
    } finally {
      clearTimeout(timeout);
    }
  }

  function setupZoom(state) {
    const form = document.querySelector('#range_form');
    let initial;
    state.surface.classList.add('atlas-renderer-navigator');
    const selection = document.createElement('div');
    selection.className = 'atlas-zoom-selection';
    selection.hidden = true;
    state.surface.append(selection);
    const position = event => {
      const rect = state.image.getBoundingClientRect();
      return (event.clientX - rect.left) / rect.width * state.metadata.geometry.image_width;
    };
    state.image.addEventListener('pointerdown', event => {
      if (!state.metadata || event.pointerType === 'touch' || event.button !== 0) return;
      event.preventDefault();
      initial = position(event);
      state.image.setPointerCapture(event.pointerId);
    });
    state.image.addEventListener('pointermove', event => {
      if (initial === undefined || !state.metadata) return;
      const rect = state.image.getBoundingClientRect();
      const scale = rect.width / state.metadata.geometry.image_width;
      selection.hidden = false;
      selection.style.left = `${state.image.offsetLeft + Math.min(initial, position(event))*scale}px`;
      selection.style.width = `${Math.abs(initial-position(event))*scale}px`;
      selection.style.top = `${state.image.offsetTop}px`;
      selection.style.height = `${rect.height}px`;
    });
    state.image.addEventListener('pointercancel', () => {initial=undefined; selection.hidden=true;});
    state.image.addEventListener('pointerup', event => {
      if (initial === undefined || !state.metadata) return;
      const geometry = state.metadata.geometry;
      const range = croppedRange({x1:initial,x2:position(event)}, geometry.image_width, geometry.start, geometry.end,
        {left:geometry.graph_left, right:geometry.image_width-geometry.graph_left-geometry.graph_width});
      initial = undefined;
      selection.hidden = true;
      if (!range || range.end-range.start < 60) return;
      state.descriptor = {...state.descriptor, ...range};
      for (const name of ['start','end','epoch_start','epoch_end']) {
        const field = form?.elements.namedItem(name);
        if (field) field.value = String(name.includes('start') ? range.start : range.end);
      }
      update(state, true);
    });
    const hint = state.panel.querySelector('.atlas-navigator-hint');
    if (hint) hint.textContent = 'Drag across the graph to zoom. On a phone, use the time-range fields. Times on the graph are UTC.';
  }

  let timer;
  const observer = new ResizeObserver(() => {clearTimeout(timer); timer=setTimeout(() => states.forEach(state => update(state)), 180);});
  states.forEach(state => {observer.observe(state.surface); update(state);});
  const refresh = () => states.forEach(state => update(state, true));
  document.getElementById('atlas-theme')?.addEventListener('change', refresh);
  scheme.addEventListener('change', refresh);
}
