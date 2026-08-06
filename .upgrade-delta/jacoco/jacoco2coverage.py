#!/usr/bin/env python3
"""
jacoco2coverage — convert per-test JaCoCo .exec files into the router's coverage.json.

JaCoCo exec binary format (ExecutionDataWriter / CompactDataOutput):
  file  = sequence of blocks, first byte = block type
  0x01  header:        char magic 0xC0C0, char format version (0x1007)
  0x10  session info:  UTF id, long start, long dump
  0x11  execution data: long classid, UTF vmname, boolean[] probes
        boolean[] = varint count, then bits packed LSB-first, 8 per byte
  varint = 7 bits/byte, high bit is the continuation flag

Convention: one .exec per test class, named <TestClassName>.exec — produced by the
Maven profile in pom-profile.xml (fresh agent session per test class, see README).
A class counts as covered by a test when ANY of its probes is true.

Usage:
  jacoco2coverage.py DIR_OF_EXEC_FILES --sha <map-sha> --build <id> --age-commits N \
      [--only-prefix com/example/payments] -o coverage.json
  jacoco2coverage.py --selftest       # writer/reader round-trip on synthetic data
"""
import argparse, io, json, os, struct, sys

MAGIC, VERSION = 0xC0C0, 0x1007


# ------------------------------------------------------------------ reader

def _read_utf(f):
    (n,) = struct.unpack(">H", f.read(2))
    return f.read(n).decode("utf-8")


def _read_varint(f):
    result, shift = 0, 0
    while True:
        b = f.read(1)[0]
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result
        shift += 7


def _read_bool_array(f):
    n = _read_varint(f)
    out, buf, bits = [], 0, 0
    for _ in range(n):
        if bits == 0:
            buf, bits = f.read(1)[0], 8
        out.append(bool(buf & 1))
        buf >>= 1
        bits -= 1
    return out


def read_exec(path):
    """-> (sessions, {vmname: any_probe_true})"""
    sessions, classes = [], {}
    with open(path, "rb") as fh:
        f = io.BufferedReader(fh)
        while True:
            t = f.read(1)
            if not t:
                break
            t = t[0]
            if t == 0x01:
                magic, ver = struct.unpack(">HH", f.read(4))
                if magic != MAGIC:
                    raise ValueError(f"{path}: bad magic {magic:#x}")
                if ver != VERSION:
                    print(f"  ! {path}: format version {ver:#x} (expected {VERSION:#x}) "
                          f"— parsing anyway", file=sys.stderr)
            elif t == 0x10:
                sid = _read_utf(f)
                start, dump = struct.unpack(">qq", f.read(16))
                sessions.append({"id": sid, "start": start, "dump": dump})
            elif t == 0x11:
                (_classid,) = struct.unpack(">q", f.read(8))
                name = _read_utf(f)
                probes = _read_bool_array(f)
                covered = any(probes)
                classes[name] = classes.get(name, False) or covered
            else:
                raise ValueError(f"{path}: unknown block type {t:#x}")
    return sessions, classes


# ------------------------------------------------------------------ writer (tests only)

def _w_utf(b, s):
    e = s.encode("utf-8")
    b += struct.pack(">H", len(e)) + e
    return b


def _w_varint(b, n):
    while True:
        if n < 0x80:
            b.append(n)
            return b
        b.append((n & 0x7F) | 0x80)
        n >>= 7


def _w_bools(b, arr):
    _w_varint(b, len(arr))
    buf, bits = 0, 0
    for v in arr:
        buf |= (1 if v else 0) << bits
        bits += 1
        if bits == 8:
            b.append(buf)
            buf, bits = 0, 0
    if bits:
        b.append(buf)
    return b


def write_exec(path, session_id, class_probes):
    b = bytearray()
    b.append(0x01)
    b += struct.pack(">HH", MAGIC, VERSION)
    b.append(0x10)
    b = bytearray(_w_utf(b, session_id))
    b += struct.pack(">qq", 1700000000000, 1700000001000)
    for name, probes in class_probes.items():
        b.append(0x11)
        b += struct.pack(">q", hash(name) & 0x7FFFFFFFFFFFFFFF)
        b = bytearray(_w_utf(b, name))
        _w_bools(b, probes)
    with open(path, "wb") as f:
        f.write(bytes(b))


# ------------------------------------------------------------------ convert

def convert(exec_dir, out, sha, build, age, only_prefix=None):
    tests = {}
    for f in sorted(os.listdir(exec_dir)):
        if not f.endswith(".exec"):
            continue
        test = f[:-5]
        _s, classes = read_exec(os.path.join(exec_dir, f))
        covers = sorted(n.replace("/", ".") for n, hit in classes.items()
                        if hit and (only_prefix is None
                                    or n.startswith(only_prefix)))
        tests[test] = {"covers": covers}
        print(f"  {test}: {len(covers)} covered class(es)")
    doc = {"collected_at_sha": sha, "build": build, "age_commits": age, "tests": tests}
    with open(out, "w") as f:
        json.dump(doc, f, indent=2)
    print(f"wrote {out} ({len(tests)} tests)")


def selftest():
    import tempfile
    d = tempfile.mkdtemp()
    write_exec(os.path.join(d, "AlphaTest.exec"), "AlphaTest", {
        "com/example/payments/PaymentService": [True, False, True],
        "com/example/payments/Ledger": [False] * 9,       # loaded, never executed
        "org/yaml/snakeyaml/Yaml": [True] * 4,          # dependency class
    })
    write_exec(os.path.join(d, "BetaTest.exec"), "BetaTest", {
        "com/example/payments/GatewayClient": [False] * 260 + [True],  # multi-byte varint+packing
    })
    _s, a = read_exec(os.path.join(d, "AlphaTest.exec"))
    _s, b = read_exec(os.path.join(d, "BetaTest.exec"))
    assert a["com/example/payments/PaymentService"] is True
    assert a["com/example/payments/Ledger"] is False, "all-false probes must NOT count as covered"
    assert b["com/example/payments/GatewayClient"] is True, "probe 261 lost in bit packing"
    out = os.path.join(d, "coverage.json")
    convert(d, out, "abc1234", "#1288", 3, only_prefix="com/example/payments")
    doc = json.load(open(out))
    assert doc["tests"]["AlphaTest"]["covers"] == ["com.example.payments.PaymentService"], \
        "prefix filter must drop dependency classes and unexecuted classes"
    assert doc["tests"]["BetaTest"]["covers"] == ["com.example.payments.GatewayClient"]
    print("SELFTEST PASS: round-trip, bit packing, varint, probe semantics, prefix filter")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("exec_dir", nargs="?")
    ap.add_argument("-o", "--out", default="coverage.json")
    ap.add_argument("--sha", default="unknown")
    ap.add_argument("--build", default="unknown")
    ap.add_argument("--age-commits", type=int, default=0)
    ap.add_argument("--only-prefix", help="keep only classes under this internal-name prefix")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        selftest()
    else:
        if not args.exec_dir:
            ap.error("exec_dir required (or --selftest)")
        convert(args.exec_dir, args.out, args.sha, args.build,
                args.age_commits, args.only_prefix)
