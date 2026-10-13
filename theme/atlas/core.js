/** SmokePing 2.8.2 accepts both semicolon- and ampersand-separated CGI parameters. */
export function smokePingURL(value, base) {
  const url = new URL(value, base);
  url.search = url.search.replace(/;/g, '&');
  return url;
}

export function intervalLabel(seconds) {
  if (seconds < 60) return `${seconds} s`;
  if (seconds % 60 === 0) return `${seconds / 60} min`;
  return `${seconds} s`;
}

export function epochValue(value, now = Math.floor(Date.now() / 1000)) {
  if (value === 'now' || value === 'last') return now;
  if (/^\d+$/.test(String(value))) return Number(value);
  const match = /^([+-]?)(\d+)(s|m|h|d|w|mo|y)$/.exec(String(value).trim());
  if (!match) return NaN;
  const units = { s:1, m:60, h:3600, d:86400, w:604800, mo:2592000, y:31536000 };
  return now + (match[1] === '+' ? 1 : -1) * Number(match[2]) * units[match[3]];
}

/** Cropper coordinates use the intrinsic PNG width, including RRDtool's margins. */
export function croppedRange(coords, width, start, end, margins = {left:67, right:26}) {
  const leftMargin = margins.left;
  const rightMargin = margins.right;
  const usable = width - leftMargin - rightMargin;
  if (usable <= 0 || !Number.isFinite(start) || !Number.isFinite(end) || end <= start) return null;
  const left = Math.max(leftMargin, Math.min(coords.x1, coords.x2));
  const right = Math.min(width - rightMargin, Math.max(coords.x1, coords.x2));
  if (right <= left) return null;
  const span = end - start;
  const result = {
    start: Math.floor(start + (left - leftMargin) / usable * span),
    end: Math.ceil(start + (right - leftMargin) / usable * span)
  };
  return result.end > result.start ? result : null;
}

export function navigatorImageURL(endpoint, target, hierarchy, range, base) {
  const url = smokePingURL(endpoint, base);
  // Keep other endpoint parameters (for reverse proxies/custom CGI setups).
  url.searchParams.set('displaymode', 'a');
  url.searchParams.set('start', String(range.start));
  url.searchParams.set('end', String(range.end));
  url.searchParams.set('target', target);
  if (hierarchy && hierarchy !== '0') url.searchParams.set('hierarchy', hierarchy);
  else url.searchParams.delete('hierarchy');
  url.searchParams.delete('epoch_start');
  url.searchParams.delete('epoch_end');
  return url.href;
}

/** Missing latency can mean recorded probe failures, rather than missing measurements. */
export function graphDataState(stats) {
  if (['median_ms','average_ms','maximum_ms'].some(key => Number.isFinite(stats[key]))) return 'latency';
  if (stats.loss_percent === 100) return 'no_replies';
  if (['loss_percent','last_loss_percent'].some(key => Number.isFinite(stats[key]))) return 'no_latency';
  return 'no_data';
}
