#!/usr/bin/env python3
"""Prepare a checked ARM ELF patch on the host; never edit the input folder."""
import argparse
import hashlib
from pathlib import Path
import re
import struct

RENAMES = {b"libcrypto.so": b"libbili_o.so", b"libssl.so": b"libbsl.so"}


def patch_elf(raw: bytes) -> bytes:
    if len(raw) < 52 or raw[:7] != b"\x7fELF\x01\x01\x01":
        raise ValueError("Expected a little-endian ELF32 file")
    if struct.unpack_from("<H", raw, 18)[0] != 40:
        raise ValueError("Expected ARM machine type")
    phoff = struct.unpack_from("<I", raw, 28)[0]
    phsize, phnum = struct.unpack_from("<HH", raw, 42)
    if phsize != 32 or phoff + phsize * phnum > len(raw):
        raise ValueError("Invalid program headers")
    headers = [struct.unpack_from("<8I", raw, phoff + i * phsize) for i in range(phnum)]
    dynamics = [p for p in headers if p[0] == 2]
    if len(dynamics) != 1:
        raise ValueError("Expected one PT_DYNAMIC segment")
    dynamic = dynamics[0]
    if dynamic[1] + dynamic[4] > len(raw) or dynamic[4] % 8:
        raise ValueError("Invalid dynamic segment")
    entries = []
    for offset in range(dynamic[1], dynamic[1] + dynamic[4], 8):
        tag, value = struct.unpack_from("<II", raw, offset)
        if not tag:
            break
        entries.append((tag, value))
    else:
        raise ValueError("Unterminated dynamic segment")
    tags = dict(entries)
    if 5 not in tags or 10 not in tags:
        raise ValueError("Missing dynamic string table")
    table_size = tags[10]
    offsets = [p[1] + tags[5] - p[2] for p in headers
               if p[0] == 1 and p[2] <= tags[5] and tags[5] + table_size <= p[2] + p[4]]
    if len(offsets) != 1 or offsets[0] + table_size > len(raw):
        raise ValueError("Invalid string-table mapping")
    base = offsets[0]
    patched = bytearray(raw)
    for tag, value in entries:
        if tag not in (1, 14):  # DT_NEEDED, DT_SONAME only
            continue
        if value >= table_size:
            raise ValueError("String offset out of bounds")
        end = raw.find(b"\0", base + value, base + table_size)
        if end < 0:
            raise ValueError("Unterminated dynamic string")
        name = raw[base + value:end]
        if name in RENAMES:
            replacement = RENAMES[name]
            assert len(name) == len(replacement)
            patched[base + value:end] = replacement
    return bytes(patched)


def prepare(source: Path, output: Path):
    if output.exists():
        raise ValueError("Output must be a new directory")
    originals, patched = {}, {}
    for path in sorted(source.glob("*.so")):
        if not re.fullmatch(r"[A-Za-z0-9_.+-]+\.so", path.name) or path.is_symlink():
            raise ValueError(f"Unsupported filename: {path}")
        raw = path.read_bytes()
        result = patch_elf(raw)
        if result != raw:
            originals[path.name], patched[path.name] = raw, result
    if not patched:
        raise ValueError("No matching dependencies; nothing to patch")
    for old, new in RENAMES.items():
        old, new = old.decode(), new.decode()
        if not (source / old).is_file() or (source / new).exists():
            raise ValueError("Missing originals or pre-existing patch; restore/reinstall first")
        raw = (source / old).read_bytes()
        originals[old], patched[new] = raw, patch_elf(raw)
    output.mkdir(parents=True)
    for name, data in patched.items():
        (output / name).write_bytes(data)
    for name, contents in (("original.sha256", originals), ("patched.sha256", patched)):
        (output / name).write_text("".join(f"{hashlib.sha256(data).hexdigest()}  {filename}\n"
                                          for filename, data in sorted(contents.items())), encoding="ascii", newline="\n")
    print(f"Prepared {len(patched)} libraries in {output}; inputs unchanged.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        prepare(args.input, args.output)
    except (ValueError, OSError, struct.error) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
