"""Assemble the distributable from public bundle and packaged helper."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import sys
import subprocess
import time
import zipfile
from prepare_bundle import manifest

HERE=Path(__file__).parent
OUTPUTS=Path(os.environ.get('GUILDSIM_OUTPUTS',str(HERE/'dist'))).resolve()
RELEASE=OUTPUTS/'GuildSimBeta-0.2.0-beta.2'

def run():
    RELEASE.mkdir(parents=True,exist_ok=True)
    if not RELEASE.resolve().is_relative_to(OUTPUTS.resolve()):raise ValueError('Release output escaped the intended folder')
    for previous in RELEASE.rglob('*'):
        if previous.is_file():previous.chmod(0o666)
    shutil.copytree(HERE/'bundle',RELEASE,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copytree(HERE/'packaged/GuildSim Helper',RELEASE,dirs_exist_ok=True)
    # Source is shipped for guild maintenance, without build-environment paths.
    source=RELEASE/'source';(source/'engine').mkdir(parents=True,exist_ok=True)
    for name in ('helper.py','lua_data.py','ret_runtime.py','updates.py'):
        shutil.copy2(HERE/name,source/name)
    shutil.copy2(HERE/'engine/main.go',source/'engine/main.go')
    for folder in ('ret','bulk','launcher','setup','trust','signrelease'):
        shutil.copytree(HERE/'engine'/folder,source/'engine'/folder,dirs_exist_ok=True,ignore=shutil.ignore_patterns('payload.zip','update.json','update.json.sig'))
    shutil.copytree(HERE/'pipeline',source/'pipeline',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copy2(HERE/'README.md',RELEASE/'README.md')
    shutil.copy2(HERE/'BUILD.md',source/'BUILD.md')
    for name in ('prepare_bundle.py','release.py'):
        shutil.copy2(HERE/name,source/name)
    gomod=(HERE/'engine/go.mod').read_text()
    gomod=gomod.split('replace github.com/wowsims/forever')[0]+'replace github.com/wowsims/forever => ./upstream\n'
    (source/'engine/go.mod').write_text(gomod,encoding='utf-8')
    shutil.copy2(HERE/'engine/go.sum',source/'engine/go.sum')
    shutil.copy2(HERE/'signing/public-key.txt',source/'RELEASE-PUBLIC-KEY.txt')
    (source/'BUILD.txt').write_text('Source maintenance\n\nThe runnable release does not need these tools.\nUse Python 3.13, PyInstaller 6.22.3, Go 1.27.4, and WoWSims Forever\ncommit a8bd7fd83a3a7c5102012ed87d86a71d175b3a89.\nPlace the unmodified upstream checkout at engine/upstream (or edit\nthe local go.mod replacement), then from engine run:\n  go build -trimpath -buildvcs=false -ldflags="-s -w" -tags=with_db -o guildsim-engine.exe .\nGenerate public defaults using --prepare <upstream> --defaults defaults.json.\nPackage helper.py with PyInstaller --windowed --onedir --name "GuildSim Helper".\nKeep public items.json, suffixes.json, profiles.json, addons and licenses.\nRegenerate manifest.json SHA-256 records for every release file except the\nmanifest itself; change helper VERSION and addon version together.\nDo not copy user caches, SavedVariables or account exports into a release.\n',encoding='utf-8')
    licenses=RELEASE/'licenses'
    for previous in licenses.glob('*.txt'):
        # Module-cache license files can carry Windows' read-only attribute.
        previous.chmod(0o666)
    go_root=Path(os.environ.get('GUILDSIM_GO_ROOT','.missing-go-sdk'))
    mod_root=Path(os.environ.get('GOMODCACHE','engine/upstream'))
    for path,name in [(go_root/'LICENSE','Go-BSD.txt'),(mod_root/'google.golang.org/protobuf@v1.36.12/LICENSE','Protobuf-BSD.txt')]:
        if path.exists():shutil.copy2(path,licenses/name)
    python_root=Path(sys.base_prefix)
    for folder,label in [('tcl8.6','Tcl'),('tk8.6','Tk')]:
        p=python_root/'tcl'/folder/'license.terms'
        if p.exists():shutil.copy2(p,licenses/(label+'.txt'))
    boot=HERE.parent/'guild-build-venv/Lib/site-packages/pyinstaller-6.22.3.dist-info/licenses/COPYING.txt'
    if boot.exists():shutil.copy2(boot,licenses/'PyInstaller.txt')
    (licenses/'NOTICE.txt').write_text('Bundled components\n\nWoWSims Forever v1.0.4 (MIT), commit a8bd7fd83a3a7c5102012ed87d86a71d175b3a89.\nWowSimsExporter v3.2.11 (MIT); embedded libraries retain notices in addon/Libs.\nCPython 3.13.3 (PSF and included third-party licenses).\nTcl/Tk 8.6.15 (notices included in Python.txt and Tk.txt).\nOpenSSL 3.0.16 (Apache 2.0 terms included in Python.txt).\nGo 1.27.4 runtime (BSD). Google Protobuf v1.36.12 (BSD).\nPyInstaller 6.22.3 bootloader (GPL with distribution exception; PyInstaller.txt).\n',encoding='utf-8')
    sums=RELEASE/'SHA256SUMS.txt'
    sums.unlink(missing_ok=True)
    manifest(RELEASE)
    lines=[]
    for path in sorted(RELEASE.rglob('*')):
        if path.is_file():lines.append(hashlib.sha256(path.read_bytes()).hexdigest()+'  '+path.relative_to(RELEASE).as_posix())
    sums.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    # Include the sums themselves in runtime integrity, without circular hashes:
    # SHA256SUMS covers the prior manifest; runtime manifest omits SHA256SUMS.
    # Therefore keep the existing manifest and verify sums separately.
    archive=OUTPUTS/(RELEASE.name+'-Windows-x64.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for path in RELEASE.rglob('*'):
            if path.is_file():z.write(path,RELEASE.name+'/'+path.relative_to(RELEASE).as_posix())
    update={'schemaVersion':1,'channel':'beta','version':'0.2.0-beta.2','sequence':int(time.time()),'minimumLauncher':1,'url':'https://github.com/bryan970/guildsim/releases/download/v0.2.0-beta.2/'+archive.name,'size':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}
    update_path=OUTPUTS/'update.json';update_path.write_text(json.dumps(update,sort_keys=True,separators=(',',':')),encoding='utf-8')
    signature=OUTPUTS/'update.json.sig'
    subprocess.run([str(HERE/'signing/signrelease.exe'),'--key',str(HERE/'signing/release.ed25519'),'--file',str(update_path),'--out',str(signature)],check=True)
    shutil.copy2(archive,HERE/'engine/setup/payload.zip');shutil.copy2(update_path,HERE/'engine/setup/update.json');shutil.copy2(signature,HERE/'engine/setup/update.json.sig')
    print(json.dumps({'zip':str(archive),'bytes':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files':len(lines)+1},indent=2))

if __name__=='__main__':run()
