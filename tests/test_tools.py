import importlib.util
from pathlib import Path
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

    def test_restore_precision_guard_and_legacy_flag(self):
        restore_sh = (ROOT / 'scripts/restore_bloatware.sh').read_text(encoding='utf-8')
        self.assertIn('STATUS:IN_PROGRESS', restore_sh, "restore_bloatware.sh must handle incomplete WAL transactions")
        self.assertIn('--legacy-restore', restore_sh, "restore_bloatware.sh must require explicit flag when snapshot missing")
        self.assertIn('Refusing to blindly enable all packages', restore_sh)
        self.assertIn('FAILED_COUNT', restore_sh, "restore_bloatware.sh must check pm enable exit status")

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


if __name__ == '__main__':
    unittest.main()
