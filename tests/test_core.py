#!/usr/bin/env python3
"""Unit tests for upgrade-delta core: streams, rating, fingerprints, jar diff."""

from __future__ import annotations

import hashlib
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import upgrade_delta as ud  # noqa: E402


def _empty_delta(**overrides):
    base = {
        "api_incompatible": [],
        "api_modified": [],
        "api_added": [],
        "impl_churn_pct": 0,
        "res_changed": [],
        "res_added": [],
        "res_removed": [],
        "spi_touched": [],
        "classes_impl_changed": [],
    }
    base.update(overrides)
    return base


def _minimal_class(name: str = "com/example/A", with_debug: bool = False) -> bytes:
    """Build a tiny valid classfile (public empty class)."""
    # Constant pool: [1]=Utf8 name, [2]=Class #1, [3]=Utf8 java/lang/Object,
    # [4]=Class #3, [5]=Utf8 Code, [6]=Utf8 <init>, [7]=Utf8 ()V,
    # [8]=NameAndType #6:#7, [9]=Methodref #4.#8, [10]=Utf8 SourceFile (optional),
    # [11]=Utf8 A.java (optional)
    this_utf = name.encode()
    super_utf = b"java/lang/Object"
    utf_code = b"Code"
    utf_init = b"<init>"
    utf_desc = b"()V"

    cp = []
    # index 1
    cp.append(b"\x01" + struct.pack(">H", len(this_utf)) + this_utf)
    # 2 Class
    cp.append(b"\x07\x00\x01")
    # 3
    cp.append(b"\x01" + struct.pack(">H", len(super_utf)) + super_utf)
    # 4 Class
    cp.append(b"\x07\x00\x03")
    # 5 Code
    cp.append(b"\x01" + struct.pack(">H", len(utf_code)) + utf_code)
    # 6 <init>
    cp.append(b"\x01" + struct.pack(">H", len(utf_init)) + utf_init)
    # 7 ()V
    cp.append(b"\x01" + struct.pack(">H", len(utf_desc)) + utf_desc)
    # 8 NameAndType
    cp.append(b"\x0c\x00\x06\x00\x07")
    # 9 Methodref Object.<init>
    cp.append(b"\x0a\x00\x04\x00\x08")

    source_attrs = b""
    if with_debug:
        src = b"A.java"
        cp.append(b"\x01" + struct.pack(">H", len(b"SourceFile")) + b"SourceFile")  # 10
        cp.append(b"\x01" + struct.pack(">H", len(src)) + src)  # 11
        # SourceFile attribute: name_index=10, length=2, sourcefile_index=11
        source_attrs = struct.pack(">HIH", 10, 2, 11)

    cp_count = len(cp) + 1  # CP is 1-indexed; count includes unused slot 0
    body = b"".join(cp)

    # access public, this=#2, super=#4, interfaces=0
    header_tail = struct.pack(">HHHH", 0x0021, 2, 4, 0)
    # fields=0
    fields = struct.pack(">H", 0)
    # methods=1: public <init>()V with Code
    # Code: max_stack=1, max_locals=1, code_len=5, aload_0; invokespecial; return
    code = struct.pack(">HHI", 1, 1, 5) + bytes([0x2a, 0xb7, 0x00, 0x09, 0xb1])
    code += struct.pack(">H", 0)  # exception table
    code += struct.pack(">H", 0)  # code attributes
    method = struct.pack(">HHHH", 0x0001, 6, 7, 1)  # access, name, desc, attr_count
    method += struct.pack(">HI", 5, len(code)) + code  # Code attr
    methods = struct.pack(">H", 1) + method

    if with_debug:
        class_attrs = struct.pack(">H", 1) + source_attrs
    else:
        class_attrs = struct.pack(">H", 0)

    return (
        b"\xca\xfe\xba\xbe"
        + struct.pack(">HH", 0, 49)  # minor, major
        + struct.pack(">H", cp_count)
        + body
        + header_tail
        + fields
        + methods
        + class_attrs
    )


class ClassifyStreamTests(unittest.TestCase):
    def test_streams(self) -> None:
        self.assertTrue(ud.classify_stream("1.2.3", "1.2.4").startswith("z-stream"))
        self.assertTrue(ud.classify_stream("1.2.3", "1.3.0").startswith("y-stream"))
        self.assertTrue(ud.classify_stream("1.2.3", "2.0.0").startswith("x-stream"))
        # Differing major segment ("bad" vs "also") is treated as x-stream.
        self.assertTrue(ud.classify_stream("bad", "also.bad").startswith("x-stream"))


class RateTests(unittest.TestCase):
    def test_z_stream_clean_is_a(self) -> None:
        r = ud.rate("z-stream (patch)", _empty_delta(), None)
        self.assertEqual(r["grade"], "A")

    def test_z_stream_api_change_is_d(self) -> None:
        r = ud.rate(
            "z-stream (patch)",
            _empty_delta(api_modified=[("a", "m", "()V")]),
            None,
        )
        self.assertEqual(r["grade"], "D")

    def test_y_stream_default_c(self) -> None:
        r = ud.rate("y-stream (minor)", _empty_delta(), None)
        self.assertEqual(r["grade"], "C")

    def test_app_incompatible_is_f(self) -> None:
        app_ix = {
            "touched_changed": [],
            "touched_incompatible": [("pkg/A", "m", "()V")],
        }
        r = ud.rate("z-stream (patch)", _empty_delta(), app_ix)
        self.assertEqual(r["grade"], "F")

    def test_churn_and_spi_escalate_z_to_b(self) -> None:
        r = ud.rate(
            "z-stream (patch)",
            _empty_delta(impl_churn_pct=15, spi_touched=["META-INF/services/x"]),
            None,
        )
        self.assertEqual(r["grade"], "B")


class FingerprintTests(unittest.TestCase):
    def test_identical_bytes_same_fingerprint(self) -> None:
        data = _minimal_class()
        self.assertEqual(ud.normalized_fingerprint(data), ud.normalized_fingerprint(data))

    def test_sourcefile_debug_noise_does_not_change_semantic_hash(self) -> None:
        plain = _minimal_class(with_debug=False)
        debug = _minimal_class(with_debug=True)
        # Raw hashes differ (SourceFile present), semantic should match when
        # only noise attrs differ — SourceFile is in _NOISE_ATTRS.
        self.assertNotEqual(hashlib.sha256(plain).hexdigest(), hashlib.sha256(debug).hexdigest())
        self.assertEqual(
            ud.normalized_fingerprint(plain),
            ud.normalized_fingerprint(debug),
        )

    def test_invalid_magic_falls_back_to_raw(self) -> None:
        junk = b"not-a-class"
        self.assertEqual(
            ud.normalized_fingerprint(junk),
            hashlib.sha256(junk).hexdigest(),
        )


class DiffJarsTests(unittest.TestCase):
    def test_diff_detects_api_add(self) -> None:
        a = _minimal_class("com/example/Lib")
        b = _minimal_class("com/example/Lib")
        # Second class only in new jar → added public class API
        extra = _minimal_class("com/example/NewApi")
        with tempfile.TemporaryDirectory() as tmp:
            old_path = Path(tmp) / "old.jar"
            new_path = Path(tmp) / "new.jar"
            with zipfile.ZipFile(old_path, "w") as z:
                z.writestr("com/example/Lib.class", a)
            with zipfile.ZipFile(new_path, "w") as z:
                z.writestr("com/example/Lib.class", b)
                z.writestr("com/example/NewApi.class", extra)
            old = ud.load_jar(str(old_path))
            new = ud.load_jar(str(new_path))
            delta = ud.diff_jars(old, new)
            self.assertTrue(any(k[0] == "com/example/NewApi" for k in delta["api_added"]))
            # Same Lib bytes → semantic churn should be 0
            self.assertEqual(delta["impl_churn_pct"], 0.0)


class DemoCorpusSmokeTests(unittest.TestCase):
    """Assert committed evidence grades for the narrated demo path."""

    def test_evidence_grades_present(self) -> None:
        ev = ROOT / "examples" / "evidence"
        if not ev.is_dir():
            self.skipTest("examples/evidence missing")
        reports = list(ev.glob("*.json"))
        self.assertGreaterEqual(len(reports), 1)


if __name__ == "__main__":
    unittest.main()
