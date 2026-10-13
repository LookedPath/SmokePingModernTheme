#!/usr/bin/env python3
"""Development-only synthetic RRD fixtures and bridge for the local Atlas preview."""
import argparse
import importlib.util
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import time
from unittest.mock import patch
from urllib.parse import parse_qsl

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('renderer', ROOT/'server/atlas_graph.py')
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


def create(directory):
    directory.mkdir(parents=True,exist_ok=True)
    (directory/'cache').mkdir(exist_ok=True)
    targets = json.loads((ROOT/'tests/fixtures/targets.json').read_text())
    end = int(time.time())//300*300
    catalog = dict(datadir=str(directory.resolve()),overview_range=10800,targets={})
    for index,target in enumerate(targets):
        file = target['id']+'.rrd'
        rrd = directory/file
        rrd.unlink(missing_ok=True)
        subprocess.run(['rrdtool','create',str(rrd),'--start',str(end-86400),'--step','300',
            'DS:median:GAUGE:600:0:U','DS:loss:GAUGE:600:0:20',
            *[f'DS:ping{i}:GAUGE:600:0:U' for i in range(1,21)],'RRA:AVERAGE:0.5:1:300'],check=True)
        rows=[]
        for sample in range(1,289):
            median=(.012+index*.005)*(1+.08*math.sin(sample/11))
            loss=20 if index==5 else (0 if sample%71 else 2)
            median='U' if index==5 else median
            values=[median,loss]+[median*(.7+ping*.03) if ping<=20-loss else 'U' for ping in range(1,21)]
            rows.append(':'.join(map(str,[end-86400+sample*300,*values])))
        subprocess.run(['rrdtool','update',str(rrd),*rows],check=True)
        catalog['targets'][target['id']]=dict(file=file,pings=20,step=300,unit='Seconds',title=target['title'])
    (directory/'catalog.json').write_text(json.dumps(catalog))
    print(directory.resolve())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    parser.add_argument('--create',action='store_true')
    parser.add_argument('--query')
    args=parser.parse_args()
    if args.create:
        create(args.directory)
    else:
        config=json.loads((args.directory/'catalog.json').read_text())
        settings=dict(cache_dir=str(args.directory/'cache'),rrdtool=shutil.which('rrdtool'))
        try:
            with patch.object(renderer,'catalog',return_value=config):
                kind,body=renderer.render(dict(parse_qsl(args.query or '')),settings)
            sys.stdout.buffer.write(b'200\n'+kind.encode()+b'\n'+body)
        except renderer.RequestError as error:
            sys.stdout.buffer.write(str(error.status).encode()+b'\napplication/json\n'+json.dumps(dict(error=str(error))).encode())

if __name__=='__main__':
    main()
