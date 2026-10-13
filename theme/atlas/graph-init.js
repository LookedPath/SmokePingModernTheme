/* Classic bootstrap: keep native PNGs inert until the graph renderer chooses them. */
(() => {
  const mode = document.querySelector('meta[name="atlas-graph-loading"]')?.content;
  if (mode !== 'renderer-first') return;
  const root = document.documentElement;
  root.classList.add('atlas-renderer-first');
  for (const template of document.querySelectorAll('template[data-atlas-graphs]')) {
    const content = template.content;
    for (const image of content.querySelectorAll('img[src]')) {
      image.dataset.atlasNativeSrc = new URL(image.getAttribute('src'), document.baseURI).href;
      image.removeAttribute('src');
      if (image.hasAttribute('srcset')) {
        image.dataset.atlasNativeSrcset = image.getAttribute('srcset');
        image.removeAttribute('srcset');
      }
      image.classList.add('atlas-graph-deferred');
    }
    template.parentElement.querySelector(':scope > noscript')?.remove();
    template.replaceWith(content);
  }
  // If the module cannot load, the classic bootstrap still restores usable graphs.
  setTimeout(() => {
    if (root.dataset.atlasRendererStarted === 'true') return;
    root.classList.add('no-js');
    root.classList.remove('js');
    for (const image of document.querySelectorAll('img[data-atlas-native-src]')) {
      if (image.hasAttribute('src')) continue;
      if (image.dataset.atlasNativeSrcset) image.srcset = image.dataset.atlasNativeSrcset;
      image.src = image.dataset.atlasNativeSrc;
    }
  }, 10000);
})();
