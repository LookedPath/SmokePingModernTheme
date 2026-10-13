import argparse
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('atlas_install', Path(__file__).resolve().parents[1] / 'tools/install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)

CONFIG = '''*** Presentation ***
template = /etc/smokeping/basepage.html
charset = utf-8
htmltitle = no
graphborders = no

+ overview
width = 600
height = 50
range = 10h

+ detail
width = 600
height = 200
"Last 3 Hours" 3h
'''


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='atlas-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = self.root / 'etc/smokeping/config.d/Presentation'
        self.config.parent.mkdir(parents=True)
        self.config.write_text(CONFIG)
        self.config.chmod(0o640)
        self.core = self.root / 'usr/share/perl5/Smokeping.pm'
        self.core.parent.mkdir(parents=True)
        self.core.write_text('untouched package code')
        self.args = argparse.Namespace(root=str(self.root), presentation=installer.DEFAULT_PRESENTATION, assets_url='/smokeping/atlas', skip_config_check=True, dry_run=False)

    def install(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return installer.install(self.args)

    def test_install_and_restore_preserve_original_configuration_and_core(self):
        identifier = self.install()
        updated = self.config.read_text()
        self.assertIn('template = /etc/smokeping/atlas/basepage.html', updated)
        self.assertIn('htmltitle = yes', updated)
        self.assertIn('width = 600', updated)
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o640)
        self.assertEqual(self.core.read_text(), 'untouched package code')
        self.assertTrue((self.root / 'usr/share/smokeping/www/atlas/atlas.js').exists())
        with contextlib.redirect_stdout(io.StringIO()):
            installer.restore(argparse.Namespace(root=str(self.root), backup_id=identifier, dry_run=False))
        self.assertEqual(self.config.read_text(), CONFIG)
        self.assertFalse((self.root / 'etc/smokeping/atlas/basepage.html').exists())
        self.assertEqual(self.core.read_text(), 'untouched package code')

    def test_renderer_preflight_drops_privileges_from_accessible_directory(self):
        with patch.object(installer.subprocess, 'run') as run:
            run.return_value.returncode = 0
            installer.check_renderer('/etc/smokeping/config')
        command = run.call_args.args[0]
        self.assertEqual(command[:4], ['/usr/sbin/runuser','-u','www-data','--'])
        self.assertEqual(run.call_args.kwargs['cwd'], '/')
        self.assertEqual(run.call_args.kwargs['env']['LC_ALL'], 'C')

    def test_optional_renderer_install_and_restore(self):
        self.args.with_renderer = True
        identifier = self.install()
        template = (self.root / 'etc/smokeping/atlas/basepage.html').read_text()
        self.assertIn('name="atlas-renderer" content="/smokeping/atlas-graph.cgi"', template)
        self.assertEqual((self.root / installer.RENDERER.lstrip('/')).stat().st_mode & 0o777, 0o755)
        self.assertEqual((self.root / installer.CACHE.lstrip('/')).stat().st_mode & 0o777, 0o700)
        self.assertIn('ScriptAlias /smokeping/atlas-graph.cgi', (self.root / installer.APACHE_CONFIG.lstrip('/')).read_text())
        with contextlib.redirect_stdout(io.StringIO()):
            installer.restore(argparse.Namespace(root=str(self.root),backup_id=identifier,dry_run=False))
        for path in installer.RENDERER_FILES:
            self.assertFalse((self.root/path.lstrip('/')).exists())

    def test_startup_colors_and_inline_appearance_precede_external_assets(self):
        files,_=installer.plan(self.root.resolve(),installer.DEFAULT_PRESENTATION,'/smokeping/atlas',True)
        template=files[str(installer.TEMPLATE)].decode()
        colors=template.index('<style id="atlas-startup-colors">')
        appearance=template.index('<script data-atlas-appearance>')
        stylesheet=template.index('<link rel="stylesheet"')
        self.assertLess(colors,appearance)
        self.assertLess(appearance,stylesheet)
        self.assertNotIn('src="/smokeping/atlas/theme-init.js',template)
        self.assertIn('localStorage.getItem',template[appearance:stylesheet])
        self.assertIn('body { margin:0; background:var(--atlas-bg); }',template)
        self.assertIn("root.classList.add('atlas-renderer-first')",template[appearance:stylesheet])

    def test_renderer_first_template_keeps_native_markup_inert(self):
        from html.parser import HTMLParser
        files,_=installer.plan(self.root.resolve(),installer.DEFAULT_PRESENTATION,'/smokeping/atlas',True)
        template=files[str(installer.TEMPLATE)].decode()
        self.assertIn('name="atlas-graph-loading" content="renderer-first"',template)
        self.assertEqual(template.count('<template data-atlas-graphs>'),2)
        self.assertEqual(template.count('<##overview##>'),2)
        self.assertEqual(template.count('<##body##>'),2)
        rendered=template.replace('<##overview##>','<img src="/native-overview.png">').replace('<##body##>','<img src="/native-detail.png">')
        class ImageLocations(HTMLParser):
            def __init__(self):
                super().__init__(); self.inert=0; self.eager=[]; self.deferred=[]
            def handle_starttag(self,tag,attrs):
                if tag in ('template','noscript'): self.inert+=1
                if tag=='img' and dict(attrs).get('src'):
                    (self.deferred if self.inert else self.eager).append(dict(attrs)['src'])
            def handle_endtag(self,tag):
                if tag in ('template','noscript'): self.inert-=1
        parser=ImageLocations();parser.feed(rendered)
        self.assertEqual(parser.eager,[])
        self.assertEqual(len(parser.deferred),4)
        native,_=installer.plan(self.root.resolve(),installer.DEFAULT_PRESENTATION,'/smokeping/atlas')
        self.assertNotIn('<template data-atlas-graphs>',native[str(installer.TEMPLATE)].decode())

    def test_failed_configuration_check_rolls_back_every_managed_file(self):
        existing = self.root / 'usr/share/smokeping/www/atlas/atlas.css'
        existing.parent.mkdir(parents=True)
        existing.write_text('previous theme')
        self.args.skip_config_check = False
        with patch.object(installer, 'check_config', side_effect=RuntimeError('invalid config')), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(RuntimeError):
                self.install()
        self.assertEqual(self.config.read_text(), CONFIG)
        self.assertEqual(existing.read_text(), 'previous theme')
        self.assertFalse((self.root / 'usr/share/smokeping/www/atlas/atlas.js').exists())

    def test_dry_run_writes_nothing(self):
        self.args.dry_run = True
        self.install()
        self.assertEqual(self.config.read_text(), CONFIG)
        self.assertFalse((self.root / 'var/backups/smokeping-atlas').exists())

    def test_custom_asset_alias_is_applied_to_template(self):
        self.args.assets_url = '/monitor/smokeping/atlas'
        self.install()
        template = (self.root / 'etc/smokeping/atlas/basepage.html').read_text()
        self.assertRegex(template, r'src="/monitor/smokeping/atlas/atlas\.js\?v=[a-f0-9]{16}"')
        self.assertNotIn('href="/smokeping/atlas/', template)

    def test_asset_versions_are_consistent_and_change_with_source(self):
        import re
        files, _ = installer.plan(self.root.resolve(),installer.DEFAULT_PRESENTATION,'/smokeping/atlas')
        template = files[str(installer.TEMPLATE)].decode()
        versions = re.findall(r'\?v=([a-f0-9]{16})',template)
        self.assertEqual(len(versions),3)
        self.assertEqual(len(set(versions)),1)
        version=versions[0]
        for name in ('atlas.js','renderer.js'):
            module = files[str(installer.ASSETS/name)].decode()
            self.assertIn("from './core.js?v="+version+"'",module)
        self.assertIn("from './renderer.js?v="+version+"'",files[str(installer.ASSETS/'atlas.js')].decode())
        original = installer.PROJECT/'theme/atlas/renderer.js'
        read_bytes = Path.read_bytes
        def changed(path):
            return read_bytes(path)+(b'\n// changed source' if path==original else b'')
        with patch.object(Path,'read_bytes',changed):
            updated,_=installer.plan(self.root.resolve(),installer.DEFAULT_PRESENTATION,'/smokeping/atlas')
        self.assertNotEqual(files[str(installer.TEMPLATE)],updated[str(installer.TEMPLATE)])

    def test_rejects_asset_injection_duplicate_settings_and_symlink_escape(self):
        self.args.assets_url = '/bad/"script'
        with self.assertRaises(ValueError): self.install()
        self.args.assets_url = '/smokeping/atlas'
        self.config.write_text(CONFIG.replace('htmltitle = no', 'template = /duplicate\nhtmltitle = no'))
        with self.assertRaises(ValueError): self.install()
        self.config.write_text(CONFIG)
        (self.root / 'etc/smokeping/atlas').symlink_to(self.root.parent)
        with self.assertRaises(ValueError): self.install()

    def test_only_the_presentation_section_is_edited(self):
        text = '*** General ***\ntemplate = /leave/alone\n'+CONFIG
        updated = installer.presentation_text(text)
        self.assertIn('*** General ***\ntemplate = /leave/alone', updated)
        self.assertIn('range = 10h', updated)

    def test_new_theme_directories_are_traversable_with_restrictive_umask(self):
        previous = os.umask(0o077)
        try:
            self.install()
        finally:
            os.umask(previous)
        for relative in ('etc/smokeping/atlas', 'usr/share/smokeping/www/atlas'):
            self.assertEqual((self.root / relative).stat().st_mode & 0o777, 0o755)


if __name__ == '__main__':
    unittest.main()
