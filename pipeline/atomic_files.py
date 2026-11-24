from guild_runtime import runtime_root, usable_faction
"""Atomic text publication with bounded retries for short Windows reader locks."""
import os
from pathlib import Path
import tempfile
import time


def write_text(path, text):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',newline='\n',
            prefix='.'+path.name+'.',suffix='.tmp',dir=path.parent,delete=False) as stream:
            temporary=Path(stream.name)
            stream.write(text)
        for attempt in range(8):
            try:
                os.replace(temporary,path)
                return
            except PermissionError:
                if attempt==7:raise
                time.sleep(min(.01*2**attempt,.1))
    finally:
        if temporary is not None:
            try:temporary.unlink(missing_ok=True)
            except OSError:pass
