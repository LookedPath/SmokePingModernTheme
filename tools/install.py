#!/usr/bin/env python3
"""Install/restore Atlas without editing SmokePing's Perl modules or databases."""
import argparse
import difflib
import hashlib
import json
import os
import pwd
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from uuid import uuid4

PROJECT = Path(__file__).resolve().parents[1]
TEMPLATE = PurePosixPath('/etc/smokeping/atlas/basepage.html')
ASSETS = PurePosixPath('/usr/share/smokeping/www/atlas')
BACKUPS = PurePosixPath('/var/backups/smokeping-atlas')
DEFAULT_PRESENTATION = '/etc/smokeping/config.d/Presentation'
RENDERER = '/usr/lib/cgi-bin/smokeping-atlas.cgi'
CATALOG = '/usr/share/smokeping-atlas/catalog.pl'
RENDERER_CONFIG = '/etc/smokeping/atlas/renderer.json'
APACHE_CONFIG = '/etc/apache2/conf-available/smokeping-atlas.conf'
CACHE = '/var/cache/smokeping-atlas'
RENDERER_FILES = {RENDERER, CATALOG, RENDERER_CONFIG, APACHE_CONFIG}



def destination(root, path):
    relative = PurePosixPath(path)
    if not relative.is_absolute() or '..' in relative.parts:
        raise ValueError(f'Expected an absolute path without traversal: {path}')
    target = root.joinpath(*relative.parts[1:])
    if target.is_symlink() or not target.resolve().is_relative_to(root):
        raise ValueError(f'Refusing a symlink or a path outside the installation root: {target}')
    return target


def presentation_text(text):
    lines = text.splitlines(keepends=True)
    start = next((i+1 for i, line in enumerate(lines) if re.match(r'^\s*\*\*\*\s+Presentation\s+\*\*\*\s*$', line)), None)
    if start is None:
        raise ValueError('The selected configuration has no *** Presentation *** section.')
    end = next((i for i in range(start, len(lines)) if re.match(r'^\s*(?:\+|\*\*\*)', lines[i])), len(lines))
    template_lines = [i for i in range(start, end) if re.match(r'^\s*template\s*=', lines[i])]
    if len(template_lines) != 1:
        raise ValueError('Expected exactly one template setting in the Presentation section.')
    lines[template_lines[0]] = f'template = {TEMPLATE}\n'
    title_lines = [i for i in range(start, end) if re.match(r'^\s*htmltitle\s*=', lines[i])]
    if len(title_lines) > 1:
        raise ValueError('Duplicate htmltitle settings in the Presentation section.')
    if title_lines:
        lines[title_lines[0]] = 'htmltitle = yes\n'
    else:
        lines.insert(template_lines[0]+1, 'htmltitle = yes\n')
    return ''.join(lines)


def renderer_first_template(template):
    template = template.replace('name="atlas-graph-loading" content="native"',
                                'name="atlas-graph-loading" content="renderer-first"')
    # SmokePing substitutes these placeholders globally. Template contents are
    # inert to the browser; noscript preserves access when scripting is disabled.
    for tag in ('overview', 'body'):
        placeholder = '<##'+tag+'##>'
        template = template.replace(placeholder,
            '<template data-atlas-graphs>'+placeholder+'</template><noscript>'+placeholder+'</noscript>')
    return template


def plan(root, presentation, assets_url, with_renderer=False, renderer_url='/smokeping/atlas-graph.cgi', smokeping_config='/etc/smokeping/config'):
    if not re.fullmatch(r'/(?:[A-Za-z0-9_.~-]+/)*[A-Za-z0-9_.~-]+', assets_url) or '..' in assets_url.split('/'):
        raise ValueError('--assets-url must be an absolute URL path such as /smokeping/atlas, without a trailing slash.')
    config = destination(root, presentation)
    if not config.is_file():
        raise ValueError(f'Presentation configuration not found: {config}')
    original = config.read_text(encoding='utf-8')
    template = (PROJECT / 'theme/basepage.html').read_text(encoding='utf-8').replace('/smokeping/atlas/', assets_url+'/')
    files = {}
    if with_renderer:
        if not re.fullmatch(r'/(?:[A-Za-z0-9_.~-]+/)*[A-Za-z0-9_.~-]+', renderer_url) or '..' in renderer_url.split('/'):
            raise ValueError('--renderer-url must be an absolute URL path without traversal.')
        destination(root, smokeping_config)
        template = renderer_first_template(template)
        template = template.replace('name="atlas-renderer" content=""', f'name="atlas-renderer" content="{renderer_url}"')
        files[RENDERER] = (PROJECT / 'server/atlas_graph.py').read_bytes()
        files[CATALOG] = (PROJECT / 'server/catalog.pl').read_bytes()
        files[RENDERER_CONFIG] = json.dumps(dict(smokeping_config=smokeping_config,
            catalog_helper=CATALOG, cache_dir=CACHE, rrdtool='/usr/bin/rrdtool'), indent=2).encode()
        files[APACHE_CONFIG] = (f'ScriptAlias {renderer_url} {RENDERER}\n'
            '<Directory "/usr/lib/cgi-bin">\n  <Files "smokeping-atlas.cgi">\n'
            '    Options +ExecCGI\n    SetHandler cgi-script\n  </Files>\n</Directory>\n').encode()
    # Inline the small appearance bootstrap so saved dark mode never waits for
    # a network request. The critical colors in basepage work without the full CSS.
    appearance = (PROJECT / 'theme/atlas/theme-init.js').read_text(encoding='utf-8')
    template = template.replace(f'<script src="{assets_url}/theme-init.js"></script>',
                                '<script data-atlas-appearance>\n'+appearance+'\n</script>')
    assets = {asset.name:asset.read_bytes() for asset in sorted((PROJECT / 'theme/atlas').iterdir())
              if asset.is_file() and asset.suffix in ('.css', '.js')}
    digest = hashlib.sha256(template.encode('utf-8'))
    for name, content in assets.items():
        digest.update(name.encode('utf-8') + b'\0' + content)
    version = digest.hexdigest()[:16]
    # Version the entire module graph together, not just the entry point. A cached
    # atlas.js/core.js pair must not silently suppress or break the new renderer.
    template = re.sub(r'((?:src|href)="'+re.escape(assets_url)+r'/[^"?]+\.(?:js|css))"',
                      lambda match: match[1]+'?v='+version+'"', template)
    files[str(TEMPLATE)] = template.encode('utf-8')
    for name, content in assets.items():
        if name.endswith('.js'):
            source = re.sub(r"((?:from\s+|import\s*)['\"])(\./[A-Za-z0-9_-]+\.js)(['\"])",
                            lambda match: match[1]+match[2]+'?v='+version+match[3], content.decode('utf-8'))
            content = source.encode('utf-8')
        files[str(ASSETS / name)] = content
    files[presentation] = presentation_text(original).encode('utf-8')
    for path in files:
        target = destination(root, path)
        if target.exists() and not target.is_file():
            raise ValueError(f'Expected a regular file: {target}')
    return files, original


def atomic_write(path, content, mode=0o644, uid=None, gid=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.atlas-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, mode)
        if os.geteuid() == 0 and uid is not None and gid is not None:
            os.chown(temporary, uid, gid)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def snapshot(root, files, presentation):
    identifier = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8]
    backup = destination(root, BACKUPS / identifier)
    backup.mkdir(parents=True, mode=0o700)
    records = []
    for index, path in enumerate(files):
        target = destination(root, path)
        record = {'path': path, 'exists': target.exists()}
        if target.exists():
            metadata = target.stat()
            name = f'{index}.original'
            shutil.copyfile(target, backup / name)
            os.chmod(backup / name, 0o600)
            record.update(backup=name, mode=metadata.st_mode & 0o7777, uid=metadata.st_uid, gid=metadata.st_gid)
        records.append(record)
    manifest = {'version':1, 'presentation':presentation, 'files':records}
    atomic_write(backup / 'manifest.json', json.dumps(manifest, indent=2).encode('utf-8'), 0o600)
    return identifier, manifest, backup


def restore_records(root, manifest, backup):
    allowed = {str(TEMPLATE), manifest['presentation']} | RENDERER_FILES
    allowed.update(str(ASSETS / path.name) for path in (PROJECT / 'theme/atlas').iterdir() if path.suffix in ('.css', '.js'))
    # Validate every destination/backup before restoring anything.
    for record in manifest['files']:
        if record['path'] not in allowed:
            raise ValueError(f'Unexpected path in backup manifest: {record["path"]}')
        destination(root, record['path'])
        if record['exists'] and (not re.fullmatch(r'\d+\.original', record.get('backup', '')) or not (backup / record['backup']).is_file()):
            raise ValueError('Backup is incomplete or has an invalid filename.')
    for record in reversed(manifest['files']):
        target = destination(root, record['path'])
        if record['exists']:
            atomic_write(target, (backup / record['backup']).read_bytes(), record['mode'], record['uid'], record['gid'])
        else:
            target.unlink(missing_ok=True)


def check_config():
    executable = shutil.which('smokeping')
    if not executable:
        raise RuntimeError('smokeping is not on PATH. Install the Ubuntu package first, or explicitly use --skip-config-check.')
    result = subprocess.run([executable, '--check'], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('SmokePing configuration check failed:\n'+(result.stderr or result.stdout).strip())


def check_renderer(config):
    # runuser inherits cwd. A checkout under /root is inaccessible to www-data,
    # and SmokePing's probe base adds a relative ".." entry to Perl's @INC.
    result = subprocess.run(['/usr/sbin/runuser', '-u', 'www-data', '--', '/usr/bin/perl', CATALOG,
        config], capture_output=True, text=True, timeout=30, cwd='/',
        env={**os.environ, 'LC_ALL': 'C', 'TZ': 'UTC'})
    if result.returncode:
        raise RuntimeError('Renderer configuration cannot be read as www-data:\n'+result.stderr.strip())


def install(args):
    root = Path(args.root).resolve()
    with_renderer = getattr(args, 'with_renderer', False)
    files, original = plan(root, args.presentation, args.assets_url, with_renderer,
        getattr(args, 'renderer_url', '/smokeping/atlas-graph.cgi'), getattr(args, 'smokeping_config', '/etc/smokeping/config'))
    if with_renderer and root == Path('/') and not args.dry_run and not Path('/usr/bin/rrdtool').is_file():
        raise RuntimeError('Install the renderer dependency first: sudo apt install rrdtool')
    if args.dry_run:
        print('Files to install/update:')
        print('\n'.join(str(destination(root, path)) for path in files))
        print(''.join(difflib.unified_diff(original.splitlines(True), files[args.presentation].decode().splitlines(True), fromfile=args.presentation, tofile=args.presentation+' (Atlas)')))
        return None
    identifier, manifest, backup = snapshot(root, files, args.presentation)
    try:
        for directory in ({destination(root, path).parent for path in files}):
            if not directory.exists():
                directory.mkdir(parents=True, mode=0o755)
                # A restrictive sudo umask must not make the theme unreadable to www-data.
                directory.chmod(0o755)
        for path, content in files.items():
            old = next(record for record in manifest['files'] if record['path'] == path)
            atomic_write(destination(root, path), content, 0o755 if path in (RENDERER, CATALOG) else old.get('mode', 0o644), old.get('uid'), old.get('gid'))
        if with_renderer:
            cache = destination(root, CACHE)
            cache.mkdir(parents=True, exist_ok=True)
            cache.chmod(0o700)
            if root == Path('/'):
                account = pwd.getpwnam('www-data')
                os.chown(cache, account.pw_uid, account.pw_gid)
                check_renderer(getattr(args, 'smokeping_config', '/etc/smokeping/config'))
        if not args.skip_config_check:
            check_config()
    except Exception:
        restore_records(root, manifest, backup)
        print(f'Installation failed; the previous files were restored. Backup: {backup}', file=sys.stderr)
        raise
    print(f'Atlas installed. Backup ID: {identifier}')
    if args.skip_config_check:
        print('Configuration validation was skipped. Run sudo smokeping --check on the VM before reloading.')
    print('Reload the SmokePing service and any persistent CGI workers. See README.md for commands.')
    print(f'Rollback: sudo python3 tools/install.py restore {identifier}')
    if with_renderer:
        print('Enable the Apache CGI endpoint: sudo a2enmod cgid && sudo a2enconf smokeping-atlas')
        print('Then validate/reload: sudo apache2ctl configtest && sudo systemctl reload apache2')
        print('For custom web servers or authentication, apply the equivalent endpoint mapping and access policy; see README.md.')
    return identifier


def restore(args):
    root = Path(args.root).resolve()
    if not re.fullmatch(r'\d{8}T\d{6}Z-[a-f0-9]{8}', args.backup_id):
        raise ValueError('Invalid backup ID. Use the ID printed by the installer.')
    backup = destination(root, BACKUPS / args.backup_id)
    manifest = json.loads((backup / 'manifest.json').read_text())
    if manifest.get('version') != 1:
        raise ValueError('Unsupported backup manifest version.')
    if args.dry_run:
        print('\n'.join('Restore '+str(destination(root, record['path'])) for record in manifest['files']))
        return
    restore_records(root, manifest, backup)
    print(f'Restored backup {args.backup_id}. Reload SmokePing and any persistent CGI workers.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    installing = commands.add_parser('install', help='Install Atlas and back up changed files')
    installing.add_argument('--presentation', default=DEFAULT_PRESENTATION)
    installing.add_argument('--assets-url', default='/smokeping/atlas')
    installing.add_argument('--with-renderer', action='store_true', help='Install the optional themed PNG CGI endpoint')
    installing.add_argument('--renderer-url', default='/smokeping/atlas-graph.cgi')
    installing.add_argument('--smokeping-config', default='/etc/smokeping/config', help='Full SmokePing configuration for the renderer')
    installing.add_argument('--skip-config-check', action='store_true')
    restoring = commands.add_parser('restore', help='Restore a backup printed by the installer')
    restoring.add_argument('backup_id')
    for command in (installing, restoring):
        command.add_argument('--root', default='/', help='Staging filesystem root for testing/packaging')
        command.add_argument('--dry-run', action='store_true', help='Show intended changes without writing files')
    args = parser.parse_args()
    if Path(args.root).resolve() == Path('/') and not args.dry_run and os.geteuid() != 0:
        parser.error('Installation/restoration on the VM requires sudo.')
    if args.action == 'install' and Path(args.root).resolve() != Path('/') and not args.dry_run and not args.skip_config_check:
        parser.error('Staged installs require --skip-config-check; configuration validation runs on the actual VM.')
    try:
        install(args) if args.action == 'install' else restore(args)
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
