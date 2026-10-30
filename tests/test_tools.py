import importlib.util
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from factorytest_crypt import xor_transform
from prepare_bilibili_ssl import patch_elf, prepare


def elf_fixture():
    """ELF32 ARM, two program headers, dynamic names and unrelated text."""
    raw = bytearray(512)
    raw[:7] = b'\x7fELF\x01\x01\x01'
    struct.pack_into('<H', raw, 18, 40)
    struct.pack_into('<I', raw, 28, 52)
    struct.pack_into('<HH', raw, 42, 32, 2)
    struct.pack_into('<8I', raw, 52, 1, 0, 0x1000, 0, 512, 512, 5, 4096)
    struct.pack_into('<8I', raw, 84, 2, 128, 0x1080, 0, 40, 40, 4, 4)
    names = b'\0libcrypto.so\0libssl.so\0'
    raw[256:256 + len(names)] = names
    for index, pair in enumerate([(5, 0x1100), (10, len(names)), (1, 1), (14, 14), (0, 0)]):
        struct.pack_into('<II', raw, 128 + index * 8, *pair)
    raw[400:412] = b'libcrypto.so'
    return bytes(raw)


class ToolTests(unittest.TestCase):
    def test_published_config_roundtrip_and_xml(self):
        plain = (ROOT / 'configs/factorytest_config_plain.xml').read_bytes()
        cipher = (ROOT / 'configs/factorytest_config.xml').read_bytes()
        self.assertEqual(xor_transform(cipher), plain)
        node = ET.fromstring(plain)
        self.assertIn(') & am start', node.find('.//setOrderPoint').text)
        self.assertNotIn(b'adb_enabled 1', plain)

    def test_invalid_xml_does_not_overwrite_output(self):
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder) / 'bad.xml', Path(folder) / 'out'
            source.write_text('<x>a & b</x>')
            output.write_bytes(b'keep')
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/factorytest_crypt.py'), str(source), str(output)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(output.read_bytes(), b'keep')

    def test_empty_xor_key(self):
        with self.assertRaises(ValueError):
            xor_transform(b'a', b'')

    def test_only_dynamic_names_change(self):
        raw = elf_fixture()
        patched = patch_elf(raw)
        self.assertEqual(len(raw), len(patched))
        self.assertEqual(patched[400:412], b'libcrypto.so')
        self.assertEqual(patched[257:269], b'libbili_o.so')
        self.assertEqual(patched[270:279], b'libbsl.so')
        self.assertEqual(patch_elf(patched), patched)

    def test_bad_elf_rejected(self):
        for data in (b'not ELF', elf_fixture()[:100]):
            with self.assertRaises(ValueError):
                patch_elf(data)

    def test_prepare_preserves_input_and_refuses_reuse(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'original'
            source.mkdir()
            for name in ('libcrypto.so', 'libssl.so', 'libignet.so'):
                (source / name).write_bytes(elf_fixture())
            output = root / 'patched'
            prepare(source, output)
            self.assertTrue((output / 'libbili_o.so').is_file())
            self.assertTrue((output / 'original.sha256').is_file())
            self.assertNotIn(b'\r', (output / 'original.sha256').read_bytes())
            self.assertEqual((source / 'libignet.so').read_bytes(), elf_fixture())
            with self.assertRaises(ValueError):
                prepare(source, output)

    @unittest.skipUnless(importlib.util.find_spec('cryptography'), 'cryptography unavailable')
    def test_signing_identity_reused(self):
        from cryptography.hazmat.primitives.serialization.pkcs7 import load_der_pkcs7_certificates
        from cryptography.hazmat.primitives.serialization import Encoding
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            key = folder / 'signing.pem'
            certificates = []
            for index in range(2):
                output = folder / f'{index}.apk'
                command = [sys.executable, str(ROOT / 'scripts/build_autostart_apk.py'), '--key', str(key), '--output', str(output)]
                if index == 0:
                    command.append('--init-key')
                subprocess.run(command, check=True, capture_output=True)
                with zipfile.ZipFile(output) as archive:
                    certificates.append(load_der_pkcs7_certificates(archive.read('META-INF/CERT.RSA'))[0].public_bytes(Encoding.DER))
            self.assertEqual(*certificates)

    def test_debloat_tmc_retained_by_default(self):
        debloat_txt = (ROOT / 'scripts/debloat-packages.txt').read_text(encoding='utf-8')
        active_pkgs = [line.strip() for line in debloat_txt.splitlines() if line.strip() and not line.strip().startswith('#')]
        self.assertNotIn('com.tatv.android.TMC', active_pkgs, "TMC must remain commented/retained by default to protect Home key navigation")

    def test_key_threshold_consistency_across_code_and_docs(self):
        toggle_sh = (ROOT / 'scripts/key_remap/toggle.sh').read_text(encoding='utf-8')
        adc_sh = (ROOT / 'scripts/key_remap/adc_toggle.sh').read_text(encoding='utf-8')
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        skill = (ROOT / 'skills/skyworth-c10h-modding/SKILL.md').read_text(encoding='utf-8')
        remap_readme = (ROOT / 'scripts/key_remap/README.md').read_text(encoding='utf-8')

        self.assertIn('POWER_HOLD_SEC=0.35', toggle_sh)
        self.assertIn('F9_HOLD_SEC=0.35', toggle_sh)
        self.assertIn('F10_HOLD_SEC=0.35', adc_sh)

        for doc_name, text in [('README.md', readme), ('SKILL.md', skill), ('key_remap/README.md', remap_readme)]:
            self.assertNotIn('<0.6s', text, f"Found obsolete <0.6s in {doc_name}")
            self.assertNotIn('>=0.6s', text, f"Found obsolete >=0.6s in {doc_name}")
            self.assertIn('0.35', text, f"Missing 0.35s threshold description in {doc_name}")

    def test_fix_launcher_script_exists_and_references_dangbei(self):
        fix_sh = (ROOT / 'scripts/fix_launcher.sh').read_text(encoding='utf-8')
        self.assertIn('com.dangbei.tvlauncher', fix_sh)
        self.assertIn('epg.launcher.packagename', fix_sh)

    def test_debloat_wal_architecture_and_tmc_hard_guard(self):
        debloat_sh = (ROOT / 'scripts/debloat.sh').read_text(encoding='utf-8')
        self.assertIn('STATUS:IN_PROGRESS', debloat_sh, "debloat.sh must write STATUS:IN_PROGRESS at transaction start")
        self.assertIn('STATUS:COMPLETED', debloat_sh, "debloat.sh must write STATUS:COMPLETED at transaction end")
        self.assertIn('sync', debloat_sh, "debloat.sh must sync WAL entries to disk")
        self.assertIn('com.tatv.android.TMC is permanently protected', debloat_sh, "debloat.sh must hard-block disabling TMC")
        self.assertIn('disabledComponents:', debloat_sh)
        self.assertIn('Retaining WAL entry for recovery', debloat_sh, "debloat.sh must retain WAL entry if pm disable fails")

    def test_restore_precision_guard_and_legacy_flag(self):
        restore_sh = (ROOT / 'scripts/restore_bloatware.sh').read_text(encoding='utf-8')
        self.assertIn('STATUS:IN_PROGRESS', restore_sh, "restore_bloatware.sh must handle incomplete WAL transactions")
        self.assertIn('--legacy-restore', restore_sh, "restore_bloatware.sh must require explicit flag when snapshot missing")
        self.assertIn('Refusing to blindly enable all packages', restore_sh)
        self.assertIn('FAILED_COUNT', restore_sh, "restore_bloatware.sh must check pm enable exit status")
        self.assertIn('pm default-state', restore_sh, "restore_bloatware.sh should restore default-state for fidelity")

    def test_enable_keys_verifies_root_uid(self):
        cmd_content = (ROOT / 'scripts/key_remap/enable_keys.cmd').read_text(encoding='utf-8')
        self.assertIn('id -u | findstr /x 0', cmd_content, "enable_keys.cmd must verify root UID is 0 via findstr /x 0")

    def test_wal_recovery_logic_simulation(self):
        """Simulate WAL state parsing for both normal and interrupted transactions."""
        def parse_and_simulate_restore(snapshot_content: str, fail_on_pkg: str = None):
            lines = [line.strip() for line in snapshot_content.splitlines() if line.strip()]
            is_in_progress = any(l == 'STATUS:IN_PROGRESS' for l in lines) and not any(l == 'STATUS:COMPLETED' for l in lines)
            enabled_pkgs = []
            enabled_services = []
            failed_count = 0

            for line in lines:
                if line.startswith('PKG:'):
                    pkg = line[4:]
                    if pkg == fail_on_pkg:
                        failed_count += 1
                    else:
                        enabled_pkgs.append(pkg)
                elif line.startswith('SERVICE:'):
                    enabled_services.append(line[8:])

            success = (failed_count == 0)
            return is_in_progress, enabled_pkgs, enabled_services, success

        # Scenario 1: Interrupted transaction (crashed after 2 packages)
        interrupted_wal = (
            "STATUS:IN_PROGRESS\n"
            "# Debloat WAL transaction started\n"
            "PKG:com.test.bloat1\n"
            "PKG:com.test.bloat2\n"
        )
        in_prog, pkgs, svcs, ok = parse_and_simulate_restore(interrupted_wal)
        self.assertTrue(in_prog, "Must detect in-progress interrupted transaction")
        self.assertEqual(pkgs, ["com.test.bloat1", "com.test.bloat2"])
        self.assertTrue(ok)

        # Scenario 2: Restore encounter partial failure (retains failure status)
        _, _, _, ok_fail = parse_and_simulate_restore(interrupted_wal, fail_on_pkg="com.test.bloat1")
        self.assertFalse(ok_fail, "Must report failure if package re-enable fails so snapshot is not archived")

        # Scenario 3: Completed transaction with service
        completed_wal = (
            "STATUS:IN_PROGRESS\n"
            "PKG:com.test.app\n"
            "SERVICE:com.dangbei.tvlauncher/com.dangbei.launcher.service.HomeKeyEventCatchService\n"
            "STATUS:COMPLETED\n"
        )
        in_prog3, pkgs3, svcs3, ok3 = parse_and_simulate_restore(completed_wal)
        self.assertFalse(in_prog3, "Must detect completed transaction")
        self.assertEqual(pkgs3, ["com.test.app"])
        self.assertEqual(svcs3, ["com.dangbei.tvlauncher/com.dangbei.launcher.service.HomeKeyEventCatchService"])
        self.assertTrue(ok3)


class ShellIntegrationTests(unittest.TestCase):
    """End-to-end integration tests actually executing the shell scripts with mock Android tools."""

    @classmethod
    def setUpClass(cls):
        cls.sh_exe = shutil.which('sh') or r'C:\Program Files\Git\bin\sh.exe'
        if not Path(cls.sh_exe).exists():
            raise unittest.SkipTest("POSIX sh executable not found for integration testing")

    def create_mock_env(self, tmp_path, mock_dumpsys_text=""):
        mock_bin = tmp_path / 'bin'
        mock_bin.mkdir(exist_ok=True)

        pm_code = '''#!/bin/sh
cmd="$1"
case "$cmd" in
    path)
        pkg="$2"
        if [ "$pkg" = "com.uninstalled.app" ]; then
            exit 1
        fi
        echo "package:/system/app/$pkg.apk"
        exit 0
        ;;
    list)
        if [ "$2" = "packages" ] && [ "$3" = "-d" ]; then
            if [ -f "$MOCK_DISABLED_FILE" ]; then
                cat "$MOCK_DISABLED_FILE"
            fi
            exit 0
        elif [ "$2" = "packages" ]; then
            echo "package:com.test.app1"
            echo "package:com.dangbei.tvlauncher"
            exit 0
        fi
        ;;
    disable-user)
        pkg="$4"
        if [ "$pkg" = "$FAIL_ON_PKG" ]; then
            echo "Error: mock failure on $pkg" >&2
            exit 1
        fi
        echo "package:$pkg" >> "$MOCK_DISABLED_FILE"
        exit 0
        ;;
    disable)
        svc="$2"
        if [ "$FAIL_ON_SVC" = "1" ]; then
            echo "Error: mock failure on service" >&2
            exit 1
        fi
        echo "service:$svc" >> "$MOCK_DISABLED_FILE"
        exit 0
        ;;
    default-state|enable)
        exit 0
        ;;
esac
exit 0
'''
        (mock_bin / 'pm').write_text(pm_code, encoding='utf-8')
        (mock_bin / 'am').write_text('#!/bin/sh\nexit 0\n', encoding='utf-8')
        (mock_bin / 'free').write_text('#!/bin/sh\necho "             total        used        free"\necho "Mem:           1800        1200         600"\n', encoding='utf-8')
        (mock_bin / 'sync').write_text('#!/bin/sh\nif [ "$FAIL_SYNC" = "1" ]; then exit 1; fi\nexit 0\n', encoding='utf-8')
        (mock_bin / 'setprop').write_text('#!/bin/sh\nexit 0\n', encoding='utf-8')

        dumpsys_file = tmp_path / 'dumpsys_output.txt'
        dumpsys_file.write_text(mock_dumpsys_text, encoding='utf-8')

        dumpsys_code = f'''#!/bin/sh
cat "{dumpsys_file.as_posix()}"
exit 0
'''
        (mock_bin / 'dumpsys').write_text(dumpsys_code, encoding='utf-8')

        env = os.environ.copy()
        env['PATH'] = str(mock_bin) + os.pathsep + env.get('PATH', '')
        env['MOCK_DISABLED_FILE'] = str(tmp_path / 'disabled_pkgs.txt')
        return env

    def test_shell_debloat_and_restore_full_cycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            state_dir = tmp_path / 'state'
            pkg_file = tmp_path / 'packages.txt'
            pkg_file.write_text("com.test.app1\ncom.test.app2\n", encoding='utf-8')

            env = self.create_mock_env(tmp_path)
            env['STATE_DIR'] = str(state_dir)
            env['PACKAGES_FILE'] = str(pkg_file)

            debloat_script = (ROOT / 'scripts/debloat.sh').as_posix()
            restore_script = (ROOT / 'scripts/restore_bloatware.sh').as_posix()

            # 1. Run debloat
            res = subprocess.run([self.sh_exe, debloat_script], env=env, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"debloat.sh failed: {res.stderr}")

            snapshot = state_dir / 'snapshot.txt'
            self.assertTrue(snapshot.exists(), "snapshot.txt must exist after debloat")
            snap_text = snapshot.read_text(encoding='utf-8')
            self.assertIn("STATUS:IN_PROGRESS", snap_text)
            self.assertIn("PKG:com.test.app1", snap_text)
            self.assertIn("PKG:com.test.app2", snap_text)
            self.assertIn("STATUS:COMPLETED", snap_text)

            # 2. Run debloat again -> must reject because completed snapshot exists
            res_repeat = subprocess.run([self.sh_exe, debloat_script], env=env, capture_output=True, text=True)
            self.assertEqual(res_repeat.returncode, 1)
            self.assertIn("Active debloat snapshot already exists", res_repeat.stderr)

            # 3. Run restore_bloatware.sh
            res_restore = subprocess.run([self.sh_exe, restore_script], env=env, capture_output=True, text=True)
            self.assertEqual(res_restore.returncode, 0, f"restore_bloatware.sh failed: {res_restore.stderr}")
            self.assertFalse(snapshot.exists(), "snapshot.txt must be archived")
            self.assertTrue((state_dir / 'snapshot.txt.restored').exists(), "snapshot.txt.restored must exist")

    def test_shell_failure_injection_retains_wal_and_recovers(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            state_dir = tmp_path / 'state'
            pkg_file = tmp_path / 'packages.txt'
            pkg_file.write_text("com.test.ok\ncom.test.failpkg\ncom.test.unreached\n", encoding='utf-8')

            env = self.create_mock_env(tmp_path)
            env['STATE_DIR'] = str(state_dir)
            env['PACKAGES_FILE'] = str(pkg_file)
            env['FAIL_ON_PKG'] = 'com.test.failpkg'

            debloat_script = (ROOT / 'scripts/debloat.sh').as_posix()
            restore_script = (ROOT / 'scripts/restore_bloatware.sh').as_posix()

            # 1. Run debloat -> must fail on com.test.failpkg
            res = subprocess.run([self.sh_exe, debloat_script], env=env, capture_output=True, text=True)
            self.assertEqual(res.returncode, 1)
            self.assertIn("Retaining WAL entry for recovery", res.stderr)

            snapshot = state_dir / 'snapshot.txt'
            self.assertTrue(snapshot.exists())
            snap_text = snapshot.read_text(encoding='utf-8')
            self.assertIn("STATUS:IN_PROGRESS", snap_text)
            self.assertIn("PKG:com.test.ok", snap_text)
            self.assertIn("PKG:com.test.failpkg", snap_text, "Failed package MUST be retained in WAL")
            self.assertNotIn("PKG:com.test.unreached", snap_text)
            self.assertNotIn("STATUS:COMPLETED", snap_text)

            # 2. Run debloat again -> must detect interrupted transaction and block
            res_repeat = subprocess.run([self.sh_exe, debloat_script], env=env, capture_output=True, text=True)
            self.assertEqual(res_repeat.returncode, 1)
            self.assertIn("interrupted debloat transaction was detected", res_repeat.stderr)

            # 3. Run restore_bloatware.sh -> recovers interrupted transaction
            env['FAIL_ON_PKG'] = ''  # Clear failure trigger for restore
            res_restore = subprocess.run([self.sh_exe, restore_script], env=env, capture_output=True, text=True)
            self.assertEqual(res_restore.returncode, 0, f"restore failed: {res_restore.stderr}")
            self.assertIn("Detected incomplete or interrupted debloat transaction", res_restore.stdout)
            self.assertTrue((state_dir / 'snapshot.txt.restored').exists())

    def test_shell_dangbei_multi_component_preservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            state_dir = tmp_path / 'state'
            pkg_file = tmp_path / 'packages.txt'
            pkg_file.write_text("", encoding='utf-8')

            # Codex's multi-component test case where HomeKeyEventCatchService is already disabled
            codex_dumpsys = """
    User 0: ceDataInode=-12345 installed=true
      disabledComponents:
        com.example.FirstService
        com.dangbei.launcher.service.HomeKeyEventCatchService
      enabledComponents:
"""
            env = self.create_mock_env(tmp_path, mock_dumpsys_text=codex_dumpsys)
            env['STATE_DIR'] = str(state_dir)
            env['PACKAGES_FILE'] = str(pkg_file)

            debloat_script = (ROOT / 'scripts/debloat.sh').as_posix()
            res = subprocess.run([self.sh_exe, debloat_script], env=env, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"debloat failed: {res.stderr}")

            snap_text = (state_dir / 'snapshot.txt').read_text(encoding='utf-8')
            self.assertNotIn("SERVICE:com.dangbei.tvlauncher/com.dangbei.launcher.service.HomeKeyEventCatchService", snap_text,
                             "Service already disabled in multi-component list must NOT be added to WAL snapshot")

    def test_shell_corrupted_snapshot_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            state_dir = tmp_path / 'state'
            state_dir.mkdir()
            bad_snap = state_dir / 'snapshot.txt'
            bad_snap.write_text("CORRUPTED_GARBAGE_NO_HEADER\nPKG:com.test.bad\n", encoding='utf-8')

            env = self.create_mock_env(tmp_path)
            env['STATE_DIR'] = str(state_dir)

            restore_script = (ROOT / 'scripts/restore_bloatware.sh').as_posix()
            res = subprocess.run([self.sh_exe, restore_script], env=env, capture_output=True, text=True)
            self.assertEqual(res.returncode, 1, "restore must reject corrupted snapshot")
            self.assertIn("corrupted or missing a valid transaction status header", res.stderr)
            self.assertTrue(bad_snap.exists(), "Corrupted snapshot file must NOT be deleted")

    def test_shell_mid_file_corruption_preflight_blocks_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            state_dir = tmp_path / 'state'
            state_dir.mkdir()
            bad_snap = state_dir / 'snapshot.txt'
            # Has valid header, but invalid record in the middle
            bad_snap.write_text("STATUS:IN_PROGRESS\nPKG:com.test.valid\nINVALID_RECORD_LINE\nSTATUS:COMPLETED\n", encoding='utf-8')

            env = self.create_mock_env(tmp_path)
            env['STATE_DIR'] = str(state_dir)

            restore_script = (ROOT / 'scripts/restore_bloatware.sh').as_posix()
            res = subprocess.run([self.sh_exe, restore_script], env=env, capture_output=True, text=True)
            self.assertEqual(res.returncode, 1, "restore must abort during pre-flight on corrupted record")
            self.assertIn("Snapshot pre-flight validation failed", res.stderr)
            self.assertIn("Device state has NOT been altered", res.stderr)
            self.assertTrue(bad_snap.exists(), "Snapshot must be retained untouched")


if __name__ == '__main__':
    unittest.main()
