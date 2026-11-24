"""Signed, resumable-free release updates. User data never travels with releases."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
import uuid

import helper as h

MAX_DOWNLOAD=256*1024*1024
MAX_EXPANDED=512*1024*1024
RESERVED={'con','prn','aux','nul'}|{'com'+str(i) for i in range(1,10)}|{'lpt'+str(i) for i in range(1,10)}
VERSION=re.compile(r'^\d+\.\d+\.\d+(?:-[a-zA-Z0-9.]+)?$')

class HTTPSOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        if not newurl.startswith('https://'):raise ValueError('Update redirected outside HTTPS')
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def fetch(url,limit):
    if not url.startswith('https://'):raise ValueError('Release updates require HTTPS')
    request=urllib.request.Request(url,headers={'User-Agent':'GuildSim/'+h.VERSION})
    with urllib.request.build_opener(HTTPSOnly()).open(request,timeout=30) as response:
        length=response.headers.get('Content-Length')
        if length and int(length)>limit:raise ValueError('Release download exceeds its limit')
        data=response.read(limit+1)
        if len(data)>limit:raise ValueError('Release download exceeds its limit')
        return data

def verify_signature(raw,signature,base):
    launcher=base/'GuildSim Launcher.exe'
    if not launcher.is_file():raise ValueError('Trusted release verifier is missing')
    with tempfile.TemporaryDirectory(prefix='guildsim-signature-') as tmp:
        manifest=Path(tmp)/'update.json';sig=Path(tmp)/'update.sig'
        manifest.write_bytes(raw);sig.write_bytes(signature)
        result=subprocess.run([str(launcher),'--verify-manifest',str(manifest),'--signature',str(sig)],capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:raise ValueError('Release signature did not verify; current version preserved')

def metadata(raw,signature,base,state):
    verify_signature(raw,signature,base)
    data=json.loads(raw)
    if data.get('schemaVersion')!=1 or data.get('channel')!='beta':raise ValueError('Unsupported update channel or schema')
    if not VERSION.fullmatch(str(data.get('version',''))):raise ValueError('Invalid release version')
    if not isinstance(data.get('sequence'),int) or data['sequence']<=0:raise ValueError('Invalid release sequence')
    if data['sequence']<h.read_json(state/'update-state.json',{}).get('highestSequence',0):raise ValueError('Older release metadata rejected')
    if not re.fullmatch('[0-9a-f]{64}',str(data.get('sha256',''))):raise ValueError('Invalid release checksum')
    if not isinstance(data.get('size'),int) or not 0<data['size']<=MAX_DOWNLOAD:raise ValueError('Invalid release download size')
    if not data.get('url','').startswith('https://github.com/bryan970/guildsim/releases/download/'):raise ValueError('Release URL is outside the configured guild repository')
    if data.get('minimumLauncher',1)>1:raise ValueError('This release needs a newer installer')
    return data

def safe_members(archive):
    seen=set();size=0;members=archive.infolist()
    if len(members)>10000:raise ValueError('Too many release files')
    for entry in members:
        name=entry.filename;path=PurePosixPath(name)
        if not name or chr(92) in getattr(entry,'orig_filename',name) or path.is_absolute() or path.as_posix()!=name.rstrip('/') or any(part in ('..','.') or ':' in part or part.endswith((' ','.')) or part.split('.')[0].lower() in RESERVED for part in path.parts):raise ValueError('Unsafe release path')
        key=name.rstrip('/').casefold()
        if key in seen:raise ValueError('Duplicate release path')
        seen.add(key)
        mode=entry.external_attr>>16
        if stat.S_ISLNK(mode) or entry.flag_bits&1:raise ValueError('Linked or encrypted release file rejected')
        size+=entry.file_size
        if size>MAX_EXPANDED:raise ValueError('Expanded release exceeds its limit')
    return members

def verify_directory(base,version):
    manifest=h.read_json(base/'manifest.json')
    if not manifest or manifest.get('version')!=version:raise ValueError('Release version mismatch')
    for name,sha in manifest.get('files',{}).items():
        path=(base/name).resolve()
        if not path.is_relative_to(base.resolve()) or not path.is_file() or h.file_hash(path)!=sha:raise ValueError('Release file failed checksum: '+name)
    for required in ('GuildSim Helper.exe','GuildSim Launcher.exe','guildsim-engine.exe','addons/GuildSimBeta/GuildSimBeta.toc','ret-engine/retlocal.exe','ret-engine/retbulk.exe'):
        if required not in manifest.get('files',{}):raise ValueError('Incomplete release: '+required)
    return manifest

def stage(data,raw,signature,base,state,transport=fetch,healthcheck=True):
    """Download into an owned temporary folder; commit only complete tested versions."""
    import zipfile
    data=metadata(raw,signature,base,state)
    content=transport(data['url'],data['size'])
    if len(content)!=data['size'] or hashlib.sha256(content).hexdigest()!=data['sha256']:raise ValueError('Release archive checksum/size mismatch')
    releases=state/'releases';releases.mkdir(parents=True,exist_ok=True)
    target=releases/data['version']
    with tempfile.TemporaryDirectory(prefix='.staging-',dir=releases) as temp:
        temp=Path(temp);archive=temp/'release.zip';archive.write_bytes(content)
        extracted=temp/'files';extracted.mkdir()
        with zipfile.ZipFile(archive) as z:
            members=safe_members(z);prefix='GuildSimBeta-'+data['version']+'/'
            if any(not row.filename.startswith(prefix) for row in members):raise ValueError('Unexpected release root')
            for row in members:
                if row.is_dir():continue
                relative=row.filename[len(prefix):]
                if not relative:continue
                dest=extracted/relative;dest.parent.mkdir(parents=True,exist_ok=True)
                with z.open(row) as source,dest.open('wb') as output:shutil.copyfileobj(source,output)
        verify_directory(extracted,data['version'])
        if healthcheck:
            report=temp/'health.json'
            result=subprocess.run([str(extracted/'GuildSim Helper.exe'),'--self-test','--gui-smoke','--report',str(report)],capture_output=True,timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            health=h.read_json(report,{})
            if result.returncode or health.get('integrity')!='passed' or 'guiRuntime' not in health:raise ValueError('Downloaded helper failed startup checks; current version preserved')
        if target.exists():
            verify_directory(target,data['version'])
        else:extracted.rename(target)
    h.save(state/'pending-update.json',{'version':data['version'],'sequence':data['sequence'],'created':time.time()})
    return target

def check(base=None,state=None,transport=fetch):
    base=base or h.BASE;state=state or h.STATE
    channel=h.read_json(base/'update-channel.json',{})
    if not channel.get('enabled'):return None
    url=channel['manifestUrl']
    try:raw=transport(url,256*1024);signature=transport(url+'.sig',1024)
    except urllib.error.HTTPError as error:
        if error.code==404:return None # First publication may still be pending.
        raise
    data=metadata(raw,signature,base,state)
    if data['version']==h.read_json(state/'active.json',{}).get('failedVersion'):return None
    if data['version']==h.VERSION:return None
    return stage(data,raw,signature,base,state,transport)

def launch_activation(target,root,parent_pid):
    command=[str(target/'GuildSim Helper.exe'),'--activate-update',str(target),'--parent-pid',str(parent_pid)]
    if root:command+=['--game-root',str(root)]
    subprocess.Popen(command,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),cwd=target)

def process_alive(pid):
    if os.name!='nt':
        try:os.kill(pid,0);return True
        except ProcessLookupError:return False
    import ctypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.OpenProcess.restype=ctypes.c_void_p
    handle=kernel.OpenProcess(0x100000,False,pid)
    if not handle:return False
    try:
        kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
        return kernel.WaitForSingleObject(handle,0)==258
    finally:
        kernel.CloseHandle.argtypes=[ctypes.c_void_p];kernel.CloseHandle(handle)

def activate(target,parent_pid,root,state=None):
    state=state or h.STATE;target=Path(target).resolve()
    if target.parent!=(state/'releases').resolve():raise ValueError('Update is outside the installed release directory')
    verify_directory(target,target.name)
    for _ in range(240):
        if not process_alive(parent_pid):break
        time.sleep(.25)
    else:raise ValueError('Current helper is still running; update deferred')
    if h.game_running():raise ValueError('WoW started before update installation; update deferred')
    active=h.read_json(state/'active.json',{})
    if root:
        installed=h.install(root,target,details=True)
        h.save(state/'update-rollback.json',{'targetVersion':target.name,'root':str(h.game_root(root)),'addonBackup':installed['backup']})
    pending=h.read_json(state/'pending-update.json',{})
    h.save(state/'active.json',{'version':target.name,'previous':active.get('version',h.VERSION),'sequence':pending.get('sequence',0)})
    previous=h.read_json(state/'update-state.json',{})
    h.save(state/'update-state.json',{'highestSequence':max(previous.get('highestSequence',0),pending.get('sequence',0)),'installedVersion':target.name,'installedAt':time.time()})
    (state/'pending-update.json').unlink(missing_ok=True)
    launcher=state/'GuildSim Launcher.exe'
    if not launcher.exists() or h.file_hash(launcher)!=h.file_hash(target/'GuildSim Launcher.exe'):
        try:
            temp=state/'GuildSim Launcher.pending.exe';shutil.copy2(target/'GuildSim Launcher.exe',temp);os.replace(temp,launcher)
        except PermissionError:
            # A shortcut may briefly have the launcher open. Queue its replacement.
            shutil.copy2(target/'GuildSim Launcher.exe',state/'GuildSim Launcher.next.exe')
    subprocess.Popen([str(launcher),'--background'],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),cwd=state)

def restore_after_rollback(base,state,root):
    root=h.game_root(root);active=h.read_json(state/'active.json',{});record=h.read_json(state/'update-rollback.json',{})
    if not active.get('failedVersion') or record.get('targetVersion')!=active['failedVersion']:return False
    recovered=h.read_json(state/'rollback-recovered.json',{})
    if recovered.get('failedVersion')==active['failedVersion']:return False
    if h.game_running():raise ValueError('Close WoW to finish addon recovery')
    h.install(root,base)
    if record.get('addonBackup'):
        backup=Path(record['addonBackup']).resolve()
        if not backup.is_relative_to((root/'GuildSimBetaBackups').resolve()) or not (backup/'.guildsim-owned').is_file():raise ValueError('Invalid addon recovery backup')
        for name in ('Results.lua','GuildResults.json','Profiles.lua','Weights.lua','TargetWeights.lua','ItemResults.lua','WeaponResults.lua'):
            source=backup/name
            if source.exists():
                dest=root/'Interface/AddOns/GuildSimBeta'/name
                temp=dest.with_name(dest.name+'.recovery');shutil.copy2(source,temp);os.replace(temp,dest)
    h.save(state/'rollback-recovered.json',{'failedVersion':active['failedVersion'],'restoredVersion':h.VERSION,'time':time.time()})
    return True

def finish_launcher_update(state):
    pending=state/'GuildSim Launcher.next.exe'
    if pending.exists():
        try:os.replace(pending,state/'GuildSim Launcher.exe')
        except PermissionError:pass

def startup(enabled,state=None):
    if os.name!='nt':return
    import winreg
    state=state or h.STATE
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
        if enabled:winreg.SetValueEx(key,'GuildSimBeta',0,winreg.REG_SZ,'"'+str(state/'GuildSim Launcher.exe')+'" --background')
        else:
            try:winreg.DeleteValue(key,'GuildSimBeta')
            except FileNotFoundError:pass
