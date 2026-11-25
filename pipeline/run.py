"""Local SavedVariables -> WoWSims -> GearMatic workflow (standard library only)."""
from __future__ import annotations
from guild_runtime import runtime_root, usable_faction
import argparse
import copy
import hashlib
import html
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from lua_data import loads, saved_characters
import sim_progress
import addon_maintenance
from atomic_files import write_text as atomic

BASE=runtime_root()
STAT_KEYS={0:'Strength',1:'Agility',3:'Intellect',5:'SpellDamage',9:'HolySpellDamage',12:'SpellPenetration',13:'Spirit',14:'Ap',17:'HitRating',18:'CritRating',19:'HasteRating',20:'ArmorPenetration',21:'ExpertiseRating',31:'Mp5'}
def digest(data): return hashlib.sha256(data).hexdigest()

def cached_stats(out, fingerprint):
    """Keep validated stat runs for every setup, rather than only the last one."""
    current=out/'result.json'
    if current.exists():
        try:
            result=json.loads(current.read_text(encoding='utf-8'))
            key=result.get('modelFingerprint','')
            if len(key)==64 and all(ch in '0123456789abcdef' for ch in key):
                pawn_scale(result)
                target=out/'stat-cache'/(key+'.json')
                if not target.exists():atomic(target,json.dumps(result))
        except (OSError,ValueError,KeyError,TypeError):pass
    path=out/'stat-cache'/(fingerprint+'.json')
    try:
        result=json.loads(path.read_text(encoding='utf-8'))
        if result.get('modelFingerprint')!=fingerprint:return None
        pawn_scale(result)
        return result
    except (OSError,ValueError,KeyError,TypeError):return None
def model_identity(character,mode):
    if mode=='current':
        return {key:character[key] for key in ('id','name','race','class','level','talents')} | {
            'gear':native_character(character)['gear'],
            'professions':[p['name'] for p in character.get('professions',[])[:2]]}
    return {key:character[key] for key in ('id','name','race','class')} | {
        'professions':[p['name'] for p in character.get('professions',[])[:2]]}

def native_character(character):
    """The exporter's null slot is an empty protobuf item, not a JSON null.

    Retain the original export for freshness checks and never shift slot indexes.
    """
    data=copy.deepcopy(character)
    items=data.get('gear',{}).get('items')
    if not isinstance(items,list) or len(items)>17:
        raise ValueError('Invalid exported equipment slot count.')
    if any(item is not None and not isinstance(item,dict) for item in items):
        raise ValueError('Invalid exported equipment item.')
    data['gear']['items']=[item if item is not None else {} for item in items]+[{} for _ in range(17-len(items))]
    return data
def ensure_flb_adapter(config):
    """Restore our namespace adapter after an addon manager replaces FLB."""
    folder=Path(config['bridge_directory']).parent/'ForeverLevelingBiS'
    toc=folder/'ForeverLevelingBiS.toc'
    if not toc.exists():return False
    profiles=folder/'WeightProfiles.lua';tooltip=folder/'Tooltip.lua'
    if not profiles.exists() or not tooltip.exists():return False
    if not all(token in profiles.read_text(encoding='utf-8-sig') for token in ['function WP.Resolve(', 'function WP.Create(']) or 'function Tip.AddBlock(' not in tooltip.read_text(encoding='utf-8-sig'):
        print('Leveling BiS API changed; automatic adapter restoration needs review.',flush=True);return False
    wanted=(BASE/'addon/FLBAdapter.lua').read_text(encoding='utf-8')
    adapter=folder/'FLBAdapter.lua';changed=False
    if not adapter.exists() or adapter.read_text(encoding='utf-8-sig')!=wanted:
        atomic(adapter,wanted);changed=True
    text=toc.read_text(encoding='utf-8-sig')
    if 'FLBAdapter.lua' not in [line.strip() for line in text.splitlines()]:
        backup=BASE/'backups/flb-auto-restore'/('before-'+digest(text.encode())[:12]+'.toc')
        if not backup.exists():atomic(backup,text)
        atomic(toc,text.rstrip()+'\n\n# Local GuildSimBeta native profile adapter\nFLBAdapter.lua\n');changed=True
    if changed:print('Restored the Leveling BiS companion adapter. Restart WoW to load the TOC entry.',flush=True)
    return changed
def latest(config):
    path=Path(config['saved_variables'])
    if not path.exists(): raise ValueError('No exporter save yet. In WoW run /wse export, then /reload.')
    records=saved_characters(loads(path.read_text(encoding='utf-8-sig')))
    matches=[]
    for record in records:
        c=json.loads(record['data'])
        if c.get('flavor')!='forever' or c.get('class','').lower()!='paladin': continue
        if config.get('character_guid') and c.get('id')!=config['character_guid']:continue
        if config.get('character_name') and c.get('name','').casefold()!=config['character_name'].casefold(): continue
        matches.append((record,c))
    if not matches: raise ValueError('No saved export for '+config.get('character_name','your Paladin')+'. Run /wse export, wait for the text, then /reload.')
    record,c=max(matches,key=lambda rc:rc[0]['timestamp'])
    age=time.time()-record['timestamp']
    if age>config.get('max_export_age_hours',24)*3600: raise ValueError('Character export is old. Run /wse export and /reload first.')
    if age < -300: raise ValueError('Export timestamp is in the future; check the computer clock.')
    if c.get('race','').replace(' ','').lower() not in ('human','dwarf','undead'): raise ValueError('This engine supports Human, Dwarf and Undead Paladins.')
    if not c.get('id') or not c.get('name') or not 1<=int(c.get('level',0))<=60: raise ValueError('Incomplete character identity/level in export.')
    if config.get('_catalog_reference'):
        c=reference_character(c,config['catalog_reference_trinkets'])
    else:
        try:c=resolve_combat_trinkets(c,config)
        except ValueError:
            if not config.get('catalog_reference_trinkets'):raise
            # A reference catalog must not be blocked by riding-trinket memory.
            # Current weights use the literal saved equipment in this case.
            print('Combat trinket memory unavailable; current weights use the literal saved trinkets. Reference catalog is independent.',flush=True)
    return record,c

def reference_character(character,pair):
    result=native_character(character)
    if len(pair)!=2 or any(not isinstance(item,dict) or not item.get('id') for item in pair):
        raise ValueError('Catalog reference requires two explicit trinkets.')
    result['gear']['items'][12:14]=copy.deepcopy(pair)
    return result

def resolve_combat_trinkets(character,config):
    mount_ids=set(config.get('mount_trinket_ids',[]))
    if not mount_ids:return character
    result=copy.deepcopy(character)
    path=Path(config.get('combat_trinket_cache',BASE/'output/combat-trinkets.json'))
    previous=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    state=copy.deepcopy(previous)
    slots=state.setdefault(character['id'],copy.deepcopy(config.get('combat_trinket_fallback',{})))
    original=copy.deepcopy(slots)
    live=[result['gear']['items'][i] or {} for i in (12,13)]
    for index,slot in ((12,'13'),(13,'14')):
        equipped=result['gear']['items'][index] or {}
        if equipped.get('id') in mount_ids:
            if not slots.get(slot):raise ValueError('Mount trinket equipped and no combat replacement saved. Capture once with combat trinkets equipped.')
            replacement=original[slot]
            other=live[1 if index==12 else 0]
            if replacement.get('id')==other.get('id'):
                # The remembered combat item moved to the other slot. Recover
                # the displaced member of the last complete pair, not a clone.
                replacement=original.get('14' if slot=='13' else '13',{})
                if not replacement.get('id') or replacement.get('id') in mount_ids or replacement.get('id')==other.get('id'):
                    raise ValueError('Combat trinket memory is ambiguous. Equip both combat trinkets, then capture and /reload once to repair it.')
            result['gear']['items'][index]=copy.deepcopy(replacement)
        elif equipped.get('id'):
            slots[slot]=copy.deepcopy(equipped)
    resolved=[result['gear']['items'][i] or {} for i in (12,13)]
    if any(item.get('id') in mount_ids for item in live) and resolved[0].get('id') and resolved[0].get('id')==resolved[1].get('id'):
        raise ValueError('Combat trinket memory would duplicate an item. Equip both combat trinkets, then capture and /reload once.')
    for item,slot in zip(resolved,('13','14')):slots[slot]=copy.deepcopy(item)
    if state!=previous:atomic(path,json.dumps(state,indent=2))
    return result
def pawn_scale(result):
    w=result['weights']
    if w.get('error'): raise ValueError('Engine returned a stat-weight error: '+str(w['error']))
    ep=w['dps']['epValues']['stats']; ps=w['dps']['epValues'].get('pseudoStats',[])
    if len(ep)<32 or not math.isfinite(ep[14]) or abs(ep[14]-1)>0.001: raise ValueError('Invalid AP-normalized result; nothing will be installed.')
    values={key:float(ep[i]) for i,key in STAT_KEYS.items()}
    # GearMatic extracts Spell Power and Spell Damage separately; support either tooltip form.
    values['SpellPower']=values['SpellDamage']
    values['Dps']=float(ps[0])
    if any(not math.isfinite(v) for v in values.values()): raise ValueError('Non-finite weight result.')
    mode='Planning' if result['mode']=='planning' else 'Current'
    name=result.get('scaleName',f'Ret60 UW {mode}')
    scale='( Pawn: v1: "'+name+'": Class=Paladin, Spec=Retribution, '+', '.join(f'{k}={v:.6f}' for k,v in values.items())+' )'
    return scale,values

def refresh_plan_stats(result):
    """Read cap totals from the simulator, including talents and set bonuses."""
    path=BASE/'prebis-targets.json'
    if result['mode']!='planning' or result.get('context')=='equipped' or not path.exists(): return
    plan=json.loads(path.read_text(encoding='utf-8'))
    slots=[1,2,3,15,5,9,10,6,7,8,11,12,13,14,16,17,18]
    simulated=[(x.get('id',0),x.get('randomSuffix',0),x.get('enchant',0)) for x in result['settings']['player']['equipment']['items']]
    by_slot={x['wow_slot']:(x['id'],x.get('random_suffix',0),x.get('enchant',0)) for x in plan['items']}
    expected=[by_slot.get(slot,(0,0,0)) for slot in slots]
    if simulated!=expected: raise ValueError('Planning result does not match the farming targets, suffixes or enchants.')
    player=result['characterStats']['raidStats']['parties'][0]['players'][0]
    pseudo=player['finalStats']['pseudoStats']
    minimum=plan.get('constraints',{}).get('minimum_melee_hit_percent',0)
    if pseudo[12]+0.000001<minimum: raise ValueError('Planning set is below the required melee hit cap; weights were not published.')
    precision=plan['caps']['precision_hit_percent']
    plan['caps'].update(gear_hit_percent=round(pseudo[12]-precision,4),
        total_melee_hit_percent=round(pseudo[12],4),expertise_percent=round(pseudo[27],4))
    plan['baseline_dps']=result['baseline']['raidMetrics']['dps']['avg']
    plan['active_sets']=player.get('sets',[])
    atomic(path,json.dumps(plan,indent=2))
def bridge_payload(result,record,character,scale,run_id):
    payload={'guid':character['id'],'generated':int(time.time()),'runId':run_id,'mode':result['mode'],
             'scenario':result['scenario'],'sourceExport':record['data'],'pawn':scale}
    payload['context']=result.get('context')
    provenance=json.loads((BASE/'provenance.json').read_text(encoding='utf-8'))
    payload['wowsims']={key:provenance.get(key) for key in ('release_tag','release_url','upstream_commit')}
    payload['profileName']=result.get('scaleName')
    config=json.loads((BASE/'config.json').read_text(encoding='utf-8'))
    payload['mountTrinketIds']=config.get('mount_trinket_ids',[])
    gear=character.get('gear',{}).get('items',[])
    payload['combatTrinkets']={str(slot):gear[index] for index,slot in ((12,13),(13,14)) if len(gear)>index}
    if result.get('weights'):
        _, values = pawn_scale(result)
        # FLB stores flat hit/crit/expertise percentages, not sim rating points.
        mapping = {'Strength':'str','Agility':'agi','Intellect':'int','Spirit':'spi',
                   'Ap':'atkpwr','SpellDamage':'spldmg','HolySpellDamage':'holsplpwr',
                   'SpellPenetration':'splpen','Mp5':'manargn','Dps':'dps','HasteRating':'hastertng'}
        stats = {dest:values[src] for src,dest in mapping.items()}
        stats.update(splpwr=values['SpellDamage'], hitPct=values['HitRating']*10,
                     critPct=values['CritRating']*14, expPct=values['ExpertiseRating']*10)
        payload['flbStats'] = stats
    # JSON quoted strings use only the Lua-compatible escapes needed here. Unicode stays UTF-8.
    def quote(s):
        s=str(s)
        if any(ord(c)<32 and c not in '\n\r\t' for c in s): raise ValueError('Unsupported control character in payload')
        return json.dumps(s,ensure_ascii=False)
    plan_path=BASE/'prebis-targets.json'
    if plan_path.exists(): payload['plan']=json.loads(plan_path.read_text(encoding='utf-8'))
    def lua(v):
        if v is None:return 'nil'
        if isinstance(v,bool):return 'true' if v else 'false'
        if isinstance(v,(int,float)):
            if not math.isfinite(v):raise ValueError('Non-finite Lua payload number')
            return str(v)
        if isinstance(v,list):return '{'+','.join(lua(x) for x in v)+'}'
        if isinstance(v,dict):return '{'+','.join('['+quote(k)+']='+lua(x) for k,x in v.items())+'}'
        return quote(v)
    fields=[f'  {k} = {lua(v)},' for k,v in payload.items()]
    return 'local _, ns = ...\nns.payload = {\n'+'\n'.join(fields)+'\n}\n'
def make_report(result,c,values,scale,record,run_id):
    mode=result['mode']; dps=result['baseline']['raidMetrics']['dps']['avg']
    plan_path=BASE/'prebis-targets.json'
    target=json.loads(plan_path.read_text(encoding='utf-8')) if plan_path.exists() else None
    plan=('Uses the sourced Horde pre-raid target set and its planned level-60 talents. It does NOT simulate your current leveling character.' if target else 'Uses upstream level-60 placeholder gear/talents, or your scenario target overrides. It does NOT simulate your current leveling character.') if mode=='planning' else 'Uses your exported equipped gear and talents, at level 60.'
    if result.get('context')=='equipped':
        hit=result['characterStats']['raidStats']['parties'][0]['players'][0]['finalStats']['pseudoStats'][12]
        plan=f"Uses your exported gear projected to level 60, planned Unsealed Wrath talents and the selected raid support. This is not a simulation of your current level below 60. Modeled melee hit: {hit:.2f}%. The farming target below is a separate complete set."
    farm=''
    if target:
        farm_rows=''.join('<tr><td>'+html.escape(x['slot'])+'</td><td><a href="https://www.wowhead.com/forever/item='+str(x['id'])+'">'+html.escape(x['name'])+'</a></td><td>'+html.escape(x['where'])+'<br><small>Alternatives: '+html.escape(', '.join(a['name'] for a in x.get('alternatives',[])[:2]) or 'See source list')+'</small></td></tr>' for x in target['items'])
        excluded=''.join('<li>'+html.escape(x['name']+': '+x['reason'])+'</li>' for x in target['exclusions'])
        caps=target.get('caps',{})
        cap_text=f"Gear hit {caps.get('gear_hit_percent','?')}% + Precision {caps.get('precision_hit_percent','?')}% = {caps.get('total_melee_hit_percent','?')}% total melee hit. Expertise {caps.get('expertise_percent','?')}%."
        farm='<h2>Your pre-raid farming targets</h2><p>'+html.escape(target['talents'])+'. '+html.escape(target['method'])+'</p><p>'+html.escape(cap_text)+'</p><p>Open <code>/guildsim farm</code> in WoW for the checklist. <code>/guildsim target</code> saves it as a GearMatic target loadout. GearMatic upgrade scores still use the imported scale.</p><table><tr><th>Slot</th><th>Target</th><th>Where to obtain it</th></tr>'+farm_rows+'</table><details><summary>Excluded items and source restrictions</summary><ul>'+excluded+'</ul></details>'
        if target.get('audit_summary'):
            audit=target['audit_summary']
            folder='all-sources' if audit.get('coverage_file') else 'expanded-audit'
            craft='source-overrides.json' if folder=='all-sources' else 'craft-audit.json'
            farm+='<h3>Candidate and crafting audit</h3><p>'+str(audit['simulated_sets'])+' distinct gear comparisons. The search tests individual items and grouped sets; it is not an exhaustive proof of BiS. <a href="'+folder+'/comparisons.json">All simulated comparisons</a>; <a href="'+folder+'/candidate-pool.json">candidate pool</a>; <a href="../'+craft+'">recipes and material routes</a>.</p>'
            if audit.get('coverage_file'):
                farm+='<p>'+str(audit['included_base_items'])+' compatible base items; '+str(audit['included_variants'])+' item/stat variants. Includes reputation grinds and PvP without a rank/cost ceiling. <a href="all-sources/catalog.html">Search the full item catalog and source notes</a>; <a href="all-sources/coverage.json">coverage data</a>.</p>'
                farm+='<p>'+html.escape(target.get('source_policy',''))+'</p>'
        if target.get('named_comparisons'):
            comparisons=''.join('<tr><td>'+html.escape(x['name'])+'</td><td>'+f"{x['dps']:.2f}"+'</td><td>'+str(x['iterations'])+'</td></tr>' for x in target['named_comparisons'])
            farm+='<h3>Named alternatives in the final set</h3><p>Only the named item changes. Set thresholds and stat caps can change with it.</p><table><tr><th>Alternative</th><th>DPS</th><th>Iterations</th></tr>'+comparisons+'</table>'
        if target.get('availability_notes'):
            farm+='<h3>Availability and model assumptions</h3><ul>'+''.join('<li>'+html.escape(note)+'</li>' for note in target['availability_notes'])+'</ul>'
        if target.get('raid_assumptions'):
            farm+='<h3>Explicit raid assumptions</h3><ul>'+''.join('<li><strong>'+html.escape(group)+':</strong> '+html.escape(', '.join(names))+'</li>' for group,names in target['raid_assumptions'].items())+'</ul>'
        if target.get('mana_comparison'):
            data=target['mana_comparison']
            farm+='<h3>Why the old MP5 weight was high</h3><p>The controlled checks below use the same hit-capped seed equipment for 180 seconds. Mana starvation changes the marginal value of regeneration. Final weights use the final target separately.</p><table><tr><th>Setup</th><th>Seconds waiting for mana</th></tr>'+''.join('<tr><td>'+html.escape(row['setup'])+'</td><td>'+f"{row['seconds_oom']:.2f}"+'</td></tr>' for row in data['rows'])+'</table>'
        if target.get('constraints',{}).get('minimum_melee_hit_percent'):
            farm+='<p><strong>Required minimum: '+str(target['constraints']['minimum_melee_hit_percent'])+'% total melee hit.</strong> The engine and publisher refuse an under-cap planning target. <a href="hit-cap/comparisons.json">Hit-constrained refinement</a>; <a href="hit-cap/set-relocation-finalists.jsonl">set relocation finalists</a>.</p>'
        if target.get('chest_audit'):
            comparisons=''.join('<tr><td>'+html.escape(x['context'])+'</td><td>'+f"{x['dps']:.2f}"+'</td></tr>' for x in target['chest_audit'])
            farm+='<h3>Savage Gladiator comparison</h3><p>These 5,000-iteration swaps hold other equipment and settings fixed within each context. The final set has six Soulforge pieces; replacing its chest also loses that set threshold. Neither chest contributes hit.</p><table><tr><th>Chest comparison</th><th>DPS</th></tr>'+comparisons+'</table>'
    table=''.join(f'<tr><td>{html.escape(k)}</td><td>{v:.4f}</td></tr>' for k,v in values.items())
    gear=result['settings']['player']['equipment']['items']
    items=''.join(f'<li><a href="https://www.wowhead.com/forever/item={x["id"]}">Item {x["id"]}</a></li>' for x in gear if x and x.get('id'))
    eps=result['weights']['dps'].get('epValuesStdev',{}).get('stats',[])
    noisy=[STAT_KEYS[i] for i in STAT_KEYS if i<len(eps) and eps[i]>max(.25,abs(values[STAT_KEYS[i]])*.15)]
    warnings='; '.join(noisy) or 'None above the helper threshold; inspect detailed engine output for uncertainty.'
    return f'''<!doctype html><meta charset="utf-8"><title>Ret Sim results</title>
<style>body{{font:17px system-ui;max-width:960px;margin:40px auto;padding:0 24px;background:#15171c;color:#eee}}a{{color:#ffd478}}td,th{{padding:7px 18px;border-bottom:1px solid #444;text-align:left}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#232630;padding:16px}}.note{{border-left:4px solid #ffd478;padding:12px;background:#232630}}</style>
<h1>Ret60 Unsealed Wrath — {mode.upper()}</h1>
<p>{html.escape(c['name'])}, exported level {c['level']}; simulated level 60.</p>
<p class="note">{plan} WoWSims Paladin is alpha. These are model estimates. Imported weights do not adjust for caps after a gear change.</p>
<p>Scenario: {html.escape(result['scenario'])}. {result['iterations']:,} requested iterations. Baseline: {dps:.2f} simulated DPS.</p>
<p>Data exported: {time.strftime('%Y-%m-%d %H:%M:%S UTC',time.gmtime(record['timestamp']))}. Run: {run_id[:12]}.</p>
<h2>GearMatic weights</h2><p>Attack Power = 1. Hit/Crit/Expertise weights are PER RATING POINT, as required by GearMatic's Pawn import. They are not per 1%.</p>
<table><tr><th>Stat</th><th>EP</th></tr>{table}</table>
<p>Potentially noisy EP estimates: {html.escape(warnings)}</p>
<p>Weapon speed, procs and set interactions require direct gear-set comparisons; this scale does not capture them fully.</p>
<h2>Apply</h2><p>Reload WoW to read the result. {'Then run <code>/guildsim planning</code> to explicitly select the level-60 planning scale. Keep your leveling scale for normal leveling.' if mode=='planning' else 'The bridge imports automatically when your character export still matches. Run <code>/guildsim</code> to check status.'}</p>
<pre>{html.escape(scale)}</pre>
{farm}
<h2>Gear actually simulated</h2><ul>{items}</ul>
<h2>Candidate sources, not verified personal BiS</h2>
<ul><li><a href="https://wowforeverbislist.com/preraid/paladin/retribution/">Unsealed Wrath pre-raid candidates</a> — check Horde availability; proc values include estimates.</li>
<li><a href="https://foreverspec.com/pre-raid-bis/paladin/retribution/">ForeverSpec alternatives</a> — some drop sources inherit Classic data; procs/on-use omitted.</li>
<li><a href="https://www.method.gg/wow-forever/class-guides/retribution-paladin/bis-gear-and-stats">Method mechanics reference</a> — gear list currently unfinished.</li></ul>
<p>Full settings, requests, baseline metrics and weight uncertainties: <a href="result.json">result.json</a>. <a href="../README.txt">Workflow guide</a>.</p>'''
def run(config,force=False,publish=True,iterations=None):
    record,c=latest(config)
    mode=config.get('mode','auto')
    if mode=='auto': mode='current' if c['level']==60 else 'planning'
    scenario=(BASE/'scenario.json').read_bytes()
    context='current' if mode=='current' else 'target'
    scenario_path=BASE/'scenario.json'
    if mode=='planning' and config.get('leveling_weights')=='equipped':
        definition=json.loads(scenario)
        items=[copy.deepcopy(item or {}) for item in c['gear']['items']]
        definition['target_gear']={'items':(items+[{}]*17)[:17]}
        definition['minimum_melee_hit_percent']=0
        definition['name']='Exported gear projected to level 60 — planned Unsealed Wrath, selected raid support'
        scenario=json.dumps(definition,sort_keys=True).encode()
        scenario_path=BASE/'output/equipped-scenario.json'
        atomic(scenario_path,scenario.decode())
        context='equipped'
    elif mode=='current':
        definition=json.loads(scenario)
        definition.pop('target_gear',None);definition.pop('target_talents',None)
        definition['minimum_melee_hit_percent']=0
        definition['name']='Exported level-60 gear and talents — selected raid support'
        scenario=json.dumps(definition,sort_keys=True).encode()
        scenario_path=BASE/'output/current-scenario.json'
        atomic(scenario_path,scenario.decode())
    engine=BASE/'retlocal.exe'
    if not engine.exists(): raise ValueError('Local engine missing.')
    plan_path=BASE/'prebis-targets.json'
    plan_data=plan_path.read_bytes() if plan_path.exists() else b''
    policy=json.dumps(config.get('mount_trinket_ids',[]),sort_keys=True).encode()
    fingerprint=digest((record['data']+mode+str(iterations or config['iterations'])).encode()+scenario+engine.read_bytes()+plan_data+policy)
    state=BASE/'output'/'last-run.json'
    previous=json.loads(state.read_text(encoding='utf-8')) if state.exists() else {}
    installed_weights=Path(config['bridge_directory'])/'Weights.lua'
    installed_matches=installed_weights.exists() and previous.get('payloadHash')==digest(installed_weights.read_bytes())
    if not force and previous.get('fingerprint')==fingerprint and (not publish or (previous.get('published') and installed_matches)):
        if publish:
            atomic(BASE/'addon/Weights.lua',installed_weights.read_text(encoding='utf-8'))
        print('Gear, talents and scenario unchanged. Existing results are still current.'); return False
    out=BASE/'output';out.mkdir(exist_ok=True)
    atomic(out/'character.json',json.dumps(native_character(c),ensure_ascii=False,indent=2))
    pending=out/'result.pending.json'
    if pending.exists(): pending.unlink()
    identity=model_identity(c,mode)
    model_fingerprint=digest(json.dumps([mode,identity,iterations or config['iterations']],sort_keys=True).encode()+scenario+engine.read_bytes())
    old_result=cached_stats(out,model_fingerprint) if not force else None
    if old_result:
        result=old_result
        result['export']=c
        result['sourceRefreshed']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
        atomic(pending,json.dumps(result,indent=2))
        print('Previously simulated combat setup; reusing its validated stat simulations for the fresh export.',flush=True)
    else:
        command=[str(engine),'--root',str(BASE/'vendor'/'forever-master'),'--character',str(out/'character.json'),
                 '--scenario',str(scenario_path),'--mode',mode,'--iterations',str(iterations or config['iterations']),'--out',str(pending)]
        print(f"Simming {c['name']} (exported level {c['level']}); mode={mode}. This engine models level 60.",flush=True)
        proc=sim_progress.engine(command,cwd=BASE,log_path=out/'engine.log',stage='Stat weights — exported gear at 60' if context=='equipped' else 'Stat weights')
        print(proc.stderr[-1800:],flush=True)
        if proc.returncode: raise ValueError('Simulation failed; previous installed weights were preserved. See output/engine.log.')
        result=json.loads(pending.read_text(encoding='utf-8'))
        result['modelFingerprint']=model_fingerprint
        atomic(pending,json.dumps(result,indent=2))
    result['context']=context
    sim_progress.update('Saving results', 'Validating and publishing GearMatic weights')
    if context in ('equipped','current'):result['scaleName']='Ret60 UW Equipped'
    else:result.pop('scaleName',None)
    atomic(pending,json.dumps(result,indent=2))
    scale,values=pawn_scale(result)
    refresh_plan_stats(result)
    atomic(out/'stat-cache'/(model_fingerprint+'.json'),json.dumps(result))
    # Computed cap metadata is part of the published plan and its identity.
    plan_data=plan_path.read_bytes() if plan_path.exists() else b''
    fingerprint=digest((record['data']+mode+str(iterations or config['iterations'])).encode()+scenario+engine.read_bytes()+plan_data+policy)
    payload_hash=None
    if publish:
        if (iterations or config['iterations'])<5000: raise ValueError('At least 5,000 iterations required before publishing weights.')
        destination=Path(config['bridge_directory'])
        if not (destination/'GuildSimBeta.toc').is_file(): raise ValueError('Bridge addon is not installed; no weights published.')
        payload=bridge_payload(result,record,c,scale,fingerprint)
        atomic(destination/'Weights.lua',payload)
        atomic(BASE/'addon/Weights.lua',payload)
        payload_hash=digest((destination/'Weights.lua').read_bytes())
    os.replace(pending,out/'result.json')
    atomic(out/'gearmatic-pawn.txt',scale+'\n')
    atomic(out/'report.html',make_report(result,c,values,scale,record,fingerprint))
    atomic(state,json.dumps({'fingerprint':fingerprint,'payloadHash':payload_hash,'published':publish,'mode':mode,'created':int(time.time())},indent=2))
    print('Report: '+str(out/'report.html'))
    print('Published to bridge. /reload in WoW.' if publish else 'Diagnostic only; no in-game weights changed.')
    return True
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--watch',action='store_true');ap.add_argument('--force',action='store_true')
    ap.add_argument('--no-publish',action='store_true');ap.add_argument('--no-open',action='store_true');ap.add_argument('--iterations',type=int)
    args=ap.parse_args()
    lock=BASE/'output'/'running.lock';lock.parent.mkdir(exist_ok=True)
    try: fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError: raise SystemExit('Another helper may be running. If it was interrupted, close it and remove output/running.lock.')
    os.write(fd,str(os.getpid()).encode());os.close(fd)
    try:
        last_error=None;last_input=None;observed_input=None
        while True:
            config=json.loads((BASE/'config.json').read_text(encoding='utf-8'))
            p=Path(config['saved_variables'])
            plan_path=BASE/'prebis-targets.json'
            weapon_queue_path=p.with_name('GuildSimBeta.lua')
            bis_toc=Path(config['bridge_directory']).parent/'ForeverLevelingBiS/ForeverLevelingBiS.toc'
            marker=(p.stat().st_mtime_ns if p.exists() else 0,(BASE/'scenario.json').stat().st_mtime_ns,(BASE/'config.json').stat().st_mtime_ns,plan_path.stat().st_mtime_ns if plan_path.exists() else 0,weapon_queue_path.stat().st_mtime_ns if weapon_queue_path.exists() else 0,bis_toc.stat().st_mtime_ns if bis_toc.exists() else 0)
            marker+=(addon_maintenance.inputs(config),)
            request=BASE/'output/refresh.request.json'
            marker+=(request.stat().st_mtime_ns if request.exists() else 0,)
            catalog_request=BASE/'output/full-catalog.request.json'
            marker+=(catalog_request.stat().st_mtime_ns if catalog_request.exists() else 0,)
            if args.watch and marker!=observed_input:
                observed_input=marker
                time.sleep(3) # Let addon-manager file replacements settle before restoration.
                continue
            try:
                import update_wowsims
                if update_wowsims.check(config,force=marker!=last_input):last_input=None
            except ValueError as error:
                message=str(error);sim_progress.update('WoWSims update needs attention',message,state='error')
                if message!=last_error:print(message,flush=True);last_error=message
                if not args.watch:return 1
                time.sleep(5);continue
            if marker!=last_input:
                try:
                    sim_progress.update('Checking saved character', 'Checking export, gear and cached results')
                    if not args.no_publish:
                        sim_progress.update('Checking addon integration','Checking addon APIs and restoring compatible bridge files')
                        maintenance=addon_maintenance.reconcile(config,verify=True)
                        if maintenance['restored']:print(maintenance['message'],flush=True)
                        if not maintenance['ok']:raise ValueError(maintenance['message'])
                    changed=run(config,args.force,not args.no_publish,args.iterations)
                    import weapon_sims
                    weapon_sims.refresh(config,publish=not args.no_publish)
                    import item_sims
                    item_sims.refresh(config,publish=not args.no_publish)
                    import trinket_pairs
                    trinket_pairs.refresh(config,publish=not args.no_publish)
                    if not args.no_publish:
                        import target_weights
                        target_weights.refresh()
                    sim_progress.update('Ready to reload' if not args.no_publish else 'Diagnostic finished',
                        'Results saved. Click Load results in /guildsim; imports and scoring checks run automatically.' if not args.no_publish else 'Diagnostic completed; no in-game weights changed.', state='ready')
                    import refresh_scope
                    refresh_scope.run_requested(config,publish=not args.no_publish)
                    if changed and not args.no_open: os.startfile(BASE/'output'/'report.html')
                    last_error=None
                except (ValueError,OSError,KeyError,json.JSONDecodeError) as e:
                    message=str(e)
                    superseded=type(e).__name__=='SupersededCapture'
                    sim_progress.update('Switching to newer capture' if superseded else 'Simulation needs attention',message,state='running' if superseded else 'error')
                    if message!=last_error: print('Ret Sim: '+message,flush=True);last_error=message
                    if not args.watch: return 1
                last_input=marker
            if args.watch and not args.no_publish and last_error is None:
                import refresh_scope
                try:refresh_scope.schedule_catalog(config)
                except (ValueError,OSError,KeyError) as error:
                    print('Automatic catalog scheduling needs attention: '+str(error),flush=True)
            if not args.watch: return 0
            time.sleep(5)
    finally: lock.unlink(missing_ok=True)
if __name__=='__main__': sys.exit(main())
