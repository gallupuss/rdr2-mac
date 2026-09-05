#!/usr/bin/env python3
"""RDR2Mac managed WineCX/Steam supervisor. Stdout is JSON Lines only."""
from __future__ import annotations
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid

from broker import Broker
from storage import atomic, clone_game, digest, download, extract_runtime, make_overlay, patch_helper, RUNTIME_URL, RUNTIME_SHA256, STEAM_URL
import vdf

DEFAULTS = {'runtime_path': '', 'gptk_path': '', 'game_path': '', 'display_mode': 'auto', 'setup_complete': False}
COMMANDS = ('status', 'configure', 'install', 'repair', 'steam', 'play', 'stop', 'diagnostics')


def emit(kind, message, state='idle', **extra):
    print(json.dumps({'type': kind, 'message': message, 'state': state, **extra}), flush=True)


class Engine:
    def __init__(self, config):
        self.path = Path(config).expanduser().absolute()
        if self.path.is_symlink():
            raise ValueError('Configuration cannot be a symbolic link')
        self.root = self.path.parent.resolve()
        self.path = self.root / self.path.name
        self.prefix = self.root / 'Bottle'
        self.overlay = self.root / 'RuntimeOverlay'
        self.steam_dir = self.prefix / 'drive_c/Program Files (x86)/Steam'
        self.steam_exe = self.steam_dir / 'steam.exe'
        self.resources = Path(__file__).resolve().parent.parent
        self.helpers = self.resources / 'helpers'
        self.config = dict(DEFAULTS)
        if self.path.exists():
            data = json.loads(self.path.read_text())
            self.validate(data, loaded=True)
            self.config.update(data)
        self.cancelled = False
        self.session = None
        self.log = None
        self.broker = None
        self.env = None
        self.children = []

    @staticmethod
    def validate(data, loaded=False):
        if not isinstance(data, dict) or set(data) - set(DEFAULTS):
            raise ValueError('Configuration contains unknown fields')
        if not loaded and 'setup_complete' in data:
            raise ValueError('setup_complete is managed by the engine')
        for key, value in data.items():
            if key == 'setup_complete':
                if type(value) is not bool:
                    raise ValueError('setup_complete must be boolean')
            elif not isinstance(value, str) or '\0' in value or '\n' in value or '\r' in value:
                raise ValueError('Configuration values must be plain strings')
            elif key == 'display_mode' and value not in ('auto', '1080p', '900p'):
                raise ValueError('Choose Automatic, 1080p or 900p')
            elif key.endswith('_path') and value and not Path(value).expanduser().is_absolute():
                raise ValueError('Directory selections must be absolute paths')

    def secure_root(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name in ('Bottle', 'RuntimeOverlay', 'Runtime', 'Logs', 'Downloads', 'session.json', 'stop.json', 'operation.lock', '.managed-bottle', '.needs-cleanup'):
            if (self.root / name).is_symlink():
                raise ValueError('Managed storage contains an unsafe symbolic link')
        if self.prefix.exists() and not (self.root / '.managed-bottle').is_file():
            raise ValueError('Refusing to adopt an existing bottle; choose a new configuration directory')
        for managed in (self.steam_dir, self.prefix / 'drive_c/windows/system32', self.prefix / 'drive_c/users', self.prefix / 'drive_c/Program Files/Rockstar Games'):
            if not managed.resolve().is_relative_to(self.prefix.resolve()):
                raise ValueError('Managed application directories must not link outside this app’s bottle')

    @contextlib.contextmanager
    def lock(self, allow_dirty=False):
        self.secure_root()
        fd = os.open(self.root / 'operation.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('Another managed operation is active; stop it before changing setup') from None
            if not allow_dirty and (self.root / '.needs-cleanup').exists():
                raise ValueError('Previous managed shutdown was not confirmed; use Stop to finish cleanup before continuing')
            yield
        finally:
            os.close(fd)

    def active(self):
        path = self.root / 'operation.lock'
        if not path.exists() or path.is_symlink():
            return False
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return False
            except BlockingIOError:
                return True
        finally:
            os.close(fd)

    def save(self):
        atomic(self.path, json.dumps(self.config, indent=2) + '\n')

    @property
    def runtime(self):
        return Path(self.config['runtime_path']).expanduser().resolve() if self.config['runtime_path'] else self.root / 'Runtime'

    @property
    def gptk(self):
        return Path(self.config['gptk_path']).expanduser().resolve() if self.config['gptk_path'] else None

    def checks(self):
        runtime = self.runtime
        values = [
            ('Apple Silicon macOS', sys.platform == 'darwin' and platform.machine() == 'arm64', 'Apple Silicon Mac required'),
            ('WineCX runtime', (runtime / 'bin/wine64').is_file() and (runtime / 'bin/wineserver').is_file(), 'Install downloads the verified free WineCX runtime when no directory is selected'),
            ('GPTK graphics', bool(self.gptk and (self.gptk / 'lib/external/libd3dshared.dylib').is_file()), 'Select the extracted Apple game porting toolkit evaluation environment'),
            ('Managed Steam', self.steam_exe.is_file(), 'Run Install, finish the Steam installer and sign in inside Windows Steam'),
            ('Setup', self.config['setup_complete'], 'Finish Install and vendor prerequisite dialogs'),
            ('Game payload', self.game() is not None, 'Use Open Steam and install app 1174180 into its default managed library'),
            ('Managed shutdown', not (self.root / '.needs-cleanup').exists(), 'Use Stop to finish an interrupted managed cleanup'),
        ]
        try:
            targets = self.helper_targets()
            ok = bool(targets) and any(t.name == 'SocialClubHelper.exe' for t in targets)
            for target in targets:
                shim = self.helpers / target.name
                delegate = target.with_name(target.stem + '_real.exe')
                ok = ok and shim.is_file() and delegate.is_file() and digest(target) == digest(shim)
        except (OSError, ValueError):
            ok = False
        values.append(('Compatibility helpers', ok, 'After Steam and Rockstar finish installing/updating, Stop then Repair'))
        return [{'name': n, 'ok': bool(ok), 'detail': detail} for n, ok, detail in values]

    def status(self, message='Setup status'):
        checks = self.checks()
        ready = all(c['ok'] for c in checks)
        state = 'idle' if ready else 'needs_setup'
        if self.active():
            try:
                stored = json.loads((self.root / 'session.json').read_text())
                state = stored.get('state', 'installing')
            except (OSError, ValueError):
                state = 'installing'
        elif (self.root / '.needs-cleanup').exists():
            state = 'stopping'
            message = 'A previous managed session needs cleanup. Use Stop before continuing.'
        emit('status', message, state, config=self.config, checks=checks, ready=ready)

    def configure(self, data):
        self.validate(data)
        with self.lock():
            for key in ('runtime_path', 'gptk_path', 'game_path'):
                if key in data and data[key]:
                    data[key] = str(Path(data[key]).expanduser().resolve())
                    if not Path(data[key]).is_dir():
                        raise ValueError('A selected directory does not exist')
            if any(data.get(k, self.config[k]) != self.config[k] for k in ('runtime_path', 'gptk_path', 'game_path')):
                self.config['setup_complete'] = False
            self.config.update(data)
            self.save()
        self.status('Configuration saved')

    def state(self, state, message):
        if self.session:
            atomic(self.root / 'session.json', json.dumps({'token': self.session, 'state': state}))
        emit('progress', message, state)

    def interrupted(self):
        if self.cancelled:
            return True
        try:
            return json.loads((self.root / 'stop.json').read_text()).get('token') == self.session
        except (OSError, ValueError, AttributeError):
            return False

    def wait(self, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self.interrupted():
                raise InterruptedError('Managed operation stopped')
            time.sleep(min(0.2, max(0, deadline - time.monotonic())))

    def environment(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith(('WINE', 'CX_', 'DYLD_', 'D3DM_', 'DXMT_'))}
        env.update(WINEPREFIX=str(self.prefix), WINEARCH='win64', WINESERVER=str(self.runtime / 'bin/wineserver'), WINELOADER=str(self.runtime / 'bin/wine64'), WINEDLLPATH=str(self.runtime / 'lib/wine'), DYLD_FALLBACK_LIBRARY_PATH=f'{self.runtime}/lib/silo-bundled:/usr/lib', PATH=f'{self.runtime}/bin:/usr/bin:/bin:/usr/sbin:/sbin', WINEMSYNC='1', ROSETTA_ADVERTISE_AVX='1', WINEDEBUG='-all', WINEDLLOVERRIDES='bcrypt=b;ncrypt=b;gameoverlayrenderer,gameoverlayrenderer64=d', WINE_D3D_CONFIG='renderer=gl')
        return env

    def start(self, args, cwd=None):
        atomic(self.root / '.needs-cleanup', 'Managed Wine may be active\n')
        proc = subprocess.Popen([str(a) for a in args], env=self.env, cwd=cwd or self.root, stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log)
        self.children.append(proc)
        return proc

    def run(self, args, timeout=180, allowed=(0,)):
        proc = self.start(args)
        deadline = time.monotonic() + timeout
        while proc.poll() is None:
            if time.monotonic() > deadline:
                raise ValueError('A vendor process did not finish in time; stop and retry its setup')
            self.wait(0.2)
        if proc.returncode not in allowed:
            raise ValueError('A Wine or vendor installer operation failed; check selected dependencies and retry setup')
        return proc.returncode

    def wine(self, *args, **kwargs):
        return self.run([self.runtime / 'bin/wine64', *args], **kwargs)
    def capture_wine(self, *args):
        atomic(self.root / '.needs-cleanup', 'Managed Wine may be active\n')
        with tempfile.TemporaryFile() as output:
            proc = subprocess.Popen([str(self.runtime / 'bin/wine64'), *map(str, args)], env=self.env, stdin=subprocess.DEVNULL, stdout=output, stderr=self.log)
            self.children.append(proc)
            deadline = time.monotonic() + 30
            while proc.poll() is None:
                if time.monotonic() > deadline:
                    raise ValueError('Managed Wine state query timed out')
                self.wait(0.2)
            output.seek(0)
            text = output.read(65536).decode('utf-8', 'replace')
        if proc.returncode:
            raise ValueError('Managed Wine state query failed')
        return text

    def isolate_user_folders(self):
        users = self.prefix / 'drive_c/users'
        if users.is_dir():
            for user in users.iterdir():
                if user.is_symlink():
                    user.unlink()
                    user.mkdir()
                if user.is_dir():
                    for folder in user.iterdir():
                        if folder.is_symlink() and not folder.resolve().is_relative_to(self.prefix.resolve()):
                            folder.unlink()
                            folder.mkdir()
        for key in (r'HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders', r'HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders'):
            for name, folder in (('Personal', 'Documents'), ('Desktop', 'Desktop'), ('My Pictures', 'Pictures'), ('My Music', 'Music'), ('My Video', 'Videos')):
                self.reg(key, name, 'REG_EXPAND_SZ', rf'%USERPROFILE%\{folder}')

    def reg(self, key, name, kind, value):
        self.wine('reg.exe', 'add', key, '/v', name, '/t', kind, '/d', str(value), '/f')

    def cleanup(self):
        if self.env is None:
            return
        self.state('stopping', 'Closing managed Steam and this bottle’s Wine processes')
        if self.steam_exe.exists():
            try:
                proc = self.start([self.runtime / 'bin/wine64', self.steam_exe, '-shutdown'])
                proc.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                pass
        stopped = False
        for flag, timeout in [('-k', 15), ('-w', 20)]:
            try:
                result = subprocess.run([str(self.runtime / 'bin/wineserver'), flag], env=self.env, stdout=self.log, stderr=self.log, timeout=timeout)
                if flag == '-w':
                    stopped = result.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                pass
        if self.broker:
            self.broker.close()
            self.broker = None
        for child in self.children:
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                # Only processes spawned by this supervisor, never global Wine.
                child.terminate()
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
        self.children.clear()
        self.env = None
        if not stopped:
            atomic(self.root / '.needs-cleanup', 'Managed wineserver exit not confirmed\n')
            raise ValueError('Managed Wine shutdown was not confirmed. Use Stop again; other operations are blocked until cleanup completes')
        (self.root / '.needs-cleanup').unlink(missing_ok=True)

    @contextlib.contextmanager
    def operation(self):
        with self.lock():
            self.session = uuid.uuid4().hex
            (self.root / 'stop.json').unlink(missing_ok=True)
            (self.root / 'Logs').mkdir(exist_ok=True, mode=0o700)
            # Vendor output stays local and private. Never include it in the
            # allowlisted diagnostics export or emit it on the JSON stream.
            log_fd = os.open(self.root / 'Logs' / f'session-{self.session}.log', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            self.log = os.fdopen(log_fd, 'wb')
            previous = {sig: signal.signal(sig, lambda *_: setattr(self, 'cancelled', True)) for sig in (signal.SIGINT, signal.SIGTERM)}
            try:
                yield
            finally:
                try:
                    self.cleanup()
                finally:
                    self.log.close()
                    (self.root / 'session.json').unlink(missing_ok=True)
                    (self.root / 'stop.json').unlink(missing_ok=True)
                    self.session = None
                    for sig, handler in previous.items():
                        signal.signal(sig, handler)

    def prepare_runtime(self):
        if sys.platform != 'darwin' or platform.machine() != 'arm64':
            raise ValueError('Installation requires an Apple Silicon Mac')
        downloads = self.root / 'Downloads'
        downloads.mkdir(exist_ok=True, mode=0o700)
        if not self.config['runtime_path'] and not self.runtime.exists():
            self.state('installing', 'Downloading checksum-verified free WineCX runtime')
            archive = downloads / 'wine.tar.xz'
            if not archive.exists() or digest(archive) != RUNTIME_SHA256:
                download(RUNTIME_URL, archive, RUNTIME_SHA256)
            extract_runtime(archive, self.runtime)
        if not (self.runtime / 'bin/wine64').is_file() or not (self.runtime / 'bin/wineserver').is_file():
            raise ValueError('Selected WineCX runtime is incomplete')
        if self.runtime == self.overlay or self.root.is_relative_to(self.runtime):
            raise ValueError('Choose a neutral runtime directory separate from this app’s managed storage root and graphics overlay')
        if self.gptk is None:
            raise ValueError('Download Apple’s game porting toolkit evaluation environment, extract it, and select its root directory')
        self.state('installing', 'Building a private GPTK graphics overlay without changing the neutral runtime')
        make_overlay(self.runtime, self.gptk, self.overlay)
        # The picker may point to Apple's mounted disk image. All graphics
        # components now live in our durable overlay; never depend on the
        # original mount after import, including on later reinstalls.
        self.config['gptk_path'] = str(self.overlay)
        self.save()
        self.env = self.environment()

    def install(self):
        with self.operation():
            self.config['setup_complete'] = False
            self.save()
            self.prepare_runtime()
            if not self.prefix.exists():
                self.prefix.mkdir(mode=0o700)
                atomic(self.root / '.managed-bottle', 'RDR2Mac managed prefix\n')
            self.state('installing', 'Initializing a new Windows 10 64-bit Wine bottle; macOS may request Rosetta installation')
            self.wine('wineboot.exe', '--init', timeout=300)
            self.isolate_user_folders()
            self.reg(r'HKCU\Software\Wine', 'Version', 'REG_SZ', 'win10')
            self.reg(r'HKCU\Software\CrossOver\UseAltLoader', 'RDR2', 'REG_DWORD', 0)
            self.reg(r'HKCU\Software\Wine\Direct3D', 'renderer', 'REG_SZ', 'gl')
            for source, target in (('nvapi64.dll', 'nvapi64.dll'), ('nvngx-on-metalfx.dll', 'nvngx.dll')):
                destination = self.prefix / 'drive_c/windows/system32' / target
                destination.unlink(missing_ok=True)
                shutil.copy2(self.gptk / 'lib/wine/x86_64-windows' / source, destination)
            for arch in ('x86', 'x64'):
                installer = self.root / f'Downloads/vc_redist.{arch}.exe'
                self.state('installing', f'Downloading Microsoft Visual C++ {arch} runtime; accept its license in the vendor dialog')
                download(f'https://aka.ms/vc14/vc_redist.{arch}.exe', installer, limit=128 * 1024 ** 2)
                self.wine(installer, '/install', '/norestart', timeout=900, allowed=(0, 194, 102))
                # 3010 (restart required) and 1638 (newer version) wrap to
                # 8-bit exit statuses on Unix. Require vendor-installed state
                # rather than treating either wrapped code as proof of setup.
                installed = self.capture_wine('reg.exe', 'query', rf'HKLM\Software\Microsoft\VisualStudio\14.0\VC\Runtimes\{arch}', '/v', 'Installed', '/reg:32' if arch == 'x86' else '/reg:64')
                if not re.search(r'Installed\s+REG_DWORD\s+0x1\b', installed):
                    raise ValueError('Microsoft Visual C++ setup did not register a completed installation')
            if not self.steam_exe.is_file():
                installer = self.root / 'Downloads/SteamSetup.exe'
                self.state('installing', 'Downloading the official Windows Steam installer')
                download(STEAM_URL, installer, limit=64 * 1024 ** 2)
                self.state('waiting_for_login', 'Complete Steam Setup in its window using the default location; close Setup when finished')
                self.wine(installer, timeout=1800)
                if not self.steam_exe.is_file():
                    raise ValueError('Steam Setup did not install to the managed default location; rerun Install and keep the default destination')
            # Stop vendor processes before replacing helpers or cloning payload.
            self.cleanup()
            if self.config['game_path']:
                self.state('installing', 'Importing an independent game copy; the selected source will remain untouched')
                clone_game(self.config['game_path'], self.steam_dir / 'steamapps/common/Red Dead Redemption 2')
            targets = self.helper_targets()
            for target in targets:
                patch_helper(target, self.helpers / target.name)
            self.config['setup_complete'] = True
            self.save()
        self.status('Bottle and prerequisites installed. Open Steam to sign in and Install Red Dead Redemption 2. After first-time Rockstar setup, Stop and Repair.')

    def helper_targets(self):
        targets = []
        cef = self.steam_dir / 'bin/cef'
        if cef.exists():
            for folder in cef.iterdir():
                target = folder / 'steamwebhelper.exe'
                if folder.name in ('cef.win64', 'cef.win7x64') and target.is_file():
                    targets.append(target)
        social = self.prefix / 'drive_c/Program Files/Rockstar Games/Social Club/SocialClubHelper.exe'
        if social.is_file():
            targets.append(social)
        if any(not target.resolve().is_relative_to(self.prefix.resolve()) for target in targets):
            raise ValueError('Vendor helpers must be installed inside this app’s managed bottle, not linked from another installation')
        return targets

    def repair(self):
        with self.operation():
            if not self.steam_exe.is_file():
                raise ValueError('Install managed Steam before Repair')
            targets = self.helper_targets()
            if not any(t.name == 'steamwebhelper.exe' for t in targets):
                raise ValueError('Steam helper layout is unsupported or its update is incomplete; Open Steam to finish updating, then Stop and Repair')
            for target in targets:
                patch_helper(target, self.helpers / target.name)
            if not any(t.name == 'SocialClubHelper.exe' for t in targets):
                raise ValueError('Steam helpers repaired. In Steam, run RDR2 once to complete Rockstar setup; then Stop and Repair again')
        self.status('Current vendor helpers preserved and compatibility helpers installed')

    def libraries(self):
        # Only managed libraries are eligible. Never follow an external Steam
        # library into the original installation, even if a user edited VDF.
        roots = [self.steam_dir]
        config = self.steam_dir / 'steamapps/libraryfolders.vdf'
        if config.is_file():
            root = vdf.get(vdf.parse(config.read_text(encoding='utf-8')), 'libraryfolders')
            if root and isinstance(root.value, list):
                for item in root.value:
                    if not isinstance(item.value, list):
                        continue
                    entry = vdf.get(item.value, 'path')
                    if entry and isinstance(entry.value, str):
                        path = self.windows_path(entry.value)
                        if path and path.is_relative_to(self.prefix.resolve()) and path not in roots:
                            roots.append(path)
        return roots

    def windows_path(self, text):
        if re.match(r'^[Cc]:[\\/]', text):
            return (self.prefix / 'drive_c' / text[3:].replace('\\', '/')).resolve()
        if text.startswith('/'):
            return Path(text).resolve()
        return None

    def game(self):
        try:
            for library in self.libraries():
                manifest = library / 'steamapps/appmanifest_1174180.acf'
                if not manifest.is_file():
                    continue
                root = vdf.get(vdf.parse(manifest.read_text(encoding='utf-8')), 'AppState')
                if not root or not isinstance(root.value, list):
                    continue
                appid, installed, flags = [vdf.get(root.value, k) for k in ('appid', 'installdir', 'StateFlags')]
                if not appid or appid.value != '1174180' or not installed or not isinstance(installed.value, str) or not flags or flags.value != '4':
                    continue
                path = (library / 'steamapps/common' / installed.value).resolve()
                if path.is_relative_to(self.prefix.resolve()) and (path / 'RDR2.exe').is_file():
                    return path
        except (OSError, ValueError):
            pass
        return None

    def edit_launch_options(self, dimensions):
        found = 0
        userdata = self.steam_dir / 'userdata'
        if userdata.exists():
            for account in userdata.iterdir():
                if not account.name.isdecimal() or account.is_symlink():
                    continue
                path = account / 'config/localconfig.vdf'
                if not path.is_file() or not path.resolve().is_relative_to(self.prefix.resolve()):
                    continue
                original = path.read_text(encoding='utf-8')
                updated = vdf.launch_options(original, dimensions)
                if updated is not None:
                    if updated != original:
                        atomic(path, updated)
                    found += 1
        return found

    def display(self):
        mode = self.config['display_mode']
        if mode != 'auto':
            return ((1920, 1080) if mode == '1080p' else (1440, 900)), 'n'
        script = 'ObjC.import("AppKit");ObjC.import("CoreGraphics");const d=$.CGMainDisplayID();const m=$.CGDisplayCopyDisplayMode(d);console.log([Number($.CGDisplayModeGetPixelWidth(m)),Number($.CGDisplayModeGetPixelHeight(m)),Number($.NSScreen.mainScreen.backingScaleFactor)].join(" "));$.CGDisplayModeRelease(m);'
        result = subprocess.run(['/usr/bin/osascript', '-l', 'JavaScript', '-e', script], capture_output=True, text=True, timeout=20)
        try:
            width, height, scale = map(float, (result.stdout + result.stderr).strip().split())
            if result.returncode or not 320 <= width <= 16384 or not 200 <= height <= 16384 or scale not in (1, 2):
                raise ValueError()
        except ValueError:
            raise ValueError('Could not read the main display; choose 1080p or 900p and retry') from None
        return (int(width), int(height)), 'y' if scale == 2 else 'n'

    def open_session(self, play):
        with self.operation():
            if not self.config['setup_complete'] or not self.steam_exe.is_file():
                raise ValueError('Complete Install before opening Steam')
            if not (self.overlay / 'bin/wine64').is_file() or not self.gptk:
                raise ValueError('Runtime overlay is missing; rerun Install')
            if play and self.game() is None:
                raise ValueError('The managed game is not fully installed. Open Steam, choose Install for RDR2, and wait for verification/download to finish')
            if play and not next(c['ok'] for c in self.checks() if c['name'] == 'Compatibility helpers'):
                raise ValueError('Compatibility helpers need Repair after vendor setup or updates; Stop Steam and run Repair before Play')
            self.env = self.environment()
            dimensions, retina = self.display()
            self.reg(r'HKCU\Software\Wine\Mac Driver', 'RetinaMode', 'REG_SZ', retina)
            self.reg(r'HKCU\Software\CrossOver\UseAltLoader', 'RDR2', 'REG_DWORD', 0)
            self.run([self.runtime / 'bin/wineserver', '-w'])
            # VDF changes happen with Steam stopped; command-line arguments also
            # supply early D3D12 on a first login without a localconfig entry.
            self.edit_launch_options(dimensions)
            private = Path(tempfile.gettempdir()) / ('rdr2mac-' + str(os.getuid()) + '-' + hashlib.sha256(str(self.path).encode()).hexdigest()[:16])
            if private.is_symlink():
                raise ValueError('Unsafe private broker directory')
            private.mkdir(mode=0o700, exist_ok=True)
            if private.stat().st_uid != os.getuid() or private.stat().st_mode & 0o077:
                raise ValueError('Private broker directory has unsafe ownership or permissions')
            endpoint = private / 'broker.sock'
            endpoint.unlink(missing_ok=True)
            game_env = {'WINEDLLPATH': str(self.overlay / 'lib/wine'), 'DYLD_FALLBACK_FRAMEWORK_PATH': str(self.gptk / 'lib/external'), 'DYLD_FALLBACK_LIBRARY_PATH': f'{self.gptk}/lib/external:{self.overlay}/lib/silo-bundled:/usr/lib', 'CX_APPLEGPTK_LIBD3DSHARED_PATH': str(self.gptk / 'lib/external/libd3dshared.dylib'), 'WINEDLLOVERRIDES': 'd3d9,d3d10,d3d10_1,d3d10core,d3d11,d3d12,d3d12core,dxgi,nvapi64,nvngx=b', 'WINED3DMETAL': '1', 'CX_GRAPHICS_BACKEND': 'd3dmetal', 'D3DM_ENABLE_METALFX': '0', 'DXMT_ENABLE_NVEXT': '1'}
            self.broker = Broker(endpoint, self.overlay / 'bin/wine64', self.prefix.resolve(), game_env)
            self.env['CX_ALT_LOADER_SOCKET'] = str(endpoint)
            connection = self.steam_dir / 'logs/connection_log.txt'
            offset = connection.stat().st_size if connection.exists() else 0
            self.run([self.runtime / 'bin/wineserver', '-p300'])
            server_wait = self.start([self.runtime / 'bin/wineserver', '-w'])
            self.start([self.runtime / 'bin/wine64', 'start.exe', '/exec', 'explorer', f'/desktop=RDR2,{dimensions[0]}x{dimensions[1]}', r'C:\Program Files (x86)\Steam\steam.exe'], cwd=self.steam_dir)
            self.state('waiting_for_login', 'Sign in inside Windows Steam. Install RDR2 there; keep all credentials in the vendor window')
            logged_in = False
            launched = False
            confirmed = False
            deadline = time.monotonic() + 900
            log_tail = ''
            process_check = 0.0
            unacknowledged = 0
            while True:
                self.wait(0.4)
                if server_wait.poll() is not None:
                    if confirmed or not play:
                        break
                    raise ValueError('Managed Wine exited before RDR2 started; check setup and try Repair after vendor updates')
                running = self.broker.poll()
                if self.broker.failed:
                    raise ValueError('The GPTK game handoff failed; verify GPTK and runtime selections, then Repair')
                if time.monotonic() >= process_check:
                    processes = self.capture_wine('tasklist.exe', '/fo', 'csv').casefold()
                    process_check = time.monotonic() + 2
                    if 'rdr2.exe' in processes and not self.broker.started:
                        unacknowledged += 1
                        if unacknowledged >= 2:
                            raise ValueError('RDR2 bypassed the GPTK handoff; the managed session is being stopped. Run Repair and retry')
                    else:
                        unacknowledged = 0
                if not logged_in and connection.exists():
                    size = connection.stat().st_size
                    if size < offset:
                        offset = 0
                    with connection.open('rb') as stream:
                        stream.seek(offset)
                        data = stream.read(1024 * 1024)
                        offset = stream.tell()
                    log_tail = (log_tail + data.decode('utf-8', 'replace'))[-8192:]
                    logged_in = 'RecvMsgClientLogOnResponse() : processing complete' in log_tail
                    if logged_in and not play:
                        self.state('waiting_for_login', 'Steam is signed in. Install RDR2 and complete Rockstar’s first-time setup; Stop then Repair after vendor updates')
                if play and logged_in and not launched:
                    self.state('launching', 'Launching owned Steam app 1174180; complete Rockstar sign-in and prerequisite dialogs if shown')
                    self.start([self.runtime / 'bin/wine64', self.steam_exe, '-applaunch', '1174180', '-sgadriver=d3d12', '-width', str(dimensions[0]), '-height', str(dimensions[1])])
                    launched = True
                    deadline = time.monotonic() + 900
                if self.broker.started and running and not confirmed:
                    confirmed = True
                    self.state('running', 'RDR2 is running through the GPTK alternate loader')
                if confirmed and not running:
                    break
                if play and not confirmed and time.monotonic() > deadline:
                    raise ValueError('Steam login or RDR2 startup timed out. Finish vendor setup, Stop, then Repair and retry')
        self.status('Managed session ended')

    def stop(self):
        if not self.active():
            if (self.root / '.needs-cleanup').exists():
                with self.lock(allow_dirty=True):
                    with open(os.devnull, 'wb') as self.log:
                        self.env = self.environment()
                        self.cleanup()
                emit('result', 'Managed cleanup completed', 'idle')
                return
            emit('result', 'No managed session is active', 'idle')
            return
        try:
            session = json.loads((self.root / 'session.json').read_text())
            token = session['token']
        except (OSError, ValueError, KeyError):
            raise ValueError('The managed operation is still initializing; retry Stop shortly') from None
        atomic(self.root / 'stop.json', json.dumps({'token': token}))
        emit('progress', 'Requesting orderly managed-session shutdown', 'stopping')
        deadline = time.monotonic() + 90
        while self.active():
            if time.monotonic() > deadline:
                raise ValueError('Managed operation has not stopped yet; keep the app open and retry Stop')
            time.sleep(0.2)
        if (self.root / '.needs-cleanup').exists():
            raise ValueError('Managed Wine shutdown was not confirmed; use Stop again to finish cleanup')
        emit('result', 'Managed session stopped', 'idle')

    def diagnostics(self, output):
        if not output:
            raise ValueError('Choose a diagnostics destination')
        checks = self.checks()
        report = {'application': 'RDR2Mac', 'format_version': 1, 'python_version': platform.python_version(), 'macos_version': platform.mac_ver()[0], 'architecture': platform.machine(), 'display_mode': self.config['display_mode'], 'setup_complete': self.config['setup_complete'], 'checks': [{'name': c['name'], 'ok': c['ok']} for c in checks], 'privacy': 'No credentials, account IDs, user paths, process command lines, or vendor logs collected', 'verification': 'Clean second-machine game launch has not been verified'}
        destination = Path(output).expanduser().absolute()
        if destination.is_symlink() or not destination.parent.is_dir():
            raise ValueError('Choose a regular diagnostics file in an existing folder')
        atomic(destination, json.dumps(report, indent=2) + '\n')
        emit('result', 'Privacy-safe diagnostics exported', 'idle', path=str(destination))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=COMMANDS)
    parser.add_argument('--config', default=str(Path.home() / 'Library/Application Support/RDR2Mac/config.json'))
    parser.add_argument('--json')
    parser.add_argument('--output')
    args = parser.parse_args()
    try:
        if args.json is not None and args.command != 'configure':
            raise ValueError('--json is only accepted by configure')
        if args.output is not None and args.command != 'diagnostics':
            raise ValueError('--output is only accepted by diagnostics')
        engine = Engine(args.config)
        if args.command == 'configure':
            engine.configure(json.loads(args.json or '{}'))
        elif args.command == 'diagnostics':
            engine.diagnostics(args.output)
        elif args.command in ('steam', 'play'):
            engine.open_session(args.command == 'play')
        else:
            getattr(engine, args.command)()
        return 0
    except InterruptedError:
        emit('result', 'Managed operation stopped', 'idle')
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        # Never interpolate OSError, subprocess command lines, or vendor output:
        # they may carry private paths/account data. Our ValueErrors are static.
        message = str(exc) if type(exc) is ValueError and not isinstance(exc, json.JSONDecodeError) else 'The operation could not complete. Check dependency selections, permissions and network access, then retry.'
        if 'engine' in locals() and (engine.root / 'Logs').is_dir():
            message += ' Local details are in this app’s managed Logs folder; these logs may contain account information and are not included in diagnostics.'
        emit('error', message, 'error', category=type(exc).__name__)
        return 1


if __name__ == '__main__':
    sys.exit(main())
