"""Exercise the Perl catalog adapter with a controlled SmokePing configuration/probe."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

@unittest.skipUnless(shutil.which('perl'), 'Perl is required for the catalog adapter test')
class CatalogTests(unittest.TestCase):
    def test_nested_target_slaves_hidden_aggregate_and_probe_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            checkout = Path(folder)/'private-checkout'
            checkout.mkdir(mode=0o700)
            ipc = Path(folder)/'IPC'
            ipc.mkdir()
            (ipc/'Open3.pm').write_text('die "Loaded IPC::Open3 from the inherited checkout parent";')
            modules=Path(folder)/'modules'
            modules.mkdir()
            stub=modules/'Smokeping.pm'
            stub.write_text('''package Smokeping;
our $cgimode;
sub get_parser { return {} }
sub get_config {require Cwd; die 'Catalog inherited caller cwd' unless Cwd::getcwd() eq '/'; return {General=>{datadir=>'/var/lib/smokeping'}, Presentation=>{overview=>{range=>'3h'},detail=>{}},
Slaves=>{remote_probe=>{display_name=>'Remote'}},Targets=>{Group=>{
Host=>{host=>'example.org',probe=>'FPing',slaves=>'remote_probe',title=>'Example'},
Hidden=>{hide=>'yes',host=>'hidden',probe=>'FPing'},
SlaveOnly=>{host=>'slave',nomasterpoll=>'yes',probe=>'FPing',slaves=>'remote_probe'},
Multi=>{host=>'/Group/Host',probe=>'FPing'}}}}}
sub load_probes {unshift @INC, '..'; require IPC::Open3; return {FPing=>bless({},'TestProbe')}}
sub exp2seconds {return 10800}
package TestProbe;
sub _pings {return 20} sub step {return 300} sub ProbeUnit {return 'Seconds'}
1;
''')
            script=Path(__file__).resolve().parents[1]/'server/catalog.pl'
            result=subprocess.run(['perl','-I'+str(modules),'-MSmokeping',str(script)],capture_output=True,text=True,check=True,cwd=checkout)
            data=json.loads(result.stdout)
            self.assertEqual(set(data['targets']),{'Group.Host','Group.Host~remote_probe','Group.SlaveOnly~remote_probe'})
            self.assertEqual(data['targets']['Group.Host']['file'],'Group/Host.rrd')
            self.assertEqual(data['targets']['Group.Host~remote_probe']['file'],'Group/Host~remote_probe.rrd')
            self.assertEqual(data['targets']['Group.Host']['pings'],20)
            self.assertEqual(data['overview_range'],10800)
