"""GuildSim beta: isolated installer, native comparisons and desktop setup.

All private configuration/cache stays in the user's LocalAppData directory.
No game input automation, Lua execution, or writes to other addons.
"""
from __future__ import annotations
import argparse
import copy
import ctypes
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from lua_data import loads, saved_characters

VERSION = '0.2.0-beta.6'
ENGINE_VERSION = 'v1.0.7'
ENGINE_COMMIT = 'a342c253e642d98273b50ee14fff4b097e8e52bf'
BASE = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent / 'bundle'
STATE = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'GuildSimBeta'
PROFILES = {'ret': 'Retribution â€” native DPS', 'disc-raid': 'Discipline â€” native healing assignments'}
SLOTS = ['Head','Neck','Shoulders','Back','Chest','Wrists','Hands','Waist','Legs','Feet','Ring 1','Ring 2','Trinket 1','Trinket 2','Main hand','Off hand','Relic / wand']
TYPES = {1:[0],2:[1],3:[2],4:[3],5:[4],6:[5],7:[6],8:[7],9:[8],10:[9],11:[10,11],12:[12,13],13:[14],14:[16]}
UTILITY = {11122,12846}
TARGETS = {'Unspecified':0,'Beast':1,'Demon':2,'Dragonkin':3,'Elemental':4,'Giant':5,'Humanoid':6,'Mechanical':7,'Undead':8}
FAMILIES = ['Unspecified','Naga','Satyr','Aquatic','Earth elemental','Fire elemental','Mountain giant','Swine','Plant','Troll','Orc','Ogre','Wolf','Worgen','Murloc','Furbolg','Dwarf','Dinosaur','Serpentine']

def read_json(path, default=None):
    try: return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except FileNotFoundError: return default

def atomic(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        tmp.write_text(data, encoding='utf-8'); os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)

def save(path, data): atomic(path, json.dumps(data, indent=2, ensure_ascii=False))
def digest(data): return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',',':')).encode()).hexdigest()
def file_hash(path):
    with open(path,'rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()

def verify_bundle(base=BASE):
    manifest = read_json(base / 'manifest.json')
    if not manifest or manifest.get('version') != VERSION: raise ValueError('Missing or incompatible release manifest. Extract the complete ZIP again.')
    for relative, expected in manifest['files'].items():
        path = (base / relative).resolve()
        if not path.is_relative_to(base.resolve()) or not path.is_file() or file_hash(path) != expected:
            raise ValueError('Release file failed verification: ' + relative)
    return manifest

def game_root(path):
    root = Path(path).expanduser().resolve()
    if (root / '_forever_' / 'Interface' / 'AddOns').is_dir(): root /= '_forever_'
    if not (root / 'Interface' / 'AddOns').is_dir() or not (root / 'WTF').is_dir():
        raise ValueError('Select the _forever_ folder containing Interface/AddOns and WTF.')
    return root

def game_running():
    if os.name != 'nt': return False
    result = subprocess.run(['tasklist','/FO','CSV','/NH'], capture_output=True, text=True, creationflags=0x08000000)
    return any(re.match(r'"(?:wow|wowclassic|wow-64|wowclassic-64)\.exe"', line, re.I) for line in result.stdout.splitlines())

def install(root, base=BASE, check_running=True, details=False):
    """Install only our folder and a missing exporter. Never replace another addon."""
    root = game_root(root); verify_bundle(base)
    if check_running and game_running(): raise ValueError('Close WoW before installing or upgrading addons, then try again.')
    addons = root / 'Interface' / 'AddOns'; dest = addons / 'GuildSimBeta'
    exporter = addons / 'WowSimsExporter'
    for path in (addons, dest, exporter):
        if path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction()): raise ValueError('Linked addon folders are not supported by the beta installer.')
    if dest.exists() and not (dest / '.guildsim-owned').is_file(): raise ValueError('GuildSimBeta folder exists without an ownership marker; move it aside before installing.')
    stage = addons / ('.GuildSimBeta-stage-' + uuid.uuid4().hex)
    backup = root / 'GuildSimBetaBackups' / (time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
    had_dest = dest.exists(); installed = False; added_exporter = False
    try:
        shutil.copytree(base / 'addons' / 'GuildSimBeta', stage)
        for generated in ('Results.lua','GuildResults.json','Profiles.lua','Weights.lua','TargetWeights.lua','ItemResults.lua','WeaponResults.lua'):
            if had_dest and (dest / generated).exists(): shutil.copy2(dest / generated, stage / generated)
        if had_dest:
            backup.parent.mkdir(parents=True, exist_ok=True)
            dest.rename(backup)
        stage.rename(dest); installed = True
        if not exporter.exists():
            exporter_stage = addons / ('.WowSimsExporter-stage-' + uuid.uuid4().hex)
            try:
                shutil.copytree(base / 'addons' / 'WowSimsExporter', exporter_stage)
                exporter_stage.rename(exporter); added_exporter = True
            finally:
                if exporter_stage.exists(): shutil.rmtree(exporter_stage)
    except Exception:
        if installed: shutil.rmtree(dest)
        if had_dest and backup.exists(): backup.rename(dest)
        if added_exporter: shutil.rmtree(exporter)
        raise
    finally:
        if stage.exists(): shutil.rmtree(stage)
    message=f'Installed GuildSimBeta. Exporter {"installed" if added_exporter else "preserved"}. ' + (f'Previous beta backed up at {backup}' if had_dest else '')
    return {'message':message,'backup':str(backup) if had_dest else None,'destination':str(dest)} if details else message

def discover(root):
    """Read every account; keep realm/GUID, not names, as identity."""
    found = {}
    for path in sorted((game_root(root) / 'WTF' / 'Account').glob('*/SavedVariables/WowSimsExporter.lua')):
        try:
            rows = saved_characters(loads(path.read_text(encoding='utf-8-sig')))
            for row in rows:
                char = json.loads(row['data']); key = char.get('id')
                if not isinstance(key,str) or not key or char.get('flavor') != 'forever': continue
                if str(char.get('class','')).lower() not in ('paladin','priest'): continue
                entry = {'character':char, 'timestamp':row['timestamp'], 'account':path.parent.parent.name,'path':str(path)}
                identity = (entry['account'], key)
                if identity not in found or entry['timestamp'] > found[identity]['timestamp']: found[identity] = entry
        except (ValueError, KeyError, IndexError, TypeError): continue
    return sorted(found.values(), key=lambda r:(r['character'].get('name',''),r['account']))

def profile_for(char):
    return 'ret' if char.get('class','').lower() == 'paladin' else 'disc-raid'

def sv_request(entry):
    path = Path(entry['path']).with_name('GuildSimBeta.lua')
    if not path.exists(): return {}
    data = loads(path.read_text(encoding='utf-8-sig')).get('GuildSimBetaDB',{})
    if profile_for(entry['character'])=='ret':
        return {'requestedAt':float(entry.get('timestamp',0))}
    request = data.get('characters',{}).get(entry['character']['id'],{})
    return request if isinstance(request,dict) else {}

def item_spec(link):
    if isinstance(link,dict): return {k:v for k,v in link.items() if k in ('id','enchant','randomSuffix') and (k=='id' or v)}
    if isinstance(link,int): return {'id':link}
    fields = str(link).split('item:')[-1].split('|')[0].split(':')
    try:
        if any(int(fields[i] or 0) for i in range(2,min(6,len(fields)))): raise ValueError('Sockets not supported by this beta')
        if len(fields)>12 and int(fields[12] or 0): raise ValueError('Bonus IDs not supported by this beta')
        return item_spec({'id':int(fields[0]), 'enchant':int(fields[1] or 0) if len(fields)>1 else 0, 'randomSuffix':int(fields[6] or 0) if len(fields)>6 else 0})
    except (ValueError,IndexError): raise ValueError('Unsupported item link')

def eligible(item, char, profile):
    class_id = 2 if profile=='ret' else 5
    if item.get('classAllowlist') and class_id not in item['classAllowlist']: return False
    if item.get('reqLvl',0)>60 or item.get('phase',1)>1: return False
    horde = char['race'] in ('Undead','Troll','Orc','Tauren','WindshaperSkyborne')
    if item.get('factionRestriction',0) == (1 if horde else 2): return False
    professions = {p['name'] for p in char.get('professions',[])}
    prof = {1:'Alchemy',2:'Blacksmithing',3:'Enchanting',4:'Engineering',8:'Leatherworking',11:'Tailoring'}.get(item.get('requiredProfession'))
    if prof and prof not in professions: return False
    typ = item.get('type')
    if typ not in TYPES: return False
    if profile=='ret':
        if typ==13: return item.get('handType')==4 and item.get('weaponType') in (1,4,6,9)
        if typ==14: return item.get('rangedWeaponType')==7
        return item.get('armorType',0)<=4
    if typ==13: return item.get('weaponType') in (2,4,5,8)
    if typ==14: return item.get('rangedWeaponType')==5
    return item.get('armorType',0)<=1

def legal(gear, db):
    items=gear['items']; ids=[it.get('id',0) for it in items if it]
    categories={}
    for ident in ids:
        row=db.get(str(ident),{})
        if row.get('unique') and ids.count(ident)>1: return False
        category=row.get('limitCategory')
        if category:
            categories[category]=categories.get(category,0)+1
            if categories[category]>1: return False
    return True

def normalize_gear(gear):
    result=copy.deepcopy(gear);result.pop('version',None)
    result['items']=(result['items']+[{}]*17)[:17]
    return result

def candidates(entry, profile, request, db, reference, full=False):
    char=entry['character']; equipped=normalize_gear(char['gear'])
    rows=[]; seen=set()
    def add(kind, gear, **extra):
        key=digest({'kind':kind,'gear':gear})
        if key in seen or not legal(gear,db): return
        seen.add(key);rows.append({'key':key,'gear':gear,'kind':kind,**extra})
    pool={}
    links=request.get('items',{})
    links=list(links.values()) if isinstance(links,dict) else links
    for it in equipped['items']+list(links or []):
        try:
            spec=item_spec(it);ident=spec.get('id',0);row=db.get(str(ident))
            if row and eligible(row,char,profile): pool[digest(spec)]=spec
        except ValueError: pass
    explicit=request.get('pool',{})
    for ident,enabled in explicit.items():
        if enabled:
            row=db.get(str(ident))
            if row and row.get('type')==12 and eligible(row,char,profile): pool[digest({'id':int(ident)})]={'id':int(ident)}
    exclusions={int(k) for k,v in request.get('excluded',{}).items() if v}
    trinkets=[s for s in pool.values() if db[str(s['id'])].get('type')==12 and s['id'] not in UTILITY|exclusions]
    unique={digest(s):s for s in trinkets};trinkets=list(unique.values())
    if len(trinkets)>40: raise ValueError('Trinket pool exceeds 40 variants; exclude some items before comparing.')
    for a,b in itertools.combinations(trinkets,2):
        for left,right in ((a,b),(b,a)):
            gear=copy.deepcopy(equipped);gear['items'][12:14]=[left,right]
            add('pair',gear,items=[left,right],slot=-1)
    if full:
        specs=[]
        for row in db.values():
            if row.get('type')==12 or not eligible(row,char,profile): continue
            suffixes=row.get('randomSuffixOptions') or [0]
            specs.extend({'id':row['id'],'randomSuffix':s} for s in suffixes)
    else: specs=list(pool.values())
    for spec in specs:
        row=db[str(spec['id'])]
        if row.get('type')==12: continue # Pair tab covers the joint trinket objective.
        slots=[15] if row['type']==13 and row.get('handType')==3 else TYPES[row['type']]
        for slot in slots:
            gear=copy.deepcopy(reference);gear['items'][slot]=spec
            if row['type']==13 and row.get('handType')==4: gear['items'][15]={}
            if slot==15 and db.get(str(gear['items'][14].get('id')),{}).get('handType')==4: continue
            add('gear',gear,items=[spec],slot=slot)
    return rows

def native(request, base=BASE):
    with tempfile.TemporaryDirectory(prefix='guildsim-') as tmp:
        inp=Path(tmp)/'request.json';out=Path(tmp)/'response.json';save(inp,request)
        result=subprocess.run([str(base/'guildsim-engine.exe'),'--defaults',str(base/'defaults.json'),'--input',str(inp),'--output',str(out)],capture_output=True,text=True,creationflags=0x08000000 if os.name=='nt' else 0)
        if result.returncode: raise ValueError(result.stderr.strip()[-2000:] or 'Native engine failed')
        return read_json(out)

def lua(value):
    if value is None: return 'nil'
    if isinstance(value,bool): return 'true' if value else 'false'
    if isinstance(value,(float,int)):
        if not math.isfinite(value): raise ValueError('Non-finite native result')
        return str(value)
    if isinstance(value,str): return '"'+value.replace('\\','\\\\').replace('"','\\"').replace('\r','\\r').replace('\n','\\n')+'"'
    if isinstance(value,list): return '{'+','.join(lua(v) for v in value)+'}'
    return '{'+','.join('['+lua(k)+']='+lua(v) for k,v in value.items())+'}'

class Runner:
    def __init__(self, base=BASE, state=STATE):
        self.base=base;self.state=state;self.stop=threading.Event()
        self.db=read_json(base/'items.json');self.engine=file_hash(base/'guildsim-engine.exe')
        self.suffixes=read_json(base/'suffixes.json',{})

    def run(self, entry, settings, notify=lambda x:None, full=False):
        root=game_root(settings['root']); addon=root/'Interface/AddOns/GuildSimBeta'
        if not (addon/'.guildsim-owned').exists(): raise ValueError('Install the beta addon first.')
        if time.time()-entry['timestamp']>86400: raise ValueError('This character export is over 24 hours old. Use /guildsim â†’ Update sims, then /reload in game.')
        request=sv_request(entry);char=copy.deepcopy(entry['character']);profile=profile_for(char)
        char['guildTalentSignature']=request.get('talentSignature')
        identity=digest({'account':entry['account'],'guid':char['id'],'profile':profile})
        refs=self.state/'characters'/identity/'reference.json'
        ref=read_json(refs)
        if ref is None:
            pair=normalize_gear(char['gear'])['items'][12:14]
            if any(not it.get('id') or it.get('id') in UTILITY for it in pair): raise ValueError('Equip two combat trinkets for the first reference capture. The saved reference stays fixed after that.')
            ref=pair;save(refs,ref)
        refgear=normalize_gear(char['gear']);refgear['items'][12:14]=ref
        mob=int(request.get('mobType',settings.get('mobType',0)));family=int(request.get('creatureFamily',settings.get('creatureFamily',0)))
        if mob not in TARGETS.values() or not 0<=family<len(FAMILIES): raise ValueError('Invalid encounter profile')
        scenario=read_json(self.state/'scenario.json',{})
        base_request={'profile':profile,'character':char,'reference':refgear,'iterations':settings.get('iterations',12500),'duration':settings.get('duration',180),'mobType':mob,'creatureFamily':family,'scenario':scenario}
        if profile=='disc-raid':
            assignment=request.get('healingAssignment','group');duration=int(request.get('healingDuration',180))
            if assignment not in ('group','tank','burst') or duration not in (180,300):raise ValueError('Invalid healing assignment or duration')
            base_request.update(iterations=int(settings.get('healing_iterations',256)),duration=duration,healing={'assignment':assignment})
        # Remember observed combat trinkets even after they move to the bank.
        poolfile=self.state/'characters'/identity/'trinket-pool.json'
        remembered=read_json(poolfile,{})
        links=request.get('items',{})
        links=list(links.values()) if isinstance(links,dict) else list(links or [])
        for item in normalize_gear(char['gear'])['items']+links:
            try:
                spec=item_spec(item);meta=self.db.get(str(spec.get('id')), {})
                if meta.get('type')==12 and spec['id'] not in UTILITY and eligible(meta,char,profile):remembered[digest(spec)]=spec
            except ValueError:pass
        save(poolfile,remembered)
        request={**request,'items':links+list(remembered.values())}
        jobs=candidates(entry,profile,request,self.db,refgear,full)
        cache=self.state/'cache';cache.mkdir(parents=True,exist_ok=True)
        def evaluate(req):
            # Cache every exact request; Aâ†’Bâ†’A reuses results without mixing race, target, talents, gear or engine versions.
            key=digest({'engine':self.engine,'adapter':VERSION,'request':req})
            path=cache/(key+'.json');result=read_json(path)
            if result is None:
                result=native(req,self.base)
                if result['baseline'].get('error') or result['reference'].get('error'): raise ValueError(result['baseline'].get('error') or result['reference'].get('error'))
                save(path,result)
            return result
        notify(f'{char.get("name")} Â· {PROFILES[profile]} Â· baseline')
        baseline=evaluate({**base_request,'candidates':[]})
        if profile=='disc-raid':
            completed=self.healing_comparisons(addon,char,baseline,jobs,ref,mob,family,base_request,full,notify)
            notify(f'Ready: {char.get("name")} Â· {len(completed)} healing comparisons. Use /reload to load results.')
            return baseline,completed
        completed=[]
        published=time.monotonic()
        for number,job in enumerate(jobs):
            if self.stop.is_set(): raise InterruptedError('Paused. Completed comparisons are cached; click Run to resume.')
            # Per-candidate records permit interruption and pool expansion without restarting prior pairs.
            req=copy.deepcopy(base_request)
            req['character']['gear']=refgear if job['kind']=='gear' else job['gear']
            req['candidates']=[{'key':job['key'],'gear':job['gear']}]
            result=evaluate(req);completed.append({**job,**result['rows'][0]})
            if number%5==0 or number+1==len(jobs):
                notify(f'{char.get("name")} Â· {number+1} / {len(jobs)} comparisons')
            if time.monotonic()-published>=30 or number+1==len(jobs):
                self.publish(addon,char,profile,baseline,completed,ref,mob,family,len(jobs),number+1==len(jobs))
                published=time.monotonic()
        if not jobs: self.publish(addon,char,profile,baseline,[],ref,mob,family,0,True)
        notify(f'Ready: {char.get("name")} Â· {len(completed)} comparisons. Use /reload to load results.')
        return baseline,completed

    def healing_comparisons(self,addon,char,baseline,jobs,ref,mob,family,base_request,full,notify):
        """Batch native fights; cache every variant and refine broad-catalog leaders."""
        cache=self.state/'healing-cache';rows={};published=time.monotonic()
        final_iterations=base_request['iterations']
        if not 20<=final_iterations<=10000:raise ValueError('Healing comparisons require 20..10000 fights')
        def run_batch(chunk,iterations):
            missing={};found={}
            for job in chunk:
                context=copy.deepcopy(base_request);context['character']['gear']=job['gear']
                context.update(iterations=iterations,skipBaseline=True,candidates=[{'key':'candidate','gear':job['gear']}])
                key=digest({'engine':self.engine,'adapter':VERSION,'request':context})
                path=cache/key[:2]/(key+'.json');value=read_json(path)
                if value is None:missing[key]=(job,path)
                else:found[key]=value
                job['_healing_cache_key']=key
            if missing:
                request=copy.deepcopy(base_request)
                request.update(iterations=iterations,skipBaseline=True,candidates=[{'key':key,'gear':job['gear']} for key,(job,_) in missing.items()])
                response=native(request,self.base)
                for value in response['rows']:
                    key=value['key']
                    if key not in missing:raise ValueError('Native healing batch returned an unknown candidate')
                    save(missing[key][1],value);found[key]=value
                if len(found)<len({job['_healing_cache_key'] for job in chunk}):raise ValueError('Native healing batch is incomplete')
            for job in chunk:
                value=found[job['_healing_cache_key']]
                clean={k:v for k,v in job.items() if not k.startswith('_')}
                rows[job['key']]={**clean,**value,'key':job['key'],'screening':iterations<final_iterations}
        def publish(complete):
            self.publish(addon,char,'disc-raid',baseline,[rows[j['key']] for j in jobs if j['key'] in rows],ref,mob,family,len(jobs),complete)
        screen_iterations=min(32,final_iterations) if full else final_iterations
        for start in range(0,len(jobs),16):
            if self.stop.is_set():raise InterruptedError('Paused. Completed healing batches are cached; click Run to resume.')
            chunk=jobs[start:start+16];run_batch(chunk,screen_iterations)
            notify(f'{char.get("name")} Â· {min(start+16,len(jobs))} / {len(jobs)} healing comparisons Â· {screen_iterations} fights each')
            if time.monotonic()-published>=30 or start+16>=len(jobs):publish(not full);published=time.monotonic()
        if full and screen_iterations<final_iterations:
            def score(row):
                alive=row.get('survival',0)
                return (alive>=.99,alive if alive<.99 else 1,row.get('usefulHps',-1))
            shortlist=[];counts={}
            for job in sorted(jobs,key=lambda j:score(rows[j['key']]),reverse=True):
                row=rows[job['key']]
                if row.get('error'):continue
                if job['kind']=='pair':shortlist.append(job);continue
                per_item=counts.setdefault(job['slot'],{})
                item=job['items'][0]['id']
                if (item not in per_item and len(per_item)>=12) or per_item.get(item,0)>=2:continue
                per_item[item]=per_item.get(item,0)+1;shortlist.append(job)
            for start in range(0,len(shortlist),8):
                if self.stop.is_set():raise InterruptedError('Paused. Completed healing batches are cached; click Run to resume.')
                run_batch(shortlist[start:start+8],final_iterations)
                notify(f'{char.get("name")} Â· refine healing upgrades {min(start+8,len(shortlist))} / {len(shortlist)} Â· {final_iterations} fights each')
                if time.monotonic()-published>=30:publish(False);published=time.monotonic()
        publish(True)
        return [rows[j['key']] for j in jobs]

    def publish(self, addon, char, profile, baseline, rows, ref, mob, family, total, complete):
        output=[]
        for row in rows:
            items=[]
            for spec in row['items']:
                meta=self.db[str(spec['id'])]
                name=meta['name'];suffix=self.suffixes.get(str(spec.get('randomSuffix',0)))
                if suffix and suffix not in name:name+=' '+suffix
                items.append({**spec,'name':name,'icon':meta.get('icon',''),'quality':meta.get('quality',1),'source':meta.get('source','Acquisition source unverified'),'setName':meta.get('setName','')})
            gaps={}
            for gear in (row['gear'],{'items':normalize_gear(char['gear'])['items']}):
                for spec in gear['items']:
                    meta=self.db.get(str(spec.get('id')), {})
                    if meta.get('missingEffects'):gaps[str(spec['id'])]=meta['missingEffects']
            output.append({k:v for k,v in {**row,'items':items,'missingEffects':gaps}.items() if k!='gear'})
        payload={'version':VERSION,'engine':ENGINE_COMMIT,'generated':int(time.time()),'guid':char['id'],'name':char['name'],'race':char['race'],'profile':profile,'equipped':normalize_gear(char['gear'])['items'],'baseline':baseline['baseline'],'reference':baseline['reference'],'referencePair':ref,'mobType':mob,'creatureFamily':family,'rows':output,'total':total,'complete':complete,'talents':char['talents'],'talentSignature':char.get('guildTalentSignature'),'objective':baseline['objective']}
        if profile=='disc-raid':payload['healingScenario']=baseline['baseline'].get('healingScenario')
        # Preserve results for alts; account identity stays in local state, addon payload is keyed by GUID.
        path=addon/'GuildResults.json';all_results=read_json(path,{})
        if profile=='disc-raid':
            context=copy.deepcopy(baseline['request'])
            gear=normalize_gear(char['gear']);gear['items'][12:14]=ref
            parties=context.get('raid',{}).get('parties',[])
            if parties and parties[0].get('players'):parties[0]['players'][0]['equipment']=gear
            else:context={'character':{**char,'gear':gear},'request':context}
            payload['catalogContext']=digest({'engine':self.engine,'adapter':VERSION,'native':context,'healing':payload.get('healingScenario')})
            old=all_results.get(char['id'],{})
            if old.get('version')==VERSION and old.get('catalogContext')==payload['catalogContext']:
                # Keep broad gear results when bags/pool change or combat trinkets
                # are swapped. Pair rows always come from the current owned pool.
                merged={r['key']:r for r in old.get('rows',[]) if r.get('kind')=='gear'}
                merged.update({r['key']:r for r in output})
                payload['rows']=list(merged.values());payload['total']=max(total,len(merged))
        all_results[char['id']]=payload
        save(path,all_results)
        atomic(addon/'Results.lua','local _, ns = ...\nns.results = '+lua(all_results)+'\n')
        healing=baseline['baseline'].get('healingScenario') if profile=='disc-raid' else None
        record=digest({'guid':char['id'],'profile':profile,'engine':self.engine,'request':baseline['request'],'healing':healing})
        save(self.state/'fights'/f'{record}.json',{'payload':payload,'nativeRequest':baseline['request'],'healingScenario':healing})

def diagnose(base=BASE):
    manifest=verify_bundle(base)
    result=subprocess.run([str(base/'guildsim-engine.exe'),'--capabilities'],capture_output=True,text=True,creationflags=0x08000000 if os.name=='nt' else 0,check=True)
    caps=json.loads(result.stdout)
    return {'version':VERSION,'integrity':'passed','races':caps,'profiles':PROFILES,'engineCommit':manifest['engineCommit'],'pythonRequired':False,'adminRequired':False}

class App:
    def __init__(self):
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox
        self.tk=tk;self.ttk=ttk;self.dialog=filedialog;self.msg=messagebox
        self.window=tk.Tk();self.window.title('GuildSim Â· Setup & comparisons');self.window.geometry('820x780');self.window.minsize(750,730)
        style=ttk.Style();style.theme_use('clam');style.configure('.',font=('Segoe UI',10));style.configure('Title.TLabel',font=('Segoe UI Semibold',18));style.configure('TButton',padding=(12,7))
        self.settings=read_json(STATE/'settings.json',{});self.entries=[];self.busy=False;self.runner=None;self.events=queue.Queue()
        frame=ttk.Frame(self.window,padding=24);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='GuildSim Beta',style='Title.TLabel').pack(anchor='w')
        ttk.Label(frame,text='Ret: Human Â· Dwarf Â· Undead   |   Discipline: native healing assignments',wraplength=720).pack(anchor='w',pady=(5,20))
        ttk.Label(frame,text='1. Choose your WoW Forever folder').pack(anchor='w')
        line=ttk.Frame(frame);line.pack(fill='x',pady=6)
        default=self.settings.get('root','')
        if not default:
            for guess in ('D:/World of Warcraft/_forever_','C:/World of Warcraft/_forever_','C:/Program Files (x86)/World of Warcraft/_forever_'):
                if (Path(guess)/'Interface/AddOns').is_dir(): default=guess;break
        self.path=tk.StringVar(value=default);ttk.Entry(line,textvariable=self.path).pack(side='left',fill='x',expand=True)
        ttk.Button(line,text='Browseâ€¦',command=self.browse).pack(side='left',padx=(8,0))
        ttk.Button(frame,text='Install / upgrade addon',command=self.install).pack(anchor='w',pady=(2,8))
        ttk.Label(frame,text='Ret users: have GearMatic preinstalled. Its files and settings are preserved.',wraplength=720).pack(anchor='w',pady=(0,8))
        self.auto_updates=tk.BooleanVar(value=self.settings.get('auto_updates',True))
        self.startup=tk.BooleanVar(value=self.settings.get('start_with_windows',True))
        ttk.Checkbutton(frame,text='Automatically update GuildSim when WoW is closed',variable=self.auto_updates,command=self.persist_options).pack(anchor='w')
        ttk.Checkbutton(frame,text='Keep the helper running when Windows starts',variable=self.startup,command=self.persist_options).pack(anchor='w',pady=(0,10))
        ttk.Label(frame,text='2. In game: /guildsim â†’ Update sims â†’ /reload').pack(anchor='w')
        ttk.Label(frame,text='Keep this helper open. Results need another /reload after comparisons finish.',wraplength=720).pack(anchor='w',pady=(4,8))
        line=ttk.Frame(frame);line.pack(fill='x')
        self.char=tk.StringVar();self.combo=ttk.Combobox(line,textvariable=self.char,state='readonly');self.combo.pack(side='left',fill='x',expand=True)
        ttk.Button(line,text='Refresh characters',command=self.refresh).pack(side='left',padx=(8,0))
        ttk.Label(frame,text='3. Compare gear and your trinket pool',font=('Segoe UI Semibold',11)).pack(anchor='w',pady=(22,8))
        line=ttk.Frame(frame);line.pack(fill='x')
        ttk.Button(line,text='Run / resume comparisons',command=self.start).pack(side='left')
        ttk.Button(line,text='Pause after current comparison',command=self.pause).pack(side='left',padx=8)
        self.full=tk.BooleanVar(value=False);ttk.Checkbutton(frame,text='Full phase-1 catalog (many comparisons; resumes from cache)',variable=self.full).pack(anchor='w',pady=8)
        self.watch=tk.BooleanVar(value=True);ttk.Checkbutton(frame,text='Watch for Update sims requests while this helper is open',variable=self.watch).pack(anchor='w')
        line=ttk.Frame(frame);line.pack(fill='x',pady=(12,5))
        ttk.Button(line,text='Check GuildSim updates',command=self.check_updates).pack(side='left')
        ttk.Button(line,text='Open local data / fight library',command=lambda:os.startfile(STATE)).pack(side='left',padx=8)
        ttk.Button(line,text='Move personal setup',command=self.migrate).pack(side='left')
        ttk.Button(frame,text='Quit helper',command=self.quit).pack(anchor='w',pady=(5,0))
        ttk.Label(frame,text='Catalog: fixed reference trinkets. Pair comparisons: exported combat gear.\nDisc simulates effective healing, consumed shields, survival, overhealing and mana for the selected assignment.',wraplength=720).pack(anchor='w',pady=12)
        self.status=tk.StringVar(value='Ready to install. Your existing RetSimBridge and helper remain untouched.')
        ttk.Label(frame,textvariable=self.status,wraplength=720,foreground='#156f83').pack(anchor='w',pady=10)
        self.engine_status=tk.StringVar(value='Simulation engine: '+ENGINE_VERSION+' · checking upstream releases automatically')
        ttk.Label(frame,textvariable=self.engine_status,wraplength=720).pack(anchor='w')
        self.window.protocol('WM_DELETE_WINDOW',self.close);self.window.after(500,self.poll)
        self.last_job=None;self.catalog_due=None
        try: verify_bundle();self.refresh()
        except Exception as e:self.status.set(str(e))
        self.seen={}
        self.last_update_check=0
        self.pending_update=None;self.job_ok=False
        self.last_pending_stamp=None
        self.pending_install=False
        self.rollback_required=bool(read_json(STATE/'active.json',{}).get('failedVersion'))

    def auto_setup(self):
        candidates=[p for p in ('D:/World of Warcraft/_forever_','C:/World of Warcraft/_forever_','C:/Program Files (x86)/World of Warcraft/_forever_') if (Path(p)/'Interface/AddOns').is_dir()]
        if len(candidates)!=1:
            self.status.set('Select your WoW Forever folder, then click Install. This is only needed once.');return
        self.path.set(candidates[0])
        if game_running():
            self.pending_install=True;self.status.set('Close WoW once. GuildSim will install automatically when the game exits.');return
        self.install()

    def browse(self):
        value=self.dialog.askdirectory(title='Choose _forever_ folder')
        if value:self.path.set(value);self.refresh()
    def install(self):
        try:
            self.status.set(install(self.path.get()));self.persist();self.refresh();self.persist_options()
            if (Path(self.path.get())/'Interface/AddOns/RetSimBridge').exists():
                self.status.set('GuildSim installed alongside RetSimBridge. Import your personal setup before switching; the existing helper remains active.')
        except Exception as e:self.msg.showerror('Install',str(e))
    def persist_options(self):
        self.settings.update(auto_updates=self.auto_updates.get(),start_with_windows=self.startup.get())
        save(STATE/'settings.json',self.settings)
        import updates
        if (STATE/'GuildSim Launcher.exe').exists():updates.startup(self.startup.get())
    def migrate(self):
        try:
            if game_running():raise ValueError('Close WoW before importing saved addon settings. Your existing helper can remain running.')
            self.refresh();index=self.combo.current()
            if index<0:raise ValueError('Choose the Ret character to migrate first.')
            entry=self.entries[index]
            if profile_for(entry['character'])!='ret':raise ValueError('Personal Ret migration applies to Paladins.')
            source=self.dialog.askdirectory(title='Choose the existing Ret helper folder (config.json and output)')
            if source:
                from ret_runtime import migrate_personal
                migrate_personal(source,entry,{'root':self.path.get()})
                self.settings['migration_source']=source;save(STATE/'settings.json',self.settings)
                self.status.set('Personal state copied. GuildSim will validate new results, then switch only when WoW is closed and the original helper has finished.')
                self.start(entry)
        except Exception as e:self.msg.showerror('Import personal setup',str(e))
    def persist(self):
        self.settings['root']=str(game_root(self.path.get()));save(STATE/'settings.json',self.settings)
    def refresh(self):
        try:
            self.entries=discover(self.path.get());values=[]
            for entry in self.entries:
                c=entry['character'];values.append(f'{c.get("name")} Â· {c.get("realm") or "realm unspecified"} Â· {c.get("race")} {c.get("class")} Â· {entry["account"]}')
            previous=self.char.get();self.combo['values']=values
            if previous in values:self.combo.current(values.index(previous))
            elif values:self.combo.current(0)
            if not values:self.status.set('No supported saved characters yet. Log in, /guildsim â†’ Update sims, then /reload and refresh.')
        except Exception as e:self.status.set(str(e))
    def start(self, entry=None, full_catalog=False):
        if self.busy:return
        try:
            self.persist();verify_bundle()
            if entry is None:
                self.refresh();idx=self.combo.current()
                if idx<0:raise ValueError('Capture a supported character first.')
                entry=self.entries[idx]
            if profile_for(entry['character'])=='ret':
                from ret_runtime import RetRunner
                self.runner=RetRunner()
            else:self.runner=Runner()
            self.busy=True;self.job_ok=False;full=self.full.get() or full_catalog;settings=dict(self.settings)
            self.last_job=(entry,full)
            def work():
                try:
                    self.runner.run(entry,settings,self.events.put,full);self.job_ok=True
                except Exception as e:self.events.put(str(e))
                finally:self.events.put(None)
            threading.Thread(target=work,daemon=True).start()
        except Exception as e:self.msg.showerror('Comparisons',str(e))
    def pause(self):
        if self.runner:self.runner.stop.set();self.status.set('Pausing after the current native comparisonâ€¦')
    def close(self):
        self.window.withdraw()
    def quit(self):
        if self.busy:self.pause();self.status.set('Pausing safely. Click Quit helper again when paused.');return
        self.window.destroy()
    def poll(self):
        import updates
        updates.finish_launcher_update(STATE)
        if not self.pending_update:
            try:
                marker=STATE/'pending-update.json';stamp=marker.stat().st_mtime_ns if marker.exists() else None
                if stamp!=self.last_pending_stamp:
                    self.last_pending_stamp=stamp
                    target=updates.pending_target()
                    if target:self.events.put(('update',str(target)))
            except Exception as e:self.status.set('Staged update needs attention: '+str(e))
        while not self.events.empty():
            message=self.events.get()
            if message is None:
                self.busy=False
                if self.job_ok and self.last_job and profile_for(self.last_job[0]['character'])=='ret' and not self.last_job[1] and not self.runner.stop.is_set():
                    self.catalog_due=(time.time()+120,self.last_job[0])
            elif isinstance(message,tuple) and message[0]=='update':
                self.pending_update=Path(message[1]);self.status.set('Update downloaded and verified. It will install when WoW and simulations are closed.')
            elif isinstance(message,tuple) and message[0]=='engine':
                data=message[1]
                text='Simulation engine: '+data['installed']
                if data.get('status')=='unavailable':text+=' · upstream check unavailable; will retry automatically'
                elif data.get('newer'):text+=' · '+data['latest']+' available upstream; awaiting a tested GuildSim update'
                else:text+=' · latest upstream release'
                self.engine_status.set(text)
            else:self.status.set(message)
        show=STATE/'show.request'
        if show.exists():show.unlink();self.window.deiconify();self.window.lift()
        if self.pending_install and not game_running():self.pending_install=False;self.install()
        if self.rollback_required and not self.busy and self.settings.get('root') and not game_running():
            try:
                import updates
                updates.restore_after_rollback(BASE,STATE,self.settings['root']);self.rollback_required=False
            except Exception as e:self.status.set('Update recovery needs attention: '+str(e))
        if self.pending_update and not self.busy and not game_running():
            import updates
            updates.launch_activation(self.pending_update,self.settings.get('root'),os.getpid())
            self.window.destroy();return
        if self.job_ok and not self.busy and self.settings.get('migration_source'):
            try:
                from ret_runtime import finish_migration
                finished,message=finish_migration(self.settings['migration_source'],self.path.get())
                self.status.set(message)
                if finished:self.settings.pop('migration_source');save(STATE/'settings.json',self.settings)
            except Exception as e:self.status.set('Migration needs attention: '+str(e))
        if self.watch.get() and not self.busy:
            try:
                for entry in discover(self.path.get()):
                    request=sv_request(entry);stamp=request.get('requestedAt',0);key=(entry['account'],entry['character']['id'])
                    if stamp>self.seen.get(key,0):
                        self.seen[key]=stamp
                        if stamp>time.time()-86400:self.start(entry);break
            except (ValueError,OSError,KeyError,IndexError,TypeError):pass
        if not self.busy and self.catalog_due and time.time()>=self.catalog_due[0]:
            _,entry=self.catalog_due;self.catalog_due=None;self.start(entry,True)
        if time.time()-self.last_update_check>1800:self.check_updates(False)
        self.window.after(3000,self.poll)
    def check_updates(self,manual=True):
        self.last_update_check=time.time()
        download=manual or self.auto_updates.get()
        def work():
            try:
                import updates
                self.events.put(('engine',updates.upstream_release(force=manual)))
                target=updates.check() if download else None
                if target:self.events.put(('update',str(target)))
            except Exception as e:self.events.put('Update check unavailable: '+str(e))
        threading.Thread(target=work,daemon=True).start()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--diagnose',action='store_true');parser.add_argument('--report');parser.add_argument('--install');parser.add_argument('--simulate');parser.add_argument('--output');parser.add_argument('--self-test',action='store_true');parser.add_argument('--gui-smoke',action='store_true');parser.add_argument('--ret-task');parser.add_argument('--full-catalog',action='store_true');parser.add_argument('--background',action='store_true');parser.add_argument('--health-file');parser.add_argument('--activate-update');parser.add_argument('--parent-pid',type=int);parser.add_argument('--game-root');parser.add_argument('--first-run',action='store_true')
    args=parser.parse_args()
    if args.ret_task:
        from ret_runtime import execute_task
        return execute_task(args.ret_task,args.full_catalog)
    if args.activate_update:
        import updates
        return updates.activate(args.activate_update,args.parent_pid,args.game_root)
    if args.diagnose or args.self_test:
        data=diagnose()
        if args.self_test:
            preset=read_json(BASE/'defaults.json')
            checks=[]
            for profile,key,cls in [('ret','ret','Paladin'),('disc-raid','disc','Priest')]:
                player=preset[key]['player'] if key=='ret' else preset[key]
                for race in data['races'][cls]:
                    char={'flavor':'forever','class':cls,'race':race,'name':'Public preset smoke test','level':60,'talents':player['talentsString'],'gear':player['equipment']}
                    result=native({'profile':profile,'character':char,'iterations':20,'duration':30,'candidates':[]},BASE)
                    if result['baseline'].get('error'):raise ValueError(result['baseline']['error'])
                    if profile=='ret' and result['baseline'].get('dps',0)<=0:raise ValueError('No native DPS')
                    if profile=='disc-raid' and ('dps' in result['baseline'] or result['baseline']['stats']['HealingPower']<=0 or result['baseline'].get('usefulHps',0)<=0):raise ValueError('Invalid healer objective')
                    checks.append({'profile':profile,'race':race,'passed':True})
            data['nativeSmokeTests']=checks
            portable=[]
            with tempfile.TemporaryDirectory(prefix='guildsim-ret-check-') as tmp:
                tmp=Path(tmp);player=preset['ret']['player']
                for race in data['races']['Paladin']:
                    char={'flavor':'forever','class':'paladin','race':race,'name':'Public Ret smoke test','level':60,'talents':player['talentsString'],'gear':player['equipment']}
                    save(tmp/'character.json',char)
                    command=[str(BASE/'ret-engine/retlocal.exe'),'--root',str(BASE/'ret-engine/vendor/forever-master'),'--character',str(tmp/'character.json'),'--scenario',str(BASE/'ret-engine/scenario.json'),'--mode','current','--iterations','20','--no-weights','--out',str(tmp/'result.json')]
                    result=subprocess.run(command,capture_output=True,timeout=60,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    if result.returncode:raise ValueError('Portable Ret engine failed for '+race)
                    native_result=read_json(tmp/'result.json')
                    if native_result['baseline']['raidMetrics']['dps']['avg']<=0 or native_result['export']['race']!=race:raise ValueError('Portable Ret result failed validation')
                    portable.append({'race':race,'passed':True})
            data['portableRetEngine']=portable
        if args.gui_smoke:
            # Construct the actual setup screen without mapping a visible window,
            # running the watcher, installing anything, or saving user settings.
            app=App();app.window.withdraw();app.window.update_idletasks()
            data['guiRuntime']={'tcl':app.window.tk.call('info','patchlevel'),'tk':app.window.tk.call('package','require','Tk'),'setupScreen':'constructed'}
            app.window.destroy()
        if args.report:save(args.report,data)
        elif sys.stdout:print(json.dumps(data,indent=2))
        return
    if args.install:
        message=install(args.install)
        if args.report:save(args.report,{'result':message})
        return
    if args.simulate:
        result=native(read_json(args.simulate));save(args.output or 'result.json',result);return
    verify_bundle()
    STATE.mkdir(parents=True,exist_ok=True)
    # Session-local kernel lock; beta cannot start two helpers writing the same addon.
    handle=None
    if os.name=='nt':
        ctypes.windll.kernel32.CreateMutexW.restype=ctypes.c_void_p
        handle=ctypes.windll.kernel32.CreateMutexW(None,False,'Local\\GuildSimBetaHelper')
        if ctypes.windll.kernel32.GetLastError()==183:
            atomic(STATE/'show.request',str(time.time()))
            if args.health_file:save(args.health_file,{'version':VERSION,'ready':True,'alreadyRunning':True})
            return
    try:
        app=App()
        if args.background:app.window.withdraw()
        if args.health_file:save(args.health_file,{'version':VERSION,'ready':True})
        if args.first_run:app.window.after(500,app.auto_setup)
        app.window.mainloop()
    finally:
        if handle:ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        if '--report' in sys.argv:
            try:save(sys.argv[sys.argv.index('--report')+1],{'error':str(exc)})
            except Exception:pass
        elif not any(flag in sys.argv for flag in ('--ret-task','--activate-update','--diagnose','--self-test','--install')) and os.name=='nt':ctypes.windll.user32.MessageBoxW(None,str(exc),'GuildSim Beta',16)
        if sys.stderr:print(str(exc),file=sys.stderr)
        sys.exit(1)
