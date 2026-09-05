"""Bounded WineCX alternate-loader protocol; only RDR2 enters GPTK."""
import array
import os
import select
import socket
import struct
import signal
import time

REQUEST = 0x52C17355
MAX_BUFFER = 1024 * 1024


def exact(conn, count):
    data = bytearray()
    while len(data) < count:
        part = conn.recv(count - len(data))
        if not part:
            raise ValueError('Incomplete alternate-loader request')
        data.extend(part)
    return bytes(data)


def buffer(conn, limit=MAX_BUFFER):
    size = struct.unpack('=Q', exact(conn, 8))[0]
    if size > limit:
        raise ValueError('Alternate-loader request exceeds limit')
    return exact(conn, size)


def close_fds(fds):
    for fd in fds:
        try:
            os.close(fd)
        except OSError:
            pass


def receive_fds(conn):
    fds = array.array('i')
    _, ancillary, flags, _ = conn.recvmsg(1, socket.CMSG_SPACE(16 * fds.itemsize))
    for level, kind, payload in ancillary:
        if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
            fds.frombytes(payload[:len(payload) // fds.itemsize * fds.itemsize])
    if flags & socket.MSG_CTRUNC or len(fds) not in (4, 5):
        close_fds(fds)
        raise ValueError('Invalid alternate-loader descriptor handoff')
    return list(fds)


class Broker:
    def __init__(self, path, loader, prefix, game_env):
        self.path, self.loader, self.prefix = str(path), str(loader), str(prefix)
        self.game_env = game_env
        self.children = set()
        self.started = False
        self.failed = False
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(self.path)
        os.chmod(self.path, 0o600)
        self.server.listen(4)
        self.server.setblocking(False)

    def handle(self, conn):
        conn.settimeout(5)
        if struct.unpack('=I', exact(conn, 4))[0] != REQUEST:
            raise ValueError('Unsupported alternate-loader protocol')
        cwd = buffer(conn, 32768).rstrip(b'\0').decode('utf-8', 'surrogateescape')
        env_raw, args_raw = buffer(conn), buffer(conn)
        fds = receive_fds(conn)
        try:
            args = [x.decode('utf-8', 'surrogateescape') for x in args_raw.split(b'\0') if x]
            if not args or len(args) > 4096 or args[0].replace('\\', '/').rsplit('/', 1)[-1].casefold() != 'rdr2.exe':
                raise ValueError('Only RDR2.exe may use the alternate loader')
            if '-sgadriver=d3d12' not in [x.casefold() for x in args]:
                raise ValueError('RDR2 startup is missing the required D3D12 argument')
            if len(self.children) >= 4:
                raise ValueError('Too many concurrent alternate-loader requests')
            env = {}
            for raw in env_raw.split(b'\0'):
                key, sep, value = raw.decode('utf-8', 'surrogateescape').partition('=')
                if sep and key:
                    env[key] = value
            if os.path.realpath(env.get('WINEPREFIX', '')) != self.prefix:
                raise ValueError('Alternate-loader prefix does not match this session')
            env.pop('CX_ALT_LOADER_SOCKET', None)
            env.update(self.game_env)
            # CPython receives descriptors non-inheritable; Wine must inherit the
            # server socket and optional startup wait pipe across the exec.
            env['WINESERVERSOCKET'] = str(fds[3])
            env.pop('WINE_WAIT_CHILD_PIPE', None)
            if len(fds) == 5:
                env['WINE_WAIT_CHILD_PIPE'] = str(fds[4])
            read_fd, write_fd = os.pipe()
            try:
                pid = os.fork()
            except BaseException:
                close_fds([read_fd, write_fd])
                raise
            if pid == 0:
                try:
                    os.close(read_fd)
                    conn.close()
                    self.server.close()
                    for fd in fds:
                        os.set_inheritable(fd, True)
                    for target, source in enumerate(fds[:3]):
                        os.dup2(source, target)
                    if cwd:
                        os.chdir(cwd)
                    os.execve(self.loader, [self.loader, *args], env)
                except BaseException:
                    os.write(write_fd, b'!')
                os._exit(127)
            os.close(write_fd)
            try:
                if not select.select([read_fd], [], [], 10)[0] or os.read(read_fd, 1):
                    self.failed = True
                    self.children.add(pid)
                    # Acknowledge ownership even on exec failure: Wine must not
                    # silently fall back to the neutral renderer.
                    raise ValueError('GPTK alternate loader could not start')
            finally:
                os.close(read_fd)
            self.children.add(pid)
            self.started = True
            conn.sendall(struct.pack('=I', REQUEST + 1))
        except Exception:
            self.failed = True
            # Claim a received process record even on validation failure so
            # Wine cannot run a rejected RDR2 launch on the neutral renderer.
            try:
                conn.sendall(struct.pack('=I', REQUEST + 1))
            except OSError:
                pass
            raise
        finally:
            close_fds(fds)

    def poll(self):
        if select.select([self.server], [], [], 0)[0]:
            conn, _ = self.server.accept()
            with conn:
                try:
                    self.handle(conn)
                except Exception:
                    self.failed = True
                    raise
        for pid in list(self.children):
            done, status = os.waitpid(pid, os.WNOHANG)
            if done:
                self.children.remove(pid)
                if status:
                    self.failed = True
        return bool(self.children)

    def close(self):
        self.server.close()
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
        alive = set()
        for pid in self.children:
            try:
                done, _ = os.waitpid(pid, os.WNOHANG)
                if not done:
                    os.kill(pid, signal.SIGTERM)
                    alive.add(pid)
            except (ChildProcessError, ProcessLookupError):
                pass
        deadline = time.monotonic() + 3
        while alive and time.monotonic() < deadline:
            for pid in list(alive):
                try:
                    if os.waitpid(pid, os.WNOHANG)[0]:
                        alive.remove(pid)
                except ChildProcessError:
                    alive.remove(pid)
            if alive:
                time.sleep(0.05)
        for pid in alive:
            try:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
            except (ChildProcessError, ProcessLookupError):
                pass
        self.children.clear()
