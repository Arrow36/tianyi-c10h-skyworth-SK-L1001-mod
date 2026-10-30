#!/usr/bin/env python3
"""
build_autostart_apk.py
Zero-SDK Python generator for AutoStartHelper.apk (com.autostart.factoryhelper v1.1).
Listens for android.intent.action.BOOT_COMPLETED, waits 5 seconds for Dangbei Launcher
to settle, and launches com.yeker.factorytest.tool/.activity.StartupActivity to enable
Wireless Root ADB and auto-close.

Dependency: pip install cryptography
"""

import struct
import hashlib
import zlib
import zipfile
import base64
import datetime
import pathlib
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs7


def make_axml() -> bytes:
    res_strings = [
        ("name", 0x01010003),
        ("enabled", 0x0101000E),
        ("exported", 0x01010010),
        ("priority", 0x0101001C),
        ("versionCode", 0x0101021B),
        ("versionName", 0x0101021C),
    ]
    other_strings = [
        "android",
        "http://schemas.android.com/apk/res/android",
        "",
        "manifest",
        "package",
        "com.autostart.factoryhelper",
        "1.1",
        "uses-permission",
        "android.permission.RECEIVE_BOOT_COMPLETED",
        "application",
        "receiver",
        "com.autostart.factoryhelper.BootReceiver",
        "intent-filter",
        "action",
        "android.intent.action.BOOT_COMPLETED",
        "category",
        "android.intent.category.DEFAULT",
    ]
    all_strs = [s for s, _ in res_strings] + other_strings
    s_idx = {s: i for i, s in enumerate(all_strs)}

    encoded_strs = [
        struct.pack("<H", len(s)) + s.encode("utf-16le") + b"\x00\x00"
        for s in all_strs
    ]
    offsets = []
    cur = 0
    for es in encoded_strs:
        offsets.append(cur)
        cur += len(es)
    pool_data = b"".join(encoded_strs)
    while len(pool_data) % 4 != 0:
        pool_data += b"\x00"

    strings_start = 28 + len(all_strs) * 4
    sp_chunk = struct.pack(
        "<HHIIIIII",
        0x0001,
        28,
        strings_start + len(pool_data),
        len(all_strs),
        0,
        0,
        strings_start,
        0,
    )
    sp_chunk += b"".join(struct.pack("<I", o) for o in offsets) + pool_data

    rm_body = b"".join(struct.pack("<I", rid) for _, rid in res_strings)
    rm_chunk = struct.pack("<HHI", 0x0180, 8, 8 + len(rm_body)) + rm_body

    NS_URI = s_idx["http://schemas.android.com/apk/res/android"]
    NS_PFX = s_idx["android"]
    NO_STR = 0xFFFFFFFF

    def start_ns(line=1):
        return struct.pack("<HHIIIII", 0x0100, 16, 24, line, NO_STR, NS_PFX, NS_URI)

    def end_ns(line=1):
        return struct.pack("<HHIIIII", 0x0101, 16, 24, line, NO_STR, NS_PFX, NS_URI)

    def attr_str(ns, name, val_str):
        si = s_idx[val_str]
        return struct.pack("<IIIHBBI", ns, s_idx[name], si, 8, 0, 0x03, si)

    def attr_int(ns, name, val_int):
        return struct.pack("<IIIHBBI", ns, s_idx[name], NO_STR, 8, 0, 0x10, val_int)

    def attr_bool(ns, name, val_bool):
        return struct.pack(
            "<IIIHBBI",
            ns,
            s_idx[name],
            NO_STR,
            8,
            0,
            0x12,
            0xFFFFFFFF if val_bool else 0,
        )

    def start_el(name, attrs, line=1):
        ext = struct.pack(
            "<IIHHHHHH", NO_STR, s_idx[name], 20, 20, len(attrs), 0, 0, 0
        )
        attr_bytes = b"".join(attrs)
        total = 16 + len(ext) + len(attr_bytes)
        hdr = struct.pack("<HHIII", 0x0102, 16, total, line, NO_STR)
        return hdr + ext + attr_bytes

    def end_el(name, line=1):
        return struct.pack(
            "<HHIIIII", 0x0103, 16, 24, line, NO_STR, NO_STR, s_idx[name]
        )

    xml_chunks = b"".join(
        [
            start_ns(),
            start_el(
                "manifest",
                [
                    attr_int(NS_URI, "versionCode", 2),
                    attr_str(NS_URI, "versionName", "1.1"),
                    attr_str(NO_STR, "package", "com.autostart.factoryhelper"),
                ],
            ),
            start_el(
                "uses-permission",
                [
                    attr_str(
                        NS_URI, "name", "android.permission.RECEIVE_BOOT_COMPLETED"
                    ),
                ],
            ),
            end_el("uses-permission"),
            start_el("application", []),
            start_el(
                "receiver",
                [
                    attr_str(
                        NS_URI, "name", "com.autostart.factoryhelper.BootReceiver"
                    ),
                    attr_bool(NS_URI, "enabled", True),
                    attr_bool(NS_URI, "exported", True),
                ],
            ),
            start_el(
                "intent-filter",
                [
                    attr_int(NS_URI, "priority", 0),
                ],
            ),
            start_el(
                "action",
                [
                    attr_str(NS_URI, "name", "android.intent.action.BOOT_COMPLETED"),
                ],
            ),
            end_el("action"),
            start_el(
                "category",
                [
                    attr_str(NS_URI, "name", "android.intent.category.DEFAULT"),
                ],
            ),
            end_el("category"),
            end_el("intent-filter"),
            end_el("receiver"),
            end_el("application"),
            end_el("manifest"),
            end_ns(),
        ]
    )

    body = sp_chunk + rm_chunk + xml_chunks
    return struct.pack("<HHI", 0x0003, 8, 8 + len(body)) + body


def uleb128(val: int) -> bytes:
    out = bytearray()
    while True:
        b = val & 0x7F
        val >>= 7
        if val:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)


def make_dex() -> bytes:
    strs = sorted(
        [
            "<init>",
            "I",
            "J",
            "L",
            "Landroid/content/BroadcastReceiver;",
            "Landroid/content/ComponentName;",
            "Landroid/content/Context;",
            "Landroid/content/Intent;",
            "Lcom/autostart/factoryhelper/BootReceiver;",
            "Ljava/lang/String;",
            "Ljava/lang/Thread;",
            "LLL",
            "LL",
            "LI",
            "V",
            "VJ",
            "VL",
            "VLL",
            "addFlags",
            "com.yeker.factorytest.tool",
            "com.yeker.factorytest.tool.activity.StartupActivity",
            "onReceive",
            "setClassName",
            "sleep",
            "startActivity",
        ]
    )
    s_idx = {s: i for i, s in enumerate(strs)}

    type_strs = sorted(
        [
            "Landroid/content/BroadcastReceiver;",
            "Landroid/content/ComponentName;",
            "Landroid/content/Context;",
            "Landroid/content/Intent;",
            "Lcom/autostart/factoryhelper/BootReceiver;",
            "Ljava/lang/String;",
            "Ljava/lang/Thread;",
            "V",
            "I",
            "J",
        ],
        key=lambda s: s_idx[s],
    )
    t_idx = {s: i for i, s in enumerate(type_strs)}

    proto_defs = [
        ("V", "V", []),
        ("VJ", "V", ["J"]),
        ("LI", "Landroid/content/Intent;", ["I"]),
        ("VL", "V", ["Landroid/content/Intent;"]),
        ("VLL", "V", ["Landroid/content/Context;", "Landroid/content/Intent;"]),
        ("LLL", "Landroid/content/Intent;", ["Ljava/lang/String;", "Ljava/lang/String;"]),
    ]
    proto_defs.sort(key=lambda p: (t_idx[p[1]], [t_idx[x] for x in p[2]]))
    p_idx = {(p[1], tuple(p[2])): i for i, p in enumerate(proto_defs)}

    method_defs = [
        ("Landroid/content/BroadcastReceiver;", "V", (), "<init>"),
        ("Landroid/content/Context;", "V", ("Landroid/content/Intent;",), "startActivity"),
        ("Landroid/content/Intent;", "V", (), "<init>"),
        ("Landroid/content/Intent;", "Landroid/content/Intent;", ("I",), "addFlags"),
        (
            "Landroid/content/Intent;",
            "Landroid/content/Intent;",
            ("Ljava/lang/String;", "Ljava/lang/String;"),
            "setClassName",
        ),
        ("Lcom/autostart/factoryhelper/BootReceiver;", "V", (), "<init>"),
        (
            "Lcom/autostart/factoryhelper/BootReceiver;",
            "V",
            ("Landroid/content/Context;", "Landroid/content/Intent;"),
            "onReceive",
        ),
        ("Ljava/lang/Thread;", "V", ("J",), "sleep"),
    ]
    method_defs.sort(key=lambda m: (t_idx[m[0]], s_idx[m[3]], p_idx[(m[1], m[2])]))
    m_idx = {(m[0], m[3]): i for i, m in enumerate(method_defs)}

    hdr_size = 0x70
    str_ids_off = hdr_size
    type_ids_off = str_ids_off + len(strs) * 4
    proto_ids_off = type_ids_off + len(type_strs) * 4
    method_ids_off = proto_ids_off + len(proto_defs) * 12
    class_defs_off = method_ids_off + len(method_defs) * 8
    data_off = class_defs_off + 32

    data = bytearray()

    def align4():
        while (data_off + len(data)) % 4 != 0:
            data.append(0)

    typelist_offs = {}
    for _, ret, params in proto_defs:
        if not params:
            typelist_offs[(ret, tuple(params))] = 0
        else:
            align4()
            off = data_off + len(data)
            typelist_offs[(ret, tuple(params))] = off
            data += struct.pack("<I", len(params))
            for pt in params:
                data += struct.pack("<H", t_idx[pt])

    align4()
    code_init_off = data_off + len(data)
    insns_init = struct.pack(
        "<HHHH",
        0x1070,
        m_idx[("Landroid/content/BroadcastReceiver;", "<init>")],
        0x0000,
        0x000E,
    )
    data += (
        struct.pack("<HHHHII", 1, 1, 1, 0, 0, len(insns_init) // 2) + insns_init
    )

    align4()
    code_onrec_off = data_off + len(data)
    insns_onrec = b"".join(
        [
            struct.pack("<HH", 0x0016, 5000),
            struct.pack("<HHH", 0x2071, m_idx[("Ljava/lang/Thread;", "sleep")], 0x0010),
            struct.pack("<HH", 0x0022, t_idx["Landroid/content/Intent;"]),
            struct.pack(
                "<HHH", 0x1070, m_idx[("Landroid/content/Intent;", "<init>")], 0x0000
            ),
            struct.pack("<HH", 0x011A, s_idx["com.yeker.factorytest.tool"]),
            struct.pack(
                "<HH",
                0x021A,
                s_idx["com.yeker.factorytest.tool.activity.StartupActivity"],
            ),
            struct.pack(
                "<HHH",
                0x306E,
                m_idx[("Landroid/content/Intent;", "setClassName")],
                0x0210,
            ),
            struct.pack("<HH", 0x0115, 0x1000),
            struct.pack(
                "<HHH", 0x206E, m_idx[("Landroid/content/Intent;", "addFlags")], 0x0010
            ),
            struct.pack(
                "<HHH",
                0x206E,
                m_idx[("Landroid/content/Context;", "startActivity")],
                0x0004,
            ),
            struct.pack("<H", 0x000E),
        ]
    )
    data += (
        struct.pack("<HHHHII", 6, 3, 3, 0, 0, len(insns_onrec) // 2) + insns_onrec
    )

    str_data_offs = []
    for s in strs:
        str_data_offs.append(data_off + len(data))
        b = s.encode("utf-8")
        data += uleb128(len(s)) + b + b"\x00"

    class_data_off = data_off + len(data)
    m_init = m_idx[("Lcom/autostart/factoryhelper/BootReceiver;", "<init>")]
    m_onrec = m_idx[("Lcom/autostart/factoryhelper/BootReceiver;", "onReceive")]
    data += (
        uleb128(0)
        + uleb128(0)
        + uleb128(1)
        + uleb128(1)
        + uleb128(m_init)
        + uleb128(0x10001)
        + uleb128(code_init_off)
        + uleb128(m_onrec)
        + uleb128(0x0001)
        + uleb128(code_onrec_off)
    )

    align4()
    map_off = data_off + len(data)
    map_items = [
        (0x0000, 1, 0),
        (0x0001, len(strs), str_ids_off),
        (0x0002, len(type_strs), type_ids_off),
        (0x0003, len(proto_defs), proto_ids_off),
        (0x0005, len(method_defs), method_ids_off),
        (0x0006, 1, class_defs_off),
        (
            0x1001,
            sum(1 for v in typelist_offs.values() if v != 0),
            min(v for v in typelist_offs.values() if v != 0),
        ),
        (0x2001, 2, code_init_off),
        (0x2002, len(strs), str_data_offs[0]),
        (0x2000, 1, class_data_off),
        (0x1000, 1, map_off),
    ]
    data += struct.pack("<I", len(map_items))
    for mtype, msize, moff in map_items:
        data += struct.pack("<HHII", mtype, 0, msize, moff)

    align4()
    file_size = data_off + len(data)

    str_ids_bin = b"".join(struct.pack("<I", o) for o in str_data_offs)
    type_ids_bin = b"".join(struct.pack("<I", s_idx[s]) for s in type_strs)
    proto_ids_bin = b"".join(
        struct.pack(
            "<III", s_idx[shorty], t_idx[ret], typelist_offs[(ret, tuple(params))]
        )
        for shorty, ret, params in proto_defs
    )
    method_ids_bin = b"".join(
        struct.pack("<HHI", t_idx[c], p_idx[(r, p)], s_idx[n])
        for c, r, p, n in method_defs
    )
    class_defs_bin = struct.pack(
        "<IIIIIIII",
        t_idx["Lcom/autostart/factoryhelper/BootReceiver;"],
        0x0001,
        t_idx["Landroid/content/BroadcastReceiver;"],
        0,
        0xFFFFFFFF,
        0,
        class_data_off,
        0,
    )

    body_after_sig = (
        struct.pack("<II", file_size, 0x70)
        + struct.pack("<I", 0x12345678)
        + struct.pack("<II", 0, 0)
        + struct.pack("<I", map_off)
        + struct.pack("<II", len(strs), str_ids_off)
        + struct.pack("<II", len(type_strs), type_ids_off)
        + struct.pack("<II", len(proto_defs), proto_ids_off)
        + struct.pack("<II", 0, 0)
        + struct.pack("<II", len(method_defs), method_ids_off)
        + struct.pack("<II", 1, class_defs_off)
        + struct.pack("<II", len(data), data_off)
        + str_ids_bin
        + type_ids_bin
        + proto_ids_bin
        + method_ids_bin
        + class_defs_bin
        + bytes(data)
    )
    sha1 = hashlib.sha1(body_after_sig).digest()
    adler = zlib.adler32(sha1 + body_after_sig) & 0xFFFFFFFF
    return b"dex\n035\x00" + struct.pack("<I", adler) + sha1 + body_after_sig


def build_signed_apk(out_path: pathlib.Path):
    axml = make_axml()
    dex = make_dex()

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "Android Debug")]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc))
        .not_valid_after(datetime.datetime(2050, 1, 1, tzinfo=datetime.timezone.utc))
        .sign(key, hashes.SHA256())
    )

    def b64_sha256(b: bytes) -> str:
        return base64.b64encode(hashlib.sha256(b).digest()).decode("ascii")

    mf_entry_1 = (
        f"Name: AndroidManifest.xml\r\nSHA-256-Digest: {b64_sha256(axml)}\r\n\r\n"
    ).encode("ascii")
    mf_entry_2 = (
        f"Name: classes.dex\r\nSHA-256-Digest: {b64_sha256(dex)}\r\n\r\n"
    ).encode("ascii")
    mf_main = b"Manifest-Version: 1.0\r\nCreated-By: 1.0 (Android)\r\n\r\n"
    manifest_mf = mf_main + mf_entry_1 + mf_entry_2

    sf_main = (
        f"Signature-Version: 1.0\r\nCreated-By: 1.0 (Android)\r\n"
        f"SHA-256-Digest-Manifest: {b64_sha256(manifest_mf)}\r\n\r\n"
    ).encode("ascii")
    sf_entry_1 = (
        f"Name: AndroidManifest.xml\r\nSHA-256-Digest: {b64_sha256(mf_entry_1)}\r\n\r\n"
    ).encode("ascii")
    sf_entry_2 = (
        f"Name: classes.dex\r\nSHA-256-Digest: {b64_sha256(mf_entry_2)}\r\n\r\n"
    ).encode("ascii")
    cert_sf = sf_main + sf_entry_1 + sf_entry_2

    cert_rsa = (
        pkcs7.PKCS7SignatureBuilder()
        .set_data(cert_sf)
        .add_signer(cert, key, hashes.SHA256())
        .sign(
            serialization.Encoding.DER,
            [
                pkcs7.PKCS7Options.DetachedSignature,
                pkcs7.PKCS7Options.Binary,
                pkcs7.PKCS7Options.NoAttributes,
            ],
        )
    )

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("AndroidManifest.xml", axml)
        z.writestr("classes.dex", dex)
        z.writestr("META-INF/MANIFEST.MF", manifest_mf)
        z.writestr("META-INF/CERT.SF", cert_sf)
        z.writestr("META-INF/CERT.RSA", cert_rsa)


if __name__ == "__main__":
    out = pathlib.Path(__file__).resolve().parent.parent / "configs" / "AutoStartHelper.apk"
    build_signed_apk(out)
    print(f"[+] Built signed APK: {out}")
