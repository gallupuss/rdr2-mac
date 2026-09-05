"""Managed storage, audited downloads, and reversible vendor helper replacement."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

RUNTIME_URL = 'https://github.com/mikaelhug/Silo/releases/download/wine-cx-26.3.0/wine.tar.xz'
RUNTIME_SHA256 = '045cc60af1a0de2a40a3406690d48dbcf7010aa8269ad103506b6942a2b15238'
STEAM_URL = 'https://cdn.akamai.steamstatic.com/client/installer/SteamSetup.exe'


def atomic(path, text):
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix='.rdr2-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def digest(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def download(url, destination, expected=None, limit=1024 * 1024 * 1024):
    destination = Path(destination)
    temporary = destination.with_suffix('.download')
    total = 0
    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'RDR2Mac/0.1'})
        with urllib.request.urlopen(request, timeout=60) as response, temporary.open('wb') as stream:
            if not response.url.startswith('https://'):
                raise ValueError('Dependency download redirected away from HTTPS')
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > limit:
                    raise ValueError('Dependency download exceeded its size limit')
                stream.write(chunk)
        if expected and digest(temporary) != expected:
            raise ValueError('Dependency checksum mismatch; retry the download')
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def extract_runtime(archive, destination):
    destination = Path(destination)
    staging = Path(tempfile.mkdtemp(prefix='.runtime-', dir=destination.parent))
    try:
        with tarfile.open(archive) as source:
            members = source.getmembers()
            if sum(m.size for m in members) > 6 * 1024 ** 3 or len(members) > 100000:
                raise ValueError('Runtime archive exceeds extraction limits')
            # Python's data filter rejects outside-tree links, devices and
            # absolute/traversing names. Validate all members before extraction.
            for member in members:
                tarfile.data_filter(member, str(staging))
            source.extractall(staging, filter='data')
        roots = [staging] + [x for x in staging.iterdir() if x.is_dir()]
        roots = [x for x in roots if (x / 'bin/wine64').is_file() and (x / 'bin/wineserver').is_file()]
        if len(roots) != 1:
            raise ValueError('Downloaded Wine runtime has an unsupported layout')
        os.rename(roots[0], destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def make_overlay(runtime, gptk, destination):
    runtime, gptk, destination = map(Path, (runtime, gptk, destination))
    external = gptk / 'lib/external'
    required = ['d3d10', 'd3d11', 'd3d12', 'dxgi', 'nvapi64', 'nvngx-on-metalfx']
    for name in required:
        if not (gptk / f'lib/wine/x86_64-windows/{name}.dll').is_file():
            raise ValueError('GPTK is missing its Windows graphics libraries; select the extracted evaluation environment root')
    if not (external / 'libd3dshared.dylib').is_file() or not (external / 'D3DMetal.framework').is_dir():
        raise ValueError('GPTK is missing lib/external graphics components')
    staging = Path(tempfile.mkdtemp(prefix='.overlay-', dir=destination.parent))
    try:
        # Runtime contains no account/game data. A real copy keeps relative
        # runtime loader paths valid and never mutates the neutral source.
        shutil.copytree(runtime, staging, dirs_exist_ok=True, symlinks=True)
        for parent in ('lib', 'lib/wine', 'lib/wine/x86_64-windows', 'lib/wine/x86_64-unix'):
            if not (staging / parent).resolve().is_relative_to(staging.resolve()):
                raise ValueError('The runtime has graphics directory links outside its root; select a self-contained neutral runtime')
        target_external = staging / 'lib/external'
        if target_external.is_symlink():
            target_external.unlink()
        elif target_external.exists():
            shutil.rmtree(target_external)
        shutil.copytree(external, target_external, symlinks=True)
        for name in required:
            windows = staging / f'lib/wine/x86_64-windows/{name}.dll'
            windows.unlink(missing_ok=True)
            shutil.copy2(gptk / f'lib/wine/x86_64-windows/{name}.dll', windows)
            unix = staging / f'lib/wine/x86_64-unix/{name}.so'
            unix.unlink(missing_ok=True)
            unix.symlink_to('../../external/libd3dshared.dylib')
        alias = staging / 'lib/wine/x86_64-windows/nvngx.dll'
        alias.unlink(missing_ok=True)
        shutil.copy2(gptk / 'lib/wine/x86_64-windows/nvngx-on-metalfx.dll', alias)
        alias = staging / 'lib/wine/x86_64-unix/nvngx.so'
        alias.unlink(missing_ok=True)
        alias.symlink_to('../../external/libd3dshared.dylib')
        framework = staging / 'lib/wine/x86_64-unix/D3DMetal.framework'
        if framework.is_symlink():
            framework.unlink()
        elif framework.exists():
            shutil.rmtree(framework)
        framework.symlink_to('../../external/D3DMetal.framework')
        old = destination.with_name('.previous-overlay')
        if old.exists():
            shutil.rmtree(old)
        if destination.exists():
            destination.rename(old)
        try:
            staging.rename(destination)
        except BaseException:
            if old.exists():
                old.rename(destination)
            raise
        if old.exists():
            shutil.rmtree(old)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def is_vendor_pe(path):
    # Packaged shims carry this marker. Unknown RDR2Mac shims must never be
    # preserved as delegates (recursive delegation would wedge Steam).
    with open(path, 'rb') as stream:
        data = stream.read(32 * 1024 * 1024)
    return data.startswith(b'MZ') and b'RDR2MAC_HELPER_SHIM' not in data and (b'Valve' in data or b'Rockstar' in data or b'V\x00a\x00l\x00v\x00e' in data or b'R\x00o\x00c\x00k\x00s\x00t\x00a\x00r' in data)


def patch_helper(target, shim):
    target, shim = Path(target), Path(shim)
    delegate = target.with_name(target.stem + '_real.exe')
    if not shim.is_file():
        raise ValueError('Packaged compatibility helper is missing; reinstall RDR2Mac')
    if not target.is_file():
        raise ValueError('Vendor helper is not installed yet; finish vendor setup before Repair')
    expected = digest(shim)
    if digest(target) == expected:
        if not delegate.is_file() or not is_vendor_pe(delegate):
            raise ValueError('Compatibility helper has no valid vendor delegate; let the vendor repair its installation first')
        return
    if not is_vendor_pe(target):
        raise ValueError('Unknown helper update or shim; restore the vendor helper using its installer before Repair')
    # Keep current vendor version, including after automatic vendor updates.
    temp_delegate = delegate.with_suffix('.new')
    shutil.copy2(target, temp_delegate)
    os.replace(temp_delegate, delegate)
    temp_shim = target.with_suffix('.new')
    shutil.copy2(shim, temp_shim)
    os.replace(temp_shim, target)


def clone_game(source, destination):
    source, destination = Path(source).resolve(), Path(destination)
    if not (source / 'RDR2.exe').is_file():
        raise ValueError('Selected game source does not contain RDR2.exe')
    if destination.exists():
        if source == destination.resolve():
            return
        raise ValueError('The managed game directory already exists; leave game source empty to keep it, or choose a fresh configuration directory')
    if destination.resolve().is_relative_to(source):
        raise ValueError('The game source cannot contain the managed destination directory')
    for directory, folders, files in os.walk(source):
        for name in folders + files:
            item = Path(directory) / name
            if item.is_symlink() and not item.resolve().is_relative_to(source):
                raise ValueError('The game source contains links outside its directory; use a self-contained source or download with Steam')
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name('.rdr2-source-clone')
    if temporary.exists():
        shutil.rmtree(temporary)
    try:
        result = subprocess.run(['/bin/cp', '-cR', str(source), str(temporary)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode:
            if temporary.exists():
                shutil.rmtree(temporary)
            size = 0
            for directory, _, files in os.walk(source):
                for name in files:
                    item = Path(directory) / name
                    if not item.is_symlink():
                        size += item.stat().st_size
            if shutil.disk_usage(destination.parent).free < size + 5 * 1024 ** 3:
                raise ValueError('Not enough free disk space for an independent game copy; free space or download in managed Steam instead')
            # Dereference source links: vendor writes must never reach the source.
            shutil.copytree(source, temporary, symlinks=False)
        # cp -R preserves symlinks, which could escape back into the source.
        # Reject such payloads rather than letting a vendor write through them.
        for directory, folders, files in os.walk(temporary):
            for name in folders + files:
                item = Path(directory) / name
                if item.is_symlink() and not item.resolve().is_relative_to(temporary.resolve()):
                    raise ValueError('The game source contains links outside its directory; use a self-contained source or download with Steam')
        temporary.rename(destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
