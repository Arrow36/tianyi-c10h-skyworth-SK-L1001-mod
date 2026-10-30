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


def parse_axml_elements(axml_data: bytes):
    """Minimal AXML parser for test assertions on generated manifests."""
    offset = 0
    root_type, root_hdr_size, _ = struct.unpack_from("<HHI", axml_data, offset)
    assert root_type == 0x0003, f"Expected 0x0003, got {hex(root_type)}"
    offset += root_hdr_size

    strings = []
    elements = []

    while offset < len(axml_data):
        chunk_type, _, chunk_size = struct.unpack_from("<HHI", axml_data, offset)
        if chunk_type == 0x0001:  # STRING_POOL
            str_count = struct.unpack_from("<I", axml_data, offset + 8)[0]
            str_start = struct.unpack_from("<I", axml_data, offset + 20)[0] + offset
            str_offsets = [struct.unpack_from("<I", axml_data, offset + 28 + i * 4)[0] for i in range(str_count)]
            for o in str_offsets:
                s_ptr = str_start + o
                s_len = struct.unpack_from("<H", axml_data, s_ptr)[0]
                s_bytes = axml_data[s_ptr + 2: s_ptr + 2 + s_len * 2]
                strings.append(s_bytes.decode("utf-16le"))
        elif chunk_type == 0x0102:  # START_ELEMENT
            name_idx = struct.unpack_from("<I", axml_data, offset + 20)[0]
            tag_name = strings[name_idx]
            attr_count = struct.unpack_from("<H", axml_data, offset + 28)[0]
            attrs = {}
            attr_offset = offset + 36
            for _ in range(attr_count):
                _, a_name_idx, a_val_str_idx, _, _, a_type, a_data = struct.unpack_from("<IIIHBBI", axml_data, attr_offset)
                a_name = strings[a_name_idx]
                if a_val_str_idx != 0xFFFFFFFF:
                    a_val = strings[a_val_str_idx]
                elif a_type == 0x12:  # BOOL
                    a_val = bool(a_data != 0)
                elif a_type == 0x10:  # INT
                    a_val = int(a_data)
                else:
                    a_val = a_data
                attrs[a_name] = a_val
                attr_offset += 20
            elements.append((tag_name, attrs))
        offset += chunk_size

    return strings, elements


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

    def test_autostart_apk_production_and_test_isolation(self):
        prod_apk = ROOT / 'configs/AutoStartHelper.apk'
        self.assertTrue(prod_apk.exists(), "Production AutoStartHelper.apk must exist")
        with zipfile.ZipFile(prod_apk) as z:
            axml = z.read('AndroidManifest.xml')
            dex = z.read('classes.dex')
            _, elems = parse_axml_elements(axml)
            manifest = next(attrs for tag, attrs in elems if tag == 'manifest')
            self.assertEqual(manifest['package'], 'com.autostart.factoryhelper', "Prod package must be com.autostart.factoryhelper")
            self.assertIn(b'com.yeker.factorytest.tool', dex)
            self.assertIn(b'AlarmManager', dex, "Prod DEX must use AlarmManager")
            self.assertIn(b'PendingIntent', dex)
            self.assertIn(b'SystemClock', dex)
            self.assertNotIn(b'sleep', dex, "Prod DEX must not contain Thread.sleep")
            self.assertNotIn(b'TestActivity', dex, "Prod DEX must not contain TestActivity")
            receiver = next(attrs for tag, attrs in elems if tag == 'receiver')
            self.assertFalse(receiver['exported'], "Prod receiver must be exported=false")

        # Build test APK into temp dir
        with tempfile.TemporaryDirectory() as tmp:
            test_apk_out = Path(tmp) / 'AutoStartHelper_test.apk'
            cmd = [
                sys.executable,
                str(ROOT / 'scripts/build_autostart_apk.py'),
                '--key', str(ROOT / 'scripts/debug.key'),
                '--output', str(test_apk_out),
                '--test-mode',
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"build_autostart_apk failed: {res.stderr}")
            self.assertTrue(test_apk_out.exists())

            with zipfile.ZipFile(test_apk_out) as z:
                t_axml = z.read('AndroidManifest.xml')
                t_dex = z.read('classes.dex')
                _, t_elems = parse_axml_elements(t_axml)

                t_manifest = next(attrs for tag, attrs in t_elems if tag == 'manifest')
                self.assertEqual(t_manifest['package'], 'com.autostart.factoryhelper.test')

                t_receiver = next(attrs for tag, attrs in t_elems if tag == 'receiver')
                self.assertFalse(t_receiver['exported'], "Test receiver must declare exported=false")

                # TestActivity must be registered in test mode
                act_elem = next((attrs for tag, attrs in t_elems if tag == 'activity'), None)
                self.assertIsNotNone(act_elem, "TestActivity must be declared in test manifest")
                self.assertEqual(act_elem['name'], 'com.autostart.factoryhelper.test.TestActivity')

                # DEX checks: Must use non-blocking AlarmManager, check-cast, getAction, and structured Log events
                self.assertIn(b'AlarmManager', t_dex)
                self.assertIn(b'PendingIntent', t_dex)
                self.assertIn(b'SystemClock', t_dex)
                self.assertIn(b'getAction', t_dex)
                self.assertIn(b'BOOT_RECEIVED', t_dex, "Test DEX must include BOOT_RECEIVED log event")
                self.assertIn(b'ALARM_SCHEDULED', t_dex, "Test DEX must include ALARM_SCHEDULED log event")
                self.assertIn(b'ALARM_FIRED', t_dex, "Test DEX must include ALARM_FIRED log event")
                self.assertNotIn(b'sleep', t_dex, "Test DEX must not contain Thread.sleep blocking call")
                self.assertNotIn(b'com.yeker.factorytest.tool', t_dex, "Test DEX must NOT target real FactoryTest tool")
                self.assertIn(b'com.autostart.factoryhelper.test.TestActivity', t_dex)

    def test_enable_keys_verifies_root_uid(self):
        cmd_content = (ROOT / 'scripts/key_remap/enable_keys.cmd').read_text(encoding='utf-8')
        self.assertIn('id -u | findstr /x 0', cmd_content, "enable_keys.cmd must verify root UID is 0 via findstr /x 0")

    def test_bilibili_script_bans_wildcard_sed_and_requires_modes(self):
        bili_sh = (ROOT / 'scripts/fix_bilibili_ssl.sh').read_text(encoding='utf-8')
        self.assertNotIn('sed -i', bili_sh, "Wildcard sed -i is banned from fix_bilibili_ssl.sh")
        self.assertNotIn('s/libcrypto', bili_sh, "No sed replacement should occur on library files")
        self.assertNotIn('s/libssl', bili_sh, "No sed replacement should occur on library files")
        self.assertIn('STATUS:BACKED_UP', bili_sh)
        self.assertIn('STATUS:APPLYING', bili_sh)
        self.assertIn('STATUS:COMPLETED', bili_sh)
        self.assertIn('STATUS:ROLLING_BACK', bili_sh)
        self.assertIn('STATUS:ROLLED_BACK', bili_sh)
        self.assertIn('STATUS:RESTORED', bili_sh)
        self.assertIn('rollback_from_backup', bili_sh)
        self.assertIn('apply', bili_sh)
        self.assertIn('restore', bili_sh)
        self.assertIn('status', bili_sh)

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
        (mock_bin / 'restorecon').write_text('#!/bin/sh\nexit 0\n', encoding='utf-8')

        perms_db = tmp_path / 'mock_perms.txt'
        chmod_code = f'''#!/bin/sh
MODE="$1"
shift
for f in "$@"; do
    echo "$MODE $f" >> "{perms_db.as_posix()}"
done
exit 0
'''
        (mock_bin / 'chmod').write_text(chmod_code, encoding='utf-8')

        stat_code = f'''#!/bin/sh
if [ "$1" = "-c" ] && [ "$2" = "%a" ]; then
    TARGET="$3"
    if [ -f "{perms_db.as_posix()}" ]; then
        RECORDED=$(grep " $TARGET$" "{perms_db.as_posix()}" 2>/dev/null | tail -n 1 | cut -d' ' -f1 || true)
        if [ -n "$RECORDED" ]; then
            echo "$RECORDED"
            exit 0
        fi
    fi
    echo "755"
    exit 0
fi
/bin/stat "$@"
'''
        (mock_bin / 'stat').write_text(stat_code, encoding='utf-8')

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
        env['SKIP_ROOT_CHECK'] = '1'
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

    def _setup_mock_bilibili_libs(self, lib_dir):
        lib_dir.mkdir(parents=True, exist_ok=True)
        for name in ('libcrypto.so', 'libssl.so', 'libignet.so'):
            (lib_dir / name).write_bytes(elf_fixture())

    def test_shell_bilibili_full_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            state_dir = tmp_path / 'state'
            lib_dir = tmp_path / 'lib'
            prep_dir = tmp_path / 'prepared'
            self._setup_mock_bilibili_libs(lib_dir)

            prepare(lib_dir, prep_dir)

            env = self.create_mock_env(tmp_path)
            env['STATE_DIR'] = state_dir.as_posix()
            env['MOCK_LIB_DIR'] = lib_dir.as_posix()

            script = (ROOT / 'scripts/fix_bilibili_ssl.sh').as_posix()

            # 1. Apply patch
            res_apply = subprocess.run([self.sh_exe, script, 'apply', prep_dir.as_posix()],
                                       env=env, capture_output=True, text=True)
            self.assertEqual(res_apply.returncode, 0, f"apply failed: {res_apply.stderr}")
            self.assertTrue((lib_dir / 'libbili_o.so').exists())
            self.assertTrue((lib_dir / 'libbsl.so').exists())

            tx_file = state_dir / 'tx_state.txt'
            self.assertTrue(tx_file.exists())
            tx_text = tx_file.read_text(encoding='utf-8')
            self.assertIn('STATUS:BACKED_UP', tx_text)
            self.assertIn('STATUS:APPLYING', tx_text)
            self.assertIn('STATUS:COMPLETED', tx_text)

            # 2. Check status
            res_status = subprocess.run([self.sh_exe, script, 'status'],
                                        env=env, capture_output=True, text=True)
            self.assertEqual(res_status.returncode, 0)
            self.assertIn('Device Status  : Patched', res_status.stdout)

            # 3. Apply again should be blocked because already patched
            res_dup = subprocess.run([self.sh_exe, script, 'apply', prep_dir.as_posix()],
                                     env=env, capture_output=True, text=True)
            self.assertNotEqual(res_dup.returncode, 0)
            self.assertIn('already patched', res_dup.stderr)

            # 4. Restore from backup
            res_restore = subprocess.run([self.sh_exe, script, 'restore'],
                                         env=env, capture_output=True, text=True)
            self.assertEqual(res_restore.returncode, 0, f"restore failed: {res_restore.stderr}")
            self.assertFalse((lib_dir / 'libbili_o.so').exists())
            self.assertFalse((lib_dir / 'libbsl.so').exists())

            tx_text_after = tx_file.read_text(encoding='utf-8')
            self.assertIn('STATUS:RESTORED', tx_text_after)

            # 5. Check status after restore
            res_status2 = subprocess.run([self.sh_exe, script, 'status'],
                                         env=env, capture_output=True, text=True)
            self.assertEqual(res_status2.returncode, 0)
            self.assertIn('Device Status  : Unpatched', res_status2.stdout)

    def test_shell_bilibili_precheck_mismatch_blocks_without_touching(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            state_dir = tmp_path / 'state'
            lib_dir = tmp_path / 'lib'
            prep_dir = tmp_path / 'prepared'
            self._setup_mock_bilibili_libs(lib_dir)

            prepare(lib_dir, prep_dir)

            # Tamper with target library before patch
            (lib_dir / 'libcrypto.so').write_bytes(b'tampered_library_content')

            env = self.create_mock_env(tmp_path)
            env['STATE_DIR'] = state_dir.as_posix()
            env['MOCK_LIB_DIR'] = lib_dir.as_posix()

            script = (ROOT / 'scripts/fix_bilibili_ssl.sh').as_posix()
            res = subprocess.run([self.sh_exe, script, 'apply', prep_dir.as_posix()],
                                 env=env, capture_output=True, text=True)
            self.assertEqual(res.returncode, 1)
            self.assertIn('Target libraries in', res.stderr)
            self.assertIn('do not match expected original.sha256', res.stderr)
            self.assertFalse((state_dir / 'tx_state.txt').exists())
            self.assertEqual(len(list(state_dir.glob('backup-*'))), 0)
            self.assertEqual((lib_dir / 'libcrypto.so').read_bytes(), b'tampered_library_content')

    def test_shell_bilibili_fault_injection_midway_write_triggers_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            state_dir = tmp_path / 'state'
            lib_dir = tmp_path / 'lib'
            prep_dir = tmp_path / 'prepared'
            self._setup_mock_bilibili_libs(lib_dir)

            prepare(lib_dir, prep_dir)

            env = self.create_mock_env(tmp_path)
            env['STATE_DIR'] = state_dir.as_posix()
            env['MOCK_LIB_DIR'] = lib_dir.as_posix()
            env['FAIL_ON_SO'] = 'libbsl.so'

            script = (ROOT / 'scripts/fix_bilibili_ssl.sh').as_posix()
            res = subprocess.run([self.sh_exe, script, 'apply', prep_dir.as_posix()],
                                 env=env, capture_output=True, text=True)
            self.assertEqual(res.returncode, 1)
            self.assertIn('Initiating rollback', res.stderr)
            self.assertIn('Rollback successful', res.stderr)

            # Verify complete rollback
            self.assertFalse((lib_dir / 'libbili_o.so').exists())
            self.assertFalse((lib_dir / 'libbsl.so').exists())
            for name in ('libcrypto.so', 'libssl.so', 'libignet.so'):
                self.assertEqual((lib_dir / name).read_bytes(), elf_fixture())

            tx_file = state_dir / 'tx_state.txt'
            self.assertTrue(tx_file.exists())
            tx_text = tx_file.read_text(encoding='utf-8')
            self.assertIn('STATUS:ROLLING_BACK', tx_text)
            self.assertIn('STATUS:ROLLED_BACK', tx_text)

    def test_shell_bilibili_fault_injection_postcheck_failure_triggers_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            state_dir = tmp_path / 'state'
            lib_dir = tmp_path / 'lib'
            prep_dir = tmp_path / 'prepared'
            self._setup_mock_bilibili_libs(lib_dir)

            prepare(lib_dir, prep_dir)

            env = self.create_mock_env(tmp_path)
            env['STATE_DIR'] = state_dir.as_posix()
            env['MOCK_LIB_DIR'] = lib_dir.as_posix()
            env['FAIL_POST_CHECK'] = '1'

            script = (ROOT / 'scripts/fix_bilibili_ssl.sh').as_posix()
            res = subprocess.run([self.sh_exe, script, 'apply', prep_dir.as_posix()],
                                 env=env, capture_output=True, text=True)
            self.assertEqual(res.returncode, 1)
            self.assertIn('Post-patch SHA-256 verification failed! Initiating rollback', res.stderr)
            self.assertIn('Rollback successful', res.stderr)

            self.assertFalse((lib_dir / 'libbili_o.so').exists())
            self.assertFalse((lib_dir / 'libbsl.so').exists())
            for name in ('libcrypto.so', 'libssl.so', 'libignet.so'):
                self.assertEqual((lib_dir / name).read_bytes(), elf_fixture())

            tx_text = (state_dir / 'tx_state.txt').read_text(encoding='utf-8')
            self.assertIn('STATUS:ROLLED_BACK', tx_text)

    def test_shell_bilibili_interrupted_transaction_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            state_dir = tmp_path / 'state'
            state_dir.mkdir()
            lib_dir = tmp_path / 'lib'
            prep_dir = tmp_path / 'prepared'
            self._setup_mock_bilibili_libs(lib_dir)

            prepare(lib_dir, prep_dir)

            # Set up mock interrupted transaction with valid backup
            backup_dir = state_dir / 'backup-12345-999'
            backup_orig = backup_dir / 'original'
            backup_orig.mkdir(parents=True)
            for name in ('libcrypto.so', 'libssl.so', 'libignet.so'):
                (backup_orig / name).write_bytes(elf_fixture())
            shutil.copy(prep_dir / 'original.sha256', backup_dir / 'original.sha256')
            shutil.copy(prep_dir / 'patched.sha256', backup_dir / 'patched.sha256')
            (backup_dir / 'lib.path').write_text(lib_dir.as_posix(), encoding='utf-8')

            tx_file = state_dir / 'tx_state.txt'
            tx_file.write_text(
                f"TIMESTAMP:12345\nLIB:{lib_dir.as_posix()}\nBACKUP_DIR:{backup_dir.as_posix()}\nSTATUS:BACKED_UP\nSTATUS:APPLYING\n",
                encoding='utf-8'
            )

            # Simulate partially modified lib directory
            (lib_dir / 'libbili_o.so').write_bytes(b'partial_artifact')

            env = self.create_mock_env(tmp_path)
            env['STATE_DIR'] = state_dir.as_posix()
            env['MOCK_LIB_DIR'] = lib_dir.as_posix()

            script = (ROOT / 'scripts/fix_bilibili_ssl.sh').as_posix()

            # 1. apply must detect interrupted state and reject
            res_apply = subprocess.run([self.sh_exe, script, 'apply', prep_dir.as_posix()],
                                       env=env, capture_output=True, text=True)
            self.assertEqual(res_apply.returncode, 1)
            self.assertIn('An interrupted transaction was detected', res_apply.stderr)

            # 2. restore without arguments automatically recovers from recorded backup
            res_restore = subprocess.run([self.sh_exe, script, 'restore'],
                                         env=env, capture_output=True, text=True)
            self.assertEqual(res_restore.returncode, 0, f"restore failed: {res_restore.stderr}")
            self.assertFalse((lib_dir / 'libbili_o.so').exists())
            self.assertFalse((lib_dir / 'libbsl.so').exists())
            for name in ('libcrypto.so', 'libssl.so', 'libignet.so'):
                self.assertEqual((lib_dir / name).read_bytes(), elf_fixture())

            tx_text = tx_file.read_text(encoding='utf-8')
            self.assertIn('STATUS:RESTORED', tx_text)

    def test_shell_bilibili_corrupted_backup_preflight_blocks_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            state_dir = tmp_path / 'state'
            state_dir.mkdir()
            lib_dir = tmp_path / 'lib'
            prep_dir = tmp_path / 'prepared'
            self._setup_mock_bilibili_libs(lib_dir)

            prepare(lib_dir, prep_dir)

            backup_dir = state_dir / 'backup-corrupted'
            backup_orig = backup_dir / 'original'
            backup_orig.mkdir(parents=True)
            for name in ('libcrypto.so', 'libssl.so', 'libignet.so'):
                (backup_orig / name).write_bytes(elf_fixture())
            shutil.copy(prep_dir / 'original.sha256', backup_dir / 'original.sha256')
            (backup_dir / 'lib.path').write_text(lib_dir.as_posix(), encoding='utf-8')

            # Corrupt one backup library
            (backup_orig / 'libcrypto.so').write_bytes(b'corrupted_backup_data')

            env = self.create_mock_env(tmp_path)
            env['STATE_DIR'] = state_dir.as_posix()
            env['MOCK_LIB_DIR'] = lib_dir.as_posix()

            script = (ROOT / 'scripts/fix_bilibili_ssl.sh').as_posix()
            res = subprocess.run([self.sh_exe, script, 'restore', backup_dir.as_posix()],
                                 env=env, capture_output=True, text=True)
            self.assertEqual(res.returncode, 1)
            self.assertIn('Backup files corrupted! Hash verification failed', res.stderr)
            self.assertIn('Device state has NOT been altered', res.stderr)

    def test_shell_bilibili_stale_lock_recovery_on_interrupted_transaction(self):
        """P0 regression test: Stale lock left after power outage/SIGKILL must be reclaimed during restore."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            state_dir = tmp_path / 'state'
            state_dir.mkdir()
            lib_dir = tmp_path / 'lib'
            prep_dir = tmp_path / 'prepared'
            self._setup_mock_bilibili_libs(lib_dir)

            prepare(lib_dir, prep_dir)

            # 1. Setup interrupted transaction
            backup_dir = state_dir / 'backup-12345-999'
            backup_orig = backup_dir / 'original'
            backup_orig.mkdir(parents=True)
            for name in ('libcrypto.so', 'libssl.so', 'libignet.so'):
                (backup_orig / name).write_bytes(elf_fixture())
            shutil.copy(prep_dir / 'original.sha256', backup_dir / 'original.sha256')
            shutil.copy(prep_dir / 'patched.sha256', backup_dir / 'patched.sha256')
            (backup_dir / 'lib.path').write_text(lib_dir.as_posix(), encoding='utf-8')

            tx_file = state_dir / 'tx_state.txt'
            tx_file.write_text(
                f"TIMESTAMP:12345\nLIB:{lib_dir.as_posix()}\nBACKUP_DIR:{backup_dir.as_posix()}\nSTATUS:BACKED_UP\nSTATUS:APPLYING\n",
                encoding='utf-8'
            )
            (lib_dir / 'libbili_o.so').write_bytes(b'partial_artifact')

            # 2. Leave stale lock directory with a dead PID
            lock_dir = state_dir / 'lock'
            lock_dir.mkdir()
            (lock_dir / 'pid').write_text('99999999\n', encoding='utf-8')
            (lock_dir / 'boot_id').write_text('dead-boot-uuid-from-previous-session\n', encoding='utf-8')

            env = self.create_mock_env(tmp_path)
            env['STATE_DIR'] = state_dir.as_posix()
            env['MOCK_LIB_DIR'] = lib_dir.as_posix()

            script = (ROOT / 'scripts/fix_bilibili_ssl.sh').as_posix()

            # 3. Status must work even with lock present
            res_status = subprocess.run([self.sh_exe, script, 'status'],
                                        env=env, capture_output=True, text=True)
            self.assertEqual(res_status.returncode, 0)
            self.assertIn('Stale lock present', res_status.stdout)

            # 4. restore must reclaim stale lock and successfully restore
            res_restore = subprocess.run([self.sh_exe, script, 'restore'],
                                         env=env, capture_output=True, text=True)
            self.assertEqual(res_restore.returncode, 0, f"restore failed: {res_restore.stderr}")
            self.assertIn('Detected stale lock from terminated process', res_restore.stderr)
            self.assertFalse((lib_dir / 'libbili_o.so').exists())
            self.assertFalse(lock_dir.exists(), "Lock must be released after restore finishes")

            tx_text = tx_file.read_text(encoding='utf-8')
            self.assertIn('STATUS:RESTORED', tx_text)

    def test_shell_bilibili_active_lock_blocks_concurrency(self):
        """Active lock from running process must block concurrent apply/restore."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            state_dir = tmp_path / 'state'
            state_dir.mkdir()
            lib_dir = tmp_path / 'lib'
            prep_dir = tmp_path / 'prepared'
            self._setup_mock_bilibili_libs(lib_dir)

            prepare(lib_dir, prep_dir)

            lock_dir = state_dir / 'lock'
            lock_dir.mkdir()

            # Spawn a background sleep process in sh so lock PID is an active shell process
            bg = subprocess.Popen([self.sh_exe, '-c', f'echo $$ > "{lock_dir.as_posix()}/pid"; sleep 30'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                import time
                for _ in range(20):
                    if (lock_dir / 'pid').exists() and (lock_dir / 'pid').read_text().strip():
                        break
                    time.sleep(0.1)

                env = self.create_mock_env(tmp_path)
                env['STATE_DIR'] = state_dir.as_posix()
                env['MOCK_LIB_DIR'] = lib_dir.as_posix()

                script = (ROOT / 'scripts/fix_bilibili_ssl.sh').as_posix()
                res_apply = subprocess.run([self.sh_exe, script, 'apply', prep_dir.as_posix()],
                                           env=env, capture_output=True, text=True)
                self.assertEqual(res_apply.returncode, 1)
                self.assertIn('Another patch operation is currently running', res_apply.stderr)
            finally:
                bg.terminate()
                bg.wait()

    def test_shell_bilibili_permission_fidelity_preserved(self):
        """P1 regression test: 0644 file permission must be preserved across patch and restore cycles."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            state_dir = tmp_path / 'state'
            lib_dir = tmp_path / 'lib'
            prep_dir = tmp_path / 'prepared'
            self._setup_mock_bilibili_libs(lib_dir)

            prepare(lib_dir, prep_dir)

            env = self.create_mock_env(tmp_path)
            env['STATE_DIR'] = state_dir.as_posix()
            env['MOCK_LIB_DIR'] = lib_dir.as_posix()

            # Set libcrypto.so permission to 0644 via mock perms db
            perms_db = tmp_path / 'mock_perms.txt'
            perms_db.write_text(f"644 {(lib_dir / 'libcrypto.so').as_posix()}\n", encoding='utf-8')

            script = (ROOT / 'scripts/fix_bilibili_ssl.sh').as_posix()

            # 1. Apply patch
            res_apply = subprocess.run([self.sh_exe, script, 'apply', prep_dir.as_posix()],
                                       env=env, capture_output=True, text=True)
            self.assertEqual(res_apply.returncode, 0, f"apply failed: {res_apply.stderr}")

            # Check that permissions were preserved
            res_perm_crypto = subprocess.run([self.sh_exe, '-c', f'stat -c "%a" "{(lib_dir / "libcrypto.so").as_posix()}"'],
                                             env=env, capture_output=True, text=True)
            res_perm_bili = subprocess.run([self.sh_exe, '-c', f'stat -c "%a" "{(lib_dir / "libbili_o.so").as_posix()}"'],
                                           env=env, capture_output=True, text=True)
            self.assertEqual(res_perm_crypto.stdout.strip(), '644', "libcrypto.so must remain 644 after patch")
            self.assertEqual(res_perm_bili.stdout.strip(), '644', "libbili_o.so template must inherit 644")

            # 2. Restore patch
            res_restore = subprocess.run([self.sh_exe, script, 'restore'],
                                         env=env, capture_output=True, text=True)
            self.assertEqual(res_restore.returncode, 0, f"restore failed: {res_restore.stderr}")

            # Check that restored libcrypto.so is STILL 644 (not blindly changed to 0755)
            res_perm_restored = subprocess.run([self.sh_exe, '-c', f'stat -c "%a" "{(lib_dir / "libcrypto.so").as_posix()}"'],
                                               env=env, capture_output=True, text=True)
            self.assertEqual(res_perm_restored.stdout.strip(), '644', "libcrypto.so must remain 644 after restore")

    def test_shell_bilibili_cross_version_restore_hard_blocked(self):
        """P1 regression test: restore across different lib paths or app versions must be strictly rejected."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            state_dir = tmp_path / 'state'
            state_dir.mkdir()
            lib_dir = tmp_path / 'lib'
            prep_dir = tmp_path / 'prepared'
            self._setup_mock_bilibili_libs(lib_dir)

            prepare(lib_dir, prep_dir)

            # Setup backup for version 7.50.0 and path /old/path
            backup_dir = state_dir / 'backup-crossver'
            backup_orig = backup_dir / 'original'
            backup_orig.mkdir(parents=True)
            for name in ('libcrypto.so', 'libssl.so', 'libignet.so'):
                (backup_orig / name).write_bytes(elf_fixture())
            shutil.copy(prep_dir / 'original.sha256', backup_dir / 'original.sha256')

            # 1. Test path mismatch hard block
            (backup_dir / 'lib.path').write_text('/different/app/path/lib/arm', encoding='utf-8')
            (backup_dir / 'app_version.txt').write_text('VERSION:versionName=7.50.0\n', encoding='utf-8')

            env = self.create_mock_env(tmp_path)
            env['STATE_DIR'] = state_dir.as_posix()
            env['MOCK_LIB_DIR'] = lib_dir.as_posix()
            env['MOCK_APP_VERSION'] = 'versionName=7.50.0'

            script = (ROOT / 'scripts/fix_bilibili_ssl.sh').as_posix()
            res_path = subprocess.run([self.sh_exe, script, 'restore', backup_dir.as_posix()],
                                      env=env, capture_output=True, text=True)
            self.assertEqual(res_path.returncode, 1)
            self.assertIn('Target library path mismatch!', res_path.stderr)
            self.assertIn('Refusing to restore across different application installations/paths', res_path.stderr)

            # 2. Test version identity mismatch hard block (path matches, version differs)
            (backup_dir / 'lib.path').write_text(lib_dir.as_posix(), encoding='utf-8')
            (backup_dir / 'app_version.txt').write_text('VERSION:versionName=7.50.0\n', encoding='utf-8')
            env['MOCK_APP_VERSION'] = 'versionName=7.60.0'  # Upgraded app version

            res_ver = subprocess.run([self.sh_exe, script, 'restore', backup_dir.as_posix()],
                                     env=env, capture_output=True, text=True)
            self.assertEqual(res_ver.returncode, 1)
            self.assertIn('Application version identity mismatch!', res_ver.stderr)
            self.assertIn('Refusing to restore backup from a different application version', res_ver.stderr)


if __name__ == '__main__':
    unittest.main()
