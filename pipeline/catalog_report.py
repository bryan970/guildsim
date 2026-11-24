from guild_runtime import runtime_root, usable_faction
"""Write a searchable view of the item coverage and acquisition notes."""
import json
from pathlib import Path

BASE=runtime_root()

def main():
    work=BASE/'output/all-sources'
    coverage=json.loads((work/'coverage.json').read_text(encoding='utf-8'))
    pool=json.loads((work/'candidate-pool.json').read_text(encoding='utf-8'))
    details={}
    for choices in pool.values():
        for row in choices:details.setdefault(row['id'],row)
    entries=[]
    for row in coverage['items']:
        detail=details.get(row['id'],{})
        entries.append(dict(row,slot=detail.get('slot',''),where=detail.get('where',row.get('reason','')),
                            conditional=not detail.get('target_eligible',True),note=detail.get('note',row.get('note',''))))
    data=json.dumps(entries,ensure_ascii=True).replace('<','\\u003c')
    document='''<!doctype html><meta charset="utf-8"><title>Ret item coverage</title>
<style>body{font:16px system-ui;background:#15171c;color:#eee;max-width:1250px;margin:35px auto;padding:20px}a{color:#ffd478}input,select,button{font:inherit;padding:10px;margin:4px;background:#252830;color:#fff;border:1px solid #777}td,th{padding:10px;border-bottom:1px solid #444;text-align:left;vertical-align:top}small{color:#bbb}table{width:100%}</style>
<h1>Ret item coverage — all sources</h1><p><a href="../report.html">Weights and target set</a></p>
<p>Includes all reputation standings, PvP ranks and crafting costs in the compatible supported catalog. Raid dependence, class/faction restrictions, profession requirements and unknown availability are recorded. Every compatible item/stat variant enters a simulation screen; stronger candidates and set combinations receive higher precision. This does not enumerate every combination or prove every live item is in the catalog.</p>
<input id="query" placeholder="Search name, faction, recipe, location or exclusion" size="50">
<select id="kind"><option value="included">Included items</option><option value="all">Entire catalog</option><option value="PvP">PvP</option><option value="reputation">Reputation</option><option value="crafted">Crafted</option><option value="quest">Quest</option><option value="drop">Drops</option><option value="vendor">Vendors</option><option value="conditional">Conditional availability/profession</option><option value="excluded">Excluded, with reason</option></select>
<p id="count"></p><table><thead><tr><th>Item</th><th>Source / requirement</th><th>Status</th></tr></thead><tbody id="rows"></tbody></table><button id="more">Show more</button>
<script>const items=DATA;let limit=100;const byId=id=>document.getElementById(id);
function render(){const query=byId('query').value.toLowerCase(),kind=byId('kind').value;
const filtered=items.filter(x=>(kind==='all'||x.status===kind||(kind==='conditional'&&x.conditional)||((x.categories||[]).includes(kind)))&&JSON.stringify(x).toLowerCase().includes(query));
byId('count').textContent=filtered.length+' matching base items; showing '+Math.min(limit,filtered.length)+'. Random-stat variants are counted per base item.';byId('rows').replaceChildren();
for(const x of filtered.slice(0,limit)){const tr=document.createElement('tr'),first=document.createElement('td'),link=document.createElement('a');link.textContent=x.name;link.href='https://www.wowhead.com/forever/item='+x.id;first.append(link,document.createElement('br'),document.createTextNode(x.slot+' · ID '+x.id));
const source=document.createElement('td');source.textContent=x.where;const note=document.createElement('small');note.textContent=x.note||'';source.append(document.createElement('br'),note);
const status=document.createElement('td');status.textContent=x.status+(x.conditional?' · conditional':'')+(x.variants?' · '+x.variants+' variants':'');tr.append(first,source,status);byId('rows').append(tr);}byId('more').hidden=limit>=filtered.length;}
for(const id of ['query','kind'])byId(id).addEventListener('input',()=>{limit=100;render()});byId('more').onclick=()=>{limit+=100;render()};render();</script>'''
    (work/'catalog.html').write_text(document.replace('DATA',data),encoding='utf-8')

if __name__=='__main__':main()
