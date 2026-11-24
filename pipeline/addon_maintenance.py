"""Maintain owned files only; third-party addons are optional, never rewritten."""
from pathlib import Path
from guild_runtime import runtime_root
from atomic_files import write_text

STATIC=['GuildSimBeta.toc','ForeverStats.lua','GearMaticPolicy.lua','WeaponViewer.lua','ItemViewer.lua','Performance.lua','Progress.lua','Bridge.lua']

def inputs(config,root=None):
    root=root or runtime_root();bridge=Path(config['bridge_directory'])
    return tuple((str(p),p.stat().st_mtime_ns if p.exists() else 0) for p in [root/'addon'/n for n in STATIC]+[bridge/n for n in STATIC])

def reconcile(config,root=None,verify=False):
    root=root or runtime_root();bridge=Path(config['bridge_directory']);changed=[]
    for name in STATIC:
        source=root/'addon'/name;dest=bridge/name
        if not source.exists():raise ValueError('Installed release is incomplete: '+name)
        if not dest.exists() or source.read_bytes()!=dest.read_bytes():
            write_text(dest,source.read_text(encoding='utf-8'));changed.append(str(dest))
    return {'ok':True,'restored':changed,'message':'GuildSim integration verified. GearMatic is used when installed.'}
