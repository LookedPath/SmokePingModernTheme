import http from 'node:http';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
const execute = promisify(execFile);
import { readFile, realpath } from 'node:fs/promises';
import { dirname, join, resolve, sep, extname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { smokePingURL } from '../theme/atlas/core.js';

const project = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2);
const option = (name, fallback) => { const index=args.indexOf(name); return index<0?fallback:args[index+1]; };
const port = Number(option('--port', '8787'));
const nativeWWW = option('--native-www', null);
const rendererFixtures = option('--renderer-fixtures', null);
const targets = JSON.parse(await readFile(join(project,'tests/fixtures/targets.json'),'utf8'));
const appearanceBootstrap = await readFile(join(project,'theme/atlas/theme-init.js'),'utf8');
const template = (await readFile(join(project,'theme/basepage.html'),'utf8')).replace(
  '<script src="/smokeping/atlas/theme-init.js"></script>', '<script data-atlas-appearance>\n'+appearanceBootstrap+'\n</script>');
const escapeHTML = value => String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const periods = [['Last 3 Hours',10800],['Last 30 Hours',108000],['Last 10 Days',864000],['Last 360 Days',31104000]];
const cgi = '/smokeping/smokeping.cgi';
const href = (target, hierarchy='') => `${cgi}?${hierarchy?`hierarchy=${encodeURIComponent(hierarchy)};`:''}target=${encodeURIComponent(target)}`;
const graph = (target, detail=false, period=10800) => `/smokeping/images/${target.id}_${detail?'last_'+period:'mini'}.png`;
const panel = (title, body) => `<div class="panel"><div class="panel-heading"><h2>${escapeHTML(title)}</h2></div><div class="panel-body">${body}</div></div>`;

function render(url) {
  const targetID=url.searchParams.get('target')||'';
  const target=targets.find(t=>t.id===targetID.split('~')[0]);
  const hierarchy=url.searchParams.get('hierarchy')||'';
  const navigation = `<form method="get" action="${cgi}" name="hswitch"><div class="hierarchy"><label class="hierarchy-label" for="hierarchy">Hierarchy:</label><div class="hierarchy-popup"><select name="hierarchy" id="hierarchy"><option value="0">Default Hierarchy</option><option value="location" ${hierarchy==='location'?'selected':''}>Location</option></select></div></div><div class="filter"><label class="filter-label" for="filter">Filter:</label><div class="filter-text"><input name="filter" id="filter" placeholder="Filter menu..." size="15" value="${escapeHTML(url.searchParams.get('filter')||'')}"></div></div></form><ul class="menu">${['DNS','Infrastructure'].map(group=>`<li class="${targetID.startsWith(group+'.')?'menuopen':targetID===group?'menuactive':'menuitem'}"><a class="${targetID===group?'menulinkactive':'menulink'}" href="${href(group,hierarchy)}">${group==='DNS'?'DNS resolvers':group}</a><ul class="menu">${targets.filter(t=>t.id.startsWith(group+'.')).map(t=>`<li class="${target?.id===t.id?'menuactive':'menuitem'}"><a class="${target?.id===t.id?'menulinkactive':'menulink'}" href="${href(t.id,hierarchy)}">${t.menu}</a></li>`).join('')}</ul></li>`).join('')}<li class="menuitem"><a class="menulink" href="${href('_charts',hierarchy)}">Charts</a></li></ul>`;
  let overview='', body='', title=target?.title||'Network overview';
  const displaymode=url.searchParams.get('displaymode');
  if (target && displaymode==='n') {
    const start=url.searchParams.get('start')||'-3h', end=url.searchParams.get('end')||'now';
    const endTime = Math.floor(Date.now()/300000)*300;
    const endEpoch=url.searchParams.get('end')?.match(/^\d+$/)?.[0]||String(endTime);
    const startEpoch=url.searchParams.get('start')?.match(/^\d+$/)?.[0]||String(endTime-10800);
    body=panel('Navigator Graph', `<img id="zoom" alt="" width="693" height="350" src="${graph(target,true)}"><form method="get" action="${cgi}" id="range_form"><p>Time range: <input type="hidden" name="epoch_start" id="epoch_start" value="${escapeHTML(startEpoch)}"><input type="hidden" name="epoch_end" id="epoch_end" value="${escapeHTML(endEpoch)}"><input type="hidden" name="target" id="target" value="${escapeHTML(targetID)}"><input type="hidden" name="hierarchy" id="hierarchy" value="${escapeHTML(hierarchy)}"><input type="hidden" name="displaymode" value="n"><input name="start" value="${escapeHTML(start)}">&nbsp;to&nbsp;<input name="end" value="${escapeHTML(end)}"><input type="submit" value="Generate!"></p></form>`);
  } else if (target) {
    body=periods.map(([label,period])=>panel(`${label} from ${targetID.includes('~')?'Remote probe':'Milan / master'}`, `<a href="${href(targetID,hierarchy)};displaymode=n;start=-${period}s;end=now"><img alt="" src="${graph(target,true,period)}"></a>`)).join('');
  } else if (targetID==='_charts') {
    title='';
    overview='<h1>The most interesting destinations</h1>'+targets.slice(4).map(t=>panel(`${t.title} · Sample packet loss`, `<a href="${href(t.id,hierarchy)}"><img alt="" src="${graph(t,true)}"></a>`)).join('');
  } else if (targetID==='Empty') {
    title='Unconfigured target group';
  } else if (targetID==='Waiting') {
    title='Waiting for data'; body='<p>Waiting for initial data ...</p>';
  } else if (targetID==='Broken') {
    title='Missing graph fixture'; overview=panel('Unavailable target', '<a href="?target=DNS.Cloudflare"><img alt="" src="/smokeping/images/missing.png"></a>');
  } else {
    const visible=targets.filter(t=>!['DNS','Infrastructure'].includes(targetID)||t.id.startsWith(targetID+'.'));
    title=targetID==='DNS'?'DNS resolvers':targetID==='Infrastructure'?'Infrastructure':'Network overview';
    overview=visible.map(t=>panel(t.title, `<a href="${href(t.id,hierarchy)}"><img alt="" width="693" height="190" src="${graph(t)}"></a>`)).join('');
  }
  const values={title:escapeHTML(title),menu:navigation,remark:`<p>Preview · sample data · <a href="${cgi}">Overview</a> / <a href="${href('DNS.Cloudflare')}">Target detail</a> / <a href="${href('DNS.Cloudflare')};displaymode=n">Navigator</a></p>`,overview,body,target_ip:escapeHTML(target?.host||''),step:'300',owner:'Demo administrator',contact:'admin@example.net',authuser:'Guest',author:'Tobi Oetiker and Niko Tyni',smokeping:'<a href="https://oss.oetiker.ch/smokeping/">SmokePing-2.8.2</a>'};
  let previewTemplate = rendererFixtures ? template.replace('name="atlas-renderer" content=""', 'name="atlas-renderer" content="/smokeping/atlas-graph.cgi"') : template;
  if (rendererFixtures && url.searchParams.get('nojs') !== '1') {
    previewTemplate = previewTemplate.replace('name="atlas-graph-loading" content="native"', 'name="atlas-graph-loading" content="renderer-first"');
    for (const tag of ['overview','body']) {
      const placeholder='<##'+tag+'##>';
      previewTemplate=previewTemplate.replace(placeholder,'<template data-atlas-graphs>'+placeholder+'</template><noscript>'+placeholder+'</noscript>');
    }
  }
  let html=previewTemplate.replace(/<##([a-z_]+)##>/g,(_,key)=>values[key]||'');
  if (args.includes('--fail-graph-module')) html=html.replace('src="/smokeping/atlas/atlas.js"','src="/smokeping/atlas/missing-module.js"');
  return url.searchParams.get('nojs')==='1'?html.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,''):html;
}

async function asset(base, relative) {
  const path=resolve(base,relative);
  if (!path.startsWith(resolve(base)+sep)) throw new Error('Path outside asset root');
  // The native www directory can legitimately contain distribution-library symlinks.
  const actual=await realpath(path);
  return {bytes:await readFile(actual),type:({'.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.png':'image/png','.gif':'image/gif'})[extname(path)]||'application/octet-stream'};
}
const server=http.createServer(async(request,response)=>{
  try {
    if (args.includes('--log-requests')) console.log(`Request: ${request.url}`);
    const url=smokePingURL(request.url,`http://127.0.0.1:${port}`);
    response.setHeader('Cache-Control','no-store');
    response.setHeader('X-Content-Type-Options','nosniff');
    if (['/','/smokeping/','/smokeping/smokeping.cgi','/cgi-bin/smokeping.cgi'].includes(url.pathname)) {
      if(url.searchParams.get('displaymode')==='a') {
        const target=targets.find(t=>t.id===(url.searchParams.get('target')||'').split('~')[0])||targets[0];
        response.setHeader('Content-Type','image/png'); response.end(await readFile(join(project,'tests/fixtures/graphs',target.id+'-detail.png')));
      } else { response.setHeader('Content-Type','text/html; charset=utf-8'); response.end(render(url)); }
      return;
    }
    if (rendererFixtures && url.pathname==='/smokeping/atlas-graph.cgi') {
      if (args.includes('--fail-renderer-png') && url.searchParams.get('format')==='png') {
        response.writeHead(503,{'Content-Type':'application/json'});response.end('{"error":"Preview PNG failure"}');return;
      }
      const {stdout} = await execute('python3',[join(project,'tools/renderer-preview.py'),resolve(rendererFixtures),'--query',url.searchParams.toString()], {encoding:'buffer',maxBuffer:4*1024*1024});
      const first=stdout.indexOf(10), second=stdout.indexOf(10,first+1);
      response.writeHead(Number(stdout.subarray(0,first).toString()),{'Content-Type':stdout.subarray(first+1,second).toString()});
      response.end(stdout.subarray(second+1));
      return;
    }
    if (args.includes('--fail-styles') && url.pathname==='/smokeping/atlas/atlas.css') {
      response.writeHead(503,{'Content-Type':'text/css'});response.end('');return;
    }
    let result;
    if(url.pathname.startsWith('/smokeping/atlas/')) result=await asset(join(project,'theme/atlas'),decodeURIComponent(url.pathname.slice('/smokeping/atlas/'.length)));
    else if(url.pathname.startsWith('/smokeping/images/')) {
      const match=/^([A-Za-z0-9.]+)_(mini|last_\d+)\.png$/.exec(url.pathname.split('/').at(-1));
      if(!match)throw new Error('Unknown graph');
      result=await asset(join(project,'tests/fixtures/graphs'),`${match[1]}-${match[2]==='mini'?'overview':'detail'}.png`);
    } else if(nativeWWW&&url.pathname.startsWith('/smokeping/js/')) result=await asset(resolve(nativeWWW,'js'),decodeURIComponent(url.pathname.slice('/smokeping/js/'.length)));
    else {response.writeHead(404);response.end('Not found');return;}
    response.setHeader('Content-Type',result.type);response.end(result.bytes);
  } catch (_) {response.writeHead(404,{'Content-Type':'text/plain; charset=utf-8'});response.end('Not found');}
});
server.listen(port,'127.0.0.1',()=>console.log(`Atlas preview: http://127.0.0.1:${port}/smokeping/smokeping.cgi (sample data)`));
process.on('SIGINT',()=>server.close(()=>process.exit(0)));
