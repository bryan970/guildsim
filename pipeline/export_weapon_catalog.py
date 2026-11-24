from guild_runtime import runtime_root, usable_faction
"""Export the full catalog and native DPS results as a readable table."""
import csv
import io
import json
from pathlib import Path
import run
import weapon_sims

BASE=runtime_root()


def export(payload=None):
    if payload is None:
        path=BASE/'output/weapons.json'
        payload=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    db=weapon_sims.database()
    results={c['key']:{f"{r['id']}:{r.get('randomSuffix',0)}":r for r in c['weapons']} for c in payload.get('contexts',[])} if payload.get('catalogMode') else {}
    rows=[]
    verified=json.loads((BASE/'source-overrides.json').read_text(encoding='utf-8')).get('verified_routes',{})
    for spec in weapon_sims.catalog_specs(db):
        item=db[spec['id']];label=f"{spec['id']}:{spec['randomSuffix']}"
        row={'item_id':spec['id'],'name':item['name'],'suffix_id':spec['randomSuffix'],'required_level':item.get('reqLvl',0),'speed':item.get('weaponSpeed',0),
             'source_status':'recorded source' if item.get('sources') or str(spec['id']) in verified else 'unverified source'}
        for context in ('equipped','target'):
            result=results.get(context,{}).get(label,{})
            for key in ('dps','delta','percent','iterations'):
                row[context+'_'+key]=result.get(key,'')
        rows.append(row)
    buffer=io.StringIO();writer=csv.DictWriter(buffer,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    destination=BASE/'output/weapon-catalog.csv';run.atomic(destination,buffer.getvalue())
    return destination


if __name__=='__main__':print(export())
