# Agent and maintainer reference

Use this file for development context. Keep `README.md` focused on repository visitors: features, supported environments, installation, upgrades, rollback, and practical troubleshooting. Put architecture, regression history, and test details here. User instructions take precedence over this file.

## Project scope

Atlas is a drop-in SmokePing presentation layer, targeting Ubuntu 24.04 Noble's `smokeping 2.8.2+ds-1`, including ARM. It consists of a supported HTML template, buildless CSS/JavaScript, and an optional on-demand graph renderer. It does not replace measurement collection.

Preserve these properties when making changes:

- Do not modify packaged SmokePing Perl modules, the original CGI, or monitoring RRDs as part of theme installation. Synthetic RRDs in development/test directories are disposable.
- Preserve native target, slave, hierarchy, charts, navigator, and manual time-range links and forms.
- Use real measurements for statistics. Do not invent probe timestamps, health badges, global target counts, or missing latency values.
- Keep native graphs available for unsupported cases and failures. Do not invert native PNGs: this distorts SmokePing's loss colors.
- Keep production dependencies small. There is no npm build or runtime dependency; Node is only for development.
- Keep commit messages and release descriptions short and feature-focused. Publishing or rewriting repository history is a separate user-requested task, not part of an ordinary fix.

## Source map

| File | Purpose |
| --- | --- |
| `theme/basepage.html` | SmokePing replacement template, inline startup colors, native placeholders |
| `theme/atlas/theme-init.js` | Canonical appearance bootstrap; inlined by installer and preview |
| `theme/atlas/graph-init.js` | Classic bootstrap for deferred graph markup and module-failure recovery |
| `theme/atlas/atlas.js` | Navigation, native panel adaptation, filtering, dialogs, refresh, native navigator |
| `theme/atlas/renderer.js` | Themed graph requests, fallback, metadata, and pointer zoom |
| `theme/atlas/core.js` | CGI URL parsing, epochs, crop mapping, graph-data state |
| `theme/atlas/atlas.css` | Appearance, responsive layout, accessibility, print, loading surfaces |
| `server/catalog.pl` | Read configured targets through installed SmokePing parser/probe metadata |
| `server/atlas_graph.py` | Python CGI, RRDtool graph generation, metadata, caching |
| `tools/install.py` | Install, validate, backup, and restore managed files |
| `tools/preview.mjs` | Local preview of real template with native-shaped synthetic HTML |
| `tools/renderer-preview.py` | Development-only synthetic RRD generator and renderer bridge |
| `tools/generate-fixtures.py` | Illustrative native PNG fixture generation, requires Pillow |
| `tools/package.py` | Portable release archive; excludes tests/demo tools and bytecode |

## SmokePing compatibility

The Noble package and upstream 2.8.2 source were inspected for template fields, menu/panel markup, static aliases, and library paths. Do not assume synthetic fixtures fully replace checks against native output.

- Native graph markup uses `.panel`, `.panel-heading`, `.panel-body`, and `img#zoom` for the navigator.
- The menu uses `.menu`, `.menuitem`, `.menuopen`, `.menuactive`, `.menulink`, and `.menulinkactive`. Normally only expanded branches are rendered; the theme must not pretend to know every target globally.
- CGI queries accept both literal `;` and `&` separators. Encoded `%3B` must remain data. Preserve `target`, `hierarchy`, and slave suffixes such as `~remote_probe`.
- The native sidebar form is named `hswitch`; preserve its filter/hierarchy fields and action.
- The native navigator form is `#range_form`, with `start`, `end`, `epoch_start`, `epoch_end`, `target`, `hierarchy`, and `displaymode` fields. Native date fields remain supported through SmokePing's own submission logic.
- SmokePing 2.8.2 generates PNGs. Statistics printed in native PNGs are not a browser-readable API.
- Native crop geometry defaults to 67 px left and 26 px right margins. Atlas-rendered zoom must instead use returned RRDtool geometry and actual displayed-to-intrinsic scaling.
- The native navigator uses distro-provided assets under `js/prototype/prototype.js`, `js/scriptaculous/{builder,effects,dragdrop}.js`, and `js/cropper/cropper.js`. Load them only for the native navigator. The manual form must work when they are unavailable.
- Do not load packaged `smokeping.js` alongside Atlas's navigator adapter; it also manages native UI behavior and can conflict.

The optional renderer handles individual latency targets and configured slaves. Alternate hierarchies, group aggregates, multi-host graphs, and non-seconds probe units retain native rendering. Hidden targets and `nomasterpoll` master entries are excluded from the catalog.

## Installer and web-server contract

Default managed locations:

| Purpose | Path |
| --- | --- |
| Full configuration | `/etc/smokeping/config` |
| Presentation section | `/etc/smokeping/config.d/Presentation` |
| Template | `/etc/smokeping/atlas/basepage.html` |
| Assets | `/usr/share/smokeping/www/atlas/` |
| Python CGI | `/usr/lib/cgi-bin/smokeping-atlas.cgi` |
| Catalog helper | `/usr/share/smokeping-atlas/catalog.pl` |
| Renderer settings | `/etc/smokeping/atlas/renderer.json` |
| Apache mapping | `/etc/apache2/conf-available/smokeping-atlas.conf` |
| Renderer cache | `/var/cache/smokeping-atlas/` |
| Backups | `/var/backups/smokeping-atlas/<backup-id>/` |

`--presentation` selects the presentation section file; `--smokeping-config` selects the full configuration including its includes. URL options are absolute URL paths, not filesystem paths. Staged installs use `--root` with `--skip-config-check`; real installs require root.

The installer changes only the root Presentation section's `template` and `htmltitle` settings. It validates a single template setting, rejects duplicate title settings, injection, traversal, and symlink escapes, writes atomically, preserves existing file metadata, and rolls back managed files on failure. Directories must remain traversable under a restrictive sudo umask. Backups are private. Generated cache directories are retained on restore.

The renderer requires Python 3, `/usr/bin/rrdtool`, installed SmokePing Perl dependencies, and access to the same configuration/RRD files as the web frontend. Its preflight runs as `www-data`; the dedicated cache is owned by that account with mode 0700.

Nginx needs an exact FastCGI location for `/smokeping/atlas-graph.cgi`, using `SCRIPT_FILENAME=/usr/lib/cgi-bin/smokeping-atlas.cgi` and the existing fcgiwrap socket. The static `/smokeping/` alias alone cannot execute it. Use `fastcgi_intercept_errors off` to retain JSON errors. The supplied Apache mapping is not enabled automatically and does not add `Require all granted`. Both CGI endpoints must share the site's access policy. The installer still prints Apache activation commands; README explains that Nginx users should ignore them.

## Renderer semantics and cache

- Targets are resolved through the installed SmokePing configuration parser and probe objects, not request-supplied file paths. The adapter reads metadata without running measurement collection.
- Only configured, readable RRD paths inside the configured data directory are accepted; symlink escapes are rejected.
- Latency comes from `median` and sorted `pingN` DS values, converted from seconds to milliseconds. Smoke bands preserve the sample distribution rather than smoothing it into decorative curves.
- Packet loss comes from `loss / configured ping count`. Default thresholds follow SmokePing's count thresholds; configured `detail/loss_colors` are honored. The default no-loss median line uses the theme's blue accent. Total loss has red shading even when latency is unknown; missing measurements have gray shading.
- Metrics use the same consolidated series and interval as the PNG. Resolution/consolidation can affect averages and maxima. `Last median` is the last non-missing median in the selected range, not the latest probe collection time. `Max median` is not the slowest individual ping. Graph timestamps use UTC.
- Null latency plus average loss of exactly 100% means **No replies**, not missing measurements. Null latency with available loss means **No latency**. Fully missing latency/loss means **No data**. Zero latency is a valid numeric result. These states do not prove a host is offline.
- `graphv` reports unzoomed geometry. Actual PNG dimensions are read from its header and used to scale geometry for 1×/2× output.
- Inputs have bounded ranges, dimensions, scale, ping counts, and parameter counts. Width/height buckets bound cache variants. Commands have timeouts; one lock limits concurrent RRDtool generation.
- Cache keys include renderer version, target/slave, theme, range, size, scale, catalog entry, RRD path, and stored last-update timestamp. Do not rely only on filesystem mtime: mmap updates can leave it unchanged.
- PNG tokens bind the exact metadata snapshot to its image, even if the RRD updates between the two requests. Validate token format and requested spec before serving cached files.
- Prune old graph pairs on render requests: up to 256 pairs and approximately 128 MiB of PNGs, with an hour age threshold. The catalog expires after 30 seconds, including for included-config changes.
- Bump the renderer version when graph generation or cached metadata semantics change. Frontend-only changes receive a new installer asset hash automatically.

## Regressions to preserve

### Native download before Atlas rendering

Changing `img.src` in a late module is too late to prevent the HTML parser's native image download. Renderer-enabled installation wraps native graph placeholders in inert `<template>` elements and provides `<noscript>` markup. The classic bootstrap saves native URLs and removes `src`/`srcset` before moving content into the document. Supported graphs request only Atlas PNGs; native URLs activate for unsupported descriptors, failed metadata/images, or timeout.

Do not reintroduce an off-screen image preloader followed by assigning the same source to the visible image: it can cause duplicate requests. Explicit image loading must not wait indefinitely on off-screen `loading=lazy`; current Atlas requests are eager, while fallback restores native loading behavior. Graph error messages/buttons recover after a successful fallback load.

If the frontend module cannot load, the classic bootstrap restores native sources after ten seconds and switches to the no-JavaScript layout. Metadata/image loading has a 60-second limit. SmokePing still generates native PNGs server-side; eliminating that work would require a separate page-generator change.

### White flash during navigation

Critical root/body colors are in `basepage.html`. The installer and preview inline the canonical `theme-init.js` before the external stylesheet. Saved appearance and the renderer-first class must be established before external assets load. Keep graph, navigator, and dialog surfaces theme-aware while loading. Native fallback images intentionally retain white surfaces. Check print styling when changing startup colors.

### Stale frontend after upgrades

The installer computes a shared content hash for the template/assets and versions CSS, scripts, and module imports together. Versioning only `atlas.js` leaves cached imports mismatched. Preserve query strings in CDN cache keys; bypass caching for the graph CGI, which returns private/revalidation headers. Restarting services does not clear browser/CDN caches.

### Permission error from a root-owned checkout

SmokePing's probe base inserts relative `..` into Perl's `@INC`. Running the `www-data` preflight from an inaccessible `/root` checkout can cause `../IPC/Open3.pm: Permission denied`, despite installed Perl modules. Installer preflight, renderer subprocesses, and the Perl helper use `/` as their working directory. Do not fix this by opening `/root` permissions or bypassing validation.

### Data labels and time ranges

A probe with all packets lost still has measurement data, even when every RTT is null. Test both complete loss and genuinely absent data. Relative ranges can be specified as large second counts (`-31104000s` for native 360-day links); avoid overly short digit limits. Slave identifiers can contain underscores; strip native range suffixes before reading the slave name.

## Development and validation

Node.js 18+ is required for preview/syntax/tests; Python 3 and Perl cover installer/catalog checks. Install RRDtool for real RRD/PNG integration tests; those tests skip explicitly if it is missing. Pillow is only needed to regenerate illustrative native PNG fixtures.

```sh
npm run check
npm test
npm run preview
```

The preview is at `http://127.0.0.1:8787/smokeping/smokeping.cgi`. Fixtures match native HTML structure but use synthetic data. Useful routes: `?target=_charts`, `?target=Empty`, `?target=Waiting`, `?target=Broken`, `?nojs=1`, and slave/hierarchy links.

To use real synthetic RRDs with the renderer:

```sh
python3 tools/renderer-preview.py .preview/renderer --create
npm run preview -- --renderer-fixtures .preview/renderer
```

The sample Frankfurt target records total loss to exercise **No replies**. Preview flags `--log-requests`, `--fail-renderer-png`, `--fail-graph-module`, and `--fail-styles` exercise loading and recovery. A successful supported page should request zero `/smokeping/images/` PNGs. The nojs fixture simulates a native-only page; it is not an actual browser scripting-disable switch.

For the native cropper, use `npm run preview -- --native-www /usr/share/smokeping/www`. Regenerate native PNG fixtures with `python3 tools/generate-fixtures.py` when Pillow is available.

Validate behavior relevant to the change:

- CGI separators, encoded separators, slaves, hierarchy, and manual range submissions.
- Real RRD statistics, unknown values, complete loss, cache hits/invalidation, token binding, and Retina geometry.
- Install/restore, failed-check rollback, custom aliases, file permissions, traversal/symlinks, and restrictive umask.
- Dark/light/system startup and navigation, including absent stylesheet and pending graphs.
- Desktop and 320/390/768 px layouts; navigation, filtering, dialog/Escape/focus, and navigator zoom.
- Renderer success without native image requests; metadata, PNG, module, and no-JavaScript fallback.

The Noble package was checked with staged install/restore to confirm only Presentation changed among original packaged files. The catalog adapter test uses a controlled parser/probe stub; the full installed parser/probe check runs during Ubuntu installation. Local RRD integration used RRDtool 1.11.0. Do not claim local checks are a fresh live VM install or verification of every probe/Ubuntu RRDtool combination.

## Packaging and references

`npm run package` produces the archive named in `tools/package.py`. Keep its version consistent with `package.json` and release assets. The release includes theme, renderer, installer, README, license, and screenshots; maintainer instructions and development tools stay in the repository. Before publishing, verify archive members against the intended commit, excluding bytecode, traversal, and unexpected files.

For standalone documentation edits, review links/examples and use `git diff --check`; implementation tests are unnecessary unless behavior or packaging changes.

Primary references:

- [Ubuntu Noble SmokePing](https://packages.ubuntu.com/noble/smokeping)
- [SmokePing 2.8.2 source](https://github.com/oetiker/SmokePing/tree/2.8.2)
- [SmokePing configuration](https://oss.oetiker.ch/smokeping/doc/smokeping_config.en.html)
- [RRDtool graph/graphv](https://oss.oetiker.ch/rrdtool/doc/rrdgraph.en.html)
- [Nginx locations](https://nginx.org/en/docs/http/ngx_http_core_module.html#location)
- [Nginx FastCGI parameters](https://nginx.org/en/docs/http/ngx_http_fastcgi_module.html#fastcgi_param)
- [fcgiwrap Ubuntu package](https://packages.ubuntu.com/noble/fcgiwrap)

No SmokePing or third-party JavaScript libraries are redistributed here; use the installed distribution's copies and preserve their licenses.
