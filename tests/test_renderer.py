import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('atlas_renderer', Path(__file__).resolve().parents[1] / 'server/atlas_graph.py')
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


class WorkingDirectoryTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('perl'), 'Perl is required for the inherited-directory regression')
    def test_subprocess_does_not_load_modules_from_private_checkout_parent(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            checkout = root/'checkout'
            checkout.mkdir(mode=0o700)
            (root/'IPC').mkdir()
            (root/'IPC/Open3.pm').write_text('die "Inherited private checkout module path";')
            source = Path(renderer.__file__).resolve()
            code = ("import importlib.util; "
                    f"spec=importlib.util.spec_from_file_location('r',{str(source)!r}); "
                    "r=importlib.util.module_from_spec(spec); spec.loader.exec_module(r); "
                    "print(r.run(['/usr/bin/perl','-e',"
                    "'use lib qw(..); use IPC::Open3; use Cwd; print Cwd::getcwd();']))")
            result = subprocess.run([sys.executable,'-c',code],cwd=checkout,capture_output=True,text=True,check=True)
            self.assertEqual(result.stdout.strip(), '/')


class RequestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'host.rrd').touch()
        self.entry = dict(file='host.rrd', pings=20, step=300, unit='Seconds', title='Test')
        self.config = dict(datadir=str(self.root), overview_range=10800, targets={'Group.Host':self.entry})

    def test_canonical_range_and_size_buckets(self):
        request, _, _ = renderer.request(dict(target='Group.Host', width='321', scale='2'), self.config, now=100000)
        self.assertEqual((request['start'], request['end']), (89100,99900))
        self.assertEqual((request['width'],request['scale']), (400,2))

    def test_rejects_traversal_unknown_targets_ranges_and_resource_abuse(self):
        for values in [dict(target='../secret'), dict(target='Other.Host'), dict(target='Group.Host',width='999999'),
                       dict(target='Group.Host',scale='3'), dict(target='Group.Host',theme='evil'),
                       dict(target='Group.Host',start='1',end='99999999'), dict(target='Group.Host',file='/etc/passwd'),
                       dict(target='Group.Host',start='now'), dict(target='Group.Host',height='0')]:
            with self.subTest(values=values), self.assertRaises(renderer.RequestError):
                renderer.request(values, self.config, now=100000)

    def test_native_long_history_range_in_seconds(self):
        values, _, _ = renderer.request(dict(target='Group.Host',start='-31104000s'),self.config,now=100000000)
        self.assertEqual(values['end']-values['start'],31104000)

    def test_catalog_cannot_resolve_a_symlink_outside_datadir(self):
        with tempfile.NamedTemporaryFile() as outside:
            (self.root/'host.rrd').unlink()
            (self.root/'host.rrd').symlink_to(outside.name)
            with self.assertRaises(renderer.RequestError):
                renderer.request(dict(target='Group.Host'), self.config, now=100000)

    def test_non_latency_units_fall_back_instead_of_using_milliseconds(self):
        self.entry['unit'] = 'Bytes'
        with self.assertRaises(renderer.RequestError) as caught:
            renderer.request(dict(target='Group.Host'), self.config, now=100000)
        self.assertEqual(caught.exception.status,422)

    def test_custom_loss_thresholds_and_colors_are_preserved(self):
        self.entry['loss_colors'] = [[0,'123456','Clean'],[20,'FF0000','Outage']]
        self.assertEqual(renderer.loss_palette(self.entry),[(0.0,'123456','Clean'),(20.0,'FF0000','Outage')])


@unittest.skipUnless(shutil.which('rrdtool'), 'Install rrdtool to run real RRD/PNG integration tests')
class RRDIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='atlas-renderer-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = self.root/'cache'
        self.cache.mkdir()
        self.end = int(time.time())//300*300
        self.rrd = self.root/'host.rrd'
        command = ['rrdtool','create',str(self.rrd),'--start',str(self.end-7200),'--step','300',
                   'DS:median:GAUGE:600:0:U','DS:loss:GAUGE:600:0:4']
        command += [f'DS:ping{i}:GAUGE:600:0:U' for i in range(1,5)]
        command += ['RRA:AVERAGE:0.5:1:100']
        subprocess.run(command,check=True,capture_output=True)
        for index in range(1,25):
            # Real sorted ping DS; partial/total loss and missing measurements.
            values = 'U:4:U:U:U:U' if index == 12 else ('U:U:U:U:U:U' if index==14 else '0.02:1:0.01:0.02:0.03:U')
            subprocess.run(['rrdtool','update',str(self.rrd),f'{self.end-7200+index*300}:{values}'],check=True,capture_output=True)
        self.entry = dict(file='host.rrd',pings=4,step=300,unit='Seconds',title='Sample latency')
        self.config = dict(datadir=str(self.root),overview_range=7200,targets={'Group.Host':self.entry})
        self.settings = dict(cache_dir=str(self.cache),rrdtool=shutil.which('rrdtool'))
        self.params = dict(target='Group.Host',start=str(self.end-7200),end=str(self.end),width='640',height='240')

    def render(self, values):
        with patch.object(renderer,'catalog',return_value=self.config):
            return renderer.render(values,self.settings)

    def test_actual_pngs_metadata_and_retina_geometry(self):
        for theme in ('dark','light'):
            content_type, data = self.render(dict(self.params,theme=theme,scale='2'))
            result = json.loads(data)
            self.assertEqual(content_type,'application/json')
            self.assertAlmostEqual(result['statistics']['median_ms'],20)
            self.assertGreater(result['statistics']['loss_percent'],25)
            self.assertEqual(result['geometry']['image_width'],1280)
            self.assertGreater(result['geometry']['graph_width'],1000)
            self.assertLess(result['geometry']['graph_left']+result['geometry']['graph_width'],1280)
            from urllib.parse import parse_qsl
            kind, png = self.render(dict(parse_qsl(result['image_query'])))
            self.assertEqual(kind,'image/png')
            self.assertEqual(png[:8],b'\x89PNG\r\n\x1a\n')
            self.assertEqual(len(list(self.cache.glob('*.png'))),1 if theme=='dark' else 2)

    def test_image_token_is_bound_to_target_and_rendered_interval(self):
        from urllib.parse import parse_qsl
        _, data = self.render(self.params)
        image_params = dict(parse_qsl(json.loads(data)['image_query']))
        with self.assertRaises(renderer.RequestError):
            self.render(dict(image_params,theme='dark'))
        with self.assertRaises(renderer.RequestError):
            self.render(dict(image_params,token='0'*64))

    def test_cache_hit_and_rrd_update_invalidation(self):
        self.render(self.params)
        original = renderer.run
        def cached_run(command):
            self.assertNotIn('graphv', command, 'Cache hit should not regenerate the PNG')
            return original(command)
        with patch.object(renderer,'run',side_effect=cached_run):
            self.render(self.params)
        subprocess.run(['rrdtool','update',str(self.rrd),f'{self.end+300}:0.03:0:0.02:0.03:0.04:0.05'],check=True,capture_output=True)
        self.render(self.params)
        self.assertEqual(len(list(self.cache.glob('*.png'))),2)

    def test_unknown_data_is_json_null(self):
        _, data = self.render(dict(self.params,start=str(self.end-36000),end=str(self.end-30000)))
        self.assertTrue(all(value is None for value in json.loads(data)['statistics'].values()))

    def test_recorded_total_loss_keeps_loss_statistics_with_unknown_latency(self):
        # A host that never replies still contributes loss measurements to the RRD.
        self.rrd.unlink()
        subprocess.run(['rrdtool','create',str(self.rrd),'--start',str(self.end-7200),'--step','300',
            'DS:median:GAUGE:600:0:U','DS:loss:GAUGE:600:0:4',
            *[f'DS:ping{i}:GAUGE:600:0:U' for i in range(1,5)],'RRA:AVERAGE:0.5:1:100'],check=True,capture_output=True)
        updates=[f'{self.end-7200+index*300}:U:4:U:U:U:U' for index in range(1,25)]
        subprocess.run(['rrdtool','update',str(self.rrd),*updates],check=True,capture_output=True)
        _,data=self.render(self.params)
        stats=json.loads(data)['statistics']
        self.assertTrue(all(stats[key] is None for key in ('median_ms','average_ms','maximum_ms')))
        self.assertEqual(stats['loss_percent'],100)
        self.assertEqual(stats['last_loss_percent'],100)

    def test_cleanup_caps_retained_graph_count(self):
        for index in range(260):
            (self.cache/f'{index}.png').write_bytes(b'png')
            (self.cache/f'{index}.json').write_text('{}')
        renderer.prune(self.cache,'protected')
        self.assertEqual(len(list(self.cache.glob('*.png'))),256)
        self.assertEqual(len(list(self.cache.glob('*.json'))),256)

if __name__ == '__main__':
    unittest.main()
