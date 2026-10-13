#!/usr/bin/env python3
"""Generate clearly synthetic PNG graph fixtures. Requires Pillow only for regeneration."""
import argparse
import json
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--font', help='Optional monospace TTF font for graph annotations')
args = parser.parse_args()
font = ImageFont.truetype(args.font, 11) if args.font else ImageFont.load_default(size=11)
output = root / 'tests/fixtures/graphs'
output.mkdir(exist_ok=True)
targets = json.loads((root / 'tests/fixtures/targets.json').read_text())

for index, target in enumerate(targets):
    for detailed in (False, True):
        width, height = (693, 350 if detailed else 190)
        left, right, top = 67, 26, 20
        bottom = height - (100 if detailed else 65)
        base = target['median']
        points = []
        for i in range(150):
            median = base * (1 + .04*math.sin(i*.67+index) + .025*math.sin(i*1.31) + .03*math.sin(i*.12))
            incident = 83 <= i <= 99 and target['loss'] > 0
            spread = base * (.02 + abs(math.sin(i*.49))* .06 + (.4 if incident else 0) + (.14 if 43 <= i <= 54 else 0))
            points.append((median + (.14*base if incident else 0), spread, incident))
        maximum = max(m+s*2.4 for m,s,_ in points)
        unit = 10 if maximum > 20 else 5 if maximum > 5 else 1
        maximum = math.ceil(maximum/unit)*unit
        x = lambda i: left+i/149*(width-left-right)
        y = lambda value: bottom-(value/maximum)*(bottom-top)
        image = Image.new('RGB', (width,height), 'white')
        draw = ImageDraw.Draw(image)
        draw.rectangle((left,top,width-right,bottom), fill='#fcfcfc', outline='#aeb8c2')
        for value in [0,maximum/4,maximum/2,maximum*3/4,maximum]:
            yy = y(value)
            draw.line((left,yy,width-right,yy), fill='#e0e5eb')
            draw.text((left-8,yy), f'{value:g}', fill='#465264', font=font, anchor='rm')
        draw.text((8,3), 'RTT (ms)', fill='#465264', font=font)
        for j,label in enumerate(['09:00','10:00','11:00','12:00']):
            draw.text((left+j/3*(width-left-right),bottom+8), label, fill='#465264', font=font, anchor='lt' if j==0 else 'rt' if j==3 else 'mt')
        for scale,color in [(2.4,'#eff1f3'),(1.7,'#e0e4e8'),(1,'#cbd1d7'),(.5,'#b4bec8')]:
            polygon = [(x(i),y(m+s*scale)) for i,(m,s,_) in enumerate(points)]
            polygon += [(x(i),y(max(0,m-s*scale))) for i,(m,s,_) in reversed(list(enumerate(points)))]
            draw.polygon(polygon, fill=color)
        for i in range(1,len(points)):
            color = '#087a54' if not points[i][2] else '#0077bb' if target['loss']<2 else '#b73149'
            draw.line((x(i-1),y(points[i-1][0]),x(i),y(points[i][0])), fill=color, width=2)
        if detailed:
            lines = [f'median rtt: {base:.1f} ms avg   {base*1.18:.1f} ms max   {base*.9:.1f} ms min   {base:.1f} ms now',
                     f'packet loss: {target["loss"]:.2f}% avg       median sd: {target["sd"]:.1f} ms',
                     'loss color:  0 packets   1 packet   2+ packets',
                     'probe: 20 ICMP probes every 300 s   |   SAMPLE DATA']
        else:
            lines = [f'{base:.1f} ms av md     {target["loss"]:.1f}% av ls     {target["sd"]:.1f} ms av sd', 'FPing / master   |   SAMPLE DATA']
        for i,line in enumerate(lines):
            draw.text((left,bottom+27+i*15), line, fill='#465264', font=font)
        image.save(output / f'{target["id"]}-{"detail" if detailed else "overview"}.png')
print(f'Wrote {len(targets)*2} synthetic graph fixtures to {output}')
