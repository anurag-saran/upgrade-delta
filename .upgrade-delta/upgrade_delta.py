#!/usr/bin/env python3
"""
upgrade-delta — measure how much a library upgrade actually changed,
intersect it with YOUR application, and turn the result into a rating,
a recommended test scope, and an evidence report you can hand to a
change advisory board.

Zero dependencies. Parses .class files directly (no JVM required).

Subcommands:
  analyze  old.jar new.jar [--app app.jar] [--old-version V] [--new-version V]
           [--library NAME] [--json out.json] [--html out.html]
  publish  report1.json report2.json ... --out site_dir/
"""

import argparse
import hashlib
import re
import html as html_mod
import json
import os
import struct
import sys
import zipfile
from collections import defaultdict
from datetime import date

TOOL_VERSION = "0.1.0"

# ---------------------------------------------------------------- class parsing

ACC_PUBLIC = 0x0001
ACC_PRIVATE = 0x0002
ACC_PROTECTED = 0x0004
ACC_STATIC = 0x0008
ACC_FINAL = 0x0010
ACC_ABSTRACT = 0x0400
ACC_SYNTHETIC = 0x1000

CP_SLOT2 = {5, 6}  # Long, Double take two constant-pool slots


def _parse_constant_pool(data, off, count):
    """Return (pool, new_offset). pool maps index -> (tag, value)."""
    pool = {}
    i = 1
    while i < count:
        tag = data[off]
        off += 1
        if tag == 1:  # Utf8
            (length,) = struct.unpack_from(">H", data, off)
            off += 2
            pool[i] = (tag, data[off:off + length].decode("utf-8", "replace"))
            off += length
        elif tag in (3, 4):  # Int, Float (keep raw bits: value identity, not float quirks)
            pool[i] = (tag, data[off:off + 4]); off += 4
        elif tag in (5, 6):  # Long, Double
            pool[i] = (tag, data[off:off + 8]); off += 8
        elif tag in (7, 8, 16, 19, 20):  # Class, String, MethodType, Module, Package
            (idx,) = struct.unpack_from(">H", data, off)
            pool[i] = (tag, idx); off += 2
        elif tag in (9, 10, 11, 12, 17, 18):  # refs, NameAndType, Dynamic
            a, b = struct.unpack_from(">HH", data, off)
            pool[i] = (tag, (a, b)); off += 4
        elif tag == 15:  # MethodHandle (kind + ref index)
            pool[i] = (tag, (data[off], struct.unpack_from(">H", data, off + 1)[0])); off += 3
        else:
            raise ValueError(f"unknown constant pool tag {tag}")
        i += 2 if tag in CP_SLOT2 else 1
    return pool, off


def _utf8(pool, idx):
    tag, val = pool.get(idx, (None, None))
    return val if tag == 1 else None


def _class_name(pool, idx):
    tag, val = pool.get(idx, (None, None))
    if tag == 7:
        return _utf8(pool, val)
    return None




# CP-indexed operand extraction (shares the width logic of the normalizer)
_CP_OPS_2 = {19, 20, 178, 179, 180, 181, 182, 183, 184, 187, 189, 192, 193}

def extract_code_refs(code, pool):
    """Per-method outbound refs: (member refs, class uses) from one Code body."""
    refs, uses, i, n = set(), set(), 0, len(code)
    def cp_member(idx):
        e = pool.get(idx)
        if e and e[0] in (9, 10, 11):
            cls = _class_name(pool, e[1][0])
            nat = pool.get(e[1][1])
            if cls and nat and nat[0] == 12:
                refs.add((cls, _utf8(pool, nat[1][0]), _utf8(pool, nat[1][1])))
        elif e and e[0] == 7:
            cn = _utf8(pool, e[1])
            if cn and not cn.startswith("["):
                uses.add(cn)
    while i < n:
        op = code[i]; start = i; i += 1
        if op == 18:
            cp_member(code[i]); i += 1
        elif op in _CP_OPS_2:
            (idx,) = struct.unpack_from(">H", code, i); cp_member(idx); i += 2
        elif op in (185, 186):
            (idx,) = struct.unpack_from(">H", code, i); cp_member(idx); i += 4
        elif op == 197:
            (idx,) = struct.unpack_from(">H", code, i); cp_member(idx); i += 3
        elif op == 196:
            i += 5 if code[i] == 132 else 3
        elif op == 170:
            i += (4 - ((start + 1) % 4)) % 4
            _d, lo, hi = struct.unpack_from(">iii", code, i); i += 12 + 4 * (hi - lo + 1)
        elif op == 171:
            i += (4 - ((start + 1) % 4)) % 4
            _d, npairs = struct.unpack_from(">ii", code, i); i += 8 + 8 * npairs
        elif op in _OP1:
            i += 1
        elif op in _OP2_PLAIN:
            i += 2
        elif op in _OP4:
            i += 4
    return refs, uses


def parse_class(data):
    """Parse one .class file. Returns dict with name, access, members, refs."""
    if data[:4] != b"\xca\xfe\xba\xbe":
        return None
    (cp_count,) = struct.unpack_from(">H", data, 8)
    pool, off = _parse_constant_pool(data, 10, cp_count)
    access, this_c, _super_c = struct.unpack_from(">HHH", data, off)
    off += 6
    name = _class_name(pool, this_c)
    super_name = _class_name(pool, _super_c)
    (if_count,) = struct.unpack_from(">H", data, off)
    off += 2
    interfaces = []
    for _i in range(if_count):
        (ii,) = struct.unpack_from(">H", data, off)
        off += 2
        cn = _class_name(pool, ii)
        if cn:
            interfaces.append(cn)

    members = []
    for _section in range(2):  # fields then methods
        (n,) = struct.unpack_from(">H", data, off)
        off += 2
        for _ in range(n):
            m_access, name_i, desc_i, attr_n = struct.unpack_from(">HHHH", data, off)
            off += 8
            m_calls, m_uses = set(), set()
            for _a in range(attr_n):
                ai, alen = struct.unpack_from(">HI", data, off)
                body = data[off + 6:off + 6 + alen]
                off += 6 + alen
                if _section == 1 and _utf8(pool, ai) == "Code" and len(body) >= 8:
                    (clen,) = struct.unpack_from(">I", body, 4)
                    try:
                        m_calls, m_uses = extract_code_refs(body[8:8 + clen], pool)
                    except Exception:
                        m_calls, m_uses = set(), set()   # over-approx handled by class refs
            members.append({
                "kind": "field" if _section == 0 else "method",
                "name": _utf8(pool, name_i),
                "desc": _utf8(pool, desc_i),
                "access": m_access,
                "calls": m_calls, "uses": m_uses,
            })

    # outbound references (for app intersection): Fieldref/Methodref/InterfaceMethodref
    refs = set()
    class_refs = set()
    for idx, (tag, val) in pool.items():
        if tag in (9, 10, 11):
            cls_i, nat_i = val
            cls = _class_name(pool, cls_i)
            nat = pool.get(nat_i)
            if cls and nat and nat[0] == 12:
                n_i, d_i = nat[1]
                refs.add((cls, _utf8(pool, n_i), _utf8(pool, d_i)))
        elif tag == 7:
            cn = _utf8(pool, val)
            if cn and not cn.startswith("["):
                class_refs.add(cn)
    strings = set()
    for _idx, (tag, val) in pool.items():
        if tag == 8:
            s = _utf8(pool, val)
            if s:
                strings.add(s)
    return {"name": name, "access": access, "super": super_name,
            "interfaces": interfaces, "members": members,
            "refs": refs, "class_refs": class_refs, "strings": strings}




# ------------------------------------------------- semantic fingerprint (churn)

# Attributes that are build metadata, not behavior. Their presence/content varies
# across javac versions and -g flags without any semantic change.
_NOISE_ATTRS = {"SourceFile", "SourceDebugExtension", "LineNumberTable",
                "LocalVariableTable", "LocalVariableTypeTable", "StackMapTable",
                "MethodParameters", "Synthetic", "Deprecated", "NestMembers",
                "NestHost", "InnerClasses"}

# opcode -> fixed operand byte count; CP-indexed opcodes handled separately
_OP1 = {16, 18, 21, 22, 23, 24, 25, 54, 55, 56, 57, 58, 169, 188}          # byte operand
_OP2_PLAIN = {17, 132, 153, 154, 155, 156, 157, 158, 159, 160, 161, 162,   # sipush, iinc,
              163, 164, 165, 166, 167, 168, 198, 199}                      # branches
_OP2_CP = {19, 20, 178, 179, 180, 181, 182, 183, 184, 187, 189, 192, 193}  # ldc_w..instanceof
_OP4 = {200, 201}                                                          # goto_w, jsr_w


def _resolve_cp(pool, idx, depth=0):
    """Resolve a constant-pool entry to a stable textual value (index-free)."""
    if depth > 6 or idx not in pool:
        return f"?{idx}"
    tag, val = pool[idx]
    if tag == 1:
        return val
    if tag in (3, 4, 5, 6):
        return f"#{tag}:{val.hex()}"
    if tag in (7, 8, 16, 19, 20):                     # Class,String,MethodType,Module,Package
        return f"#{tag}:{_resolve_cp(pool, val, depth + 1)}"
    if tag == 12:                                      # NameAndType
        return f"{_resolve_cp(pool, val[0], depth+1)}:{_resolve_cp(pool, val[1], depth+1)}"
    if tag in (9, 10, 11):                             # Field/Method/InterfaceMethodref
        return f"#{tag}:{_resolve_cp(pool, val[0], depth+1)}.{_resolve_cp(pool, val[1], depth+1)}"
    if tag == 15:                                      # MethodHandle
        return f"#15:{val[0]}:{_resolve_cp(pool, val[1], depth+1)}"
    if tag in (17, 18):                                # (Invoke)Dynamic: bsm idx + NaT
        return f"#{tag}:bsm{val[0]}:{_resolve_cp(pool, val[1], depth+1)}"
    return f"#{tag}"


def _normalize_code(code, pool):
    """Walk bytecode; emit opcodes with CP operands resolved to values and other
    operands kept numerically. Branch offsets stay numeric (relative already)."""
    out, i, n = [], 0, len(code)
    while i < n:
        op = code[i]
        start = i
        i += 1
        if op == 18:                                   # ldc: 1-byte CP index
            out.append(f"18({_resolve_cp(pool, code[i])})"); i += 1
        elif op in _OP2_CP:
            (idx,) = struct.unpack_from(">H", code, i)
            out.append(f"{op}({_resolve_cp(pool, idx)})"); i += 2
        elif op == 185 or op == 186:                   # invokeinterface / invokedynamic
            (idx,) = struct.unpack_from(">H", code, i)
            out.append(f"{op}({_resolve_cp(pool, idx)})"); i += 4
        elif op == 197:                                # multianewarray
            (idx,) = struct.unpack_from(">H", code, i)
            out.append(f"197({_resolve_cp(pool, idx)},{code[i+2]})"); i += 3
        elif op == 196:                                # wide
            wop = code[i]
            width = 5 if wop == 132 else 3
            out.append("196:" + code[i:i + width].hex()); i += width
        elif op == 170:                                # tableswitch
            pad = (4 - ((start + 1) % 4)) % 4
            i += pad
            default, lo, hi = struct.unpack_from(">iii", code, i)
            i += 12
            count = hi - lo + 1
            offs = struct.unpack_from(f">{count}i", code, i)
            i += 4 * count
            out.append(f"170({default},{lo},{hi},{','.join(map(str, offs))})")
        elif op == 171:                                # lookupswitch
            pad = (4 - ((start + 1) % 4)) % 4
            i += pad
            default, npairs = struct.unpack_from(">ii", code, i)
            i += 8
            pairs = struct.unpack_from(f">{2 * npairs}i", code, i)
            i += 8 * npairs
            out.append(f"171({default},{','.join(map(str, pairs))})")
        elif op in _OP1:
            out.append(f"{op}({code[i]})"); i += 1
        elif op in _OP2_PLAIN:
            out.append(f"{op}({struct.unpack_from('>h', code, i)[0]})"); i += 2
        elif op in _OP4:
            out.append(f"{op}({struct.unpack_from('>i', code, i)[0]})"); i += 4
        else:                                          # no operands
            out.append(str(op))
    return ";".join(out)


def _norm_attrs(data, off, count, pool):
    """Return (canonical attribute list, new offset), noise attrs dropped,
    Code attribute normalized, everything else resolved-by-value."""
    items = []
    for _ in range(count):
        name_i, alen = struct.unpack_from(">HI", data, off)
        off += 6
        body = data[off:off + alen]
        off += alen
        name = _utf8(pool, name_i) or "?"
        if name in _NOISE_ATTRS:
            continue
        if name == "Code":
            _max_s, _max_l, clen = struct.unpack_from(">HHI", body, 0)
            bytecode = body[8:8 + clen]
            p = 8 + clen
            (ex_n,) = struct.unpack_from(">H", body, p)
            p += 2
            exs = []
            for _e in range(ex_n):
                s, e, h, t = struct.unpack_from(">HHHH", body, p)
                p += 8
                exs.append(f"{s},{e},{h},{_resolve_cp(pool, t) if t else '*'}")
            (sub_n,) = struct.unpack_from(">H", body, p)
            p += 2
            sub, _ = _norm_attrs(body, p, sub_n, pool)
            items.append(f"Code[{_normalize_code(bytecode, pool)}|ex:{'|'.join(exs)}|{sub}]")
        elif name in ("ConstantValue", "Exceptions", "Signature"):
            vals = []
            if name == "ConstantValue":
                vals = [_resolve_cp(pool, struct.unpack_from(">H", body, 0)[0])]
            elif name == "Signature":
                vals = [_resolve_cp(pool, struct.unpack_from(">H", body, 0)[0])]
            else:
                (cnt,) = struct.unpack_from(">H", body, 0)
                vals = [_resolve_cp(pool, struct.unpack_from(">H", body, 2 + 2*j)[0])
                        for j in range(cnt)]
            items.append(f"{name}[{','.join(vals)}]")
        elif name == "BootstrapMethods":
            # body is full of CP indices, which shift with unrelated pool changes
            # (e.g. -g adding debug strings) — must resolve by value
            (bm_n,) = struct.unpack_from(">H", body, 0)
            p, bms = 2, []
            for _b in range(bm_n):
                ref, argc = struct.unpack_from(">HH", body, p)
                p += 4
                argv = [_resolve_cp(pool, struct.unpack_from(">H", body, p + 2*j)[0])
                        for j in range(argc)]
                p += 2 * argc
                bms.append(f"{_resolve_cp(pool, ref)}({','.join(argv)})")
            items.append(f"BootstrapMethods[{';'.join(bms)}]")
        else:
            # annotations, unknown: keep raw (conservative — a spurious diff here
            # means over-reporting churn, never hiding it)
            items.append(f"{name}[{hashlib.sha256(body).hexdigest()[:16]}]")
    return "&".join(sorted(items)), off


def normalized_fingerprint(data):
    """Semantic hash of a class file: constant-pool-order-, debug-, and
    frame-independent. Falls back to the raw hash on any parse trouble
    (fail toward reporting change, never toward hiding it)."""
    try:
        if data[:4] != b"\xca\xfe\xba\xbe":
            return hashlib.sha256(data).hexdigest()
        (cp_count,) = struct.unpack_from(">H", data, 8)
        pool, off = _parse_constant_pool(data, 10, cp_count)
        access, this_c, super_c = struct.unpack_from(">HHH", data, off)
        off += 6
        (if_n,) = struct.unpack_from(">H", data, off)
        off += 2
        ifs = []
        for j in range(if_n):
            (ii,) = struct.unpack_from(">H", data, off)
            off += 2
            ifs.append(_resolve_cp(pool, ii))
        parts = [f"cls:{access:x}:{_resolve_cp(pool, this_c)}:{_resolve_cp(pool, super_c)}",
                 "if:" + ",".join(sorted(ifs))]
        members = []
        for _section in ("F", "M"):
            (n,) = struct.unpack_from(">H", data, off)
            off += 2
            for _ in range(n):
                m_acc, name_i, desc_i, attr_n = struct.unpack_from(">HHHH", data, off)
                off += 8
                attrs, off = _norm_attrs(data, off, attr_n, pool)
                members.append(f"{_section}:{m_acc:x}:{_utf8(pool, name_i)}:"
                               f"{_utf8(pool, desc_i)}:{attrs}")
        parts += sorted(members)             # neutralize member ordering
        (ca_n,) = struct.unpack_from(">H", data, off)
        off += 2
        cattrs, off = _norm_attrs(data, off, ca_n, pool)
        parts.append("ca:" + cattrs)
        return hashlib.sha256("\n".join(parts).encode()).hexdigest()
    except Exception:
        return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- jar model

def _mods(access):
    m = []
    if access & ACC_PUBLIC: m.append("public")
    if access & ACC_PROTECTED: m.append("protected")
    if access & ACC_STATIC: m.append("static")
    if access & ACC_FINAL: m.append("final")
    if access & ACC_ABSTRACT: m.append("abstract")
    return tuple(m)


def load_jar(path):
    """Read a JAR. Returns model: classes, api, resources, hashes, packages."""
    classes = {}          # internal name -> parsed
    class_bytes = {}      # internal name -> raw sha256
    class_norm = {}       # internal name -> semantic fingerprint
    class_entries = []    # zip entry paths of class files (relocation lives here)
    resources = {}        # entry name -> sha256
    resource_text = {}    # entry name -> decoded text (small text files only)
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            data = z.read(info)
            if info.filename.endswith(".class"):
                try:
                    c = parse_class(data)
                except Exception:
                    c = None
                if c and c["name"]:
                    classes[c["name"]] = c
                    class_bytes[c["name"]] = hashlib.sha256(data).hexdigest()
                    class_norm[c["name"]] = normalized_fingerprint(data)
                    class_entries.append(info.filename)
            else:
                resources[info.filename] = hashlib.sha256(data).hexdigest()
                if len(data) <= 262144:
                    try:
                        resource_text[info.filename] = data.decode("utf-8")
                    except UnicodeDecodeError:
                        pass

    api = {}  # (cls, name, desc) or (cls, None, None) -> mods
    for cname, c in classes.items():
        if not (c["access"] & ACC_PUBLIC):
            continue
        api[(cname, None, None)] = _mods(c["access"])
        for m in c["members"]:
            if m["access"] & (ACC_PUBLIC | ACC_PROTECTED) and not (m["access"] & ACC_SYNTHETIC):
                api[(cname, m["name"], m["desc"])] = _mods(m["access"])

    packages = {cname.rsplit("/", 1)[0] for cname in classes if "/" in cname}
    return {"classes": classes, "class_hashes": class_bytes, "class_norm": class_norm,
            "resources": resources, "resource_text": resource_text,
            "class_entries": class_entries, "api": api, "packages": packages}


# ---------------------------------------------------------------- diffing

def classify_stream(old_v, new_v):
    """Red Hat z/y/x-stream == semver patch/minor/major."""
    try:
        o = old_v.split(".")
        n = new_v.split(".")
        if o[0] != n[0]:
            return "x-stream (major)"
        if len(o) > 1 and len(n) > 1 and o[1] != n[1]:
            return "y-stream (minor)"
        return "z-stream (patch)"
    except Exception:
        return "unknown"


def member_str(key, mods=None):
    cls, name, desc = key
    cls_j = cls.replace("/", ".")
    if name is None:
        return f"class {cls_j}"
    return f"{cls_j}#{name}{desc or ''}"


def diff_jars(old, new):
    o_api, n_api = old["api"], new["api"]
    sk = lambda k: (k[0], k[1] or "", k[2] or "")
    removed = sorted((k for k in o_api if k not in n_api), key=sk)
    added = sorted((k for k in n_api if k not in o_api), key=sk)
    modified = sorted((k for k in o_api if k in n_api and o_api[k] != n_api[k]), key=sk)

    # a modified entry is incompatible if visibility narrowed or final/abstract added
    def narrowed(k):
        om, nm = set(o_api[k]), set(n_api[k])
        if "public" in om and "public" not in nm: return True
        if "final" in nm and "final" not in om: return True
        if "abstract" in nm and "abstract" not in om: return True
        if "static" in om.symmetric_difference(nm): return True
        return False

    incompatible = list(removed) + [k for k in modified if narrowed(k)]  # sorted below

    common = set(old["class_hashes"]) & set(new["class_hashes"])
    raw_changed = {c for c in common
                   if old["class_hashes"][c] != new["class_hashes"][c]}
    changed_impl = sorted(c for c in raw_changed
                          if old["class_norm"][c] != new["class_norm"][c])
    build_noise = sorted(raw_changed - set(changed_impl))
    churn_pct = round(100.0 * len(changed_impl) / len(common), 1) if common else 0.0

    o_res, n_res = old["resources"], new["resources"]
    res_removed = sorted(k for k in o_res if k not in n_res)
    res_added = sorted(k for k in n_res if k not in o_res)
    res_changed = sorted(k for k in o_res if k in n_res and o_res[k] != n_res[k])
    spi_touched = sorted(k for k in (res_removed + res_added + res_changed)
                         if k.startswith("META-INF/services/"))

    return {
        "api_removed": removed, "api_added": added, "api_modified": modified,
        "api_incompatible": sorted(set(incompatible), key=lambda k: (k[0], k[1] or "", k[2] or "")),
        "classes_common": len(common), "classes_impl_changed": changed_impl,
        "classes_build_noise": build_noise,
        "impl_churn_pct": churn_pct,
        "res_removed": res_removed, "res_added": res_added,
        "res_changed": res_changed, "spi_touched": spi_touched,
    }


def intersect_app(app, lib_old, delta):
    """Which library members/classes that changed does the app actually reach?

    Known blind spot (reported, not hidden): reflection and config-driven
    instantiation don't appear in the constant pool.
    """
    lib_pkgs = lib_old["packages"]

    def in_lib(cls):
        return cls and ("/" in cls) and cls.rsplit("/", 1)[0] in lib_pkgs

    call_sites = set()
    class_uses = set()
    owners = defaultdict(set)   # app class -> refs it owns into the library
    for cname, c in app["classes"].items():
        for (cls, name, desc) in c["refs"]:
            if in_lib(cls):
                call_sites.add((cls, name, desc))
                owners[cname].add((cls, name, desc))
        for cls in c["class_refs"]:
            if in_lib(cls):
                class_uses.add(cls)
                owners[cname].add((cls, None, None))

    changed = set(delta["api_removed"]) | set(delta["api_modified"])
    incompat = set(delta["api_incompatible"])
    removed_classes = {k[0] for k in delta["api_removed"] if k[1] is None}
    impl_changed = set(delta["classes_impl_changed"])

    sk = lambda k: (k[0], k[1] or "", k[2] or "")
    touched_changed = sorted((k for k in call_sites if k in changed), key=sk)
    touched_incompat = sorted(
        [k for k in call_sites if k in incompat] +
        [(c, None, None) for c in class_uses if c in removed_classes], key=sk)
    touched_impl = sorted(c for c in class_uses if c in impl_changed)

    return {
        "lib_call_sites": len(call_sites),
        "lib_classes_used": sorted(c.replace("/", ".") for c in class_uses),
        "touched_changed": touched_changed,
        "touched_incompatible": sorted(set(touched_incompat), key=sk),
        "touched_impl_changed": sorted(c.replace("/", ".") for c in touched_impl),
        "affected_app_classes": sorted(o.replace("/", ".") for o in owners),
        "affected_app_classes_changed": sorted(
            o.replace("/", ".") for o, refs in owners.items()
            if refs & (changed | incompat)),
    }


# ---------------------------------------------------------------- rating

GRADE_ORDER = ["A", "B", "C", "D", "F"]

LANES = {
    "A": ("Fast lane", ["Smoke test the service", "Canary one instance",
                        "Watch health + error rate, then promote"]),
    "B": ("Targeted tests", ["Smoke test the service",
                             "Contract tests on the packages that call this library",
                             "Re-verify any behavior driven by the changed defaults/resources",
                             "Canary, watch, promote"]),
    "C": ("Partial regression", ["Full test suites of every module that imports this library",
                                 "One production-like boot test (DI wiring, classpath scanning)",
                                 "Contract tests on external behavior",
                                 "Canary, watch, promote"]),
    "D": ("Full regression", ["Full regression suite",
                              "Production-like boot test",
                              "Integration tests on every path that reaches this library",
                              "Canary, watch, promote"]),
    "F": ("Full regression + migration", ["Code changes required before this upgrade compiles/runs",
                                          "Full regression suite after migration",
                                          "Production-like boot test",
                                          "Extended canary window"]),
}


def internal_chain_intersect(app, lib_old, delta):
    """Same-library, multi-hop reachability: BFS the library's OWN call graph
    starting from the methods the app directly calls, and check whether ANY
    method/class reached by that internal chain is itself part of the changed
    set -- catches 'app calls public method1(), method1 internally calls
    method2(), method2 is what actually changed' even when the app never
    references method2 (or its class) anywhere in its own bytecode.

    This is the same BFS-closure technique two_hop_intersect uses to trace
    into a TRANSITIVE (different-jar) dependency, applied instead within a
    single jar. Confidence is high (statically resolved, same jar, no
    cross-library reflection compounding) -- this is not weaker evidence
    like the transitive case, it is the direct-dependency check done to the
    depth the direct dependency's own internal structure actually requires.
    """
    lib_pkgs = lib_old["packages"]

    def pkg(cls):
        return cls.rsplit("/", 1)[0] if cls and "/" in cls else ""

    defined, subclasses, implementors = _method_graph(lib_old)
    seeds, seed_owners = set(), set()
    for cname, c in app["classes"].items():
        for m in c["members"]:
            for ref in m.get("calls", ()):
                if pkg(ref[0]) in lib_pkgs:
                    seeds |= _resolve_dispatch(ref, lib_old, defined, subclasses, implementors)
                    seed_owners.add(cname)
    if not seeds:
        return None

    reached_m, queue = set(), sorted(seeds)
    while queue:
        mkey = queue.pop()
        if mkey in reached_m or mkey not in defined:
            continue
        reached_m.add(mkey)
        for ref in defined[mkey].get("calls", ()):
            if pkg(ref[0]) in lib_pkgs:
                for tgt in _resolve_dispatch(ref, lib_old, defined, subclasses, implementors):
                    if tgt not in reached_m:
                        queue.append(tgt)

    changed = set(delta["api_removed"]) | set(delta["api_modified"])
    incompat = set(delta["api_incompatible"])
    impl_changed = set(delta["classes_impl_changed"])
    sk = lambda k: (k[0], k[1] or "", k[2] or "")

    touched_changed = sorted((k for k in reached_m if k in changed), key=sk)
    touched_incompat = sorted((k for k in reached_m if k in incompat), key=sk)
    reached_classes = {k[0] for k in reached_m}
    touched_impl = sorted(c for c in reached_classes if c in impl_changed)

    return {
        "closure_methods_reached": len(reached_m),
        "closure_seed_count": len(seeds),
        "internal_touched_changed": [member_str(k) for k in touched_changed],
        "internal_touched_incompatible": [member_str(k) for k in touched_incompat],
        "internal_touched_impl_changed": sorted(c.replace("/", ".") for c in touched_impl),
        "internal_seed_owners": sorted(o.replace("/", ".") for o in seed_owners),
    }


def rate(stream, delta, app_ix, transitive=False, signoff=False):
    incompat = len(delta["api_incompatible"])
    modified = len(delta["api_modified"])
    added = len(delta["api_added"])
    churn = delta["impl_churn_pct"]
    behavior_res = [r for r in delta["res_changed"] + delta["res_added"] + delta["res_removed"]
                    if not r.startswith("META-INF/MANIFEST")]
    spi = len(delta["spi_touched"]) > 0

    reasons = []
    if stream.startswith("z"):
        grade = "A"
        reasons.append("z-stream (patch) release: intent is a fix, not new function")
        if incompat or modified:
            grade = "D"
            reasons.append(f"but {incompat or modified} API change(s) — a patch release should not do this")
        else:
            if added:
                grade = "B"; reasons.append(f"{added} new public member(s) added")
            if churn >= 10:
                grade = "B"; reasons.append(f"implementation churn {churn}% — more rewrite than a minimal fix")
            if behavior_res:
                grade = "B"; reasons.append(f"{len(behavior_res)} bundled default/resource change(s) — behavior can shift with zero API change")
            if spi:
                grade = "B"; reasons.append("SPI service registrations changed")
            if grade == "A":
                reasons.append(f"no API change, churn {churn}%, no default/resource changes")
    elif stream.startswith("y"):
        grade = "C"
        reasons.append("y-stream (minor): assumed to carry new functionality")
        if incompat:
            grade = "D"
            reasons.append(f"{incompat} binary-incompatible change(s)")
    else:
        grade = "D"
        reasons.append("x-stream (major) or unknown: treat as a migration")
        if incompat:
            reasons.append(f"{incompat} binary-incompatible change(s)")

    scope_note = None
    effective_grade = None
    hop = "via the parent's call paths" if transitive else "directly"
    if app_ix is not None:
        if app_ix["touched_incompatible"]:
            grade = "F"
            reasons.append(f"application reaches {len(app_ix['touched_incompatible'])} removed/incompatible member(s) {hop} — it will break")
        elif app_ix["touched_changed"]:
            reasons.append(f"application reaches {len(app_ix['touched_changed'])} changed member(s) {hop}")
        else:
            reasons.append(f"application reaches 0 changed members {hop}")
            chain = app_ix.get("internal_chain")
            if chain and not transitive:
                if chain["internal_touched_incompatible"]:
                    grade = "F"
                    reasons.append(
                        f"but the internal call chain from your entry point(s) reaches "
                        f"{len(chain['internal_touched_incompatible'])} removed/incompatible member(s) "
                        f"{chain['internal_touched_incompatible'][0]} — it will break even though "
                        f"you never call that member by name")
                elif chain["internal_touched_changed"] or chain["internal_touched_impl_changed"]:
                    n = len(chain["internal_touched_changed"]) + len(chain["internal_touched_impl_changed"])
                    reasons.append(
                        f"the internal call chain from your entry point(s) reaches {n} changed "
                        f"member(s)/class(es) this app never calls by name — a one-hop check alone "
                        f"would have missed this")
                    if grade == "A":
                        grade = "B"
            if grade in ("C", "D"):
                if not transitive:
                    if not delta["api_incompatible"]:
                        scope_note = ("Scope-shrink candidate: nothing this app calls changed shape. "
                                      "With sign-off, run the targeted lane instead — keep the canary either way.")
                elif signoff:
                    effective_grade = "B"
                    scope_note = ("De-escalated with sign-off: no changed member is reachable through "
                                  "the app's call paths into the parent. Two-hop evidence — reflection "
                                  "blindness compounds across hops, so the canary is not optional.")
                else:
                    scope_note = ("De-escalation available WITH SIGN-OFF (--accept-transitive-scope): "
                                  "no changed member reachable through your call paths. Not applied by "
                                  "default — two-hop evidence carries lower confidence than direct analysis.")

    lane, recipe = LANES[effective_grade or grade]
    return {"grade": grade, "effective_grade": effective_grade, "lane": lane,
            "recipe": recipe, "reasons": reasons, "scope_note": scope_note}


# ---------------------------------------------------------------- analyze

def analyze(args):
    old = load_jar(args.old_jar)
    new = load_jar(args.new_jar)
    stream = classify_stream(args.old_version, args.new_version)
    delta = diff_jars(old, new)
    app_ix = None
    if args.app:
        app_loaded = load_jar(args.app)
        app_ix = intersect_app(app_loaded, old, delta)
        app_ix["internal_chain"] = internal_chain_intersect(app_loaded, old, delta)
    rating = rate(stream, delta, app_ix)

    report = {
        "tool": {"name": "upgrade-delta", "version": TOOL_VERSION},
        "date": str(date.today()),
        "library": args.library or os.path.basename(args.old_jar),
        "old_version": args.old_version, "new_version": args.new_version,
        "old_jar": os.path.basename(args.old_jar),
        "new_jar": os.path.basename(args.new_jar),
        "app": os.path.basename(args.app) if args.app else None,
        "stream": stream,
        "delta": {
            **{k: ([member_str(x) for x in v] if k.startswith("api_") else v)
               for k, v in delta.items()},
        },
        # machine section: everything a consumer-side scan needs to re-run the
        # app intersection locally without the jars
        "machine": {
            "packages": sorted(old["packages"]),
            "api_removed": [list(k) for k in delta["api_removed"]],
            "api_added": [list(k) for k in delta["api_added"]],
            "api_modified": [list(k) for k in delta["api_modified"]],
            "api_incompatible": [list(k) for k in delta["api_incompatible"]],
            "classes_impl_changed": delta["classes_impl_changed"],
            "classes_build_noise": delta["classes_build_noise"],
            "classes_common": delta["classes_common"],
            "impl_churn_pct": delta["impl_churn_pct"],
            "res_removed": delta["res_removed"], "res_added": delta["res_added"],
            "res_changed": delta["res_changed"], "spi_touched": delta["spi_touched"],
        },
        "app_intersection": None if app_ix is None else {
            **app_ix,
            "touched_changed": [member_str(x) for x in app_ix["touched_changed"]],
            "touched_incompatible": [member_str(x) for x in app_ix["touched_incompatible"]],
        },
        "rating": rating,
        "blind_spots": [
            "Reflection and config-driven instantiation are invisible to constant-pool analysis.",
            "Churn is computed on a semantic fingerprint (debug info, constant-pool order, "
            "and stack frames stripped); residual cross-compiler noise (e.g. different "
            "bridge-method or lambda-name generation) can still over-report — never under-report.",
            "A behavior change with zero structural fingerprint will not be detected — "
            "this is why the canary and rollback stay in the plan for every grade, including A.",
        ],
    }

    print_terminal(report)
    if args.json:
        with open(args.json, "w") as f:
            json.dump(report, f, indent=2)
        print(f"  evidence: {args.json}")
    if args.html:
        with open(args.html, "w") as f:
            f.write(render_card(report))
        print(f"  report:   {args.html}")
    if getattr(args, "routing_payload", None):
        shrinkable = {"Fast lane", "Targeted tests"}
        eff = rating.get("effective_grade")
        payload = {
            "schema": "upgrade-delta/routing/v1",
            "tool": {"name": "upgrade-delta", "version": TOOL_VERSION},
            "date": str(date.today()), "app": report["app"] or "app",
            "project_grade": eff or rating["grade"],
            "shrink_allowed": rating["lane"] in shrinkable,
            "upgrades": [{
                "library": report["library"],
                "path": f"{args.old_version} -> {args.new_version}",
                "lane": rating["lane"], "grade": rating["grade"],
                "effective_grade": eff, "transitive": False, "parent": None,
                "affected_app_classes": (app_ix or {}).get("affected_app_classes", []),
                "affected_app_classes_changed": (app_ix or {}).get("affected_app_classes_changed", []),
                "confidence": {"evidence": "direct", "signed_off": bool(eff)},
            }],
            "obligations": [
                {"id": "boot-test", "stage": "in-scope",
                 "declaration": {"type": "tag", "value": "upgrade-gate"}, "min_resolved": 1},
                {"id": "canary", "stage": "downstream",
                 "note": "deployment-stage activity; a build plugin cannot run or verify this"},
                {"id": "rollback-path", "stage": "downstream",
                 "note": "verify rollback artifact + procedure before promotion"},
            ],
            "blind_spots": [
                "Reflection/config-driven use invisible to static analysis; compounds across hops.",
                "Selection strength depends on the consumer-side coverage map, which this payload knows nothing about.",
            ],
        }
        with open(args.routing_payload, "w") as f:
            json.dump(payload, f, indent=2)
        print(f"  routing payload: {args.routing_payload}")
    if getattr(args, "scorecard_compat", None):
        # Wraps this single live-diffed dependency in the same {project, libraries}
        # shape scan() produces, so upgrade-delta-summary and
        # upgrade-delta-pr-comment work completely UNCHANGED downstream --
        # whether the grade came from a whole-project scan against published
        # evidence, or a live pom.xml-diff-triggered single-dependency check.
        eff2 = rating.get("effective_grade")
        histogram = {rating["lane"]: {"direct": 1, "transitive": 0}}
        compat = {
            "tool": {"name": "upgrade-delta", "version": TOOL_VERSION},
            "date": str(date.today()), "app": report["app"] or "app",
            "libraries": [{
                "library": report["library"], "transitive": False, "parent": None,
                # 'installed' and 'call_sites' are part of scan()'s library
                # schema; summary/pr-comment read them directly, so a
                # scorecard-compat payload must supply them too.
                "installed": args.old_version,
                "call_sites": (app_ix or {}).get("lib_call_sites", 0),
                "recommended": {"old": args.old_version, "new": args.new_version,
                                 "rating": rating, "ix": app_ix or {}},
                "worst": {"old": args.old_version, "new": args.new_version, "rating": rating},
            }],
            "unrated_packages": [], "heuristics": [], "hazards": [],
            "shipped_dependencies": [],
            "project": {
                "headline_grade": eff2 or rating["grade"],
                "headline_note": "grade for this specific dependency bump, from a live "
                                  "pom.xml-diff -- not a whole-project scan",
                "worst_without_best_path": rating["grade"],
                "rated_libraries": 1, "unrated_package_roots": 0,
                "lane_histogram": histogram,
            },
        }
        with open(args.scorecard_compat, "w") as f:
            json.dump(compat, f, indent=2)
        print(f"  scorecard (compat): {args.scorecard_compat}")
    return report


def print_terminal(r):
    d = r["delta"]
    g = r["rating"]
    print(f"\n== upgrade-delta :: {r['library']} {r['old_version']} -> {r['new_version']} ==")
    print(f"   stream: {r['stream']}")
    print(f"   API: -{len(d['api_removed'])} removed  +{len(d['api_added'])} added  "
          f"~{len(d['api_modified'])} modified  ({len(d['api_incompatible'])} incompatible)")
    noise = len(d.get("classes_build_noise", []))
    print(f"   implementation churn: {d['impl_churn_pct']}% of {d['classes_common']} shared classes"
          + (f"  (+{noise} class(es) differ only as build noise — excluded)" if noise else ""))
    print(f"   resources: -{len(d['res_removed'])} +{len(d['res_added'])} ~{len(d['res_changed'])}"
          f"   SPI touched: {len(d['spi_touched'])}")
    if r["app_intersection"]:
        a = r["app_intersection"]
        print(f"   app '{r['app']}': {a['lib_call_sites']} call sites into the library; "
              f"touches {len(a['touched_changed'])} changed, "
              f"{len(a['touched_incompatible'])} incompatible member(s)")
    print(f"   RATING: {g['grade']}  ->  {g['lane']}")
    for reason in g["reasons"]:
        print(f"     - {reason}")
    if g["scope_note"]:
        print(f"     * {g['scope_note']}")


# ---------------------------------------------------------------- html

CSS = """
:root{
  --rh-red:#EE0000; --rh-red-dark:#A30000;
  --paper:#F0F0F0; --card:#FFFFFF; --ink:#151515; --ink-soft:#6A6E73;
  --rule:#D2D2D2; --steel:#0066CC;
  --pass:#3E8635; --watch:#F0AB00; --stop:#C9190B;
  --mono:'Red Hat Mono',ui-monospace,SFMono-Regular,Menlo,monospace;
  --sans:'Red Hat Text',system-ui,-apple-system,Segoe UI,sans-serif;
  --disp:'Red Hat Display',var(--sans); --head:var(--disp);
}
*{box-sizing:border-box;margin:0}
body{background:var(--paper);color:var(--ink);font-family:var(--sans);
  font-size:15px;line-height:1.6;padding:40px 16px}
.sheet{max-width:880px;margin:0 auto;background:var(--card);
  border-radius:8px;border-top:4px solid var(--rh-red);
  box-shadow:0 1px 2px rgba(0,0,0,.06),0 8px 24px rgba(21,21,21,.08);
  padding:36px 40px 44px;position:relative}
.eyebrow{font-family:var(--sans);font-weight:700;font-size:11px;letter-spacing:.14em;
  text-transform:uppercase;color:var(--rh-red)}
h1{font-family:var(--disp);font-weight:700;font-size:32px;line-height:1.15;
  letter-spacing:-.01em;margin:8px 0 2px;color:var(--ink)}
.vers{font-family:var(--mono);font-size:14px;color:var(--steel);margin-bottom:22px}
.stamp{position:absolute;top:32px;right:36px;text-align:center;
  background:var(--stamp-c);color:#fff;border-radius:8px;
  padding:10px 20px 12px;box-shadow:0 2px 6px rgba(21,21,21,.18)}
.stamp .g{font-family:var(--disp);font-size:36px;font-weight:800;line-height:.95;display:block}
.stamp .l{font-family:var(--sans);font-size:11px;font-weight:600;letter-spacing:.04em;
  text-transform:uppercase;display:block;margin-top:4px;opacity:.92}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;
  background:var(--rule);border:1px solid var(--rule);border-radius:6px;overflow:hidden;
  margin:18px 0 24px}
.metric{background:var(--card);padding:14px 16px}
.metric b{font-family:var(--disp);font-weight:700;font-size:24px;display:block;color:var(--ink)}
.metric span{font-size:11.5px;color:var(--ink-soft);text-transform:uppercase;letter-spacing:.04em}
h2{font-family:var(--disp);font-weight:700;font-size:18px;letter-spacing:0;
  color:var(--ink);border-left:4px solid var(--rh-red);padding-left:10px;
  margin:28px 0 12px}
ul{padding-left:20px}
li{margin:4px 0}
.recipe li{font-family:var(--mono);font-size:13.5px}
.reason{color:var(--ink-soft)}
.note{border-left:4px solid var(--watch);background:rgba(240,171,0,.08);
  border-radius:0 4px 4px 0;padding:10px 14px;margin:12px 0;font-size:14px}
.blind{border-left:4px solid var(--steel);background:rgba(0,102,204,.06);
  border-radius:0 4px 4px 0;padding:10px 14px;margin:12px 0;font-size:13.5px;color:var(--ink-soft)}
details{margin:8px 0}
summary{cursor:pointer;font-family:var(--sans);font-weight:600;font-size:13px;color:var(--steel)}
code,.m{font-family:var(--mono);font-size:12.5px;word-break:break-all}
.list{columns:1;padding:8px 0 0 4px;list-style:none}
.footer{margin-top:34px;padding-top:14px;border-top:1px solid var(--rule);
  font-family:var(--mono);font-size:11.5px;color:var(--ink-soft);
  display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px}
table{width:100%;border-collapse:collapse;background:var(--card)}
th,td{text-align:left;padding:11px 12px;border-bottom:1px solid var(--rule);font-size:14px}
th{font-family:var(--sans);font-weight:700;font-size:11px;letter-spacing:.08em;text-transform:uppercase;
  color:var(--ink-soft);border-bottom:2px solid var(--rule)}
tr:hover td{background:rgba(0,0,0,.02)}
td a{color:var(--steel);text-decoration:none}
td a:hover{text-decoration:underline}
.chip{display:inline-block;font-family:var(--sans);font-weight:700;font-size:13px;
  background:var(--c);color:#fff;border-radius:4px;padding:2px 10px;line-height:1.5}
.lane{font-family:var(--mono);font-size:12px;color:var(--ink-soft)}
.scale{background:#FAFAFA;border:1px solid var(--rule);border-radius:8px;
  padding:16px 18px;margin:0 0 26px}
.scale-h{font-family:var(--sans);font-weight:700;font-size:11px;letter-spacing:.06em;
  text-transform:uppercase;color:var(--ink-soft);margin:0 0 13px}
.sc-row{display:flex;align-items:baseline;gap:12px;padding:5px 0}
.sc-lane{font-weight:600;font-size:13px;color:var(--ink);min-width:150px}
.sc-desc{font-size:12.5px;color:var(--ink-soft);line-height:1.4}
.chip.sm{min-width:24px;height:24px;font-size:13px;flex:none}
@media(max-width:640px){.metrics{grid-template-columns:repeat(2,1fr)}
 .stamp{position:static;display:inline-block;margin-bottom:14px}
 .sheet{padding:24px 18px}}
"""

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link href="https://fonts.googleapis.com/css2?family=Red+Hat+Mono:wght@400;600'
         '&family=Red+Hat+Text:wght@400;500;700&family=Red+Hat+Display:wght@600;700;800'
         '&display=swap" rel="stylesheet">')


GRADE_COLOR = {"A": "var(--pass)", "B": "var(--watch)", "C": "var(--watch)",
               "D": "var(--stop)", "F": "var(--stop)"}


def esc(s):
    return html_mod.escape(str(s))


def _member_list(title, items, open_=False):
    if not items:
        return ""
    lis = "".join(f'<li class="m">{esc(i)}</li>' for i in items)
    return (f'<details{" open" if open_ else ""}><summary>{esc(title)} '
            f'({len(items)})</summary><ul class="list">{lis}</ul></details>')


def render_card(r):
    d, g = r["delta"], r["rating"]
    color = GRADE_COLOR[g["grade"]]
    app_html = ""
    if r["app_intersection"]:
        a = r["app_intersection"]
        verdict = ("it will break — migration required" if a["touched_incompatible"]
                   else ("it reaches changed members — test those paths" if a["touched_changed"]
                         else "it reaches nothing that changed shape"))
        app_html = f"""
<h2>This application, specifically</h2>
<p><code>{esc(r['app'])}</code> makes <b>{a['lib_call_sites']}</b> calls into this library
and uses <b>{len(a['lib_classes_used'])}</b> of its classes. Against this upgrade: {esc(verdict)}.</p>
{_member_list('Removed or incompatible members this app calls', a['touched_incompatible'], open_=True)}
{_member_list('Changed members this app calls', a['touched_changed'], open_=True)}
{_member_list('Library classes this app uses whose implementation changed', a['touched_impl_changed'])}
"""
    scope = f'<div class="note">{esc(g.get("scope_note"))}</div>' if g.get("scope_note") else ""
    reasons = "".join(f'<li class="reason">{esc(x)}</li>' for x in g["reasons"])
    recipe = "".join(f"<li>{esc(x)}</li>" for x in g["recipe"])
    blind = "".join(f"<li>{esc(x)}</li>" for x in r["blind_spots"])
    res_all = d["res_removed"] + d["res_added"] + d["res_changed"]

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(r['library'])} {esc(r['old_version'])} → {esc(r['new_version'])} — delta report</title>
{FONTS}<style>{CSS}</style></head><body>
<div class="sheet" style="--stamp-c:{color}">
  <div class="stamp"><span class="g">{g['grade']}</span><span class="l">{esc(g['lane'])}</span></div>
  <div class="eyebrow">Lightwell delta report · patch impact rating</div>
  <h1>{esc(r['library'])}</h1>
  <div class="vers">{esc(r['old_version'])} → {esc(r['new_version'])} · {esc(r['stream'])}</div>

  <div class="metrics">
    <div class="metric"><b>{len(d['api_removed'])}</b><span>public members removed</span></div>
    <div class="metric"><b>{len(d['api_added'])}</b><span>public members added</span></div>
    <div class="metric"><b>{len(d['api_incompatible'])}</b><span>binary-incompatible changes</span></div>
    <div class="metric"><b>{d['impl_churn_pct']}%</b><span>semantic churn
      ({len(d['classes_impl_changed'])} of {d['classes_common']} shared classes{
      f"; {len(d.get('classes_build_noise', []))} build-noise diffs excluded"
      if d.get('classes_build_noise') else ""})</span></div>
  </div>

  <h2>Why this rating</h2>{_grade_legend_html()}<ul>{reasons}</ul>{scope}
  {app_html}
  <h2>Recommended test scope — {esc(g['lane'])}</h2><ul class="recipe">{recipe}</ul>

  <h2>Evidence</h2>
  {_member_list('Removed public members', d['api_removed'])}
  {_member_list('Added public members', d['api_added'])}
  {_member_list('Modified public members', d['api_modified'])}
  {_member_list('Resource / default changes', res_all)}
  {_member_list('SPI registrations touched', d['spi_touched'])}
  {_member_list('Classes whose implementation changed (semantic)', [c.replace('/', '.') for c in d['classes_impl_changed']])}
  {_member_list('Classes differing only as build noise (excluded from churn)', [c.replace('/', '.') for c in d.get('classes_build_noise', [])])}

  <h2>What this report cannot see</h2>
  <div class="blind"><ul>{blind}</ul></div>

  <div class="footer">
    <span>{esc(r['old_jar'])} → {esc(r['new_jar'])}</span>
    <span>upgrade-delta v{TOOL_VERSION} · {esc(r['date'])}</span>
  </div>
</div></body></html>"""


# rating scale: the legend shown on the catalog index
RATING_SCALE = [
    ("A", "var(--pass)",  "Fast lane",
     "Disciplined patch — no API change, minimal churn, no shipped-default changes"),
    ("B", "var(--watch)", "Targeted tests",
     "Patch with added surface, heavy internal churn, or a changed default"),
    ("C", "var(--watch)", "Partial regression",
     "Minor release with no binary-incompatible changes"),
    ("D", "var(--stop)",  "Full regression",
     "Binary-incompatible changes, or a major release"),
    ("F", "var(--stop)",  "Migration required",
     "Incompatible changes your application provably calls — it will break"),
]
_GRADE_ORDER = {g: i for i, (g, *_ ) in enumerate(RATING_SCALE)}


def _grade_legend_html(title="How to read the grade"):
    """Shared A-F legend block, reused on every report that shows a letter
    grade. There is no 'E' -- the scale intentionally skips it, same as a
    US school report card (A, B, C, D, F)."""
    rows = "".join(
        f'<div class="sc-row"><span class="chip sm" style="--c:{color}">{grade}</span>'
        f'<span class="sc-lane">{lane}</span>'
        f'<span class="sc-desc">{desc}</span></div>'
        for grade, color, lane, desc in RATING_SCALE)
    return f'<div class="scale"><div class="scale-h">{esc(title)}</div>{rows}</div>'


def render_index(reports, links):
    # worst-first: an F belongs at the top of a change board's page
    paired = sorted(zip(reports, links),
                    key=lambda rl: -_GRADE_ORDER.get(rl[0]["rating"]["grade"], 0))

    def fmt_delta(d):
        rem, add = len(d["api_removed"]), len(d["api_added"])
        inc = len(d["api_incompatible"])
        api = f'{("+" + str(add)) if add else "0"} added, {rem} removed'
        inc_txt = (f'<b style="color:var(--stop)">{inc} incompatible</b>'
                   if inc else '0 incompatible')
        return (f'<span class="d-api">{api}</span>'
                f'<span class="d-sep">·</span>'
                f'<span class="d-churn">{d["impl_churn_pct"]}% churn</span>'
                f'<span class="d-sep">·</span>{inc_txt}')

    rows = ""
    for r, link in paired:
        g = r["rating"]
        c = GRADE_COLOR[g["grade"]]
        d = r["delta"]
        stream = r["stream"].split(" ")[0]
        rows += f"""<tr>
<td class="lib"><a href="{esc(link)}">{esc(r['library'])}</a>
  <div class="upg">{esc(r['old_version'])} <span class="to">→</span> {esc(r['new_version'])}</div></td>
<td><span class="stream">{esc(stream)}</span></td>
<td><span class="chip" style="--c:{c}">{g['grade']}</span></td>
<td class="lane-cell">{esc(g['lane'])}</td>
<td class="delta">{fmt_delta(d)}</td>
</tr>"""

    legend = _grade_legend_html("How to read the rating")

    n = len(reports)
    worst = min((r["rating"]["grade"] for r in reports),
                key=lambda x: -_GRADE_ORDER.get(x, 0)) if reports else "—"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lightwell delta reports</title>{FONTS}<style>{CSS}
.idx-sub{{max-width:66ch;color:var(--ink-soft);font-size:14px;line-height:1.55;margin:2px 0 24px}}
table.idx{{width:100%;border-collapse:collapse}}
table.idx th{{text-align:left;font:600 10.5px/1 var(--head,inherit);letter-spacing:.05em;
  text-transform:uppercase;color:var(--ink-soft);padding:0 14px 9px;border-bottom:2px solid var(--ink,#333)}}
table.idx td{{padding:13px 14px;border-bottom:1px solid var(--line,#eee);vertical-align:top}}
table.idx tr:last-child td{{border-bottom:none}}
td.lib a{{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:13px;
  font-weight:600;color:var(--ink);text-decoration:none;border-bottom:1px solid var(--line,#ddd)}}
td.lib a:hover{{border-bottom-color:var(--ink)}}
td.lib .upg{{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:11.5px;
  color:var(--ink-soft);margin-top:4px}}
td.lib .to{{color:var(--ink-soft)}}
.stream{{font-size:11px;color:var(--ink-soft);background:#f0f0f0;border-radius:4px;padding:3px 7px;white-space:nowrap}}
td.lane-cell{{font-size:13px;color:var(--ink);white-space:nowrap}}
td.delta{{font-size:12px;color:var(--ink-soft);line-height:1.7}}
td.delta .d-sep{{margin:0 7px;color:#ccc}}
td.delta .d-churn{{font-variant-numeric:tabular-nums}}
</style></head><body>
<div class="sheet">
  <div class="eyebrow">Lightwell · published with every remediated artifact</div>
  <h1>Delta reports</h1>
  <p class="idx-sub">One row per remediated artifact. Each answers a single question
  <b>before you upgrade</b>: how much did this artifact actually change, and how much
  testing does that owe? Every rating is <b>computed from the bytecode</b>, not asserted —
  open any row for the full evidence, including what the analysis cannot see.</p>

  {legend}

  <table class="idx"><thead><tr>
    <th>Library &amp; upgrade</th><th>Stream</th><th>Rating</th><th>Test lane</th>
    <th>What changed</th>
  </tr></thead><tbody>{rows}</tbody></table>
  <div class="footer"><span>{n} remediated artifact(s) · worst pending rating: {worst} · sorted worst-first</span>
  <span>upgrade-delta v{TOOL_VERSION} · {date.today()}</span></div>
</div></body></html>"""


def publish(args):
    os.makedirs(args.out, exist_ok=True)
    reports, links = [], []
    for p in args.reports:
        with open(p) as f:
            r = json.load(f)
        reports.append(r)
        slug = (f"{r['library']}-{r['old_version']}-to-{r['new_version']}"
                .replace(" ", "-").replace("/", "-"))
        link = f"{slug}.html"
        with open(os.path.join(args.out, link), "w") as f:
            f.write(render_card(r))
        links.append(link)
    with open(os.path.join(args.out, "index.html"), "w") as f:
        f.write(render_index(reports, links))
    print(f"published {len(reports)} report(s) -> {args.out}/index.html")




# ---------------------------------------------------------------- scan (consumer side)

def _tuples(lst):
    return set(tuple(x) for x in lst)




FQCN_RE = None  # compiled lazily

def config_heuristics(app, lib_pkgs_dotted):
    """Comb resources and string constants for FQCNs of the library — the cheap
    part of the reflection blind spot: Class.forName literals, DI/XML config,
    properties values, SPI files. Each hit converts an invisible use into an
    explicit 'treat as reachable' row."""
    global FQCN_RE
    if FQCN_RE is None:
        FQCN_RE = re.compile(r"[a-zA-Z_$][\w$]*(?:\.[a-zA-Z_$][\w$]*){2,}")
    hits = {}   # dotted class -> sorted list of where-found
    def check(text, where):
        for m in FQCN_RE.finditer(text):
            fq = m.group(0)
            pkg = fq.rsplit(".", 1)[0]
            if any(pkg == p or pkg.startswith(p + ".") for p in lib_pkgs_dotted):
                hits.setdefault(fq, set()).add(where)
    for rel, text in app.get("resource_text", {}).items():
        check(text, f"resource:{rel}")
    for cname, c in app["classes"].items():
        for s in c.get("strings", ()):
            check(s, f"string-constant in {cname.replace('/', '.')}")
    return {k: sorted(v) for k, v in sorted(hits.items())}


def scan_intersect(app, machine):
    """Local re-run of the app intersection against a published evidence JSON.
    The publisher never sees the app; the app's source never leaves the building."""
    pkgs = set(machine["packages"])

    def in_lib(cls):
        return cls and ("/" in cls) and cls.rsplit("/", 1)[0] in pkgs

    call_sites, class_uses = set(), set()
    owners = defaultdict(set)   # app class -> refs it owns into the library
    for cname, c in app["classes"].items():
        for ref in c["refs"]:
            if in_lib(ref[0]):
                call_sites.add(ref)
                owners[cname].add(ref)
        for cls in c["class_refs"]:
            if in_lib(cls):
                class_uses.add(cls)
                owners[cname].add((cls, None, None))
    if not call_sites and not class_uses:
        return None  # app does not use this library

    changed = _tuples(machine["api_removed"]) | _tuples(machine["api_modified"])
    incompat = _tuples(machine["api_incompatible"])
    removed_classes = {k[0] for k in _tuples(machine["api_removed"]) if k[1] is None}
    impl_changed = set(machine["classes_impl_changed"])
    sk = lambda k: (k[0], k[1] or "", k[2] or "")

    return {
        "lib_call_sites": len(call_sites),
        "lib_classes_used": sorted(c.replace("/", ".") for c in class_uses),
        "touched_changed": sorted((k for k in call_sites if k in changed), key=sk),
        "touched_incompatible": sorted(
            set([k for k in call_sites if k in incompat] +
                [(c, None, None) for c in class_uses if c in removed_classes]), key=sk),
        "touched_impl_changed": sorted(
            (c.replace("/", ".") for c in class_uses if c in impl_changed)),
        "affected_app_classes": sorted(o.replace("/", ".") for o in owners),
        "affected_app_classes_changed": sorted(
            o.replace("/", ".") for o, refs in owners.items()
            if refs & (changed | incompat)),
    }


def _delta_from_machine(m):
    return {
        "api_removed": [tuple(x) for x in m["api_removed"]],
        "api_added": [tuple(x) for x in m["api_added"]],
        "api_modified": [tuple(x) for x in m["api_modified"]],
        "api_incompatible": [tuple(x) for x in m["api_incompatible"]],
        "classes_impl_changed": m["classes_impl_changed"],
        "classes_common": m["classes_common"],
        "impl_churn_pct": m["impl_churn_pct"],
        "res_removed": m["res_removed"], "res_added": m["res_added"],
        "res_changed": m["res_changed"], "spi_touched": m["spi_touched"],
    }


def _third_party_roots(app):
    """Package roots the app calls into, other than its own (heuristic: 2-level roots)."""
    own = {c.rsplit("/", 1)[0] for c in app["classes"] if "/" in c}
    roots = set()
    for c in app["classes"].values():
        for (cls, _n, _d) in c["refs"]:
            pkg = cls.rsplit("/", 1)[0] if "/" in cls else ""
            if pkg and pkg not in own and not pkg.startswith(("java/", "javax/", "jdk/", "sun/")):
                roots.add(pkg)
    return roots




def load_sbom(path):
    """CycloneDX JSON -> {'versions': {name: version}, 'parents': {child: parent},
    'root_deps': set(direct dep names)}. dependency:tree text is a planned alternate input."""
    with open(path) as f:
        bom = json.load(f)
    versions = {c["name"]: c.get("version", "?") for c in bom.get("components", [])}
    root = bom.get("metadata", {}).get("component", {}).get("name")
    parents, root_deps = {}, set()
    for d in bom.get("dependencies", []):
        ref_name = d["ref"].split("@")[0]
        for child in d.get("dependsOn", []):
            child_name = child.split("@")[0]
            if ref_name == root:
                root_deps.add(child_name)
            else:
                parents[child_name] = ref_name
    return {"versions": versions, "parents": parents, "root_deps": root_deps}




def _method_graph(model):
    """(cls,name,desc) -> callee refs, plus dispatch maps for the model's own classes."""
    defined = {}
    subclasses = defaultdict(set)     # class -> direct subclasses (within model)
    implementors = defaultdict(set)   # interface -> classes implementing it (within model)
    for cname, c in model["classes"].items():
        for m in c["members"]:
            if m["kind"] == "method":
                defined[(cname, m["name"], m["desc"])] = m
        if c.get("super") in model["classes"]:
            subclasses[c["super"]].add(cname)
        for itf in c.get("interfaces", []):
            if itf in model["classes"]:
                implementors[itf].add(cname)
    return defined, subclasses, implementors


def _resolve_dispatch(ref, model, defined, subclasses, implementors):
    """Conservative virtual/interface dispatch: the exact target, super-chain
    fallback, plus every override in subclasses / implementors."""
    cls, name, desc = ref
    out = set()
    # up the superclass chain until a definition is found
    cur = cls
    while cur in model["classes"]:
        if (cur, name, desc) in defined:
            out.add((cur, name, desc))
            break
        cur = model["classes"][cur].get("super")
    # down: overrides in subclasses and interface implementors
    frontier = list(subclasses.get(cls, ())) + list(implementors.get(cls, ()))
    seen = set()
    while frontier:
        c2 = frontier.pop()
        if c2 in seen:
            continue
        seen.add(c2)
        if (c2, name, desc) in defined:
            out.add((c2, name, desc))
        frontier += list(subclasses.get(c2, ()))
    return out


def two_hop_intersect(app, parent_model, machine):
    """Transitive reachability: BFS the parent's class graph starting from the
    parent classes the APP references, then intersect the closure's outbound
    refs into the transitive library with its changed members.

    Evidence quality is explicitly weaker than one hop: reflection blindness
    compounds, so de-escalation from this data requires an explicit sign-off.
    """
    parent_pkgs = parent_model["packages"]
    lib_pkgs = set(machine["packages"])

    def pkg(cls):
        return cls.rsplit("/", 1)[0] if cls and "/" in cls else ""

    # hop 1: the PARENT METHODS the app actually calls (method-granular seeds)
    defined, subclasses, implementors = _method_graph(parent_model)
    seeds, seed_owners, class_seeds = set(), set(), set()
    for cname, c in app["classes"].items():
        for m in c["members"]:
            for ref in m.get("calls", ()):
                if pkg(ref[0]) in parent_pkgs:
                    seeds |= _resolve_dispatch(ref, parent_model, defined,
                                               subclasses, implementors)
                    seed_owners.add(cname)
                    class_seeds.add(ref[0])
        # classes referenced without a resolvable method call still seed classes
        for cls in c["class_refs"]:
            if pkg(cls) in parent_pkgs:
                class_seeds.add(cls)
                seed_owners.add(cname)
    if not seeds and not class_seeds:
        return None

    # method-level closure inside the parent jar
    reached_m, queue = set(), sorted(seeds)
    while queue:
        mkey = queue.pop()
        if mkey in reached_m or mkey not in defined:
            continue
        reached_m.add(mkey)
        for ref in defined[mkey].get("calls", ()):
            if pkg(ref[0]) in parent_pkgs:
                for tgt in _resolve_dispatch(ref, parent_model, defined,
                                             subclasses, implementors):
                    if tgt not in reached_m:
                        queue.append(tgt)

    # class-level closure kept ONLY as the comparison number (how wide the old way was)
    cls_reach, cq = set(), sorted(class_seeds)
    while cq:
        cls = cq.pop()
        if cls in cls_reach or cls not in parent_model["classes"]:
            continue
        cls_reach.add(cls)
        for nxt in parent_model["classes"][cls]["class_refs"]:
            if pkg(nxt) in parent_pkgs and nxt not in cls_reach:
                cq.append(nxt)

    # hop 2: outbound refs from REACHED METHODS into the transitive library
    call_sites, class_uses, via = set(), set(), {}
    for mkey in reached_m:
        m = defined[mkey]
        for ref in m.get("calls", ()):
            if pkg(ref[0]) in lib_pkgs:
                call_sites.add(ref)
                via.setdefault(ref, mkey[0])
        for c2 in m.get("uses", ()):
            if pkg(c2) in lib_pkgs:
                class_uses.add(c2)

    changed = _tuples(machine["api_removed"]) | _tuples(machine["api_modified"])
    incompat = _tuples(machine["api_incompatible"])
    removed_classes = {k[0] for k in _tuples(machine["api_removed"]) if k[1] is None}
    sk = lambda k: (k[0], k[1] or "", k[2] or "")
    result = {
        "lib_call_sites": len(call_sites),
        "lib_classes_used": sorted(c.replace("/", ".") for c in class_uses),
        "touched_changed": sorted((k for k in call_sites if k in changed), key=sk),
        "touched_incompatible": sorted(
            set([k for k in call_sites if k in incompat] +
                [(c, None, None) for c in class_uses if c in removed_classes]), key=sk),
        "touched_impl_changed": sorted(
            c.replace("/", ".") for c in class_uses if c in set(machine["classes_impl_changed"])),
        "reachable_parent_classes": len(cls_reach),
        "reachable_parent_methods": len(reached_m),
        "granularity": "method",
        "class_level_would_touch": None,   # filled below
        "via": {member_str(k): v.replace("/", ".") for k, v in sorted(via.items(), key=lambda kv: sk(kv[0]))},
        "affected_app_classes": sorted(o.replace("/", ".") for o in seed_owners),
        "affected_app_classes_changed": [],   # two-hop: changed-member ownership is the parent's
    }
    # comparison: what the coarse class-level closure would have touched
    coarse_sites = set()
    for cls in cls_reach:
        for ref in parent_model["classes"][cls]["refs"]:
            if pkg(ref[0]) in lib_pkgs:
                coarse_sites.add(ref)
    result["class_level_would_touch"] = sorted(
        (member_str(k) for k in coarse_sites
         if k in changed or k in incompat), )
    return result



def merge_models(models):
    out = {"classes": {}, "class_hashes": {}, "class_norm": {}, "resources": {},
           "resource_text": {}, "class_entries": [], "api": {}, "packages": set()}
    for m in models:
        for k in ("classes", "class_hashes", "class_norm", "resources",
                  "resource_text", "api"):
            out[k].update(m[k])
        out["class_entries"] += m["class_entries"]
        out["packages"] |= m["packages"]
    return out


def artifact_inventory(app, sbom, evidence_pkg_map):
    """Fat-jar ground truth vs the declared graph. Emits hazards:
    version drift, declared-not-shipped, shipped-not-declared, relocated copies."""
    shipped = {}
    for rel, text in app.get("resource_text", {}).items():
        if rel.startswith("META-INF/maven/") and rel.endswith("pom.properties"):
            kv = dict(line.split("=", 1) for line in text.splitlines()
                      if "=" in line and not line.startswith("#"))
            if "artifactId" in kv:
                shipped[kv["artifactId"]] = kv.get("version", "?")
    hazards = []
    if shipped and sbom:
        for name, ver in sorted(shipped.items()):
            dec = sbom["versions"].get(name)
            if dec is None:
                hazards.append(("shipped-not-declared",
                                f"{name} {ver} is inside the artifact but absent from the SBOM"))
            elif dec != ver:
                hazards.append(("version-drift",
                                f"{name}: SBOM declares {dec}, artifact ships {ver} — "
                                f"you would be rating a tree that isn't running"))
        for name, ver in sorted(sbom["versions"].items()):
            if name not in shipped:
                hazards.append(("declared-not-shipped",
                                f"{name} {ver} is in the SBOM but not fingerprinted in the artifact"))
    # relocation: library class ENTRY PATHS appearing under a shifted prefix
    # (relocated-without-rewrite copies keep their internal class name, so the
    # zip path is the only place the duplication is visible)
    for lib, pkgs in evidence_pkg_map.items():
        for pkg_root in pkgs:
            prefixes = set()
            for entry in app.get("class_entries", []):
                marker = pkg_root + "/"
                pos = entry.find(marker)
                if pos > 0:
                    prefixes.add(entry[:pos])
            for prefix in sorted(prefixes):
                hazards.append(("relocated-copy",
                                f"{lib}: classes under '{pkg_root}' also exist relocated at "
                                f"'{prefix}{pkg_root}' — classpath-ordering roulette; the "
                                f"shaded copy is invisible to version-based remediation"))
    # de-dup relocation findings per lib
    seen, dedup = set(), []
    for h in hazards:
        if h not in seen:
            seen.add(h); dedup.append(h)
    return shipped, dedup


def scan(args):
    app = merge_models([load_jar(j) for j in args.app_jars])
    evidence = []
    for p in args.evidence:
        if os.path.isdir(p):
            evidence += [os.path.join(p, f) for f in sorted(os.listdir(p)) if f.endswith(".json")]
        else:
            evidence.append(p)

    sbom = load_sbom(args.sbom) if args.sbom else None
    parent_cache = {}

    def parent_model_for(lib_name):
        parent = sbom["parents"].get(lib_name) if sbom else None
        if not parent:
            return None, None
        if parent not in parent_cache:
            ver = sbom["versions"].get(parent, "")
            jar = None
            if args.lib_jars:
                cand = os.path.join(args.lib_jars, f"{parent}-{ver}.jar")
                jar = cand if os.path.isfile(cand) else None
            parent_cache[parent] = load_jar(jar) if jar else None
            if jar is None:
                print(f"  ! no jar found for parent {parent}-{ver} in --lib-jars — "
                      f"cannot compute reachability for its transitives")
        return parent, parent_cache[parent]

    # load all evidence once
    loaded = []
    for path in evidence:
        with open(path) as f:
            r = json.load(f)
        if not r.get("machine"):
            print(f"  ! {path} has no machine section (re-run analyze with this tool version) — skipped")
            continue
        loaded.append(r)

    # the APP view excludes bundled dependency code: a fat jar carries the libraries
    # inside it, and their internals must not masquerade as application call sites
    all_lib_pkgs = set()
    for r in loaded:
        all_lib_pkgs |= set(r["machine"]["packages"])
    bundled = [c for c in app["classes"]
               if "/" in c and c.rsplit("/", 1)[0] in all_lib_pkgs]
    if bundled:
        app_view = {**app,
                    "classes": {k: v for k, v in app["classes"].items()
                                if k not in set(bundled)},
                    "resource_text": {k: v for k, v in app["resource_text"].items()
                                      if not k.startswith("META-INF/")}}
        print(f"   artifact bundles {len(bundled)} dependency class(es) — "
              f"excluded from the application view (their internals are the "
              f"library's business, not yours)")
    else:
        app_view = app

    lib_old_cache = {}

    def lib_old_model_for(lib_name, old_version):
        key = (lib_name, old_version)
        if key not in lib_old_cache:
            jar = None
            if args.lib_jars:
                cand = os.path.join(args.lib_jars, f"{lib_name}-{old_version}.jar")
                jar = cand if os.path.isfile(cand) else None
            lib_old_cache[key] = load_jar(jar) if jar else None
        return lib_old_cache[key]

    # group published reports (upgrade options) by library, keep only ones the app uses
    per_lib = defaultdict(list)
    lib_meta = {}
    rated_pkgs = set()
    for r in loaded:
        m = r["machine"]
        ix = scan_intersect(app_view, m)
        transitive, parent = False, None
        if ix is None and sbom:
            parent, pmodel = parent_model_for(r["library"])
            if parent and pmodel:
                ix = two_hop_intersect(app_view, pmodel, m)
                transitive = ix is not None
        if ix is None:
            continue
        if not transitive:
            # Same-library internal call-chain check: does the app reach a
            # changed member via internal calls it never references by name?
            # Needs the library's own OLD-version jar (from --lib-jars) to BFS.
            lib_old = lib_old_model_for(r["library"], r["old_version"])
            if lib_old:
                ix["internal_chain"] = internal_chain_intersect(
                    app_view, lib_old, _delta_from_machine(m))
        rated_pkgs |= set(m["packages"])
        rating = rate(r["stream"], _delta_from_machine(m), ix,
                      transitive=transitive, signoff=args.accept_transitive_scope)
        installed = sbom["versions"].get(r["library"]) if sbom else None
        per_lib[r["library"]].append({
            "machine": m,
            "old": r["old_version"], "new": r["new_version"], "stream": r["stream"],
            "rating": rating, "ix": ix, "churn": m["impl_churn_pct"],
            "incompatible": len(m["api_incompatible"]),
            "in_place": (installed is None or installed == r["old_version"]),
        })
        lib_meta[r["library"]] = {"transitive": transitive, "parent": parent,
                                  "installed": installed}

    gi = {g: i for i, g in enumerate(GRADE_ORDER)}
    def eff(o):
        return o["rating"]["effective_grade"] or o["rating"]["grade"]
    libs = []
    for name, options in sorted(per_lib.items()):
        options.sort(key=lambda o: (gi[eff(o)], not o["in_place"]))
        meta = lib_meta[name]
        libs.append({"library": name, "options": options,
                     "recommended": options[0], "worst": options[-1],
                     "call_sites": options[0]["ix"]["lib_call_sites"],
                     "transitive": meta["transitive"], "parent": meta["parent"],
                     "installed": meta["installed"]})
    # transitives render nested under their parent
    libs.sort(key=lambda l: ((l["parent"] or l["library"]), l["transitive"]))

    # config/reflection heuristics: one row per (library, FQCN), judged against
    # the RECOMMENDED remediation path's delta
    evidence_pkg_map = {}
    heuristic_rows = []
    for l in libs:
        m0 = l["recommended"]["machine"]
        evidence_pkg_map[l["library"]] = m0["packages"]
        dotted = [p.replace("/", ".") for p in m0["packages"]]
        hits = config_heuristics(app_view, dotted)
        changed_cls_dotted = {c.replace("/", ".") for c in
                              ({k[0] for k in _tuples(m0["api_removed"])} |
                               set(m0["classes_impl_changed"]))}
        for fq, wheres in hits.items():
            flagged = any(fq == c or fq.startswith(c + ".") or c.startswith(fq)
                          for c in changed_cls_dotted)
            heuristic_rows.append({
                "library": l["library"], "fqcn": fq, "found_in": wheres,
                "intersects_change": flagged,
                "path": f"{l['recommended']['old']} -> {l['recommended']['new']}"})

    shipped_deps, hazards = artifact_inventory(app, sbom, evidence_pkg_map)

    unrated = sorted(p for p in _third_party_roots(app) if p not in rated_pkgs)
    worst_rec = max((eff(l["recommended"]) for l in libs),
                    key=lambda g: gi[g], default=None)
    worst_any = max((l["worst"]["rating"]["grade"] for l in libs),
                    key=lambda g: gi[g], default=None)
    histogram = defaultdict(lambda: {"direct": 0, "transitive": 0})
    for l in libs:
        histogram[l["recommended"]["rating"]["lane"]][
            "transitive" if l["transitive"] else "direct"] += 1
    histogram = dict(histogram)

    result = {
        "tool": {"name": "upgrade-delta", "version": TOOL_VERSION},
        "date": str(date.today()),
        "app": " + ".join(os.path.basename(j) for j in args.app_jars),
        "libraries": libs, "unrated_packages": unrated,
        "heuristics": heuristic_rows, "hazards": hazards,
        "shipped_dependencies": shipped_deps,
        "project": {
            "headline_grade": worst_rec,
            "headline_note": "worst pending grade across best available remediation paths",
            "worst_without_best_path": worst_any,
            "rated_libraries": len(libs),
            "unrated_package_roots": len(unrated),
            "lane_histogram": dict(histogram),
        },
    }

    # terminal
    print(f"\n== upgrade-delta scan :: {result['app']} ==")
    for l in libs:
        rec = l["recommended"]
        tag = f"  [transitive via {l['parent']}]" if l["transitive"] else ""
        opts = " / ".join(
            f"{o['old']}->{o['new']}: {eff(o)}" +
            ("" if o["in_place"] else " (stream switch)") for o in l["options"])
        print(f"   {l['library']}{tag}  ({l['call_sites']} call sites)   paths: {opts}")
        g = rec["rating"]
        shown = (f"{g['grade']}->{g['effective_grade']} (signed off)"
                 if g["effective_grade"] else g["grade"])
        print(f"     -> recommended: {rec['old']}->{rec['new']}  grade {shown}  lane: {g['lane']}")
        if l["transitive"]:
            ix = rec["ix"]
            print(f"        fix lever: bump {l['parent']} (or pin an override) — "
                  f"reachability: {ix.get('reachable_parent_methods','?')} parent METHODS in closure "
                  f"(class-granular would be {ix['reachable_parent_classes']} classes)")
            clw = ix.get("class_level_would_touch") or []
            if clw and not (ix["touched_changed"] or ix["touched_incompatible"]):
                print(f"        precision: class-level analysis WOULD have flagged "
                      f"{len(clw)} member(s) ({clw[0]}...) — method-level proves those "
                      f"paths are never reached from this app")
        if g["scope_note"]:
            print(f"        * {g['scope_note']}")
    for h in heuristic_rows:
        mark = "!" if h["intersects_change"] else "·"
        print(f"   {mark} config/reflection heuristic: {h['fqcn']} "
              f"({h['library']}) found in {h['found_in'][0]}"
              + (" — INTERSECTS a changed/removed class: treat as reachable"
                 if h["intersects_change"] else ""))
    for kind, msg in hazards:
        print(f"   HAZARD [{kind}] {msg}")
    if unrated:
        print(f"   unrated third-party packages: {', '.join(p.replace('/', '.') for p in unrated)}")
    print(f"   PROJECT: {worst_rec or '—'} (best paths)"
          + (f"  |  would be {worst_any} without them" if worst_any != worst_rec else ""))
    print("   lanes: " + ", ".join(
        f"{k}: {v['direct']}+{v['transitive']}t" for k, v in histogram.items()))

    if args.json:
        # strip tuples for json
        def clean(o):
            for opt in o["options"]:
                opt.pop("machine", None)
                opt["ix"] = {**opt["ix"],
                    "touched_changed": [member_str(t) for t in opt["ix"]["touched_changed"]],
                    "touched_incompatible": [member_str(t) for t in opt["ix"]["touched_incompatible"]]}
            o["recommended"] = o["options"][0]; o["worst"] = o["options"][-1]
            return o
        out = {**result, "libraries": [clean(dict(l)) for l in libs]}
        with open(args.json, "w") as f:
            json.dump(out, f, indent=2)
        print(f"  scorecard json: {args.json}")
    if args.html:
        with open(args.html, "w") as f:
            f.write(render_scorecard(result))
        print(f"  scorecard:      {args.html}")

    if args.routing_payload:
        shrinkable = {"Fast lane", "Targeted tests"}
        payload = {
            "schema": "upgrade-delta/routing/v1",
            "tool": {"name": "upgrade-delta", "version": TOOL_VERSION},
            "date": str(date.today()), "app": result["app"],
            "project_grade": worst_rec,
            "shrink_allowed": all(l["recommended"]["rating"]["lane"] in shrinkable
                                  for l in libs) if libs else False,
            "upgrades": [{
                "library": l["library"],
                "path": f"{l['recommended']['old']} -> {l['recommended']['new']}",
                "lane": l["recommended"]["rating"]["lane"],
                "grade": l["recommended"]["rating"]["grade"],
                "effective_grade": l["recommended"]["rating"]["effective_grade"],
                "transitive": l["transitive"], "parent": l["parent"],
                "affected_app_classes": l["recommended"]["ix"].get("affected_app_classes", []),
                "affected_app_classes_changed": l["recommended"]["ix"].get("affected_app_classes_changed", []),
                "confidence": {
                    "evidence": "two-hop" if l["transitive"] else "direct",
                    "signed_off": bool(l["recommended"]["rating"]["effective_grade"]),
                },
            } for l in libs],
            "obligations": [
                {"id": "boot-test", "stage": "in-scope",
                 "declaration": {"type": "tag", "value": "upgrade-gate"}, "min_resolved": 1},
                {"id": "canary", "stage": "downstream",
                 "note": "deployment-stage activity; a build plugin cannot run or verify this"},
                {"id": "rollback-path", "stage": "downstream",
                 "note": "verify rollback artifact + procedure before promotion"},
            ],
            "blind_spots": [
                "Reflection/config-driven use invisible to static analysis; compounds across hops.",
                "Selection strength depends on the consumer-side coverage map, which this payload knows nothing about.",
            ],
        }
        with open(args.routing_payload, "w") as f:
            json.dump(payload, f, indent=2)
        print(f"  routing payload: {args.routing_payload}")

    if args.fail_on and worst_rec and gi[worst_rec] >= gi[args.fail_on]:
        print(f"  FAIL: project grade {worst_rec} >= --fail-on {args.fail_on}")
        sys.exit(2)
    return result


def render_scorecard(r):
    p = r["project"]
    color = GRADE_COLOR.get(p["headline_grade"], "var(--steel)")
    lanes_order = ["Fast lane", "Targeted tests", "Partial regression",
                   "Full regression", "Full regression + migration"]
    total = max(sum(h.get("direct", 0) + h.get("transitive", 0)
                    for h in p["lane_histogram"].values()), 1)
    bars = ""
    for lane in lanes_order:
        h = p["lane_histogram"].get(lane)
        if not h:
            continue
        d_n, t_n = h.get("direct", 0), h.get("transitive", 0)
        d_pct = round(100 * d_n / total); t_pct = round(100 * t_n / total)
        label = f"{d_n + t_n}" + (f" ({t_n}t)" if t_n else "")
        bars += (f'<div class="bar-row"><span class="bar-label">{esc(lane)}</span>'
                 f'<span class="bar"><i style="width:{d_pct}%"></i>'
                 f'<i class="t" style="width:{t_pct}%"></i></span>'
                 f'<span class="bar-n">{label}</span></div>')
    bars += ('<div class="bar-row"><span class="bar-label"></span>'
             '<span class="lane" style="grid-column:2/4">solid = direct · '
             'hatched = transitive (counted at full weight — risk does not roll up)</span></div>')

    rows = ""
    for l in r["libraries"]:
        opts_html = ""
        for o in l["options"]:
            g = o["rating"]
            shown = g["effective_grade"] or g["grade"]
            c = GRADE_COLOR[shown]
            chip = (f'{g["grade"]} → {g["effective_grade"]}' if g["effective_grade"] else g["grade"])
            marker = " ←" if o is l["recommended"] and len(l["options"]) > 1 else ""
            switch = "" if o.get("in_place", True) else                 f'<span class="lane"> · stream switch from {esc(l.get("installed") or "?")}</span>'
            opts_html += (f'<div><span class="chip" style="--c:{c}">{chip}</span> '
                          f'<span class="m">{esc(o["old"])} → {esc(o["new"])}</span>'
                          f'<span class="lane"> · {esc(g["lane"])}{marker}</span>{switch}</div>')
        rec = l["recommended"]
        g = rec["rating"]
        touched = (len(rec["ix"]["touched_incompatible"]), len(rec["ix"]["touched_changed"]))
        if l["transitive"]:
            via = rec["ix"].get("via", {})
            via_line = next(iter(via.items()), None)
            via_html = (f'<br><span class="lane">e.g. {esc(via_line[1])} → '
                        f'<span class="m">{esc(via_line[0])}</span></span>') if via_line else ""
            note = (f'<div class="note" style="margin:8px 0 0">{esc(g["scope_note"])}</div>'
                    if g["scope_note"] else "")
            rows += f"""<tr class="sub"><td><span class="lane">↳ transitive</span> <b>{esc(l['library'])}</b><br>
<span class="lane">brought in by {esc(l['parent'])} · fix lever: bump {esc(l['parent'])} or pin an override<br>
{rec['ix'].get('reachable_parent_methods', '?')} parent methods in reachability closure
(class-granular: {rec['ix']['reachable_parent_classes']} classes) ·
touches {touched[1]} changed / {touched[0]} incompatible through your paths</span>{via_html}
{f"<br><span class='lane'>precision: class-level analysis would have flagged {len(rec['ix'].get('class_level_would_touch') or [])} member(s) — method-level shows those paths are unreached</span>" if (rec['ix'].get('class_level_would_touch') and not (rec['ix']['touched_changed'] or rec['ix']['touched_incompatible'])) else ""}</td>
<td>{opts_html}{note}</td></tr>"""
        else:
            note = (f'<div class="note" style="margin:8px 0 0">{esc(g["scope_note"])}</div>'
                    if g["scope_note"] else "")
            chain = rec["ix"].get("internal_chain")
            chain_html = ""
            if chain and chain.get("closure_methods_reached"):
                hits = (chain["internal_touched_incompatible"] + chain["internal_touched_changed"]
                        + chain["internal_touched_impl_changed"])
                if hits:
                    chain_html = (f'<br><span class="lane">internal call chain traced '
                                   f'{chain["closure_methods_reached"]} method(s) from your '
                                   f'{chain["closure_seed_count"]} entry point(s) — reaches changed: '
                                   f'<span class="m">{esc(hits[0])}</span>'
                                   + (f' (+{len(hits)-1} more)' if len(hits) > 1 else '')
                                   + '</span>')
                else:
                    chain_html = (f'<br><span class="lane">internal call chain traced '
                                   f'{chain["closure_methods_reached"]} method(s) from your '
                                   f'{chain["closure_seed_count"]} entry point(s) — none reach a changed '
                                   f'member</span>')
            rows += f"""<tr><td><b>{esc(l['library'])}</b><br>
<span class="lane">{l['call_sites']} direct call sites · touches {touched[1]} changed / {touched[0]} incompatible on best path</span>{chain_html}</td>
<td>{opts_html}{note}</td></tr>"""

    hazards_html = ""
    if r.get("hazards"):
        items = "".join(
            f'<li><span class="m">[{esc(k)}]</span> {esc(msg)}</li>'
            for k, msg in r["hazards"])
        hazards_html = f"""<h2>Hazards — artifact vs declared graph</h2>
<p style="color:var(--ink-soft)">The SBOM is the map; the shipped artifact is the territory.
Where they disagree, you would otherwise be rating a dependency tree that isn't the one running.</p>
<ul>{items}</ul>"""

    heur_html = ""
    if r.get("heuristics"):
        items = ""
        for h in r["heuristics"]:
            badge = ('<span class="chip" style="--c:var(--stop)">reachable</span> '
                     if h["intersects_change"] else
                     '<span class="chip" style="--c:var(--steel)">info</span> ')
            items += (f'<li>{badge}<span class="m">{esc(h["fqcn"])}</span> '
                      f'<span class="lane">({esc(h["library"])}, path {esc(h.get("path",""))}) '
                      f'found in {esc(h["found_in"][0])}'
                      + (" — intersects a changed/removed class on the recommended path: "
                         "treat as reachable regardless of call-graph silence"
                         if h["intersects_change"] else "") + '</span></li>')
        heur_html = f"""<h2>Config &amp; reflection heuristics</h2>
<p style="color:var(--ink-soft)">FQCNs of rated libraries found in resources and string
constants — the cheap slice of the reflection blind spot, made visible instead of disclaimed.</p>
<ul>{items}</ul>"""

    unrated_html = ""
    if r["unrated_packages"]:
        items = "".join(f'<li class="m">{esc(u.replace("/", "."))}</li>' for u in r["unrated_packages"])
        unrated_html = f"""<h2>Not rated — visible whitespace</h2>
<p style="color:var(--ink-soft)">The application calls into these third-party packages, and no
delta report covers them. Every entry here is an upgrade you would be testing blind today.</p>
<ul class="list">{items}</ul>"""

    compare = ""
    if p["worst_without_best_path"] and p["worst_without_best_path"] != p["headline_grade"]:
        c2 = GRADE_COLOR[p["worst_without_best_path"]]
        compare = (f'<div class="note">Without the best available remediation paths this project '
                   f'scores <span class="chip" style="--c:{c2}">{p["worst_without_best_path"]}</span> — '
                   f'the gap between the two numbers is what a maintained backport is worth, measured.</div>')

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(r['app'])} — project delta scorecard</title>
{FONTS}<style>{CSS}
.bar-row{{display:grid;grid-template-columns:200px 1fr 30px;gap:10px;align-items:center;margin:6px 0}}
.bar-label{{font-family:var(--mono);font-size:12px;color:var(--ink-soft)}}
.bar{{background:color-mix(in srgb,var(--rule) 55%,transparent);height:14px;display:block}}
.bar{{display:flex}}
.bar i{{display:block;height:100%;background:var(--steel)}}
.bar i.t{{background:repeating-linear-gradient(45deg,var(--steel) 0 4px,color-mix(in srgb,var(--steel) 35%,var(--card)) 4px 8px)}}
tr.sub td{{background:color-mix(in srgb,var(--rule) 22%,var(--card))}}
tr.sub td:first-child{{padding-left:28px}}
.bar-n{{font-family:var(--mono);font-size:13px;text-align:right}}
</style></head><body>
<div class="sheet" style="--stamp-c:{color}">
  <div class="stamp"><span class="g">{esc(p['headline_grade'] or '—')}</span><span class="l">project</span></div>
  <div class="eyebrow">Lightwell delta scan · project scorecard</div>
  <h1>{esc(r['app'])}</h1>
  <div class="vers">{p['rated_libraries']} rated dependencies · {p['unrated_package_roots']} unrated package roots</div>
  <p style="max-width:62ch;color:var(--ink-soft)">The headline is the <b>worst pending grade across
  the best available remediation path per library</b> — never an average. One migration-grade
  dependency makes this a migration-grade project, no matter how clean the rest is.</p>
  {compare}
  <h2>Test-effort budget to get current</h2>{bars}
  <h2>Dependencies</h2>{_grade_legend_html()}
  <table><thead><tr><th>Library · exposure</th><th>Remediation paths (best first)</th></tr></thead>
  <tbody>{rows}</tbody></table>
  {hazards_html}
  {heur_html}
  {unrated_html}
  <h2>What this scan cannot see</h2>
  <div class="blind"><ul>
    <li>Reflection and config-driven use of a library will not appear as call sites — and this
    blindness compounds across hops, so transitive reachability evidence carries lower confidence
    than direct analysis. De-escalating a transitive always requires explicit sign-off.</li>
    <li>Ratings come from published, app-agnostic delta reports; only the intersection ran here — your code never left this machine.</li>
    <li>A behavior change with no structural fingerprint is invisible; canary and rollback stay in every lane.</li>
  </ul></div>
  <div class="footer"><span>gate suggestion: fail CI when project grade ≥ D</span>
  <span>upgrade-delta v{TOOL_VERSION} · {esc(r['date'])}</span></div>
</div></body></html>"""





# ---------------------------------------------------------------- lightwell coverage

RHSUFFIX = None  # compiled lazily

def _base_version(v):
    """Strip Red Hat build suffixes: 2.13.4.rhlw-00001 / 2.13.4.rhlw-00001 -> 2.13.4"""
    global RHSUFFIX
    if RHSUFFIX is None:
        RHSUFFIX = re.compile(r"[.-](redhat|rhlw)-\d+$")
    return RHSUFFIX.sub("", v or "")


def _version_key(v):
    """Loose semantic-version sort key: '5.3.18' -> (5,3,18); tolerant of
    non-numeric segments ('1.0.0-beta' -> (1,0,0,'beta')). Used only to
    compare direction (newer/older), not to validate version syntax."""
    parts = re.split(r"[.\-+]", v or "")
    key = []
    for p in parts:
        key.append((0, int(p)) if p.isdigit() else (1, p))
    return tuple(key)


def load_catalog(path):
    """Lightwell catalog SBOM -> {(group, artifact): {base_version: full_version}}"""
    with open(path) as f:
        bom = json.load(f)
    cat = defaultdict(dict)
    for c in bom.get("components", []):
        g, n, v = c.get("group"), c.get("name"), c.get("version")
        if n and v:
            cat[(g, n)][_base_version(v)] = v
    return dict(cat)


def coverage(args):
    """Match an application's dependencies against the Lightwell remediated catalog."""
    cat = load_catalog(args.catalog)
    with open(args.sbom) as f:
        bom = json.load(f)
    app_name = bom.get("metadata", {}).get("component", {}).get("name", os.path.basename(args.sbom))

    exact, near, uncovered = [], [], []
    for c in bom.get("components", []):
        if c.get("type") not in (None, "library"):
            continue
        g, n, v = c.get("group"), c.get("name"), c.get("version")
        if not n or not v:
            continue
        entry = cat.get((g, n)) or cat.get((None, n))
        base_v = _base_version(v)
        if entry is None:
            uncovered.append((g, n, v))
        elif v in entry:
            # v itself is a plain (unsuffixed) version Red Hat also publishes.
            exact.append((g, n, v, entry[v]))
        elif base_v in entry and entry[base_v] == v:
            # v IS ALREADY the exact remediated build (…rhlw-NNNNN) -- the
            # developer already adopted it. This is the best possible state,
            # not a gap: report it as covered, using itself as the target.
            exact.append((g, n, v, v))
        else:
            # Only count a base version as "serviced" if Red Hat's build is
            # the same version or NEWER than what's running -- a catalog
            # entry that's strictly older is a downgrade, not a usable
            # remediation path, so it doesn't belong in this bucket.
            # Compare on the STRIPPED base version on both sides, so a
            # running version that already carries its own build suffix
            # (adopted, but for a different release than the catalog's
            # current one) still compares correctly against plain catalog
            # base-version keys.
            run_key = _version_key(base_v)
            forward = sorted(
                (base for base in entry if _version_key(base) >= run_key),
                key=_version_key)
            if forward:
                near.append((g, n, v, [entry[b] for b in forward]))
            else:
                uncovered.append((g, n, v))

    total = len(exact) + len(near) + len(uncovered)
    result = {
        "tool": {"name": "upgrade-delta", "version": TOOL_VERSION},
        "date": str(date.today()), "app": app_name,
        "catalog": os.path.basename(args.catalog),
        "totals": {"dependencies": total, "exact": len(exact),
                   "serviced_other_version": len(near), "uncovered": len(uncovered)},
        "exact": [{"group": g, "artifact": n, "version": v, "remediated": rv}
                  for g, n, v, rv in sorted(exact)],
        "serviced_other_version": [
            {"group": g, "artifact": n, "version": v, "serviced_versions": sv}
            for g, n, v, sv in sorted(near)],
        "uncovered": [{"group": g, "artifact": n, "version": v}
                      for g, n, v in sorted(uncovered)],
    }

    pct = round(100 * len(exact) / total) if total else 0
    print(f"\n== Lightwell coverage :: {app_name} ==")
    print(f"   {total} dependencies checked against {result['catalog']}")
    print(f"   {pct}% drop-in ready — {len(exact)} covered, "
          f"{len(near)} serviced at another version, {len(uncovered)} not covered\n")
    print(f"   COVERED ({len(exact)}) — drop-in remediated build, no upgrade needed:")
    for g, n, v, rv in sorted(exact):
        print(f"     {g}:{n}  {v} -> {rv}")
    if near:
        print(f"\n   SERVICED AT ANOTHER VERSION ({len(near)}) — upgrade, or request your version:")
        for g, n, v, sv in sorted(near):
            print(f"     {g}:{n}  you run {v}  |  serviced: {', '.join(sv)}")
    if uncovered:
        print(f"\n   NOT COVERED ({len(uncovered)}) — no remediated build; full regression on any upgrade:")
        for g, n, v in sorted(uncovered):
            print(f"     {g}:{n}  {v}")

    if args.json:
        with open(args.json, "w") as f:
            json.dump(result, f, indent=2)
        print(f"  coverage json: {args.json}")
    if args.html:
        with open(args.html, "w") as f:
            f.write(render_coverage(result))
        print(f"  coverage card: {args.html}")
    return result


def render_coverage(r):
    t = r["totals"]
    total = t["dependencies"] or 1
    pct = round(100 * t["exact"] / total)
    near_pct = round(100 * t["serviced_other_version"] / total)
    unc_pct = round(100 * t["uncovered"] / total)

    def gav(e):
        g = esc(e["group"] or "")
        return f'{g}:{esc(e["artifact"])}' if g else esc(e["artifact"])

    covered_rows = "".join(
        f'<tr><td class="dep">{gav(e)}</td>'
        f'<td class="ver">{esc(e["version"])}</td>'
        f'<td class="ver arrow">{esc(e["remediated"])}</td>'
        f'<td class="act">{"Already on the Red Hat remediated build." if e["version"] == e["remediated"] else "Swap the version suffix. No code change."}</td></tr>'
        for e in r["exact"])
    near_rows = "".join(
        f'<tr><td class="dep">{gav(e)}</td>'
        f'<td class="ver">{esc(e["version"])}</td>'
        f'<td class="ver">{esc(", ".join(e["serviced_versions"]))}</td>'
        f'<td class="act">Move to a serviced version, or request your version.</td></tr>'
        for e in r["serviced_other_version"])
    unc_rows = "".join(
        f'<tr><td class="dep">{gav(e)}</td>'
        f'<td class="ver">{esc(e["version"])}</td>'
        f'<td class="ver dash">not serviced</td>'
        f'<td class="act">No remediated build. Full regression on any upgrade.</td></tr>'
        for e in r["uncovered"])

    def section(kind, color, title, subtitle, count, rows, head3):
        if not rows:
            return ""
        return f'''<section class="grp">
      <div class="grp-h" style="--gc:{color}">
        <span class="pill">{count}</span>
        <div><div class="grp-t">{title}</div><div class="grp-s">{subtitle}</div></div>
      </div>
      <table class="grid"><thead><tr>
        <th>Dependency</th><th>You run</th><th>{head3}</th><th>What it means for you</th>
      </tr></thead><tbody>{rows}</tbody></table>
    </section>'''

    body = (
        section("ok", "var(--pass)", "Covered — drop-in remediated build",
                "Red Hat rebuilt the exact version you run, with the fix. A configuration "
                "change, not an upgrade.", t["exact"], covered_rows, "Remediated build") +
        section("watch", "var(--pass)", "Serviced — at a different version",
                "Red Hat services this library at a newer or matching version. A real "
                "upgrade, or a request for your exact version.", t["serviced_other_version"], near_rows,
                "Serviced versions") +
        section("stop", "var(--stop)", "Not covered",
                "No remediated build exists. Any upgrade here carries the full, unscoped test "
                "burden — the situation this tool exists to remove.", t["uncovered"],
                unc_rows, "Status"))

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(r['app'])} — Lightwell coverage</title>{FONTS}<style>{CSS}
.cov-sub{{color:var(--ink-soft);max-width:70ch;margin:2px 0 22px;font-size:14px;line-height:1.55}}
.legend{{display:flex;gap:26px;margin:0 0 26px;flex-wrap:wrap}}
.legend .li{{display:flex;align-items:baseline;gap:9px}}
.legend .n{{font:700 22px/1 var(--head,inherit)}}
.legend .t{{font-size:12.5px;color:var(--ink-soft)}}
.legend .dot{{width:9px;height:9px;border-radius:50%;align-self:center}}
.grp{{margin:0 0 26px}}
.grp-h{{display:flex;align-items:center;gap:13px;padding:0 0 9px;border-bottom:2px solid var(--gc);margin-bottom:0}}
.grp .pill{{background:var(--gc);color:#fff;font:700 14px/1 var(--head,inherit);
  min-width:30px;height:30px;border-radius:15px;display:flex;align-items:center;justify-content:center;padding:0 8px}}
.grp-t{{font:700 15px/1.2 var(--head,inherit);color:var(--ink)}}
.grp-s{{font-size:12px;color:var(--ink-soft);margin-top:3px}}
table.grid{{width:100%;border-collapse:collapse}}
table.grid th{{text-align:left;font-size:10.5px;letter-spacing:.05em;text-transform:uppercase;
  color:var(--ink-soft);font-weight:600;padding:11px 12px 7px;border-bottom:1px solid var(--line,#e5e5e5)}}
table.grid td{{padding:9px 12px;border-bottom:1px solid var(--line,#eee);font-size:13px;vertical-align:top}}
table.grid tr:last-child td{{border-bottom:none}}
td.dep{{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px;color:var(--ink);white-space:nowrap}}
td.ver{{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px;color:var(--ink-soft);white-space:nowrap}}
td.ver.arrow{{color:var(--pass);font-weight:600}}
td.ver.arrow::before{{content:"\2192  ";color:var(--ink-soft);font-weight:400}}
td.ver.dash{{color:var(--stop)}}
td.act{{color:var(--ink);font-size:12.5px}}
</style></head><body>
<div class="sheet" style="--stamp-c:{'var(--pass)' if pct >= 60 else 'var(--watch)'}">
  <div class="stamp"><span class="g">{pct}%</span><span class="l">drop-in ready</span></div>
  <div class="eyebrow">Lightwell coverage meter</div>
  <h1>{esc(r['app'])}</h1>
  <div class="vers">{t['dependencies']} dependencies checked against {esc(r['catalog'])}</div>
  <p class="cov-sub">How much of this application's dependency risk Red Hat Lightwell can
  remediate <b>without an upgrade</b> — today, for the exact versions in production.</p>
  <div class="legend">
    <div class="li"><span class="dot" style="background:var(--pass)"></span>
      <span class="n" style="color:var(--pass)">{t['exact']}</span>
      <span class="t">drop-in remediated<br>({pct}% of deps)</span></div>
    <div class="li"><span class="dot" style="background:var(--pass)"></span>
      <span class="n" style="color:var(--pass)">{t['serviced_other_version']}</span>
      <span class="t">serviced, other version<br>({near_pct}%)</span></div>
    <div class="li"><span class="dot" style="background:var(--stop)"></span>
      <span class="n" style="color:var(--stop)">{t['uncovered']}</span>
      <span class="t">not covered<br>({unc_pct}%)</span></div>
  </div>
  {body}
  <div class="footer"><span>Covered = same base version, rebuilt by Red Hat (\u2026.rhlw-NNNNN suffix)</span>
  <span>upgrade-delta v{TOOL_VERSION} · {esc(r['date'])}</span></div>
</div></body></html>"""


# ---------------------------------------------------------------- seal / verify

def _canonical(path):
    """Signature is over canonical JSON (sorted keys, tight separators), so
    formatting changes don't break verification but VALUE changes do."""
    with open(path) as f:
        return json.dumps(json.load(f), sort_keys=True,
                          separators=(",", ":")).encode()


def seal(args):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    import base64
    if os.path.exists(args.key):
        with open(args.key, "rb") as f:
            priv = serialization.load_pem_private_key(f.read(), password=None)
    else:
        priv = Ed25519PrivateKey.generate()
        os.makedirs(os.path.dirname(args.key) or ".", exist_ok=True)
        with open(args.key, "wb") as f:
            f.write(priv.private_bytes(serialization.Encoding.PEM,
                                       serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
        os.chmod(args.key, 0o600)
        print(f"  generated signing key: {args.key} (keep this out of the repo; "
              f"production path: Sigstore keyless in CI — see integration/signing.md)")
    pub_path = args.key + ".pub"
    with open(pub_path, "wb") as f:
        f.write(priv.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    for p in args.files:
        sig = priv.sign(_canonical(p))
        with open(p + ".sig", "w") as f:
            f.write(base64.b64encode(sig).decode())
        print(f"  sealed {p} -> {p}.sig")
    print(f"  public key: {pub_path}")


def verify_seal(args):
    from cryptography.hazmat.primitives import serialization
    from cryptography.exceptions import InvalidSignature
    import base64
    with open(args.pub, "rb") as f:
        pub = serialization.load_pem_public_key(f.read())
    ok = True
    for p in args.files:
        try:
            with open(p + ".sig") as f:
                sig = base64.b64decode(f.read())
            pub.verify(sig, _canonical(p))
            print(f"  VERIFIED {p}")
        except FileNotFoundError:
            print(f"  FAILED   {p}: no detached signature ({p}.sig missing)")
            ok = False
        except InvalidSignature:
            print(f"  FAILED   {p}: signature does not match content — "
                  f"this document has been edited since it was sealed")
            ok = False
    if not ok:
        sys.exit(5)

# ---------------------------------------------------------------- cli

def main():
    ap = argparse.ArgumentParser(prog="upgrade-delta", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze", help="diff two versions of a library jar")
    a.add_argument("old_jar"); a.add_argument("new_jar")
    a.add_argument("--app", help="application jar/classes to intersect with")
    a.add_argument("--old-version", required=True)
    a.add_argument("--new-version", required=True)
    a.add_argument("--library", help="display name")
    a.add_argument("--json", help="write evidence JSON here")
    a.add_argument("--html", help="write HTML report card here")
    a.add_argument("--routing-payload", help="write the affected-code payload for the "
                   "consumer-side test router (requires --app)")
    a.add_argument("--scorecard-compat", help="write a scan()-schema-compatible scorecard.json "
                   "so upgrade-delta-summary/upgrade-delta-pr-comment work unchanged")
    a.set_defaults(fn=analyze)

    s = sub.add_parser("scan", help="score a whole application against published delta reports")
    s.add_argument("app_jars", nargs="+",
                   help="application jar(s)/modules — a reactor passes all module jars")
    s.add_argument("--evidence", nargs="+", required=True,
                   help="evidence JSON files and/or directories of them")
    s.add_argument("--json", help="write scorecard JSON here")
    s.add_argument("--html", help="write scorecard HTML here")
    s.add_argument("--sbom", help="CycloneDX JSON: the declared dependency graph "
                   "(who brought in whom); enables transitive analysis")
    s.add_argument("--lib-jars", help="directory containing the installed dependency jars "
                   "(the resolved classpath) for two-hop reachability")
    s.add_argument("--routing-payload", help="write the affected-code payload for the "
                   "test router here (contract: affected code, never selected tests)")
    s.add_argument("--accept-transitive-scope", action="store_true",
                   help="sign off on de-escalating transitives whose changed members "
                   "are unreachable through your call paths")
    s.add_argument("--fail-on", choices=GRADE_ORDER,
                   help="exit non-zero if project grade is this bad or worse")
    s.set_defaults(fn=scan)

    cv = sub.add_parser("coverage", help="match an app SBOM against the Lightwell "
                        "remediated catalog: exact drop-in builds vs blind spots")
    cv.add_argument("--sbom", required=True, help="the application's CycloneDX SBOM")
    cv.add_argument("--catalog", required=True,
                    help="Lightwell catalog SBOM (e.g. catalogs/lightwell-remediated-java-sbom.json)")
    cv.add_argument("--json"); cv.add_argument("--html")
    cv.set_defaults(fn=coverage)

    se = sub.add_parser("seal", help="detached Ed25519 signatures over evidence JSON")
    se.add_argument("files", nargs="+")
    se.add_argument("--key", default="out/keys/evidence-signing.pem")
    se.set_defaults(fn=seal)

    ve = sub.add_parser("verify", help="verify sealed evidence documents")
    ve.add_argument("files", nargs="+")
    ve.add_argument("--pub", default="out/keys/evidence-signing.pem.pub")
    ve.set_defaults(fn=verify_seal)

    p = sub.add_parser("publish", help="build a static catalog from evidence JSONs")
    p.add_argument("reports", nargs="+")
    p.add_argument("--out", required=True)
    p.set_defaults(fn=publish)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
