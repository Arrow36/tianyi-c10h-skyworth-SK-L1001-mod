#!/usr/bin/env python3
"""
factorytest_crypt.py
XOR encryption/decryption tool for Skyworth / Yeker FactoryTestTool (com.yeker.factorytest.tool)
Target file on device: /sdcard/factoryTest/factorytest_config.xml
XOR Key: "yekerv587"
"""

import argparse
import pathlib
import xml.etree.ElementTree as ET

XOR_KEY = b"yekerv587"


def xor_transform(data: bytes, key: bytes = XOR_KEY) -> bytes:
    if not key:
        raise ValueError("XOR key must not be empty")
    key_len = len(key)
    return bytes(b ^ key[i % key_len] for i, b in enumerate(data))


def main():
    parser = argparse.ArgumentParser(
        description="Encrypt or decrypt factorytest_config.xml for Skyworth C10H (SK-L1001)"
    )
    parser.add_argument("input", type=pathlib.Path, help="Input file path")
    parser.add_argument("output", type=pathlib.Path, help="Output file path")
    parser.add_argument("--mode", choices=("auto", "encrypt", "decrypt"), default="auto")
    args = parser.parse_args()

    raw = args.input.read_bytes()
    out = xor_transform(raw)
    mode = args.mode
    if mode == "auto":
        mode = "encrypt" if raw.lstrip(b"\xef\xbb\xbf \r\n\t").startswith(b"<") else "decrypt"
    try:
        ET.fromstring(raw if mode == "encrypt" else out)
    except ET.ParseError as exc:
        parser.error(f"Invalid XML; output was not changed: {exc}")
    temporary = args.output.with_name(args.output.name + ".tmp")
    temporary.write_bytes(out)
    temporary.replace(args.output)
    print(f"[+] Processed {len(out)} bytes -> {args.output}")


if __name__ == "__main__":
    main()
