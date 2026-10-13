#!/usr/bin/python3
"""Atlas CGI renderer. Reads configured RRDs; writes only its dedicated cache."""
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import time
from urllib.parse import parse_qs, urlencode

VERSION = 'atlas-renderer-1.1.0'
SETTINGS = Path('/etc/smokeping/atlas/renderer.json')
PALETTES = {
    'light': dict(back='FFFFFF', grid='E4EAF2', text='64748B', accent='2563EB', smoke='93C5FD'),
    'dark': dict(back='19222D', grid='26354B', text='94A3B8', accent='60A5FA', smoke='3B82F6'),
}

class RequestError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def run(command, timeout=20):
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, cwd='/',
                            env={**os.environ, 'LC_ALL': 'C', 'TZ': 'UTC'})
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'Renderer command failed')
    return result.stdout


def atomic(path, data):
    fd, name = tempfile.mkstemp(prefix='.atlas-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def catalog(settings, cache):
    path = cache / 'catalog.json'
    # Short-lived cache also picks up changes to included configuration files.
    if path.exists() and time.time() - path.stat().st_mtime < 30:
        return json.loads(path.read_bytes())
    data = run(['/usr/bin/perl', settings['catalog_helper'], settings['smokeping_config']])
    parsed = json.loads(data)
    atomic(path, data.encode())
    return parsed


def integer(params, name, default, low, high):
    value = params.get(name, str(default))
    if not re.fullmatch(r'\d{1,10}', value):
        raise RequestError(f'Invalid {name}')
    value = int(value)
    if not low <= value <= high:
        raise RequestError(f'{name} is out of range')
    return value


def epoch(value, now):
    if value == 'now':
        return now
    if re.fullmatch(r'\d{1,10}', value):
        return int(value)
    match = re.fullmatch(r'-?(\d{1,10})(s|m|h|d|w|y)', value)
    if not match:
        raise RequestError('Use an epoch timestamp or a relative range such as -3h')
    return now - int(match[1]) * dict(s=1, m=60, h=3600, d=86400, w=604800, y=31536000)[match[2]]


def request(params, config, now=None):
    now = int(time.time() if now is None else now)
    allowed = {'target', 'theme', 'width', 'height', 'scale', 'start', 'end', 'format', 'token'}
    if set(params) - allowed:
        raise RequestError('Unknown request parameter')
    if 'token' in params and (params.get('format') != 'png' or not re.fullmatch(r'[a-f0-9]{64}', params['token'])):
        raise RequestError('Invalid image token')
    target = params.get('target', '')
    if not re.fullmatch(r'[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*(?:~[A-Za-z0-9_-]+)?', target):
        raise RequestError('Invalid target')
    entry = config['targets'].get(target)
    if not entry:
        raise RequestError('Target is not available in the renderer', 404)
    if entry['unit'].lower() != 'seconds':
        raise RequestError('This probe uses non-latency units; use its native graph', 422)
    if not 1 <= int(entry['pings']) <= 200:
        raise RequestError('Unsupported probe ping count', 422)
    datadir = Path(config['datadir']).resolve()
    rrd = (datadir / entry['file']).resolve()
    if not rrd.is_relative_to(datadir) or not rrd.is_file():
        raise RequestError('No RRD data is available for this target', 404)
    theme = params.get('theme', 'light')
    if theme not in PALETTES or params.get('format', 'json') not in ('json', 'png'):
        raise RequestError('Invalid theme or format')
    step = max(1, int(entry['step']))
    aligned_now = now // step * step
    end = epoch(params.get('end', 'now'), aligned_now)
    start = epoch(params.get('start', '-'+str(config['overview_range'])+'s'), end)
    if start < 0 or end > now + step or not 60 <= end - start <= 315360000:
        raise RequestError('Time range must be between one minute and ten years, without future data')
    width = integer(params, 'width', 640, 240, 1600)
    # Fixed buckets bound the number of distinct cached responsive sizes.
    width = min(1600, math.ceil(width / 80) * 80)
    height = integer(params, 'height', 200, 120, 400)
    height = math.ceil(height / 40) * 40
    scale = integer(params, 'scale', 1, 1, 2)
    return dict(target=target, theme=theme, width=width, height=height, scale=scale,
                start=start, end=end), entry, rrd


def escape_rrd(value):
    return str(value).replace('\\', '\\\\').replace(':', '\\:')


def loss_palette(entry, theme='light'):
    custom = entry.get('loss_colors')
    if custom:
        result = []
        for limit, color, label in custom:
            if not re.fullmatch(r'[0-9a-fA-F]{6}', color):
                raise RuntimeError('Invalid configured loss color')
            result.append((float(limit), color, str(label)))
        return sorted(result)
    p = int(entry['pings'])
    limits = {0: (PALETTES[theme]['accent'], 'No loss'), max(int(.01*p), 1): ('00B8FF', 'Low loss'),
              max(int(.05*p), 2): ('0059FF', '5% loss'), max(int(.10*p), 3): ('7E00FF', '10% loss'),
              max(int(.25*p), 4): ('FF00FF', '25% loss'), max(int(.50*p), 5): ('FF5500', '50% loss'),
              p-1: ('FF0000', 'Partial loss'), p: ('A00000', 'Total loss')}
    limits[0] = (PALETTES[theme]['accent'], 'No loss')
    # Same count thresholds and loss colors as SmokePing, with a themed no-loss line.
    result = []
    previous = -1
    for key in sorted(limits):
        if not 0 <= key <= p:
            continue
        count = str(key) if key == previous+1 else f'{previous+1}–{key}'
        result.append((key, limits[key][0], f'{count}/{p} probes lost'))
        previous = key
    return result


def graph_command(executable, output, spec, entry, rrd):
    pal = PALETTES[spec['theme']]
    args = [executable, 'graphv', str(output), '--imgformat', 'PNG', '--start', str(spec['start']),
            '--end', str(spec['end']), '--width', str(spec['width']), '--height', str(spec['height']),
            '--full-size-mode', '--zoom', str(spec['scale']), '--border', '0', '--disable-rrdtool-tag',
            '--font', 'DEFAULT:9:DejaVu Sans', '--vertical-label', 'Latency (ms)',
            '--units-exponent', '0', '--lower-limit', '0', '--alt-autoscale-max', '--alt-y-grid', '--no-legend']
    for key, value in [('BACK',pal['back']), ('CANVAS',pal['back']), ('SHADEA',pal['back']),
                       ('SHADEB',pal['back']), ('GRID',pal['grid']), ('MGRID',pal['grid']),
                       ('FONT',pal['text']), ('AXIS',pal['grid']), ('FRAME',pal['grid']), ('ARROW',pal['text'])]:
        args += ['--color', f'{key}#{value}']
    path = escape_rrd(rrd)
    args += [f'DEF:median={path}:median:AVERAGE', 'CDEF:ms=median,1000,*',
             f'DEF:loss={path}:loss:AVERAGE', f'CDEF:percent=loss,{entry["pings"]},/,100,*']
    pings = int(entry['pings'])
    for i in range(1, pings+1):
        args += [f'DEF:ping{i}={path}:ping{i}:AVERAGE', f'CDEF:p{i}=ping{i},1000,*']
    # SmokePing ping DS values are sorted per measurement. Draw nested quantile bands.
    for low in range(1, pings//2+1):
        high = pings+1-low
        alpha = min(100, 25+int(70*low/(pings/2)))
        args += [f'CDEF:band{low}=p{high},p{low},-', f'AREA:p{low}',
                 f'AREA:band{low}#{pal["smoke"]}{alpha:02X}::STACK']
    args += [f'LINE1.5:ms#{pal["accent"]}']
    previous = -1
    for index, (limit, color, _) in enumerate(loss_palette(entry, spec['theme'])):
        args += [f'CDEF:bucket{index}=loss,{previous},GT,loss,{limit},LE,*,ms,UNKN,IF',
                 f'LINE2:bucket{index}#{color}']
        previous = limit
    # Total loss has unknown median: make it visible independently of the latency line.
    args += [f'CDEF:outage=loss,{pings},GE,INF,UNKN,IF', 'AREA:outage#EF444430',
             'CDEF:nodata=loss,UN,INF,UNKN,IF', 'AREA:nodata#94A3B818']
    for name, series, operation in [('median_ms','ms','LAST'), ('average_ms','ms','AVERAGE'),
                                  ('maximum_ms','ms','MAXIMUM'), ('loss_percent','percent','AVERAGE'),
                                  ('last_loss_percent','percent','LAST')]:
        args += [f'VDEF:{name}={series},{operation}', f'PRINT:{name}:%.6lf']
    return args


def metadata(stdout, png, spec, entry):
    values = {}
    for line in stdout.splitlines():
        match = re.fullmatch(r'(\w+(?:\[\d+\])?) = (.+)', line)
        if match:
            value = match[2].strip('"')
            try:
                number = float(value)
                values[match[1]] = number if math.isfinite(number) else None
            except ValueError:
                pass
    raw = png.read_bytes()
    if raw[:8] != b'\x89PNG\r\n\x1a\n':
        raise RuntimeError('RRDtool did not produce a PNG')
    width, height = struct.unpack('>II', raw[16:24])
    # graphv reports unzoomed geometry; use the actual PNG width to account for rounding.
    ratio = width / spec['width']
    geometry = {key: values[key] * ratio for key in ('graph_left', 'graph_top', 'graph_width', 'graph_height')}
    geometry.update(image_width=width, image_height=height,
                    start=int(values['graph_start']), end=int(values['graph_end']))
    stats = {name: values.get(f'print[{index}]') for index, name in enumerate(
        ['median_ms','average_ms','maximum_ms','loss_percent','last_loss_percent'])}
    return dict(**spec, title=entry['title'], geometry=geometry, statistics=stats,
                loss_legend=[dict(count=limit, color='#'+color, label=label) for limit,color,label in loss_palette(entry, spec['theme'])],
                generated_at=int(time.time()), timezone='UTC')


def prune(cache, protected):
    files = sorted(cache.glob('*.png'), key=lambda path: path.stat().st_mtime, reverse=True)
    total = 0
    for index, path in enumerate(files):
        total += path.stat().st_size
        if path.stem != protected and (index >= 256 or total > 128*1024*1024 or time.time()-path.stat().st_mtime > 3600):
            path.unlink(missing_ok=True)
            path.with_suffix('.json').unlink(missing_ok=True)


def render(params, settings):
    cache = Path(settings['cache_dir'])
    if not cache.is_dir():
        raise RuntimeError('Atlas cache directory is missing')
    # One lock bounds concurrent RRDtool work and protects paired cache publication.
    with (cache / 'renderer.lock').open('a') as lock:
        deadline = time.monotonic()+10
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RequestError('Renderer is busy; retry shortly', 503)
                time.sleep(.05)
        config = catalog(settings, cache)
        spec, entry, rrd = request(params, config)
        if 'token' in params:
            png = cache / (params['token']+'.png')
            data = cache / (params['token']+'.json')
            if not png.is_file() or not data.is_file():
                raise RequestError('Cached graph has expired; request metadata again', 404)
            saved = json.loads(data.read_bytes())
            if any(saved.get(key) != value for key,value in spec.items()):
                raise RequestError('Image token does not match this graph', 400)
            return 'image/png', png.read_bytes()
        # RRD mmap updates can leave filesystem mtime unchanged; use its stored last update.
        last_update = run([settings.get('rrdtool', '/usr/bin/rrdtool'), 'last', str(rrd)]).strip()
        fingerprint = [VERSION, spec, entry, str(rrd), last_update, rrd.stat().st_mtime_ns, rrd.stat().st_size]
        key = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()
        png, data = cache / (key+'.png'), cache / (key+'.json')
        if not png.exists() or not data.exists():
            fd, name = tempfile.mkstemp(prefix='.graph-', suffix='.png', dir=cache)
            os.close(fd)
            temporary = Path(name)
            try:
                stdout = run(graph_command(settings.get('rrdtool', '/usr/bin/rrdtool'), temporary, spec, entry, rrd))
                result = metadata(stdout, temporary, spec, entry)
                os.chmod(temporary, 0o600)
                os.replace(temporary, png)
                atomic(data, json.dumps(result, allow_nan=False).encode())
            finally:
                temporary.unlink(missing_ok=True)
        prune(cache, key)
        if params.get('format', 'json') == 'png':
            return 'image/png', png.read_bytes()
        result = json.loads(data.read_bytes())
        # Canonical timestamps keep PNG and metadata on precisely the same interval.
        result['image_query'] = urlencode({**spec, 'format': 'png', 'token':key})
        return 'application/json', json.dumps(result, allow_nan=False).encode()


def response(status, content_type, body):
    reasons = {200:'OK', 400:'Bad Request', 404:'Not Found', 405:'Method Not Allowed', 422:'Unprocessable Entity',
               500:'Internal Server Error', 503:'Service Unavailable'}
    headers = f'Status: {status} {reasons[status]}\r\nContent-Type: {content_type}\r\nContent-Length: {len(body)}\r\nCache-Control: private, max-age=0, must-revalidate\r\nX-Content-Type-Options: nosniff\r\n\r\n'
    sys.stdout.buffer.write(headers.encode()+body)


def main():
    try:
        if os.environ.get('REQUEST_METHOD', 'GET') != 'GET':
            raise RequestError('Only GET is supported', 405)
        query = os.environ.get('QUERY_STRING', '')
        if len(query) > 2048:
            raise RequestError('Request is too long')
        try:
            parsed = parse_qs(query, keep_blank_values=True, max_num_fields=12)
        except ValueError:
            raise RequestError('Too many request parameters') from None
        if any(len(value) != 1 for value in parsed.values()):
            raise RequestError('Duplicate request parameter')
        params = {key:value[0] for key,value in parsed.items()}
        settings = json.loads(SETTINGS.read_bytes())
        content_type, body = render(params, settings)
        response(200, content_type, body)
    except RequestError as error:
        response(error.status, 'application/json', json.dumps({'error':str(error)}).encode())
    except Exception as error:
        print(f'Atlas renderer: {error}', file=sys.stderr)
        response(500, 'application/json', b'{"error":"Graph rendering is unavailable; check the server log"}')

if __name__ == '__main__':
    main()
