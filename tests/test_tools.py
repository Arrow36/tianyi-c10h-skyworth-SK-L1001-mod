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


if __name__ == '__main__':
    unittest.main()
