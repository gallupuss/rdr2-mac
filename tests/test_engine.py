"""Isolated regression tests: never invoke Wine, Steam, or installed game files."""
import array
import contextlib
import io
import json
import os
from pathlib import Path
import socket
import struct
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from broker import Broker, REQUEST, buffer, receive_fds
from launcher import Engine
from storage import extract_runtime, patch_helper, clone_game
import vdf


class VDFTests(unittest.TestCase):
    def test_only_target_app_changes_and_comments_survive(self):
        source = '''// header
"UserLocalConfigStore" { "Software" { "Valve" { "Steam" { "apps" {
"42" { "LaunchOptions" "-width 7 -other" }
"1174180" { "LaunchOptions" "-width 800 -height=600 -foo \\\"quoted\\\"" }
} } } } } // end
'''
        updated = vdf.launch_options(source, (1920, 1080))
        root = vdf.parse(updated)
        apps = vdf.at(root, 'UserLocalConfigStore', 'Software', 'Valve', 'Steam', 'apps').value
        self.assertEqual(vdf.at(apps, '42', 'LaunchOptions').value, '-width 7 -other')
        self.assertEqual(vdf.at(apps, '1174180', 'LaunchOptions').value, '-foo "quoted" -sgadriver=d3d12 -width 1920 -height 1080')
        self.assertTrue(updated.startswith('// header\n'))
        self.assertTrue(updated.endswith('// end\n'))

    def test_inserts_missing_options_without_touching_other_apps(self):
        source = '"UserLocalConfigStore" { "Software" { "Valve" { "Steam" { "apps" { "1174180" { "name" "RDR2" } "2" { "LaunchOptions" "{" } } } } } }'
        updated = vdf.launch_options(source)
        root = vdf.parse(updated)
        apps = vdf.at(root, 'UserLocalConfigStore', 'Software', 'Valve', 'Steam', 'apps').value
        self.assertEqual(vdf.at(apps, '1174180', 'LaunchOptions').value, '-sgadriver=d3d12')
        self.assertEqual(vdf.at(apps, '2', 'LaunchOptions').value, '{')

    def test_ambiguous_app_is_rejected(self):
        source = '"UserLocalConfigStore" { "Software" { "Valve" { "Steam" { "apps" { "1174180" {} "1174180" {} } } } } }'
        with self.assertRaises(ValueError):
            vdf.launch_options(source)


class StorageTests(unittest.TestCase):
    def test_vendor_update_becomes_new_delegate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vendor, shim = root / 'steamwebhelper.exe', root / 'packaged.exe'
            shim.write_bytes(b'MZ RDR2MAC_HELPER_SHIM fixture')
            vendor.write_bytes(b'MZ Valve old fixture')
            patch_helper(vendor, shim)
            vendor.write_bytes(b'MZ Valve new fixture')
            patch_helper(vendor, shim)
            self.assertEqual(vendor.read_bytes(), shim.read_bytes())
            self.assertEqual((root / 'steamwebhelper_real.exe').read_bytes(), b'MZ Valve new fixture')

    def test_unknown_shim_and_missing_delegate_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, shim = root / 'SocialClubHelper.exe', root / 'packaged.exe'
            shim.write_bytes(b'MZ RDR2MAC_HELPER_SHIM current')
            target.write_bytes(b'MZ Rockstar RDR2MAC_HELPER_SHIM old')
            with self.assertRaises(ValueError):
                patch_helper(target, shim)
            target.write_bytes(shim.read_bytes())
            with self.assertRaises(ValueError):
                patch_helper(target, shim)
            self.assertFalse((root / 'SocialClubHelper_real.exe').exists())

    def test_archive_escape_is_rejected_without_writing_outside(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / 'runtime.tar'
            with tarfile.open(archive, 'w') as stream:
                member = tarfile.TarInfo('../escaped')
                member.size = 4
                stream.addfile(member, io.BytesIO(b'evil'))
            with self.assertRaises((ValueError, tarfile.TarError)):
                extract_runtime(archive, root / 'Runtime')
            self.assertFalse((root / 'escaped').exists())
            self.assertFalse((root / 'Runtime').exists())

    def test_import_does_not_expose_source_to_vendor_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, destination = root / 'source', root / 'managed'
            source.mkdir()
            (source / 'RDR2.exe').write_bytes(b'fixture')
            clone_game(source, destination)
            (destination / 'RDR2.exe').write_bytes(b'vendor update')
            self.assertEqual((source / 'RDR2.exe').read_bytes(), b'fixture')
            self.assertFalse(destination.is_symlink())


class OwnershipTests(unittest.TestCase):
    def test_status_does_not_create_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'absent'
            with contextlib.redirect_stdout(io.StringIO()) as output:
                Engine(root / 'config.json').status()
            self.assertFalse(root.exists())
            self.assertFalse(json.loads(output.getvalue())['ready'])

    def test_unowned_or_linked_bottle_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'Bottle').mkdir()
            engine = Engine(root / 'config.json')
            with self.assertRaises(ValueError):
                with engine.lock():
                    pass
            (root / 'Bottle').rmdir()
            outside = root / 'outside'
            outside.mkdir()
            (root / 'Bottle').symlink_to(outside)
            (root / '.managed-bottle').write_text('marker')
            with self.assertRaises(ValueError):
                with engine.lock():
                    pass

    def test_account_fields_and_forged_setup_are_rejected(self):
        for data in ({'password': 'secret'}, {'setup_complete': True}, {'display_mode': 'tv'}, {'runtime_path': 'relative'}):
            with self.assertRaises(ValueError):
                Engine.validate(data)

    def test_unconfirmed_cleanup_blocks_mutations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.needs-cleanup').write_text('pending')
            engine = Engine(root / 'config.json')
            with self.assertRaises(ValueError):
                with engine.lock():
                    pass
            with engine.lock(allow_dirty=True):
                self.assertTrue(engine.active())

    def test_diagnostics_do_not_include_config_paths_or_accounts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine = Engine(root / 'private-account/config.json')
            destination = root / 'report.json'
            with contextlib.redirect_stdout(io.StringIO()):
                engine.diagnostics(destination)
            report = destination.read_text()
            self.assertNotIn(directory, report)
            self.assertNotIn('private-account', report)
            self.assertNotIn('runtime_path', report)


class BrokerTests(unittest.TestCase):
    def test_size_limit_is_checked_before_payload_read(self):
        left, right = socket.socketpair()
        with left, right:
            left.sendall(struct.pack('=Q', 1024 * 1024 + 1))
            with self.assertRaises(ValueError):
                buffer(right)

    def test_descriptor_count_rejected(self):
        left, right = socket.socketpair()
        fd = os.open(os.devnull, os.O_RDONLY)
        try:
            with left, right:
                left.sendmsg([b'x'], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', [fd]))])
                with self.assertRaises(ValueError):
                    receive_fds(right)
        finally:
            os.close(fd)

    def test_non_game_handoff_is_claimed_without_exec(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            broker = Broker(root / 'broker.sock', '/nonexistent', root, {})
            left, right = socket.socketpair()
            fds = [os.open(os.devnull, os.O_RDWR) for _ in range(4)]
            try:
                with left, right:
                    left.sendall(struct.pack('=I', REQUEST))
                    for data in (b'', f'WINEPREFIX={root}\0'.encode(), b'not-rdr2.exe\0'):
                        left.sendall(struct.pack('=Q', len(data)) + data)
                    left.sendmsg([b'x'], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', fds))])
                    with patch('os.fork', side_effect=AssertionError('must not fork')):
                        with self.assertRaises(ValueError):
                            broker.handle(right)
                    self.assertEqual(left.recv(4), struct.pack('=I', REQUEST + 1))
                    self.assertFalse(broker.started)
            finally:
                for fd in fds:
                    os.close(fd)
                broker.close()

    def test_server_descriptor_survives_loader_exec(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / 'RDR2.exe').write_text('import os\\nos.write(int(os.environ["WINESERVERSOCKET"]), b"handoff")\\n'.replace('\\n', '\n'))
            # The fixture loader is Python, not Wine: don't let its startup
            # generate bytecode inside a sealed app when testing bundled Python.
            broker = Broker(root / 'broker.sock', sys.executable, root, {'PYTHONDONTWRITEBYTECODE': '1'})
            client, receiver = socket.socketpair()
            server_read, server_write = socket.socketpair()
            server_read.settimeout(5)
            nulls = [os.open(os.devnull, os.O_RDWR) for _ in range(3)]
            try:
                with client, receiver, server_read, server_write:
                    client.sendall(struct.pack('=I', REQUEST))
                    for data in (os.fsencode(root) + b'\0', f'WINEPREFIX={root}\0'.encode(), b'RDR2.exe\0-sgadriver=d3d12\0'):
                        client.sendall(struct.pack('=Q', len(data)) + data)
                    client.sendmsg([b'x'], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', [*nulls, server_write.fileno()]))])
                    broker.handle(receiver)
                    self.assertEqual(client.recv(4), struct.pack('=I', REQUEST + 1))
                    self.assertEqual(server_read.recv(32), b'handoff')
            finally:
                for fd in nulls:
                    os.close(fd)
                broker.close()


if __name__ == '__main__':
    unittest.main()
