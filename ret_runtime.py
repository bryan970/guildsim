"""Portable host for the complete existing Ret pipeline, isolated per GUID."""
import copy
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

import helper as h

DATA_FILES=('Weights.lua','TargetWeights.lua','WeaponResults.lua','ItemResults.lua')

def workspace_for(entry,state):
    return state/'ret-characters'/h.digest({'account':entry['account'],'guid':entry['character']['id']})

def bootstrap(entry,settings,base,state):
    work=workspace_for(entry,state);resources=base/'ret-engine'
    work.mkdir(parents=True,exist_ok=True)
    stamp=h.read_json(work/'runtime-version.json',{})
    if stamp.get('version')!=h.VERSION:
        for source in resources.rglob('*'):
            if not source.is_file():continue
            relative=source.relative_to(resources);dest=work/relative
            if relative.as_posix() in ('scenario.json','prebis-targets.json'): # Editable personal assumptions survive releases.
                if dest.exists():continue
            elif relative.parts[0]=='addon' and relative.name in DATA_FILES and dest.exists():continue
            dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest)
        h.save(work/'runtime-version.json',{'version':h.VERSION})
    (work/'output').mkdir(exist_ok=True)
    char=entry['character'];config=h.read_json(work/'config.json',{})
    config.update(saved_variables=entry['path'],bridge_directory=str(Path(settings['root'])/'Interface/AddOns/GuildSimBeta'),character_guid=char['id'],character_name=char['name'],character_race=char['race'],iterations=settings.get('iterations',12500),max_export_age_hours=24,mode='auto',leveling_weights='equipped',mount_trinket_ids=[11122,12846],combat_trinket_cache=str(work/'output/combat-trinkets.json'),item_catalog_mode='all',comparison_backend='wowsims-bulk',smart_concurrency=True,refresh_scope='quick',auto_full_catalog=True,catalog_settle_seconds=120,enable_flb_integration=False,wowsims_updates={'enabled':False})
    if not config.get('catalog_reference_trinkets'):
        refs=copy.deepcopy((char['gear']['items']+[{}]*17)[12:14])
        if any(not it or not it.get('id') or it.get('id') in h.UTILITY for it in refs):raise ValueError('Equip two combat trinkets for the first reference capture. They stay fixed after that.')
        config['catalog_reference_trinkets']=refs;config['catalog_reference_label']='Fixed reference pair'
    config.setdefault('trinket_pool_ids',[19812]);config.setdefault('fight_profiles_enabled',['undead'])
    h.save(work/'config.json',config)
    return work

def publish_profiles(work,entry,base,state,addon):
    root=state/'ret-profile-payloads'/h.digest(str(addon.resolve()));root.mkdir(parents=True,exist_ok=True)
    segments=[]
    for name in DATA_FILES:
        file=work/'addon'/name
        if file.exists():
            content=file.read_text(encoding='utf-8')
            # Empty release templates must not erase a valid standalone payload
            # loaded earlier by the TOC while a character's first job starts.
            if re.search(r'\bns\.(?:payload|targetWeights|weaponResults|itemResults)\s*=\s*nil\s*$',content):continue
            segments.append(content)
    if not segments:return
    guid=entry['character']['id']
    h.atomic(root/(h.digest(guid)+'.lua'),'do local function load(...)\n'+'\n'.join(segments)+'\nend\nif UnitGUID("player")=='+h.lua(guid)+' then load(addonName,namespace) end\nend\n')
    h.atomic(addon/'Profiles.lua','local addonName,namespace=...\n-- Native data selected by character GUID; functions bound Lua 5.1 constant counts.\n'+'\n'.join(path.read_text(encoding='utf-8') for path in sorted(root.glob('*.lua'))))

class RetRunner:
    def __init__(self,base=None,state=None):
        self.base=base or h.BASE;self.state=state or h.STATE;self.stop=threading.Event();self.process=None

    def run(self,entry,settings,notify=lambda x:None,full=False):
        work=bootstrap(entry,settings,self.base,self.state);addon=Path(settings['root'])/'Interface/AddOns/GuildSimBeta'
        (work/'output/pause.request.json').unlink(missing_ok=True)
        prefix=[sys.executable] if getattr(sys,'frozen',False) else [sys.executable,str(Path(h.__file__).resolve())]
        command=prefix+['--ret-task',str(work)]+(['--full-catalog'] if full else [])
        log=work/'output/helper.log'
        with log.open('w',encoding='utf-8') as stream:
            self.process=subprocess.Popen(command,stdout=stream,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            published=0;last='';progress={}
            while self.process.poll() is None:
                try:
                    progress=h.read_json(work/'output/progress.json',progress)
                except (PermissionError,json.JSONDecodeError):
                    # Windows can briefly deny reads during a snapshot replacement.
                    # Progress is observational: keep waiting for our worker and
                    # retain the last display rather than abandoning a live job.
                    pass
                message=progress.get('stage','Native Ret workflow')+' · '+progress.get('detail','Starting')
                if message!=last:notify(message);last=message
                if time.monotonic()-published>30:
                    publish_profiles(work,entry,self.base,self.state,addon);published=time.monotonic()
                if self.stop.is_set():
                    # Interrupt only our character worker; native chunks remain cached.
                    # Child native processes are stopped through a cooperative stop flag.
                    h.save(work/'output/pause.request.json',{'requested':time.time()})
                time.sleep(.5)
            code=self.process.returncode
        publish_profiles(work,entry,self.base,self.state,addon)
        if code:
            raise ValueError(('Paused; completed native batches are cached.' if self.stop.is_set() else 'Ret workflow needs attention. ')+log.read_text(encoding='utf-8',errors='replace')[-1800:])
        notify('Ready: full Ret results and weights saved. Use /reload to load them.')

def execute_task(workspace,full=False):
    os.environ['GUILDSIM_WORKSPACE']=str(Path(workspace).resolve())
    pipeline=Path(h.BASE)/'pipeline'
    if not pipeline.exists():pipeline=Path(h.__file__).parent/'pipeline'
    sys.path.insert(0,str(pipeline))
    from guild_task import execute
    return execute(workspace,full)

def migrate_personal(source,entry,settings,base=None,state=None):
    """Copy user-owned settings and caches locally. Never package or erase them."""
    base=base or h.BASE;state=state or h.STATE;source=Path(source).resolve()
    config=h.read_json(source/'config.json')
    if not config or not (source/'output').is_dir():raise ValueError('Select the existing Ret helper folder containing config.json and output.')
    if config.get('character_name') and config['character_name'].casefold()!=entry['character']['name'].casefold():raise ValueError('Selected personal helper belongs to a different character.')
    work=bootstrap(entry,settings,base,state)
    for name in ('scenario.json','prebis-targets.json'):
        if (source/name).is_file():shutil.copy2(source/name,work/name)
    for name in ('combat-trinkets.json','trinket-pool.json'):
        if (source/'output'/name).exists():shutil.copy2(source/'output'/name,work/'output'/name)
    library=source/'output/fight-library.sqlite'
    if library.exists():
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(library.as_uri()+'?mode=ro',uri=True)) as old_db,closing(sqlite3.connect(work/'output/fight-library.sqlite')) as new_db:
            old_db.backup(new_db)
    wanted=('catalog_reference_trinkets','catalog_reference_label','trinket_pool_ids','fight_profiles_enabled','fight_profiles','item_priority_zone_ids','combat_trinket_fallback')
    target=h.read_json(work/'config.json');target.update({key:config[key] for key in wanted if key in config});h.save(work/'config.json',target)
    old_sv=Path(entry['path']).with_name('RetSimBridge.lua')
    if old_sv.exists():
        old=h.loads(old_sv.read_text(encoding='utf-8-sig')).get('RetSimBridgeDB',{})
        dest=old_sv.with_name('GuildSimBeta.lua')
        if dest.exists():shutil.copy2(dest,work/'output/GuildSimBeta-before-migration.lua')
        new=h.loads(dest.read_text(encoding='utf-8-sig')).get('GuildSimBetaDB',{}) if dest.exists() else {}
        # Newer guild requests take priority; retain the old capture/pool/plan state.
        merged={**old,**new};h.atomic(dest,'GuildSimBetaDB = '+h.lua(merged)+'\n')
    h.save(work/'migration.json',{'source':str(source),'copied':time.time(),'character':entry['character']['id'],'legacyUntouched':True})
    return work

def finish_migration(source,root,state=None):
    """Switch only after new results passed, WoW closed and legacy workers finished."""
    state=state or h.STATE;source=Path(source).resolve();root=h.game_root(root)
    if h.game_running():return False,'Migration ready; close WoW to finish switching automatically.'
    progress=h.read_json(source/'output/progress.json',{})
    pidfile=source/'output/watch.pid'
    if pidfile.exists():
        pid=int(pidfile.read_text().strip())
        script=f'$p=Get-CimInstance Win32_Process -Filter "ProcessId={pid}"; $c=@(Get-CimInstance Win32_Process -Filter "ParentProcessId={pid}"); @{{process=$p;children=$c}} | ConvertTo-Json -Depth 3 -Compress'
        info=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],capture_output=True,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),check=True)
        observation=json.loads(info.stdout);process=observation.get('process')
        if process:
            if str(source/'run.py').casefold() not in process.get('CommandLine','').casefold():raise ValueError('Legacy PID does not match the selected helper; no process was stopped.')
            if progress.get('state')!='ready' or observation.get('children'):return False,'Waiting for the existing helper to finish its current work; it has not been interrupted.'
            subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',f'Stop-Process -Id {pid} -ErrorAction Stop'],check=True,capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    old=root/'Interface/AddOns/RetSimBridge'
    backup=root/'GuildSimBetaBackups'/('Personal-RetSimBridge-'+str(int(time.time())))
    if old.exists():
        if old.is_symlink() or (hasattr(old,'is_junction') and old.is_junction()):raise ValueError('Linked legacy addon folder needs a manual handoff.')
        if old.resolve().parent!=(root/'Interface/AddOns').resolve() or not backup.resolve().is_relative_to((root/'GuildSimBetaBackups').resolve()):raise ValueError('Legacy migration path escaped the selected game folder.')
        backup.parent.mkdir(exist_ok=True);old.rename(backup)
    h.save(state/'personal-migration.json',{'source':str(source),'addonBackup':str(backup),'completed':time.time(),'savedVariablesPreserved':True})
    return True,'Migration complete. GuildSim now owns the Ret workflow. Original helper files and saved variables are preserved for rollback.'
