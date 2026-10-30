#!/usr/bin/env python3
"""
build_autostart_apk.py
Zero-SDK Python generator for AutoStartHelper APKs.

Architecture & Operation:
- Listens for android.intent.action.BOOT_COMPLETED.
- Manifest declares android:exported="false" to prevent unauthorized invocations.
- onReceive() performs strict intent.getAction() verification.
- Non-blocking execution: Avoids Thread.sleep() or UI-thread blocking. Uses Android's
  system AlarmManager.setExact(ELAPSED_REALTIME_WAKEUP, SystemClock.elapsedRealtime() + delay, pi)
  to delegate delayed scheduling to system_server, ensuring crash/kill resilience.
- Dalvik bytecode is assembled via a two-pass symbolic label assembler with strict check-cast
  type verification on getSystemService("alarm") and structured Log.i() observability.
- In test mode (--test-mode):
  * Builds isolated package: com.autostart.factoryhelper.test
  * Targets internal, side-effect-free TestActivity
  * Emits structured Log.i("AutoStartTest", ...) tags (BOOT_RECEIVED, ALARM_SCHEDULED, ALARM_FIRED)
  * Leaves production AutoStartHelper.apk and 5555 Root ADB chain completely untouched.
"""

import argparse
import base64
import datetime
import hashlib
import pathlib
import struct
import zipfile
import zlib

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509.oid import NameOID


def make_axml(pkg_name: str = "com.autostart.factoryhelper", is_test: bool = False, exported: bool = False) -> bytes:
    res_strings = [
        ("name", 0x01010003),
        ("enabled", 0x0101000E),
        ("exported", 0x01010010),
        ("priority", 0x0101001C),
        ("minSdkVersion", 0x0101020C),
        ("targetSdkVersion", 0x01010270),
        ("versionCode", 0x0101021B),
        ("versionName", 0x0101021C),
    ]
    other_strings = [
        "android",
        "http://schemas.android.com/apk/res/android",
        "",
        "manifest",
        "package",
        pkg_name,
        "1.2" if is_test else "1.1",
        "uses-sdk",
        "uses-permission",
        "android.permission.RECEIVE_BOOT_COMPLETED",
        "application",
        "receiver",
        f"{pkg_name}.BootReceiver",
        "intent-filter",
        "action",
        "android.intent.action.BOOT_COMPLETED",
        "category",
        "android.intent.category.DEFAULT",
    ]
    if is_test:
        other_strings.extend([
            "activity",
            f"{pkg_name}.TestActivity",
        ])

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

    app_children = [
        start_el(
            "receiver",
            [
                attr_str(NS_URI, "name", f"{pkg_name}.BootReceiver"),
                attr_bool(NS_URI, "enabled", True),
                attr_bool(NS_URI, "exported", exported),
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
    ]

    if is_test:
        app_children.extend([
            start_el(
                "activity",
                [
                    attr_str(NS_URI, "name", f"{pkg_name}.TestActivity"),
                    attr_bool(NS_URI, "enabled", True),
                    attr_bool(NS_URI, "exported", True),
                ],
            ),
            end_el("activity"),
        ])

    xml_chunks = b"".join(
        [
            start_ns(),
            start_el(
                "manifest",
                [
                    attr_int(NS_URI, "versionCode", 3 if is_test else 2),
                    attr_str(NS_URI, "versionName", "1.2" if is_test else "1.1"),
                    attr_str(NO_STR, "package", pkg_name),
                ],
            ),
            start_el(
                "uses-sdk",
                [
                    attr_int(NS_URI, "minSdkVersion", 28),
                    attr_int(NS_URI, "targetSdkVersion", 28),
                ],
            ),
            end_el("uses-sdk"),
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
            *app_children,
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


def assemble(instructions):
    """
    Two-pass Dalvik bytecode assembler with symbolic label branch calculation.
    Eliminates manual code-unit counting and prevents branch off-by-one errors.
    """
    label_pos = {}
    cur_unit = 0

    # Pass 1: Measure instruction code-unit sizes and map label positions
    for item in instructions:
        if isinstance(item, str):
            if item.startswith(":"):
                label_pos[item] = cur_unit
            continue

        op = item[0]
        if op in ("nop", "return-void", "const/4", "move-result", "move-result-wide", "move-result-object"):
            cur_unit += 1
        elif op in ("const/16", "const/high16", "const-wide/16", "const-string", "check-cast", "new-instance", "if-eqz", "if-nez", "add-long"):
            cur_unit += 2
        elif op in ("invoke-virtual", "invoke-super", "invoke-direct", "invoke-static"):
            cur_unit += 3
        else:
            raise ValueError(f"Unknown assemble opcode: {op}")

    # Pass 2: Emit binary instructions with exact relative branch offsets
    output = bytearray()
    cur_unit = 0

    op_codes = {
        "invoke-virtual": 0x6E,
        "invoke-super": 0x6F,
        "invoke-direct": 0x70,
        "invoke-static": 0x71,
    }

    for item in instructions:
        if isinstance(item, str):
            continue

        op = item[0]
        if op == "nop":
            output += struct.pack("<H", 0x0000)
            cur_unit += 1
        elif op == "return-void":
            output += struct.pack("<H", 0x000E)
            cur_unit += 1
        elif op == "const/4":
            _, reg, val = item
            output += struct.pack("<H", ((val & 0xF) << 12) | ((reg & 0xF) << 8) | 0x12)
            cur_unit += 1
        elif op == "const/16":
            _, reg, val = item
            output += struct.pack("<HH", (reg << 8) | 0x13, val & 0xFFFF)
            cur_unit += 2
        elif op == "const/high16":
            _, reg, val_high = item
            output += struct.pack("<HH", (reg << 8) | 0x15, val_high & 0xFFFF)
            cur_unit += 2
        elif op == "const-wide/16":
            _, reg, val = item
            output += struct.pack("<HH", (reg << 8) | 0x16, val & 0xFFFF)
            cur_unit += 2
        elif op == "const-string":
            _, reg, s_idx = item
            output += struct.pack("<HH", (reg << 8) | 0x1A, s_idx)
            cur_unit += 2
        elif op == "check-cast":
            _, reg, t_idx = item
            output += struct.pack("<HH", (reg << 8) | 0x1F, t_idx)
            cur_unit += 2
        elif op == "new-instance":
            _, reg, t_idx = item
            output += struct.pack("<HH", (reg << 8) | 0x22, t_idx)
            cur_unit += 2
        elif op == "move-result":
            _, reg = item
            output += struct.pack("<H", (reg << 8) | 0x0A)
            cur_unit += 1
        elif op == "move-result-wide":
            _, reg = item
            output += struct.pack("<H", (reg << 8) | 0x0B)
            cur_unit += 1
        elif op == "move-result-object":
            _, reg = item
            output += struct.pack("<H", (reg << 8) | 0x0C)
            cur_unit += 1
        elif op in ("if-eqz", "if-nez"):
            _, reg, target = item
            target_pos = label_pos[target]
            rel_offset = target_pos - cur_unit
            op_byte = 0x38 if op == "if-eqz" else 0x39
            output += struct.pack("<Hh", (reg << 8) | op_byte, rel_offset)
            cur_unit += 2
        elif op == "add-long":
            _, dest, src1, src2 = item
            output += struct.pack("<HH", (dest << 8) | 0x9B, (src2 << 8) | src1)
            cur_unit += 2
        elif op in op_codes:
            _, m_idx, regs = item
            op_byte = op_codes[op]
            count = len(regs)
            g = regs[4] if count == 5 else 0
            w0 = (count << 12) | (g << 8) | op_byte
            w1 = m_idx
            c = regs[0] if count >= 1 else 0
            d = regs[1] if count >= 2 else 0
            e = regs[2] if count >= 3 else 0
            f = regs[3] if count >= 4 else 0
            w2 = (f << 12) | (e << 8) | (d << 4) | c
            output += struct.pack("<HHH", w0, w1, w2)
            cur_unit += 3
        else:
            raise ValueError(f"Unsupported assemble op: {op}")

    return bytes(output)


def make_dex(pkg_name: str = "com.autostart.factoryhelper", is_test: bool = False, delay_ms: int = 5000) -> bytes:
    target_pkg = pkg_name if is_test else "com.yeker.factorytest.tool"
    target_cls = f"{pkg_name}.TestActivity" if is_test else "com.yeker.factorytest.tool.activity.StartupActivity"
    tag = "AutoStartTest" if is_test else "AutoStartHelper"

    raw_strs = [
        "<init>",
        "I",
        "ILL",
        "J",
        "Z",
        "V",
        "VI",
        "VL",
        "VLL",
        "VJ",
        "VJL",
        "VIJL",
        "L",
        "LL",
        "LLL",
        "LLILI",
        "LI",
        "ZL",
        "Landroid/app/Activity;",
        "Landroid/app/AlarmManager;",
        "Landroid/app/PendingIntent;",
        "Landroid/content/BroadcastReceiver;",
        "Landroid/content/ComponentName;",
        "Landroid/content/Context;",
        "Landroid/content/Intent;",
        "Landroid/os/Bundle;",
        "Landroid/os/SystemClock;",
        "Landroid/util/Log;",
        f"L{pkg_name.replace('.', '/')}/BootReceiver;",
        "Ljava/lang/Object;",
        "Ljava/lang/String;",
        "action",
        "addFlags",
        "alarm",
        "android.intent.action.BOOT_COMPLETED",
        "elapsedRealtime",
        "equals",
        "finish",
        "getAction",
        "getActivity",
        "getSystemService",
        "i",
        "onCreate",
        "onReceive",
        "setClassName",
        "setExact",
        target_pkg,
        target_cls,
        tag,
        "BOOT_RECEIVED",
        "ALARM_SCHEDULED",
        "ALARM_FIRED",
    ]
    if is_test:
        raw_strs.append(f"L{pkg_name.replace('.', '/')}/TestActivity;")

    strs = sorted(list(set(raw_strs)))
    s_idx = {s: i for i, s in enumerate(strs)}

    raw_types = [
        "V", "I", "J", "Z",
        "Landroid/app/Activity;",
        "Landroid/app/AlarmManager;",
        "Landroid/app/PendingIntent;",
        "Landroid/content/BroadcastReceiver;",
        "Landroid/content/ComponentName;",
        "Landroid/content/Context;",
        "Landroid/content/Intent;",
        "Landroid/os/Bundle;",
        "Landroid/os/SystemClock;",
        "Landroid/util/Log;",
        f"L{pkg_name.replace('.', '/')}/BootReceiver;",
        "Ljava/lang/Object;",
        "Ljava/lang/String;",
    ]
    if is_test:
        raw_types.append(f"L{pkg_name.replace('.', '/')}/TestActivity;")

    type_strs = sorted(list(set(raw_types)), key=lambda s: s_idx[s])
    t_idx = {s: i for i, s in enumerate(type_strs)}

    proto_defs = [
        ("V", "V", []),
        ("VL", "V", ["Landroid/os/Bundle;"]),
        ("VLL", "V", ["Landroid/content/Context;", "Landroid/content/Intent;"]),
        ("VIJL", "V", ["I", "J", "Landroid/app/PendingIntent;"]),
        ("L", "Ljava/lang/String;", []),
        ("LL", "Ljava/lang/Object;", ["Ljava/lang/String;"]),
        ("ZL", "Z", ["Ljava/lang/Object;"]),
        ("J", "J", []),
        ("LLILI", "Landroid/app/PendingIntent;", ["Landroid/content/Context;", "I", "Landroid/content/Intent;", "I"]),
        ("LI", "Landroid/content/Intent;", ["I"]),
        ("LLL", "Landroid/content/Intent;", ["Ljava/lang/String;", "Ljava/lang/String;"]),
        ("ILL", "I", ["Ljava/lang/String;", "Ljava/lang/String;"]),
    ]
    proto_defs.sort(key=lambda p: (t_idx[p[1]], [t_idx[x] for x in p[2]]))
    p_idx = {(p[1], tuple(p[2])): i for i, p in enumerate(proto_defs)}

    raw_methods = [
        ("Landroid/app/Activity;", "V", (), "<init>"),
        ("Landroid/app/Activity;", "V", ("Landroid/os/Bundle;",), "onCreate"),
        ("Landroid/app/Activity;", "V", (), "finish"),
        ("Landroid/app/AlarmManager;", "V", ("I", "J", "Landroid/app/PendingIntent;"), "setExact"),
        ("Landroid/app/PendingIntent;", "Landroid/app/PendingIntent;", ("Landroid/content/Context;", "I", "Landroid/content/Intent;", "I"), "getActivity"),
        ("Landroid/content/BroadcastReceiver;", "V", (), "<init>"),
        ("Landroid/content/Context;", "Ljava/lang/Object;", ("Ljava/lang/String;",), "getSystemService"),
        ("Landroid/content/Intent;", "V", (), "<init>"),
        ("Landroid/content/Intent;", "Ljava/lang/String;", (), "getAction"),
        ("Landroid/content/Intent;", "Landroid/content/Intent;", ("I",), "addFlags"),
        ("Landroid/content/Intent;", "Landroid/content/Intent;", ("Ljava/lang/String;", "Ljava/lang/String;"), "setClassName"),
        ("Landroid/os/SystemClock;", "J", (), "elapsedRealtime"),
        ("Landroid/util/Log;", "I", ("Ljava/lang/String;", "Ljava/lang/String;"), "i"),
        (f"L{pkg_name.replace('.', '/')}/BootReceiver;", "V", (), "<init>"),
        (f"L{pkg_name.replace('.', '/')}/BootReceiver;", "V", ("Landroid/content/Context;", "Landroid/content/Intent;"), "onReceive"),
        ("Ljava/lang/String;", "Z", ("Ljava/lang/Object;",), "equals"),
    ]
    if is_test:
        raw_methods.extend([
            (f"L{pkg_name.replace('.', '/')}/TestActivity;", "V", (), "<init>"),
            (f"L{pkg_name.replace('.', '/')}/TestActivity;", "V", ("Landroid/os/Bundle;",), "onCreate"),
        ])

    method_defs = sorted(raw_methods, key=lambda m: (t_idx[m[0]], s_idx[m[3]], p_idx[(m[1], tuple(m[2]))]))
    m_idx = {(m[0], m[3], tuple(m[2])): i for i, m in enumerate(method_defs)}

    hdr_size = 0x70
    str_ids_off = hdr_size
    type_ids_off = str_ids_off + len(strs) * 4
    proto_ids_off = type_ids_off + len(type_strs) * 4
    method_ids_off = proto_ids_off + len(proto_defs) * 12
    num_classes = 2 if is_test else 1
    class_defs_off = method_ids_off + len(method_defs) * 8
    data_off = class_defs_off + num_classes * 32

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

    # Method 1: BootReceiver.<init>
    align4()
    code_boot_init_off = data_off + len(data)
    insns_boot_init = assemble([
        ("invoke-direct", m_idx[("Landroid/content/BroadcastReceiver;", "<init>", ())], [0]),
        ("return-void",),
    ])
    data += struct.pack("<HHHHII", 1, 1, 1, 0, 0, len(insns_boot_init) // 2) + insns_boot_init

    # Method 2: BootReceiver.onReceive
    # Registers: 12 total.
    # ins: v9 (p0=this), v10 (p1=context), v11 (p2=intent)
    # locals: v0 - v8
    align4()
    code_boot_onrec_off = data_off + len(data)
    insns_boot_onrec = assemble([
        # 1. Null intent check
        ("if-eqz", 11, ":ret"),
        # 2. Extract action
        ("invoke-virtual", m_idx[("Landroid/content/Intent;", "getAction", ())], [11]),
        ("move-result-object", 0),
        ("if-eqz", 0, ":ret"),
        # 3. Verify BOOT_COMPLETED action
        ("const-string", 1, s_idx["android.intent.action.BOOT_COMPLETED"]),
        ("invoke-virtual", m_idx[("Ljava/lang/String;", "equals", ("Ljava/lang/Object;",))], [1, 0]),
        ("move-result", 0),
        ("if-eqz", 0, ":ret"),

        # 4. Log BOOT_RECEIVED
        ("const-string", 1, s_idx[tag]),
        ("const-string", 2, s_idx["BOOT_RECEIVED"]),
        ("invoke-static", m_idx[("Landroid/util/Log;", "i", ("Ljava/lang/String;", "Ljava/lang/String;"))], [1, 2]),

        # 5. Build target Intent
        ("new-instance", 0, t_idx["Landroid/content/Intent;"]),
        ("invoke-direct", m_idx[("Landroid/content/Intent;", "<init>", ())], [0]),
        ("const-string", 1, s_idx[target_pkg]),
        ("const-string", 2, s_idx[target_cls]),
        ("invoke-virtual", m_idx[("Landroid/content/Intent;", "setClassName", ("Ljava/lang/String;", "Ljava/lang/String;"))], [0, 1, 2]),
        ("const/high16", 1, 0x1000),  # FLAG_ACTIVITY_NEW_TASK
        ("invoke-virtual", m_idx[("Landroid/content/Intent;", "addFlags", ("I",))], [0, 1]),

        # 6. PendingIntent.getActivity
        ("const/4", 1, 0),
        ("const/high16", 2, 0x1000),  # FLAG_CANCEL_CURRENT
        ("invoke-static", m_idx[("Landroid/app/PendingIntent;", "getActivity", ("Landroid/content/Context;", "I", "Landroid/content/Intent;", "I"))], [10, 1, 0, 2]),
        ("move-result-object", 3),  # v3 = pi

        # 7. AlarmManager am = (AlarmManager) context.getSystemService("alarm")
        ("const-string", 1, s_idx["alarm"]),
        ("invoke-virtual", m_idx[("Landroid/content/Context;", "getSystemService", ("Ljava/lang/String;",))], [10, 1]),
        ("move-result-object", 4),
        # P0 Fix: Explicit check-cast required by Dalvik bytecode verifier
        ("check-cast", 4, t_idx["Landroid/app/AlarmManager;"]),

        # 8. long trigger = SystemClock.elapsedRealtime() + delay_ms
        ("invoke-static", m_idx[("Landroid/os/SystemClock;", "elapsedRealtime", ())], []),
        ("move-result-wide", 5),  # now in v5, v6
        ("const-wide/16", 7, delay_ms),
        ("add-long", 5, 5, 7),  # trigger in v5, v6

        # 9. am.setExact(2, trigger, pi)
        ("const/4", 1, 2),  # ELAPSED_REALTIME_WAKEUP
        ("invoke-virtual", m_idx[("Landroid/app/AlarmManager;", "setExact", ("I", "J", "Landroid/app/PendingIntent;"))], [4, 1, 5, 6, 3]),

        # 10. Log ALARM_SCHEDULED
        ("const-string", 1, s_idx[tag]),
        ("const-string", 2, s_idx["ALARM_SCHEDULED"]),
        ("invoke-static", m_idx[("Landroid/util/Log;", "i", ("Ljava/lang/String;", "Ljava/lang/String;"))], [1, 2]),

        # Exit point: branches land directly here on return-void
        ":ret",
        ("return-void",),
    ])
    data += struct.pack("<HHHHII", 12, 3, 5, 0, 0, len(insns_boot_onrec) // 2) + insns_boot_onrec

    if is_test:
        # Method 3: TestActivity.<init>
        align4()
        code_act_init_off = data_off + len(data)
        insns_act_init = assemble([
            ("invoke-direct", m_idx[("Landroid/app/Activity;", "<init>", ())], [0]),
            ("return-void",),
        ])
        data += struct.pack("<HHHHII", 1, 1, 1, 0, 0, len(insns_act_init) // 2) + insns_act_init

        # Method 4: TestActivity.onCreate
        # Registers: 4 total. ins: v2 (p0=this), v3 (p1=savedInstanceState). locals: v0, v1
        align4()
        code_act_oncreate_off = data_off + len(data)
        insns_act_oncreate = assemble([
            ("invoke-super", m_idx[("Landroid/app/Activity;", "onCreate", ("Landroid/os/Bundle;",))], [2, 3]),
            # Log ALARM_FIRED
            ("const-string", 0, s_idx[tag]),
            ("const-string", 1, s_idx["ALARM_FIRED"]),
            ("invoke-static", m_idx[("Landroid/util/Log;", "i", ("Ljava/lang/String;", "Ljava/lang/String;"))], [0, 1]),
            ("invoke-virtual", m_idx[("Landroid/app/Activity;", "finish", ())], [2]),
            ("return-void",),
        ])
        data += struct.pack("<HHHHII", 4, 2, 2, 0, 0, len(insns_act_oncreate) // 2) + insns_act_oncreate

    # String data pool
    str_data_offs = []
    for s in strs:
        str_data_offs.append(data_off + len(data))
        b = s.encode("utf-8")
        data += uleb128(len(s)) + b + b"\x00"

    # Class data 1: BootReceiver
    class_data_boot_off = data_off + len(data)
    m_boot_init = m_idx[(f"L{pkg_name.replace('.', '/')}/BootReceiver;", "<init>", ())]
    m_boot_onrec = m_idx[(f"L{pkg_name.replace('.', '/')}/BootReceiver;", "onReceive", ("Landroid/content/Context;", "Landroid/content/Intent;"))]
    data += (
        uleb128(0) + uleb128(0) + uleb128(1) + uleb128(1)
        + uleb128(m_boot_init) + uleb128(0x10001) + uleb128(code_boot_init_off)
        + uleb128(m_boot_onrec) + uleb128(0x0001) + uleb128(code_boot_onrec_off)
    )

    if is_test:
        # Class data 2: TestActivity
        class_data_act_off = data_off + len(data)
        m_act_init = m_idx[(f"L{pkg_name.replace('.', '/')}/TestActivity;", "<init>", ())]
        m_act_oncreate = m_idx[(f"L{pkg_name.replace('.', '/')}/TestActivity;", "onCreate", ("Landroid/os/Bundle;",))]
        data += (
            uleb128(0) + uleb128(0) + uleb128(1) + uleb128(1)
            + uleb128(m_act_init) + uleb128(0x10001) + uleb128(code_act_init_off)
            + uleb128(m_act_oncreate) + uleb128(0x0004) + uleb128(code_act_oncreate_off)
        )

    align4()
    map_off = data_off + len(data)
    map_items = [
        (0x0000, 1, 0),
        (0x0001, len(strs), str_ids_off),
        (0x0002, len(type_strs), type_ids_off),
        (0x0003, len(proto_defs), proto_ids_off),
        (0x0005, len(method_defs), method_ids_off),
        (0x0006, num_classes, class_defs_off),
        (0x1001, sum(1 for v in typelist_offs.values() if v != 0), min(v for v in typelist_offs.values() if v != 0)),
        (0x2001, 4 if is_test else 2, code_boot_init_off),
        (0x2002, len(strs), str_data_offs[0]),
        (0x2000, num_classes, class_data_boot_off),
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
        struct.pack("<III", s_idx[shorty], t_idx[ret], typelist_offs[(ret, tuple(params))])
        for shorty, ret, params in proto_defs
    )
    method_ids_bin = b"".join(
        struct.pack("<HHI", t_idx[c], p_idx[(r, tuple(p))], s_idx[n])
        for c, r, p, n in method_defs
    )

    class_defs_bin = struct.pack(
        "<IIIIIIII",
        t_idx[f"L{pkg_name.replace('.', '/')}/BootReceiver;"],
        0x0001,
        t_idx["Landroid/content/BroadcastReceiver;"],
        0,
        0xFFFFFFFF,
        0,
        class_data_boot_off,
        0,
    )
    if is_test:
        class_defs_bin += struct.pack(
            "<IIIIIIII",
            t_idx[f"L{pkg_name.replace('.', '/')}/TestActivity;"],
            0x0001,
            t_idx["Landroid/app/Activity;"],
            0,
            0xFFFFFFFF,
            0,
            class_data_act_off,
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
        + struct.pack("<II", num_classes, class_defs_off)
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


def build_signed_apk(
    out_path: pathlib.Path,
    key_path: pathlib.Path,
    pkg_name: str = "com.autostart.factoryhelper",
    is_test: bool = False,
    delay_ms: int = 5000,
    exported: bool = False,
):
    axml = make_axml(pkg_name=pkg_name, is_test=is_test, exported=exported)
    dex = make_dex(pkg_name=pkg_name, is_test=is_test, delay_ms=delay_ms)

    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError("An RSA private key is required")
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

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("AndroidManifest.xml", axml)
        z.writestr("classes.dex", dex)
        z.writestr("META-INF/MANIFEST.MF", manifest_mf)
        z.writestr("META-INF/CERT.SF", cert_sf)
        z.writestr("META-INF/CERT.RSA", cert_rsa)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Zero-SDK Python generator for AutoStartHelper APK")
    parser.add_argument("--key", type=pathlib.Path, required=True, help="Path to RSA private key")
    parser.add_argument("--init-key", action="store_true", help="Create a NEW key; never overwrite an existing one")
    parser.add_argument("--output", type=pathlib.Path, default=None, help="Output APK path")
    parser.add_argument("--test-mode", action="store_true", help="Build independent test APK (com.autostart.factoryhelper.test)")
    parser.add_argument("--delay-ms", type=int, default=5000, help="Delay before firing target Intent in milliseconds")
    parser.add_argument("--exported", action="store_true", default=False, help="Set receiver exported (default: False)")

    args = parser.parse_args()
    if args.init_key:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        with args.key.open("xb") as stream:
            stream.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        args.key.chmod(0o600)
    if not args.key.is_file():
        parser.error("Key not found. Use --init-key once, then reuse the same --key.")

    repo_configs = pathlib.Path(__file__).resolve().parent.parent / "configs"
    if args.output is None:
        if args.test_mode:
            args.output = repo_configs / "AutoStartHelper_test.apk"
        else:
            args.output = repo_configs / "AutoStartHelper.apk"

    pkg_name = "com.autostart.factoryhelper.test" if args.test_mode else "com.autostart.factoryhelper"
    build_signed_apk(
        args.output,
        args.key,
        pkg_name=pkg_name,
        is_test=args.test_mode,
        delay_ms=args.delay_ms,
        exported=args.exported,
    )
    print(f"[+] Built signed APK ({'TEST' if args.test_mode else 'PROD'}): {args.output} (pkg: {pkg_name})")
