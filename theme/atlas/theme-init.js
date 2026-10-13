/* Inlined by the installer: apply appearance before any external asset loads. */
(function () {
  'use strict';
  var root = document.documentElement;
  var theme = 'system';
  try {
    var saved = localStorage.getItem('smokeping-atlas-appearance');
    if (/^(system|light|dark)$/.test(saved)) theme = saved;
  } catch (_) { /* Storage can be unavailable in private or restricted browsers. */ }
  root.setAttribute('data-theme', theme);
  root.classList.replace('no-js', 'js');
  if (document.querySelector('meta[name="atlas-graph-loading"]')?.content === 'renderer-first') {
    root.classList.add('atlas-renderer-first');
  }
}());
