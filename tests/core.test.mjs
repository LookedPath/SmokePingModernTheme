import test from 'node:test';
import assert from 'node:assert/strict';
import { smokePingURL, epochValue, croppedRange, navigatorImageURL, graphDataState } from '../theme/atlas/core.js';

test('native semicolon links retain hierarchy, filter, and slave targets', () => {
  const url = smokePingURL('?hierarchy=location;filter=DNS;target=DNS.Cloudflare~remote', 'https://monitor.example/custom/smokeping.cgi');
  assert.equal(url.searchParams.get('hierarchy'), 'location');
  assert.equal(url.searchParams.get('filter'), 'DNS');
  assert.equal(url.searchParams.get('target'), 'DNS.Cloudflare~remote');
  assert.equal(url.pathname, '/custom/smokeping.cgi');
});
test('encoded separators are data rather than query delimiters', () => {
  const url = smokePingURL('?filter=DNS%3Bedge;target=DNS', 'https://monitor.example/smokeping.cgi');
  assert.equal(url.searchParams.get('filter'), 'DNS;edge');
});
test('navigator handles relative epochs and rejects unsupported dates', () => {
  assert.equal(epochValue('-3h', 20000), 9200);
  assert.equal(epochValue('30m', 20000), 18200);
  assert.equal(epochValue('now', 20000), 20000);
  assert.equal(epochValue('12345', 20000), 12345);
  assert.ok(Number.isNaN(epochValue('invalid', 20000)));
});
test('zoom maps graph pixels to the selected time interval without extending it', () => {
  assert.deepEqual(croppedRange({ x1:67, x2:667 }, 693, 1000, 7000), {start:1000,end:7000});
  assert.deepEqual(croppedRange({ x1:217, x2:367 }, 693, 1000, 7000), {start:2500,end:4000});
  assert.deepEqual(croppedRange({ x1:800, x2:-10 }, 693, 1000, 7000), {start:1000,end:7000});
  assert.equal(croppedRange({ x1:0, x2:50 }, 693, 1000, 7000), null);
  assert.equal(croppedRange({ x1:67, x2:67 }, 693, 1000, 7000), null);
  assert.equal(croppedRange({ x1:100, x2:200 }, 693, NaN, 7000), null);
});
test('navigator requests stay on the existing CGI endpoint and preserve slave/hierarchy', () => {
  const url = new URL(navigatorImageURL('https://monitor.example/cgi-bin/smokeping.cgi?site=office;epoch_start=1', 'DNS.Cloudflare~remote', 'location', {start:2500,end:4000}, 'https://monitor.example/'));
  assert.equal(url.pathname, '/cgi-bin/smokeping.cgi');
  assert.equal(url.searchParams.get('site'), 'office');
  assert.equal(url.searchParams.get('displaymode'), 'a');
  assert.equal(url.searchParams.get('target'), 'DNS.Cloudflare~remote');
  assert.equal(url.searchParams.get('hierarchy'), 'location');
  assert.equal(url.searchParams.get('start'), '2500');
  assert.equal(url.searchParams.get('end'), '4000');
  assert.ok(!url.searchParams.has('epoch_start'));
});

test('renderer zoom uses RRDtool geometry, including Retina coordinates', () => {
  assert.deepEqual(croppedRange({x1:150,x2:1250},1280,1000,7000,{left:150,right:30}),{start:1000,end:7000});
  assert.deepEqual(croppedRange({x1:425,x2:700},1280,1000,7000,{left:150,right:30}),{start:2500,end:4000});
});

const {graphDescriptor} = await import('../theme/atlas/renderer.js');
function fakeImage(filename, href) {
  return {id:'',src:`https://monitor.example/images/${filename}`,closest:()=>({href})};
}
test('renderer preserves native detail ranges and slave names containing underscores', () => {
  const base = new URL('https://monitor.example/smokeping.cgi?target=DNS.Cloudflare');
  assert.deepEqual(graphDescriptor(fakeImage('Cloudflare~remote_probe_last_10800.png',base.href),base),
    {target:'DNS.Cloudflare~remote_probe',start:'-10800s',end:'now'});
  assert.deepEqual(graphDescriptor(fakeImage('Cloudflare_mini.png',base.href),base),{target:'DNS.Cloudflare'});
  assert.equal(graphDescriptor(fakeImage('Cloudflare_mini.png',base.href+'&hierarchy=location'),base),null);
});


test('renderer derives target/range from a deferred native URL without assigning src', () => {
  const base = new URL('https://monitor.example/smokeping.cgi?target=DNS.Cloudflare');
  const image = fakeImage('Cloudflare_last_10800.png',base.href);
  image.dataset = {atlasNativeSrc:image.src};
  image.src = '';
  assert.deepEqual(graphDescriptor(image,base),{target:'DNS.Cloudflare',start:'-10800s',end:'now'});
  assert.equal(image.src,'');
});


test('startup applies saved dark mode and renderer loading before external CSS', async () => {
  const {readFile} = await import('node:fs/promises');
  const {runInNewContext} = await import('node:vm');
  const source=await readFile(new URL('../theme/atlas/theme-init.js',import.meta.url),'utf8');
  for (const saved of ['dark','light','invalid',null]) {
    const attrs={}; const classes=new Set(['no-js']);
    const root={setAttribute:(key,value)=>attrs[key]=value,classList:{
      replace:(old,value)=>{classes.delete(old);classes.add(value);},add:value=>classes.add(value)}};
    runInNewContext(source,{document:{documentElement:root,querySelector:()=>({content:'renderer-first'})},
      localStorage:{getItem:()=>saved}});
    assert.equal(attrs['data-theme'],['dark','light'].includes(saved)?saved:'system');
    assert.ok(classes.has('atlas-renderer-first'));
    assert.ok(!classes.has('no-js'));
  }
});


test('recorded total packet loss is distinct from missing probe data', () => {
  const noLatency={median_ms:null,average_ms:null,maximum_ms:null};
  assert.equal(graphDataState({...noLatency,loss_percent:100,last_loss_percent:100}),'no_replies');
  assert.equal(graphDataState({...noLatency,loss_percent:null,last_loss_percent:null}),'no_data');
  assert.equal(graphDataState({...noLatency,loss_percent:0,last_loss_percent:0}),'no_latency');
  assert.equal(graphDataState({...noLatency,loss_percent:30,last_loss_percent:100}),'no_latency');
  assert.equal(graphDataState({...noLatency,loss_percent:120,last_loss_percent:120}),'no_latency');
  assert.equal(graphDataState({...noLatency,median_ms:0,loss_percent:0}),'latency');
  assert.equal(graphDataState({...noLatency,average_ms:20,loss_percent:50}),'latency');
});
