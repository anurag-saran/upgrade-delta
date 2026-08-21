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
import urllib.error
import urllib.request
import zipfile
from collections import defaultdict
from datetime import date

# Lightwell publishes OSV advisories (not CSAF/VEX siblings) for remediated builds.
# Public demo index — anonymous fetch works. Auth `/lightwell/osv/` is 401.
DEFAULT_OSV_URL = (
    "https://packages.redhat.com/api/pulp-content/"
    "public-lightwell-demo/osv/java/remediated"
)

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
        "lib_members_used": [member_str(k) for k in sorted(call_sites, key=sk)],
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
    "A": ("Just smoke-test it", ["Smoke test the service",
                                 "Roll out to one instance first",
                                 "Watch health and error rate, then roll out fully"]),
    "B": ("Test the parts you use", ["Smoke test the service",
                             "Test the parts of your code that call this library",
                             "Re-check anything that relied on a default setting that changed",
                             "Roll out to one instance, watch, then roll out fully"]),
    "C": ("Test each module that uses it", ["Run the full test suite of every module that uses this library",
                                 "Do one production-like startup test (wiring, classpath scanning)",
                                 "Test the behaviour other systems depend on",
                                 "Roll out to one instance, watch, then roll out fully"]),
    "D": ("Run your full test suite", ["Run the entire regression suite",
                              "Do a production-like startup test",
                              "Integration-test every path that reaches this library",
                              "Roll out to one instance, watch, then roll out fully"]),
    "F": ("Fix your code first", ["Change your code before this will even compile and run",
                                          "Run the entire regression suite afterwards",
                                          "Do a production-like startup test",
                                          "Watch a single instance for longer than usual"]),
}

# Scorecard "Do:" wording after the pipeline has already selected+run tests —
# descriptive scope, not an imperative the reader still needs to perform.
SCOPE_FROM_LANE = {
    "Just smoke-test it": "smoke test",
    "Test the parts you use": "parts of your code that call this library",
    "Test each module that uses it": "modules using this",
    "Run your full test suite": "full regression suite",
    "Fix your code first": "fix your code first, then re-test",
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
                        scope_note = ("You could test this more lightly: nothing your app calls "
                                      "actually changed shape. With sign-off, run the lighter test "
                                      "set instead — but still roll out to one instance first.")
                elif signoff:
                    effective_grade = "B"
                    scope_note = ("Downgraded from D to B, with sign-off: nothing that changed is "
                                  "reachable from your app's code paths. This evidence crosses two "
                                  "libraries, and indirect calls are harder to see through, so still "
                                  "roll out to one instance first and watch it.")
                else:
                    scope_note = ("This could be downgraded to B, but it needs explicit sign-off "
                                  "(--accept-transitive-scope): nothing that changed is reachable "
                                  "from your code paths. Not applied automatically, because evidence "
                                  "that crosses two libraries is less certain than direct evidence.")

    lane, recipe = LANES[effective_grade or grade]
    return {"grade": grade, "effective_grade": effective_grade, "lane": lane,
            "recipe": recipe, "reasons": reasons, "scope_note": scope_note}


# ---------------------------------------------------------------- analyze

def analyze(args):
    old = load_jar(args.old_jar)
    new = load_jar(args.new_jar)
    stream = classify_stream(args.old_version, args.new_version)
    delta = diff_jars(old, new)

    # 'machine' is built here (not further down) because two-hop mode needs it
    # as an input to two_hop_intersect -- it's the exact shape a published
    # evidence file's "machine" section already has, by design.
    machine_dict = {
        "packages": sorted(old["packages"]),
        "api_removed": [list(k) for k in delta["api_removed"]],
        "api_modified": [list(k) for k in delta["api_modified"]],
        "api_incompatible": [list(k) for k in delta["api_incompatible"]],
        "classes_impl_changed": delta["classes_impl_changed"],
    }

    transitive_mode = bool(args.transitive_of)
    if transitive_mode and not args.parent_jar:
        print("FATAL: --transitive-of requires --parent-jar", file=sys.stderr)
        sys.exit(2)

    app_ix = None
    if args.app:
        app_loaded = load_jar(args.app)
        if transitive_mode:
            parent_model = load_jar(args.parent_jar)
            app_ix = two_hop_intersect(app_loaded, parent_model, machine_dict)
            if app_ix is None:
                # app never calls the parent at all -- nothing to grade through it
                app_ix = {"touched_changed": [], "touched_incompatible": [],
                          "lib_call_sites": 0, "lib_classes_used": [],
                          "lib_members_used": [],
                          "reachable_parent_methods": 0, "reachable_parent_classes": 0,
                          "via": {}}
        else:
            app_ix = intersect_app(app_loaded, old, delta)
            app_ix["internal_chain"] = internal_chain_intersect(app_loaded, old, delta)
    rating = rate(stream, delta, app_ix, transitive=transitive_mode,
                  signoff=args.accept_transitive_scope)

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
            **machine_dict,
            "api_added": [list(k) for k in delta["api_added"]],
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
        shrinkable = {"Just smoke-test it", "Test the parts you use"}  # grades A / B
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
        new_entry = {
            "library": report["library"],
            "transitive": transitive_mode,
            "parent": args.transitive_of if transitive_mode else None,
            # 'installed' and 'call_sites' are part of scan()'s library
            # schema; summary/pr-comment read them directly, so a
            # scorecard-compat payload must supply them too.
            "installed": args.old_version,
            "call_sites": (app_ix or {}).get("lib_call_sites", 0),
            "recommended": {"old": args.old_version, "new": args.new_version,
                             "rating": rating, "ix": app_ix or {}},
            "worst": {"old": args.old_version, "new": args.new_version, "rating": rating},
        }

        # If the file already exists (a prior analyze --scorecard-compat run
        # for a sibling dependency -- e.g. the direct dependency was already
        # written, and this call is grading a transitive it pulled in),
        # APPEND to it instead of overwriting, so one PR comment shows both.
        if os.path.exists(args.scorecard_compat):
            with open(args.scorecard_compat) as f:
                compat = json.load(f)
            compat["libraries"].append(new_entry)
        else:
            compat = {
                "tool": {"name": "upgrade-delta", "version": TOOL_VERSION},
                "date": str(date.today()), "app": report["app"] or "app",
                "libraries": [new_entry],
                "unrated_packages": [], "heuristics": [], "hazards": [],
                "shipped_dependencies": [],
                "project": {},
            }

        # Recompute the project-level rollup across EVERY entry now present,
        # not just this one -- the worst grade of any dependency wins.
        def _eff(lib):
            r = lib["recommended"]["rating"]
            return r.get("effective_grade") or r["grade"]
        worst_rec = max((_eff(l) for l in compat["libraries"]), key=lambda g: GRADE_ORDER.index(g))
        worst_any = max((l["worst"]["rating"]["grade"] for l in compat["libraries"]),
                         key=lambda g: GRADE_ORDER.index(g))
        histogram = {}
        for l in compat["libraries"]:
            lane = l["recommended"]["rating"]["lane"]
            bucket = histogram.setdefault(lane, {"direct": 0, "transitive": 0})
            bucket["transitive" if l["transitive"] else "direct"] += 1
        compat["project"] = {
            "headline_grade": worst_rec,
            "headline_note": "grade for this specific dependency bump (and anything it "
                              "transitively pulled in), from a live pom.xml-diff -- not a "
                              "whole-project scan",
            "worst_without_best_path": worst_any,
            "rated_libraries": len(compat["libraries"]), "unrated_package_roots": 0,
            "lane_histogram": histogram,
        }
        # Catalog context is not this PR's grade — attach once for scorecard/PR.
        if not compat.get("catalog_context"):
            ctx = load_demo_grades()
            if ctx:
                compat["catalog_context"] = ctx
        with open(args.scorecard_compat, "w") as f:
            json.dump(compat, f, indent=2)
        print(f"  scorecard (compat): {args.scorecard_compat} "
              f"({len(compat['libraries'])} librar{'y' if len(compat['libraries'])==1 else 'ies'} total)")
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
.sub{margin:7px 0 0 0;padding-left:11px;border-left:2px solid var(--rule);
  font-size:12.5px;color:var(--ink-soft);line-height:1.55}
.sub b{color:var(--ink);font-weight:600}
.eg{margin-top:5px;padding:5px 9px;background:#FAFAFA;border-radius:4px;
  font-family:var(--mono);font-size:11.5px;color:var(--ink);word-break:break-all}
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
    ("A", "var(--pass)",  "Just smoke-test it",
     "A clean patch. Nothing in the public API changed and almost no code moved."),
    ("B", "var(--watch)", "Test the parts you use",
     "A patch, but it added new methods, rewrote a lot internally, or changed a default setting."),
    ("C", "var(--watch)", "Test each module that uses it",
     "A minor release. New functionality, but nothing that should break existing code."),
    ("D", "var(--stop)",  "Run your full test suite",
     "Something was removed or changed shape, or this is a major release."),
    ("F", "var(--stop)",  "Fix your code first",
     "Something your app actually calls was removed or changed. It will break as-is."),
]
_GRADE_ORDER = {g: i for i, (g, *_ ) in enumerate(RATING_SCALE)}


def _grade_legend_html(title="What each grade means for you"):
    """Shared A-F legend block, reused on every report that shows a letter
    grade. There is no 'E' -- the scale intentionally skips it, same as a
    US school report card (A, B, C, D, F)."""
    rows = "".join(
        f'<div class="sc-row"><span class="chip sm" style="--c:{color}">{grade}</span>'
        f'<span class="sc-lane">{lane}</span>'
        f'<span class="sc-desc">{desc}</span></div>'
        for grade, color, lane, desc in RATING_SCALE)
    return f'<div class="scale"><div class="sc-title">{esc(title)}</div>{rows}</div>'


def _format_member_list_html(members, limit=4):
    """Humanized class.method chips for scorecard / PR sync."""
    if not members:
        return "", 0
    bits = []
    for m in members[:limit]:
        human, _ = _humanize_member(m)
        bits.append(f'<span class="m">{esc(human)}</span>')
    more = len(members) - limit
    extra = f' <span class="lane">(+{more} more)</span>' if more > 0 else ""
    return ", ".join(bits) + extra, len(members)


def _app_use_blurb(call_sites, n_breaking, n_changed, *, transitive=False, parent=None,
                   members=None, app_classes=None):
    """Plain-English reachability line for the scorecard dependency row.

    Lead with the human-readable call count; put method signatures after as evidence.
    """
    members = members or []
    app_classes = app_classes or []
    named, n_named = _format_member_list_html(members)
    n = call_sites or n_named or 0
    places = "place" if n == 1 else "places"

    from_bit = ""
    if app_classes:
        if len(app_classes) == 1:
            from_bit = f' from <span class="m">{esc(app_classes[0])}</span>'
        else:
            from_bit = (f' from <span class="m">{esc(app_classes[0])}</span>'
                        f' <span class="lane">(+{len(app_classes)-1} more)</span>')

    sigs = f' <span class="sigs">({named})</span>' if named else ""

    if transitive and parent:
        lead = (f'You don\'t depend on this directly — <b>{esc(parent)}</b> pulls it in. '
                f'Following calls from your app through {esc(parent)} reaches it'
                f'{from_bit}.')
        if named:
            lead += f' Reachable API{"" if n_named == 1 else "s"}:{sigs}.'
    elif n:
        lead = f'Calls this in <b>{n}</b> {places}{from_bit}.{sigs}'
    else:
        lead = 'This scan found no direct call sites into it.'

    if n_breaking:
        return (f'<span class="lane">{lead} '
                f'— <b>{n_breaking}</b> hit a <b>breaking</b> API change; '
                f'fix {("that call" if n_breaking == 1 else "those calls")} before you upgrade.</span>')
    if n_changed:
        return (f'<span class="lane">{lead} '
                f'— <b>{n_changed}</b> hit an API that <b>changed</b> in this upgrade; '
                f'test those paths.</span>')
    if n or named:
        return (f'<span class="lane">{lead} '
                f'None of those calls hit an API that changed or broke in this upgrade.</span>')
    return f'<span class="lane">{lead}</span>'


def _is_remediated_version(ver):
    return bool(re.search(r"[.-](rhlw|redhat)-\d+", ver or ""))


def _humanize_member(desc):
    """Constructor#<init>(L…TypeDescription;L…Collection;)V → Constructor(TypeDescription, Collection)."""
    if not desc:
        return "", ""
    raw = desc
    cls, _, rest = desc.partition("#")
    simple = cls.rsplit(".", 1)[-1] if cls else desc
    if rest.startswith("<init>(") or rest.startswith("<init>"):
        # pull class names out of JVM type descriptors
        args = re.findall(r"L([\w/$]+);", rest)
        short = ", ".join(a.rsplit("/", 1)[-1] for a in args)
        return f"{simple}({short})", raw
    if "(" in rest:
        name, _, sig = rest.partition("(")
        args = re.findall(r"L([\w/$]+);", "(" + sig)
        short = ", ".join(a.rsplit("/", 1)[-1] for a in args)
        return f"{simple}.{name}({short})", raw
    return f"{simple}.{rest}" if rest else simple, raw


def _delta_stats(opt):
    """Counts used for per-row 'why this grade' copy. Prefer explicit fields;
    fall back to machine when rendering the in-memory scorecard."""
    if "api_added" in opt:
        return {
            "api_added": opt.get("api_added", 0),
            "api_removed": opt.get("api_removed", 0),
            "api_modified": opt.get("api_modified", 0),
            "behavior_resources": opt.get("behavior_resources", 0),
            "churn": opt.get("churn", 0),
            "incompatible": opt.get("incompatible", 0),
        }
    m = opt.get("machine") or {}
    delta = _delta_from_machine(m) if m.get("api_added") is not None else None
    if not delta:
        return {"api_added": 0, "api_removed": 0, "api_modified": 0,
                "behavior_resources": 0, "churn": opt.get("churn", 0),
                "incompatible": opt.get("incompatible", 0)}
    behavior = [r for r in delta["res_changed"] + delta["res_added"] + delta["res_removed"]
                if not r.startswith("META-INF/MANIFEST")]
    return {
        "api_added": len(delta["api_added"]),
        "api_removed": len(delta["api_removed"]),
        "api_modified": len(delta["api_modified"]),
        "behavior_resources": len(behavior),
        "churn": opt.get("churn", delta.get("impl_churn_pct", 0)),
        "incompatible": opt.get("incompatible", len(delta["api_incompatible"])),
    }


def _maven_coord(gav, version):
    """group:artifact:version when GAV known; else just version."""
    if gav and version:
        return f"{gav}:{version}"
    return version or "?"


def _lib_display_name(lib_row):
    """Prefer Maven group:artifact; fall back to short evidence library name."""
    return lib_row.get("gav") or lib_row.get("library") or "?"


def _value_contrast_html(rec, gav=None):
    """Lightwell 'with vs without remediation' line for a dependency row."""
    grade = rec["rating"]["effective_grade"] or rec["rating"]["grade"]
    c = GRADE_COLOR.get(grade, "var(--steel)")
    remediated = _is_remediated_version(rec.get("new"))
    n_break = len(rec["ix"].get("touched_incompatible") or [])
    old_c = _maven_coord(gav, rec.get("old"))
    new_c = _maven_coord(gav, rec.get("new"))
    path = f'{esc(old_c)} → {esc(new_c)}'
    if remediated:
        kind = ("remediated backport" if str(rec.get("stream", "")).startswith("z")
                else "remediated build")
        return (f'<div class="value">'
                f'<span class="chip" style="--c:{c}">{esc(grade)}</span> '
                f'with Red Hat\'s {kind}'
                f'<div class="coords"><span class="m">{path}</span></div>'
                f'</div>')
    if n_break or grade in ("D", "F"):
        return (f'<div class="value value-gap">'
                f'<b>No Red Hat remediated build</b> — community upgrade breaks your code. '
                f'This is the gap Lightwell fills.'
                f'<div class="coords"><span class="m">{path}</span></div>'
                f'</div>')
    return (f'<div class="value">'
            f'<span class="chip" style="--c:{c}">{esc(grade)}</span> '
            f'community path '
            f'<span class="lane">(no remediated build for this version)</span>'
            f'<div class="coords"><span class="m">{path}</span></div>'
            f'</div>')


def _lib_heading_html(lib_row):
    """Primary title = full Maven GAV; short name as secondary when GAV present."""
    gav = lib_row.get("gav")
    short = lib_row.get("library") or ""
    if gav:
        extra = (f'<div class="lane">artifact <span class="m">{esc(short)}</span></div>'
                 if short and short not in gav else "")
        return f'<b class="gav">{esc(gav)}</b>{extra}'
    return f'<b>{esc(short)}</b>'


def _why_grade_body(rec):
    """Inner 'Why {grade}:' prose (HTML allowed). Wording must stay stable — layout only
    reuses this; do not invent new reasons here."""
    st = _delta_stats(rec)
    stream = rec.get("stream") or ""
    grade = rec["rating"]["effective_grade"] or rec["rating"]["grade"]
    n_break = len(rec["ix"].get("touched_incompatible") or [])
    bits = []
    if stream.startswith("y"):
        bits.append("minor bump")
    elif stream.startswith("z"):
        bits.append("patch / z-stream")
    elif stream.startswith("x"):
        bits.append("major bump")
    if st["api_added"] and not st["api_removed"]:
        bits.append(f'{st["api_added"]} new API{"s" if st["api_added"] != 1 else ""}, nothing removed')
    elif st["api_added"] or st["api_removed"]:
        bits.append(f'+{st["api_added"]} / −{st["api_removed"]} public APIs')
    if st["api_modified"]:
        bits.append(f'{st["api_modified"]} modified')
    if st["incompatible"] and not n_break:
        bits.append(f'{st["incompatible"]} incompatible changes (not reached by your app)')
    if st["behavior_resources"] and st["churn"] < 1 and not st["api_added"] and not st["api_removed"]:
        return (f'code is effectively unchanged '
                f'(~{st["churn"]}% churn), but <b>{st["behavior_resources"]} config / default '
                f'resource(s) changed</b> — behavior can shift with zero API change. '
                f'Smoke-test the parts you use.')
    if st["behavior_resources"]:
        bits.append(f'{st["behavior_resources"]} default/resource change(s)')
    if n_break:
        return ('your app calls a removed/incompatible API — it will not compile or run '
                'until that call is updated.')
    if grade == "C":
        detail = ", ".join(bits) if bits else "new functionality expected"
        return f'{esc(detail)} → test each module that uses it.'
    if grade == "B":
        detail = ", ".join(bits) if bits else "patch with non-trivial surface"
        return f'{esc(detail)} → test the parts you use.'
    if bits:
        return f'{esc(", ".join(bits))}.'
    return ""


def _why_grade_html(rec):
    """Per-row reason — not the shared boilerplate reachability sentence."""
    body = _why_grade_body(rec)
    if not body:
        return ""
    grade = rec["rating"]["effective_grade"] or rec["rating"]["grade"]
    return f'<div class="why"><b>Why {esc(grade)}:</b> {body}</div>'


def _lib_shown_grade(lib_row):
    r = lib_row["recommended"]["rating"]
    return r.get("effective_grade") or r["grade"]


def _libs_worst_first(libs):
    """F → D → C → B → A. Never insertion/dict order."""
    gi = {g: i for i, g in enumerate(GRADE_ORDER)}
    return sorted(libs, key=lambda l: gi.get(_lib_shown_grade(l), -1), reverse=True)


def _partition_action_buckets(libs):
    """Partition into blocker / safe-with-testing / clean. Empty lists omitted by caller."""
    ordered = _libs_worst_first(libs)
    blocks, safe, clean = [], [], []
    for l in ordered:
        g = _lib_shown_grade(l)
        if g == "F":
            blocks.append(l)
        elif g == "A":
            clean.append(l)
        else:  # B, C, D
            safe.append(l)
    return blocks, safe, clean


def _triage_summary_html(blocks, safe, clean):
    n = len(blocks) + len(safe) + len(clean)
    if n == 0:
        return ""
    parts = []
    if blocks:
        verb = "blocks" if len(blocks) == 1 else "block"
        parts.append(f'<b>{len(blocks)}</b> {verb} your upgrade')
    if safe:
        verb = "is" if len(safe) == 1 else "are"
        parts.append(f'<b>{len(safe)}</b> {verb} safe with testing')
    if clean:
        verb = "is" if len(clean) == 1 else "are"
        parts.append(f'<b>{len(clean)}</b> {verb} clean — smoke test only')
    if not parts:
        return ""
    return (f'<p class="triage">Of <b>{n}</b> graded '
            f'{"dependency" if n == 1 else "dependencies"}: '
            + ", ".join(parts) + ".</p>")


def _dep_row_html(l, *, expanded=True, test_results=None):
    """Identical Reaches / Why / Do skeleton for every graded dependency row."""
    rec = l["recommended"]
    g = rec["rating"]
    shown = g["effective_grade"] or g["grade"]
    c = GRADE_COLOR[shown]
    touched = (len(rec["ix"]["touched_incompatible"]), len(rec["ix"]["touched_changed"]))
    lane = g["lane"]
    heading = _lib_heading_html(l)
    if l.get("transitive"):
        heading = f'<span class="lane">↳ indirect</span> {heading}'
    value = _value_contrast_html(rec, gav=l.get("gav"))
    why_body = _why_grade_body(rec)
    break_html = _breaking_call_html(rec["ix"].get("touched_incompatible") or [])
    cves_html = _cves_fixed_html(rec)
    note = (f'<div class="note" style="margin:8px 0 0">{esc(g["scope_note"])}</div>'
            if g.get("scope_note") else "")

    alt_html = ""
    if len(l["options"]) > 1:
        alts = []
        for o in l["options"]:
            if o is rec:
                continue
            og = o["rating"]
            oc = GRADE_COLOR[og["effective_grade"] or og["grade"]]
            old_c = _maven_coord(l.get("gav"), o.get("old"))
            new_c = _maven_coord(l.get("gav"), o.get("new"))
            alts.append(
                f'<div class="alt"><span class="chip" style="--c:{oc}">'
                f'{og["effective_grade"] or og["grade"]}</span> '
                f'<span class="m">{esc(old_c)} → {esc(new_c)}</span>'
                f'<span class="lane"> · {esc(og["lane"])}</span></div>')
        if alts:
            alt_html = '<div class="alts"><span class="lane">Other paths:</span>' + "".join(alts) + '</div>'

    use = _app_use_blurb(
        l["call_sites"], touched[0], touched[1],
        transitive=bool(l.get("transitive")), parent=l.get("parent"),
        members=rec["ix"].get("lib_members_used") or [],
        app_classes=rec["ix"].get("affected_app_classes") or [])

    via_html = ""
    parent_html = ""
    if l.get("transitive"):
        via = rec["ix"].get("via", {})
        via_line = next(iter(via.items()), None)
        if via_line:
            via_html = (f'<div class="eg">for example: <span class="m">{esc(via_line[1])}</span>'
                        f' calls <span class="m">{esc(via_line[0])}</span></div>')
        parent_html = (f'<div class="sub">Pulled in by <b>{esc(l["parent"])}</b> — '
                       f'upgrade the parent or pin an override.{via_html}</div>')

    reaches = f'<div class="skel"><span class="skel-k">Reaches:</span> {use}</div>'
    why = (f'<div class="skel"><span class="skel-k">Why {esc(shown)}:</span> {why_body}</div>'
           if why_body else "")
    do = _do_with_tests_html(lane, l.get("library") or "", test_results,
                             grade=shown)
    # Honest limit: static analysis cannot see reflection/DI; make it visible
    # on the rows where it most often tempts overconfidence (F + transitive).
    honest = ""
    if shown == "F" or l.get("transitive"):
        if l.get("transitive"):
            honest = ('<div class="honest">Static analysis cannot see reflection, DI, or '
                      'service-loader hops — and that blindness compounds across libraries. '
                      'De-escalating a transitive always needs explicit sign-off; tests that '
                      'pass are the real gate.</div>')
        else:
            honest = ('<div class="honest">Static analysis follows explicit calls and '
                      'internal chains only — reflection/DI hops are invisible. An F means '
                      'fix the breaking call first; tests on today\'s jars do not clear it — '
                      're-test after you migrate onto the new library.</div>')
    detail = f'{reaches}{why}{do}{break_html}{parent_html}{honest}'

    head = (f'<div class="row-head">'
            f'<span class="chip" style="--c:{c}">{esc(shown)}</span> {heading}'
            f'</div>')

    scope = _scope_label(lane)
    if expanded:
        left = f'{head}{detail}'
    else:
        left = (f'{head}'
                f'<details class="row-more"><summary>show detail · {esc(scope)}</summary>'
                f'{detail}</details>')

    right = f'{value}{cves_html}{alt_html}{note}'
    row_class = "row-block" if expanded and shown == "F" else ("row-safe" if not expanded else "")
    tr_class = "sub" if l.get("transitive") else ""
    classes = " ".join(x for x in (tr_class, row_class) if x)
    cls_attr = f' class="{classes}"' if classes else ""
    return f'<tr{cls_attr}><td>{left}</td><td>{right}</td></tr>'


def _action_bucket_html(title, rows_html, *, kind):
    if not rows_html:
        return ""
    return (
        f'<section class="bucket bucket-{kind}">'
        f'<h2 class="bucket-h">{esc(title)}</h2>'
        f'<table class="deps"><thead><tr>'
        f'<th>Dependency · what your app hits</th>'
        f'<th>Lightwell path · what to do</th>'
        f'</tr></thead><tbody>{rows_html}</tbody></table>'
        f'</section>'
    )


def _breaking_call_html(incompat_list):
    if not incompat_list:
        return ""
    human, raw = _humanize_member(incompat_list[0])
    more = ""
    if len(incompat_list) > 1:
        more = f' <span class="lane">(+{len(incompat_list)-1} more)</span>'
    note = ""
    if "Constructor" in human and "TypeDescription" in human:
        note = (" — signature changed in 1.33 (CVE-2022-1471 hardening). "
                "Your code calls it directly; it won't compile until updated.")
    else:
        note = (" — your code calls it directly; it won't compile until updated.")
    return (
        f'<div class="break">'
        f'<b>{esc(human)}</b>{note}{more}'
        f'<details class="tech"><summary>technical detail</summary>'
        f'<code>{esc(raw)}</code></details></div>'
    )


def _verdict_html(p, libs):
    grade = p.get("headline_grade") or "—"
    c = GRADE_COLOR.get(grade, "var(--steel)")
    # Pick the library that sets the project grade (worst recommended).
    gi = {g: i for i, g in enumerate(GRADE_ORDER)}
    blocker = None
    for l in libs:
        rec = l["recommended"]
        g = rec["rating"]["effective_grade"] or rec["rating"]["grade"]
        if g == grade:
            blocker = l
            break
    safe = []
    for l in libs:
        rec = l["recommended"]
        g = rec["rating"]["effective_grade"] or rec["rating"]["grade"]
        if g != grade:
            safe.append(_lib_display_name(l))
    if blocker and grade in ("D", "F"):
        n_break = len(blocker["recommended"]["ix"].get("touched_incompatible") or [])
        blocker_name = _lib_display_name(blocker)
        if n_break:
            reason = (f'<b>{esc(blocker_name)}</b> has a breaking change your code '
                      f'calls directly.')
        else:
            reason = f'<b>{esc(blocker_name)}</b> sets the project grade.'
        others = ""
        if safe:
            if len(safe) == 1:
                others = f' The other dependency (<b>{esc(safe[0])}</b>) is safe with testing.'
            else:
                named = ", ".join(f'<b>{esc(s)}</b>' for s in safe[:-1])
                others = (f' The other {len(safe)} (<b>{named}</b> and '
                          f'<b>{esc(safe[-1])}</b>) are safe with testing.')
        return (f'<div class="verdict" style="--vc:{c}">'
                f'<span class="chip" style="--c:{c}">Project {esc(grade)}</span> '
                f'{reason}{others}</div>')
    return (f'<div class="verdict" style="--vc:{c}">'
            f'<span class="chip" style="--c:{c}">Project {esc(grade)}</span> '
            f'Worst pending dependency grade across the best remediation path available.'
            f'</div>')


def _testing_summary_html(libs):
    """Replace the uninformative equal-length bar chart with one sentence + strip."""
    # Merge grades that share a customer action into one bucket.
    buckets = [
        ("needs a code fix", {"F", "D"}, "var(--stop)"),
        ("needs module testing", {"C"}, "var(--watch)"),
        ("needs a smoke test", {"B"}, "var(--watch)"),
        ("smoke-test only", {"A"}, "var(--pass)"),
    ]
    by_grade = {}
    for l in libs:
        g = l["recommended"]["rating"]["effective_grade"] or l["recommended"]["rating"]["grade"]
        by_grade.setdefault(g, []).append(_lib_display_name(l))
    parts, strip = [], ""
    total = max(len(libs), 1)
    for label, grades, color in buckets:
        names = []
        for g in grades:
            names.extend(by_grade.get(g) or [])
        if not names:
            continue
        n = len(names)
        who = ", ".join(names)
        parts.append(f'<b>{n}</b> {esc(label)} ({esc(who)})')
        pct = max(round(100 * n / total), 8)  # keep tiny segments visible
        strip += f'<i style="width:{pct}%;background:{color}" title="{esc(label)}: {esc(who)}"></i>'
    if not parts:
        return ""
    sentence = f'{len(libs)} dependencies: ' + ", ".join(parts) + "."
    return (f'<div class="test-sum"><p>{sentence}</p>'
            f'<div class="risk-strip">{strip}</div></div>')


def _hazards_html(hazards, app_name=""):
    """SBOM vs artifact notes. Thin jars flood declared-not-shipped;
    the app jar flagging itself is expected — explain, don't alarm."""
    if not hazards:
        return ""
    app_base = re.sub(r"-\d.*$", "", (app_name or "").replace(".jar", ""))
    by = {}
    for kind, msg in hazards:
        by.setdefault(kind, []).append(msg)
    items = []
    for kind, msgs in by.items():
        if kind == "shipped-not-declared":
            kept = []
            for msg in msgs:
                name = msg.split(" ", 1)[0]
                if app_base and (name == app_base or name.startswith(app_base + "-")):
                    items.append(
                        f'<li>The application jar\'s own classes ({esc(name)}) are not listed as a '
                        f'dependency in its SBOM — expected, not a packaging bug.</li>')
                else:
                    kept.append(msg)
            msgs = kept
            if not msgs:
                continue
        if kind == "declared-not-shipped" and len(msgs) > 3:
            items.append(
                f'<li>{len(msgs)} libraries are in the SBOM but were not found inside this jar '
                f'(common for <em>thin</em> jars that load deps from the classpath; a shaded/'
                f'fat jar should fingerprint them via classes or META-INF/maven pom.properties).'
                f'</li>')
        else:
            for msg in msgs:
                items.append(f'<li><span class="m">[{esc(kind)}]</span> {esc(msg)}</li>')
    if not items:
        return ""
    return f"""<h2 id="sbom-notes">SBOM vs. shipped artifact <span class="lane">(informational)</span></h2>
<p style="color:var(--ink-soft)">The SBOM is the map; the shipped artifact is the territory.
These notes explain mismatches — they are not upgrade blockers by themselves.</p>
<ul>{''.join(items)}</ul>"""


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
        "lib_members_used": [member_str(k) for k in sorted(call_sites, key=sk)],
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
    """CycloneDX JSON -> {'versions': {name: version}, 'gav': {name: 'group:artifact'},
    'parents': {child: parent}, 'root_deps': set(direct dep names)}.
    dependency:tree text is a planned alternate input."""
    with open(path) as f:
        bom = json.load(f)
    versions, gav = {}, {}
    for c in bom.get("components", []):
        name = c.get("name")
        if not name:
            continue
        versions[name] = c.get("version", "?")
        group = c.get("group") or ""
        if group:
            gav[name] = f"{group}:{name}"
        else:
            purl = c.get("purl") or ""
            m = re.match(r"pkg:maven/([^/@]+)/([^/@]+)", purl)
            if m:
                gav[name] = f"{m.group(1)}:{m.group(2)}"
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
    return {"versions": versions, "gav": gav, "parents": parents, "root_deps": root_deps}




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
        "lib_members_used": [member_str(k) for k in sorted(call_sites, key=sk)],
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


def _gav_parts(sbom, name):
    """Return (group, artifact) from sbom['gav'] entry 'group:artifact'."""
    gav = (sbom or {}).get("gav", {}).get(name) or ""
    if ":" in gav:
        group, artifact = gav.split(":", 1)
        return group, artifact
    return "", name


def _fat_jar_covers(app, group, artifact):
    """True if the app jar contains classes that belong to this Maven GAV.

    Used when META-INF/maven/.../pom.properties is missing (common for Spring
    and some Central jars). A shaded/fat jar still has the .class files.
    """
    classes = app.get("classes") or {}
    if not classes:
        return False
    candidates = []
    if group:
        candidates.append(group.replace(".", "/") + "/")
    # commons-io -> commons/io ; jackson-databind -> jackson/databind
    slug = artifact.replace("-", "/")
    if slug:
        candidates.append("/" + slug + "/")
        candidates.append(slug + "/")
    for cname in classes:
        for cand in candidates:
            if cand in cname or cname.startswith(cand.lstrip("/")):
                return True
    return False


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
    # Fat/shaded jars: fill gaps when dependencies omit pom.properties (Spring).
    if sbom:
        for name, ver in list(sbom["versions"].items()):
            if name in shipped:
                continue
            group, artifact = _gav_parts(sbom, name)
            if _fat_jar_covers(app, group, artifact):
                shipped[name] = ver
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


# ---------------------------------------------------------------- Lightwell OSV (CVE join)

def _osv_cache_dir():
    override = os.environ.get("UPGRADE_DELTA_OSV_CACHE")
    if override:
        return override
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return os.path.join(xdg, "upgrade-delta", "osv")
    return os.path.join(os.path.expanduser("~"), ".cache", "upgrade-delta", "osv")


def _http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": f"upgrade-delta/{TOOL_VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _load_osv_records_from_dir(directory):
    """Load every *.json OSV document from a local directory (offline / CI mirror)."""
    records = []
    if not directory or not os.path.isdir(directory):
        return records
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json") or name.startswith("."):
            continue
        path = os.path.join(directory, name)
        try:
            with open(path) as f:
                doc = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"  ! OSV skip {path}: {e}")
            continue
        if isinstance(doc, dict) and doc.get("affected") is not None:
            records.append(doc)
    return records


def _fetch_osv_records(base_url, cache_dir):
    """Fetch OSV advisories from a Lightwell osv/.../remediated index.

    Failure-tolerant: network/HTTP errors return [] after a warning. Successful
    bodies are cached under cache_dir so repeated scans do not re-download.
    """
    if not base_url:
        return []
    base = base_url.rstrip("/")
    os.makedirs(cache_dir, exist_ok=True)
    records = []
    try:
        manifest_url = f"{base}/PULP_MANIFEST"
        try:
            raw = _http_get(manifest_url)
            names = []
            for line in raw.decode("utf-8", errors="replace").splitlines():
                # filename,sha256,size
                fname = line.split(",", 1)[0].strip()
                if fname.endswith(".json"):
                    names.append(fname)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
            # Fall back to directory listing HTML
            html = _http_get(base + "/").decode("utf-8", errors="replace")
            names = sorted(set(re.findall(r'href="(\./)?(x_RHLW-[^"]+\.json)"', html)))
            names = [n[1] if isinstance(n, tuple) else n for n in names]
            names = [n[2:] if n.startswith("./") else n for n in names]
        for fname in names:
            if not fname.endswith(".json"):
                continue
            cached = os.path.join(cache_dir, os.path.basename(fname))
            doc = None
            if os.path.isfile(cached):
                try:
                    with open(cached) as f:
                        doc = json.load(f)
                except (OSError, json.JSONDecodeError):
                    doc = None
            if doc is None:
                try:
                    body = _http_get(f"{base}/{fname}")
                    with open(cached, "wb") as f:
                        f.write(body)
                    doc = json.loads(body.decode("utf-8"))
                except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                        OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
                    print(f"  ! OSV fetch {fname}: {e}")
                    continue
            if isinstance(doc, dict) and doc.get("affected") is not None:
                records.append(doc)
    except Exception as e:  # noqa: BLE001 — advisory join must never fail the scan
        print(f"  ! OSV index unavailable ({e}) — continuing without CVE data")
        return []
    return records


def load_osv_index(osv_dir=None, osv_url=None, fetch=True):
    """Return a list of OSV documents. Local --osv-dir wins; optional live fetch fills gaps."""
    records = _load_osv_records_from_dir(osv_dir)
    seen = {r.get("id") for r in records if r.get("id")}
    if fetch and osv_url is not False:
        url = osv_url or DEFAULT_OSV_URL
        for r in _fetch_osv_records(url, _osv_cache_dir()):
            rid = r.get("id")
            if rid and rid in seen:
                continue
            records.append(r)
            if rid:
                seen.add(rid)
    return records


def _osv_cves(doc):
    return sorted({a for a in (doc.get("aliases") or []) if isinstance(a, str) and a.startswith("CVE-")})


def _osv_fixed_events(doc):
    """Yield (maven_name, fixed_version) from an OSV document."""
    for aff in doc.get("affected") or []:
        pkg = (aff.get("package") or {}).get("name") or ""
        for rng in aff.get("ranges") or []:
            for ev in rng.get("events") or []:
                fixed = ev.get("fixed")
                if pkg and fixed:
                    yield pkg, fixed


def _version_satisfies_fixed(target, fixed):
    """True when target includes the fix named by OSV `fixed` (target >= fixed)."""
    if not target or not fixed:
        return False
    if target == fixed:
        return True
    return _version_key(target) >= _version_key(fixed)


def _package_matches_gav(osv_pkg, gav, artifact):
    if gav and osv_pkg == gav:
        return True
    if artifact and (osv_pkg == artifact or osv_pkg.endswith(":" + artifact)):
        return True
    return False


def cves_fixed_by_build(osv_records, *, gav, artifact, version):
    """CVEs a remediated build addresses, per Lightwell OSV `fixed` events.

    Only returns IDs present in advisory aliases — never invented. Empty when
    no advisory claims this GAV+version as fixed (or newer than fixed).
    """
    if not _is_remediated_version(version) or not osv_records:
        return []
    found = {}  # cve -> meta
    for doc in osv_records:
        cves = _osv_cves(doc)
        if not cves:
            continue
        for pkg, fixed in _osv_fixed_events(doc):
            if not _package_matches_gav(pkg, gav, artifact):
                continue
            if not _version_satisfies_fixed(version, fixed):
                continue
            for cve in cves:
                # Prefer the advisory whose fixed event equals the target build
                prev = found.get(cve)
                if prev is None or fixed == version or (
                        _version_key(fixed) > _version_key(prev.get("fixed_in") or "")):
                    found[cve] = {
                        "id": cve,
                        "osv_id": doc.get("id"),
                        "fixed_in": fixed,
                        "summary": (doc.get("summary") or doc.get("details") or "")[:240],
                    }
    return [found[k] for k in sorted(found)]


def attach_cves_fixed(libs, sbom, osv_records):
    """Mutate scorecard library options with cves_fixed (+ details) from OSV."""
    gav_map = (sbom or {}).get("gav") or {}
    for lib in libs:
        artifact = lib["library"]
        gav = gav_map.get(artifact)
        for opt in lib["options"]:
            if not opt.get("remediated"):
                opt["cves_fixed"] = []
                opt["cve_details"] = []
                continue
            details = cves_fixed_by_build(
                osv_records, gav=gav, artifact=artifact, version=opt.get("new"))
            opt["cve_details"] = details
            opt["cves_fixed"] = [d["id"] for d in details]
        # keep recommended/worst aliases in sync when they share option dicts
        lib["recommended"] = lib["options"][0]
        lib["worst"] = lib["options"][-1]


def _cves_fixed_html(rec):
    """Render CVE list for a remediated path; omit entirely when empty."""
    cves = rec.get("cves_fixed") or []
    if not cves:
        return ""
    details = {d["id"]: d for d in (rec.get("cve_details") or [])}
    chips = []
    for cve in cves:
        tip = (details.get(cve) or {}).get("summary") or ""
        title = f' title="{esc(tip)}"' if tip else ""
        chips.append(f'<span class="cve"{title}>{esc(cve)}</span>')
    n = len(cves)
    label = "CVE" if n == 1 else "CVEs"
    return (f'<div class="cves">This remediated build fixes {n} {label}: '
            f'{"".join(chips)}</div>')


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
        delta_m = _delta_from_machine(m)
        rating = rate(r["stream"], delta_m, ix,
                      transitive=transitive, signoff=args.accept_transitive_scope)
        installed = sbom["versions"].get(r["library"]) if sbom else None
        behavior_n = len([
            x for x in delta_m["res_changed"] + delta_m["res_added"] + delta_m["res_removed"]
            if not x.startswith("META-INF/MANIFEST")])
        per_lib[r["library"]].append({
            "machine": m,
            "old": r["old_version"], "new": r["new_version"], "stream": r["stream"],
            "rating": rating, "ix": ix, "churn": m["impl_churn_pct"],
            "incompatible": len(m["api_incompatible"]),
            "api_added": len(delta_m["api_added"]),
            "api_removed": len(delta_m["api_removed"]),
            "api_modified": len(delta_m["api_modified"]),
            "behavior_resources": behavior_n,
            "remediated": _is_remediated_version(r["new_version"]),
            "in_place": (installed is None or installed == r["old_version"]),
        })
        lib_meta[r["library"]] = {"transitive": transitive, "parent": parent,
                                  "installed": installed}

    gi = {g: i for i, g in enumerate(GRADE_ORDER)}
    def eff(o):
        return o["rating"]["effective_grade"] or o["rating"]["grade"]
    libs = []
    gav_map = (sbom or {}).get("gav") or {}
    for name, options in sorted(per_lib.items()):
        options.sort(key=lambda o: (gi[eff(o)], not o["in_place"]))
        meta = lib_meta[name]
        libs.append({"library": name, "gav": gav_map.get(name),
                     "options": options,
                     "recommended": options[0], "worst": options[-1],
                     "call_sites": options[0]["ix"]["lib_call_sites"],
                     "transitive": meta["transitive"], "parent": meta["parent"],
                     "installed": meta["installed"]})
    # transitives render nested under their parent
    libs.sort(key=lambda l: ((l["parent"] or l["library"]), l["transitive"]))

    # Join Lightwell OSV advisories → cves_fixed on remediated paths (optional).
    osv_dir = getattr(args, "osv_dir", None)
    osv_url = getattr(args, "osv_url", None)
    no_fetch = bool(getattr(args, "no_osv_fetch", False))
    osv_records = load_osv_index(
        osv_dir=osv_dir,
        osv_url=False if no_fetch else (osv_url or DEFAULT_OSV_URL),
        fetch=not no_fetch,
    )
    if osv_records:
        print(f"   OSV advisories loaded: {len(osv_records)}"
              + (f" (dir {osv_dir})" if osv_dir else "")
              + (" [fetch disabled]" if no_fetch else ""))
    attach_cves_fixed(libs, sbom, osv_records)

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

    catalog_coverage = None
    cov_path = getattr(args, "coverage", None)
    if cov_path and os.path.isfile(cov_path):
        try:
            with open(cov_path) as f:
                cov = json.load(f)
            t = cov.get("totals") or {}
            catalog_coverage = {
                "dependencies": t.get("dependencies", 0),
                "exact": t.get("exact", 0),
                "serviced_other_version": t.get("serviced_other_version", 0),
                "uncovered": t.get("uncovered", 0),
                "source": os.path.basename(cov_path),
            }
        except (OSError, json.JSONDecodeError) as e:
            print(f"  ! could not load --coverage {cov_path}: {e}")

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
            "catalog_coverage": catalog_coverage,
        },
    }
    demo_grades = load_demo_grades()
    if demo_grades:
        result["catalog_context"] = demo_grades

    # terminal
    print(f"\n== upgrade-delta scan :: {result['app']} ==")
    for l in libs:
        rec = l["recommended"]
        tag = f"  [transitive via {l['parent']}]" if l["transitive"] else ""
        label = _lib_display_name(l)
        opts = " / ".join(
            f"{_maven_coord(l.get('gav'), o['old'])}->{_maven_coord(l.get('gav'), o['new'])}: {eff(o)}" +
            ("" if o["in_place"] else " (stream switch)") for o in l["options"])
        print(f"   {label}{tag}  ({l['call_sites']} call sites)   paths: {opts}")
        g = rec["rating"]
        shown = (f"{g['grade']}->{g['effective_grade']} (signed off)"
                 if g["effective_grade"] else g["grade"])
        print(f"     -> recommended: {_maven_coord(l.get('gav'), rec['old'])}->"
              f"{_maven_coord(l.get('gav'), rec['new'])}  grade {shown}  lane: {g['lane']}")
        if rec.get("cves_fixed"):
            print(f"        fixes: {', '.join(rec['cves_fixed'])}")
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
        shrinkable = {"Just smoke-test it", "Test the parts you use"}  # grades A / B
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


def _coverage_bridge_html(p, libs):
    """Explain why catalog coverage ≠ scorecard graded rows — collapsed by default."""
    cov = p.get("catalog_coverage")
    n = p.get("rated_libraries") or len(libs or [])
    if not cov:
        body = (
            f'This scorecard grades libraries that have a <b>published delta report</b> '
            f'and that your app actually calls. Catalog drop-in coverage is a separate '
            f'meter (<a href="coverage.html">coverage.html</a>) — those numbers are not '
            f'missing from this page; they answer a different question. '
            f'Currently <span class="m">{n}</span> libraries are graded here.'
        )
    else:
        exact = cov.get("exact", 0)
        total = cov.get("dependencies", 0)
        near = cov.get("serviced_other_version", 0)
        unc = cov.get("uncovered", 0)
        body = (
            f'<span class="m">{exact}/{total}</span> dependencies have a <b>drop-in</b> Lightwell build '
            f'(suffix swap, no base-version upgrade) · '
            f'<span class="m">{near}</span> serviced at another version · '
            f'<span class="m">{unc}</span> not in the catalog. '
            f'This page grades <span class="m">{n}</span> libraries that have '
            f'<b>published delta evidence</b> your app reaches — not the full catalog list. '
            f'Drop-in covered deps usually need configuration, not an API-diff grade; '
            f'see the <a href="coverage.html">coverage report</a>.'
        )
    return (
        f'<details class="bridge-details" id="catalog-vs-scorecard">'
        f'<summary>Why do the catalog count and the graded count differ?</summary>'
        f'<div class="bridge">{body}</div></details>'
    )


def _subtitle_lines_html(p):
    """Three labeled accounting rows; link not-yet-graded to its section."""
    n = p.get("rated_libraries") or 0
    m = p.get("unrated_package_roots") or 0
    cov = p.get("catalog_coverage") or {}
    rows = [
        ('Graded',
         f'<b>{n}</b> dependencies — have published delta evidence your app reaches'),
    ]
    if cov:
        exact = cov.get("exact", 0)
        total = cov.get("dependencies", 0)
        rows.append(
            ('Catalog',
             f'<b>{exact}</b> of <b>{total}</b> drop-in ready — dependencies with an '
             f'exact Red Hat remediated build '
             f'(<a href="coverage.html">coverage report</a>)'))
    if m:
        rows.append(
            ('Not graded yet',
             f'<b>{m}</b> packages — your app calls them, but no delta report exists yet '
             f'(<a href="#no-delta-evidence">see which</a>)'))
    items = "".join(
        f'<div class="acct"><span class="acct-k">{esc(k)}</span>'
        f'<span class="acct-v">{v}</span></div>'
        for k, v in rows)
    return f'<div class="vers-block">{items}</div>'


def _scope_label(lane):
    return SCOPE_FROM_LANE.get(lane) or (lane[0].lower() + lane[1:] if lane else "testing")


def _test_class_of(name):
    """ConfigLoaderTest.foo or com.example.ConfigLoaderTest#foo → ConfigLoaderTest."""
    s = (name or "").strip()
    if not s:
        return ""
    s = s.replace("#", ".")
    if "." in s:
        # drop package / method — keep simple class token
        parts = s.split(".")
        for p in reversed(parts):
            if p and p[0].isupper():
                return p
        return parts[-2] if len(parts) > 1 else parts[-1]
    return s


def attribute_tests_by_library(selection_report, library_names,
                               routing=None, coverage=None):
    """Map selected test class names → short library names.

    Prefer selection reasons ('covers X <- json-path …'). When the router fell
    back to full-suite (no '<- lib' markers), join coverage map test→app-class
    with routing.upgrades[].affected_app_classes so rows still get per-lib
    selected/failed attribution.
    """
    by_lib = {n: [] for n in library_names}
    entries = []
    if selection_report:
        entries.extend(selection_report.get("selected") or [])
        entries.extend(selection_report.get("widened") or [])
        for name in (selection_report.get("mandatory") or {}).get("appended") or []:
            entries.append({"test": name, "reason": "mandatory"})

    reason_hit = False
    for e in entries:
        test = e.get("test") if isinstance(e, dict) else e
        reason = e.get("reason", "") if isinstance(e, dict) else ""
        if not test:
            continue
        matched = [n for n in library_names if f"<- {n} " in reason]
        if matched:
            reason_hit = True
        for n in matched:
            if test not in by_lib[n]:
                by_lib[n].append(test)

    if reason_hit or not (routing and coverage):
        return by_lib

    # Full-suite fallback: attribute via coverage ∩ affected_app_classes.
    lib_classes = {}
    for up in routing.get("upgrades") or []:
        lib = up.get("library")
        if lib not in by_lib:
            continue
        for cls in up.get("affected_app_classes") or []:
            lib_classes.setdefault(lib, set()).add(cls)

    cov_tests = (coverage or {}).get("tests") or {}
    selected_names = set()
    for e in entries:
        test = e.get("test") if isinstance(e, dict) else e
        if test:
            selected_names.add(test)
    if not selected_names:
        selected_names = set(cov_tests)

    for test in selected_names:
        covers = set((cov_tests.get(test) or {}).get("covers") or [])
        if not covers:
            continue
        for lib, classes in lib_classes.items():
            if covers & classes and test not in by_lib[lib]:
                by_lib[lib].append(test)
    return by_lib


def compose_test_results(*, methods_passed=0, methods_failed=0, summary="",
                         status="ran", failed_names=None, selection_report=None,
                         library_names=None, routing=None, coverage=None):
    """Build upgrade-delta/test-results/v1 for scorecard regeneration."""
    failed_names = list(failed_names or [])
    library_names = list(library_names or [])
    methods_run = int(methods_passed) + int(methods_failed)
    by_sel = attribute_tests_by_library(
        selection_report, library_names, routing=routing, coverage=coverage)

    by_library = {}
    for lib, tests in by_sel.items():
        lib_fails = sorted(
            n for n in failed_names
            if any(_test_class_of(n) == t or n.startswith(t + ".") or _test_class_of(n) == _test_class_of(t)
                   for t in tests)
        )
        if status != "ran":
            st = "not_run"
        elif not tests:
            st = "not_selected"
        elif methods_failed and lib_fails:
            st = "failed"
        elif methods_failed and not failed_names:
            # Aggregate failure only — flag every lib that had selected tests.
            st = "failed"
            lib_fails = failed_names[:]  # may be empty; banner carries the count
        elif methods_failed and failed_names and not lib_fails:
            st = "passed"  # failures attributed elsewhere
        else:
            st = "passed"
        by_library[lib] = {
            "selected_tests": tests,
            "selected_count": len(tests),
            "status": st,
            "failed_names": lib_fails,
        }

    totals = (selection_report or {}).get("totals") or {}
    out = {
        "schema": "upgrade-delta/test-results/v1",
        "status": status,
        "methods_passed": int(methods_passed),
        "methods_failed": int(methods_failed),
        "methods_run": methods_run,
        "summary": summary or "",
        "failed_names": failed_names,
        "by_library": by_library,
        "selection_final": totals.get("final"),
        "selection_suite": totals.get("suite"),
    }
    if selection_report:
        if selection_report.get("mode"):
            out["selection_mode"] = selection_report["mode"]
        if selection_report.get("validation_basis"):
            out["validation_basis"] = selection_report["validation_basis"]
        if selection_report.get("note"):
            out["selection_note"] = selection_report["note"]
    return out


def _do_with_tests_html(lane, library, test_results, *, grade=None):
    """Do: line — recommended scope + test outcome.

    When the row grades F or D, passing tests were run on *current* jars and do
    not clear the grade — qualify the copy so CAB is not misled.
    """
    scope = _scope_label(lane)
    base = f'Recommended scope: {esc(scope)}'
    blocking = grade in ("F", "D")
    if test_results is None:
        return f'<div class="skel"><span class="skel-k">Do:</span> {base}.</div>'

    status = test_results.get("status") or "not_run"
    per = (test_results.get("by_library") or {}).get(library) or {}
    n = per.get("selected_count")
    if n is None and test_results.get("selection_final") is not None:
        n = test_results.get("selection_final")

    if status == "reachability_only":
        return (f'<div class="skel"><span class="skel-k">Do:</span> {base}. '
                f'<span class="test-skip">No suite — relying on reachability; '
                f'canary is the compensating control.</span></div>')

    if status != "ran":
        return (f'<div class="skel"><span class="skel-k">Do:</span> {base}. '
                f'<span class="test-skip">Tests not run.</span></div>')

    st = per.get("status") or "unknown"
    fails = per.get("failed_names") or []
    # Fall back to suite-level failure names only when this row is marked failed
    # without a more specific attribution.
    if st == "failed" and not fails:
        fails = test_results.get("failed_names") or []
    n_label = "test" if n == 1 else "tests"

    def _pass_caveat(main):
        if not blocking:
            return f'<span class="test-pass">{main}</span>'
        # F/D: green check alone implies "safe to upgrade" — it isn't.
        return (f'<span class="test-pass">{main}</span>'
                f'<span class="test-caveat"> on current jars — does not clear this '
                f'{esc(grade)}; re-test after you migrate</span>')

    if st == "not_selected" and test_results.get("selection_final"):
        # Full-suite / unattributed: show aggregate suite outcome on every row.
        run = test_results.get("methods_run") or 0
        failed = test_results.get("methods_failed") or 0
        if failed:
            fails = test_results.get("failed_names") or []
            who = ""
            if fails:
                shown = ", ".join(fails[:3])
                more = f" (+{len(fails)-3} more)" if len(fails) > 3 else ""
                who = f' (<span class="m">{esc(shown)}</span>{esc(more)})'
            outcome = (f'<span class="test-fail">Suite ran <b>{run}</b> methods — '
                       f'<b>{failed} FAILED</b> ✗{who}</span>')
        elif run:
            outcome = _pass_caveat(
                f'Suite ran <b>{run}</b> methods — all passed ✓')
        else:
            outcome = '<span class="test-skip">Suite selected; no methods recorded.</span>'
    elif st == "not_selected" or (n == 0 and not test_results.get("selection_final")):
        outcome = '<span class="test-skip">No tests selected for this change.</span>'
    elif st == "failed" or (test_results.get("methods_failed") and st != "passed" and n):
        fail_n = len(fails) or test_results.get("methods_failed") or 1
        who = ""
        if fails:
            shown = ", ".join(fails[:3])
            more = ""
            if len(fails) > 3:
                more = f" (+{len(fails)-3} more)"
            elif len(fails) > 1:
                more = ""
            who = f' (<span class="m">{esc(shown)}</span>{esc(more)})'
        if n:
            outcome = (f'<span class="test-fail">Ran <b>{n}</b> selected {n_label} — '
                       f'<b>{fail_n} FAILED</b> ✗{who}</span>')
        else:
            outcome = (f'<span class="test-fail">Selected tests ran — '
                       f'<b>{fail_n} FAILED</b> ✗{who}</span>')
    elif st == "passed" or test_results.get("methods_failed") == 0:
        if n:
            outcome = _pass_caveat(
                f'Ran <b>{n}</b> selected {n_label} — all passed ✓')
        else:
            run = test_results.get("methods_run") or 0
            if run:
                outcome = _pass_caveat(
                    f'Suite ran <b>{run}</b> methods — all passed ✓')
            else:
                outcome = _pass_caveat('Selected tests ran — all passed ✓')
    else:
        outcome = '<span class="test-skip">Test outcome unavailable.</span>'

    return f'<div class="skel"><span class="skel-k">Do:</span> {base}. {outcome}</div>'


def _tests_outcome_banner_html(test_results, *, project_grade=None):
    # None = pre-test scan render (no banner). Explicit not_run / ran /
    # reachability_only from record-test-results always produces a banner.
    if test_results is None:
        return ""
    status = test_results.get("status") or "not_run"
    if status == "reachability_only":
        note = (test_results.get("selection_note")
                or "No test suite present — grade based on static reachability alone; "
                   "recommend canary rollout as the compensating control.")
        return (f'<p class="tests-banner test-skip-banner"><b>Validation: reachability only.</b> '
                f'{esc(note)}</p>')
    if status != "ran":
        return ('<p class="tests-banner test-skip-banner">Selected tests for the changed '
                'dependencies: <b>not run</b>.</p>')
    passed = test_results.get("methods_passed") or 0
    failed = test_results.get("methods_failed") or 0
    run = test_results.get("methods_run") or (passed + failed)
    sel = test_results.get("selection_final")
    sel_bit = f"{sel} classes selected · " if sel is not None else ""
    if failed:
        fails = test_results.get("failed_names") or []
        who = ""
        if fails:
            who = " — " + ", ".join(fails[:5])
            if len(fails) > 5:
                who += f" (+{len(fails)-5} more)"
        return (f'<p class="tests-banner test-fail-banner">{esc(sel_bit)}'
                f'<b>{run}</b> methods run, <b>{passed}</b> passed, '
                f'<b>{failed} FAILED</b> ✗{esc(who)}</p>')
    caveat = ""
    if project_grade in ("F", "D"):
        caveat = (f' <span class="test-caveat">— on current jars; does not clear '
                  f'project {esc(project_grade)} (re-test after migrate)</span>')
    return (f'<p class="tests-banner test-pass-banner">{esc(sel_bit)}'
            f'<b>{run}</b> methods run, <b>{passed}</b> passed, '
            f'<b>0</b> failed ✓{caveat}</p>')


def load_demo_grades():
    """Load static Lightwell demo corpus grades (validated + remidiated tables).

    Not this PR's headline — catalog context for scorecard.html / PR comments.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "catalogs", "lightwell-demo-grades.json"),
        os.path.join(here, ".upgrade-delta", "catalogs", "lightwell-demo-grades.json"),
        os.path.join("catalogs", "lightwell-demo-grades.json"),
        os.path.join(".upgrade-delta", "catalogs", "lightwell-demo-grades.json"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            try:
                with open(path) as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError):
                return None
    return None


def _catalog_context_html(r):
    """Remidiated same-base + validated ranked tables (corpus context)."""
    ctx = r.get("catalog_context") or load_demo_grades()
    if not ctx:
        return ""
    rem = ctx.get("remediated_same_base") or []
    val = ctx.get("validated_ranked") or []
    if not rem and not val:
        return ""

    rem_rows = "".join(
        f"<tr><td><b>{esc(row.get('library') or '')}</b></td>"
        f"<td class=\"m\">{esc(row.get('old') or '?')} → {esc(row.get('new') or '?')}</td>"
        f"<td><span class=\"chip\" style=\"--c:{GRADE_COLOR.get(row.get('grade'), 'var(--steel)')}\">"
        f"{esc(row.get('grade') or '?')}</span></td>"
        f"<td>{esc(row.get('flag') or '')}</td></tr>"
        for row in rem
    )
    val_rows = "".join(
        f"<tr><td>{int(row.get('rank') or 0)}</td>"
        f"<td><b>{esc(row.get('library') or '')}</b></td>"
        f"<td>{esc(str(row.get('churn_pct') if row.get('churn_pct') is not None else '?'))}%</td>"
        f"<td><span class=\"chip\" style=\"--c:{GRADE_COLOR.get(row.get('grade'), 'var(--steel)')}\">"
        f"{esc(row.get('grade') or '?')}</span></td>"
        f"<td>{esc(row.get('flag') or '')}</td></tr>"
        for row in val
    )
    summary = esc(ctx.get("validated_summary")
                  or "Every validated demo rebuild graded B — none A / C / F.")
    note = esc(ctx.get("note") or (
        "Catalog context — not this PR's project grade. Same-base remidiated and "
        "validated corpus measurements from community vs .rhlw jars."
    ))

    rem_table = (
        f'<h3>Remidiated same-base (community → .rhlw)</h3>'
        f'<table class="deps catalog-ctx"><thead><tr>'
        f'<th>Library</th><th>Pair</th><th>Grade</th><th>Flag</th>'
        f'</tr></thead><tbody>{rem_rows}</tbody></table>'
        if rem_rows else ""
    )
    val_table = (
        f'<h3>Validated catalog — all graded B</h3>'
        f'<p class="catalog-note">{summary}</p>'
        f'<table class="deps catalog-ctx"><thead><tr>'
        f'<th>Rank</th><th>Library</th><th>Churn</th><th>Grade</th>'
        f'<th>Flag for “just a rebuild”</th>'
        f'</tr></thead><tbody>{val_rows}</tbody></table>'
        if val_rows else ""
    )
    return f'''<details class="catalog-details" open id="lightwell-catalog-grades">
  <summary>Lightwell catalog grades (demo corpus)</summary>
  <p class="catalog-note">{note}</p>
  {rem_table}
  {val_table}
</details>'''


def render_scorecard(r, test_results=None):
    p = r["project"]
    libs = r["libraries"]
    tr = test_results if test_results is not None else r.get("test_results")
    has_transitive = any(l.get("transitive") for l in libs)
    verdict = _verdict_html(p, libs)
    testing = _testing_summary_html(libs)
    bridge = _coverage_bridge_html(p, libs)
    catalog_ctx = _catalog_context_html(r)

    compare = ""
    if p.get("worst_without_best_path") and p["worst_without_best_path"] != p["headline_grade"]:
        c2 = GRADE_COLOR[p["worst_without_best_path"]]
        compare = (f'<div class="note">Without Red Hat remediated builds, this project '
                   f'would score '
                   f'<span class="chip" style="--c:{c2}">{p["worst_without_best_path"]}</span>. '
                   f'That gap is the measured value of Lightwell.</div>')

    blocks, safe, clean = _partition_action_buckets(libs)
    triage = _triage_summary_html(blocks, safe, clean)
    tests_banner = _tests_outcome_banner_html(
        tr, project_grade=p.get("headline_grade"))
    deps_html = (
        _action_bucket_html(
            f"Blocks your upgrade ({len(blocks)})",
            "".join(_dep_row_html(l, expanded=True, test_results=tr) for l in blocks),
            kind="block")
        + _action_bucket_html(
            f"Safe, but test these ({len(safe)})",
            "".join(_dep_row_html(l, expanded=False, test_results=tr) for l in safe),
            kind="safe")
        + _action_bucket_html(
            f"Clean — smoke test only ({len(clean)})",
            "".join(_dep_row_html(l, expanded=False, test_results=tr) for l in clean),
            kind="clean")
    )

    transitive_key = ""
    if has_transitive:
        transitive_key = (
            '<p class="lane" style="margin:0 0 12px">Rows marked '
            '<span class="lane">↳ indirect</span> come in through another dependency '
            '(same risk accounting as a direct dependency).</p>')

    hazards_html = _hazards_html(r.get("hazards") or [], app_name=r.get("app") or "")

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
        unrated_html = f"""<h2 id="no-delta-evidence">No delta evidence yet</h2>
<p style="color:var(--ink-soft)">Your app also calls these packages, but <b>no delta report
has been published for them yet</b> — so they do not affect the project grade. This is
not the same as catalog “uncovered”: a package can be Lightwell drop-in ready on
<a href="coverage.html">coverage.html</a> and still lack a graded row here until evidence exists.</p>
<ul class="list">{items}</ul>"""

    vers = _subtitle_lines_html(p)

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(r['app'])} — project delta scorecard</title>
{FONTS}<style>{CSS}
.verdict{{margin:14px 0 18px;padding:12px 14px;border-left:4px solid var(--vc);
  background:color-mix(in srgb,var(--vc) 10%,var(--card));border-radius:0 6px 6px 0;
  font-size:14.5px;line-height:1.45;max-width:72ch}}
.vers-block{{margin:0 0 18px;max-width:78ch;display:grid;gap:8px}}
.acct{{display:grid;grid-template-columns:minmax(7.5rem,9.5rem) 1fr;gap:8px 14px;
  align-items:baseline;font-size:13.5px;line-height:1.45;color:var(--ink)}}
.acct-k{{font-family:var(--sans);font-weight:700;font-size:11px;letter-spacing:.06em;
  text-transform:uppercase;color:var(--ink-soft)}}
.acct-v{{color:var(--ink)}}
.acct a{{color:var(--steel)}}
@media(max-width:640px){{.acct{{grid-template-columns:1fr;gap:2px}}}}
.bridge-details{{margin:18px 0 0;max-width:78ch}}

.bridge-details summary{{cursor:pointer;font-weight:700;font-size:14px;color:var(--steel)}}
.bridge{{margin:8px 0 0;padding:12px 14px;border-left:4px solid var(--steel);
  background:color-mix(in srgb,var(--steel) 8%,var(--card));border-radius:0 6px 6px 0;
  font-size:13.5px;line-height:1.5;color:var(--ink)}}
.catalog-details{{margin:22px 0 0;max-width:78ch}}
.catalog-details summary{{cursor:pointer;font-weight:700;font-size:15px;color:var(--ink)}}
.catalog-details h3{{font-size:14.5px;margin:16px 0 8px}}
.catalog-note{{font-size:13px;line-height:1.45;color:var(--ink-soft);max-width:72ch;margin:8px 0 12px}}
table.catalog-ctx{{margin:0 0 8px}}
.triage{{margin:0 0 16px;font-size:15.5px;line-height:1.45;max-width:72ch;font-weight:500}}
.tests-banner{{margin:0 0 18px;padding:10px 12px;border-radius:6px;font-size:14px;
  line-height:1.45;max-width:72ch}}
.test-pass-banner{{background:color-mix(in srgb,var(--pass) 12%,var(--card));
  border:1px solid color-mix(in srgb,var(--pass) 40%,transparent)}}
.test-fail-banner{{background:color-mix(in srgb,var(--stop) 14%,var(--card));
  border:2px solid var(--stop);font-weight:600}}
.test-skip-banner{{background:color-mix(in srgb,var(--rule) 55%,var(--card));
  border:1px solid var(--rule);color:var(--ink-soft)}}
.test-pass{{color:var(--pass);font-weight:600}}
.test-caveat{{color:var(--ink-soft);font-weight:500;font-size:12.5px}}
.test-fail{{color:var(--stop);font-weight:700}}
.test-skip{{color:var(--ink-soft)}}
.test-sum{{margin:0 0 22px}}
.test-sum p{{margin:0 0 10px;font-size:14.5px;line-height:1.45;max-width:72ch}}
.risk-strip{{display:flex;height:10px;border-radius:5px;overflow:hidden;
  background:color-mix(in srgb,var(--rule) 55%,transparent);max-width:420px}}
.risk-strip i{{display:block;height:100%}}
.value{{margin:0 0 4px;font-size:14px;line-height:1.45}}
.value-gap{{padding:8px 10px;background:color-mix(in srgb,var(--stop) 12%,var(--card));
  border-radius:6px;border:1px solid color-mix(in srgb,var(--stop) 35%,transparent)}}
.gav{{font-family:var(--mono);font-size:14px;font-weight:700;word-break:break-all}}
.coords{{margin:4px 0 0;font-size:12.5px;line-height:1.4;word-break:break-all}}
.skel{{margin:6px 0 0;font-size:13.5px;line-height:1.45}}
.skel-k{{font-weight:700;color:var(--ink);margin-right:4px}}
.sigs{{font-family:var(--mono);font-size:12px}}
.row-head{{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin:0 0 2px}}
.row-more{{margin-top:6px;font-size:13px}}
.row-more summary{{cursor:pointer;color:var(--steel);font-weight:600}}
.bucket{{margin:0 0 22px}}
.bucket-h{{font-family:var(--disp);font-weight:700;font-size:17px;margin:22px 0 10px;
  padding-left:10px;border-left:4px solid var(--bucket-c,var(--rh-red))}}
.bucket-block{{--bucket-c:var(--stop)}}
.bucket-block table.deps{{border:1px solid color-mix(in srgb,var(--stop) 35%,var(--rule));
  border-radius:6px;overflow:hidden;box-shadow:0 1px 0 color-mix(in srgb,var(--stop) 12%,transparent)}}
.bucket-block tr.row-block td{{background:color-mix(in srgb,var(--stop) 6%,var(--card));
  padding-top:14px;padding-bottom:14px}}
.bucket-safe{{--bucket-c:var(--watch)}}
.bucket-safe table.deps td{{font-size:13.5px;color:var(--ink);
  background:color-mix(in srgb,var(--rule) 18%,var(--card))}}
.bucket-clean{{--bucket-c:var(--pass)}}
.bucket-clean table.deps td{{background:color-mix(in srgb,var(--pass) 5%,var(--card));
  color:var(--ink-soft)}}
table.deps{{width:100%;border-collapse:collapse;background:var(--card)}}
table.deps th,table.deps td{{text-align:left;padding:11px 12px;border-bottom:1px solid var(--rule);font-size:14px;vertical-align:top}}
table.deps th{{font-family:var(--sans);font-weight:700;font-size:11px;letter-spacing:.08em;text-transform:uppercase;
  color:var(--ink-soft);border-bottom:2px solid var(--rule)}}
.why{{margin:8px 0 0;font-size:13px;color:var(--ink);line-height:1.45}}
.break{{margin:8px 0 0;font-size:13.5px;line-height:1.45}}
.break details.tech{{margin-top:4px;font-size:12px}}
.break details.tech summary{{cursor:pointer;color:var(--ink-soft)}}
.break details.tech code{{display:block;margin-top:4px;word-break:break-all;
  font-family:var(--mono);font-size:11.5px;color:var(--ink-soft)}}
.honest{{margin:8px 0 0;font-size:12.5px;line-height:1.45;color:var(--ink-soft);
  max-width:56ch}}
.jobs{{margin:10px 0 0;font-size:13.5px;line-height:1.5;color:var(--ink-soft);max-width:62ch}}
.alts{{margin-top:8px}}
.alt{{margin-top:4px}}
.cves{{margin:8px 0 0;font-size:13px;line-height:1.55;max-width:48ch}}
.cve{{display:inline-block;margin:2px 6px 2px 0;padding:1px 7px;border-radius:4px;
  background:color-mix(in srgb,var(--pass) 14%,var(--card));
  border:1px solid color-mix(in srgb,var(--pass) 40%,transparent);
  font-family:var(--mono);font-size:12px;color:var(--ink)}}
tr.sub td:first-child{{padding-left:28px}}
details.limits{{margin:18px 0 0}}
details.limits summary{{cursor:pointer;font-weight:700;font-size:15px}}
#no-delta-evidence:target{{outline:2px solid var(--steel);outline-offset:4px}}
</style></head><body>
<div class="sheet">
  <div class="eyebrow">Lightwell delta scan · static grade early · tests decide the gate</div>
  <h1>{esc(r['app'])}</h1>
  {vers}
  {verdict}
  <p class="jobs">Two jobs on this page: the <b>static grade</b> is an early signal before a
  full suite runs; <b>selected tests that pass or fail</b> are the real merge gate.
  Reflection and DI remain invisible to static analysis — transitive de-escalation needs
  explicit sign-off, and a canary stays in every lane.</p>
  <p style="max-width:62ch;color:var(--ink-soft)">The project grade is the
  <b>worst dependency in this upgrade</b> (not an average). Each row is the
  <b>lowest-risk upgrade path</b> available — and calls out when Lightwell is what makes that path safe.</p>
  {compare}
  <h2>What this upgrade needs</h2>
  {testing}
  <h2>Dependencies</h2>{_grade_legend_html()}
  {triage}
  {tests_banner}
  {transitive_key}
  {deps_html}
  {bridge}
  {catalog_ctx}
  {hazards_html}
  {heur_html}
  {unrated_html}
  <details class="limits">
    <summary>Limitations — what this scan cannot see</summary>
    <div class="blind" style="margin-top:10px"><ul>
      <li>Reflection and config-driven use of a library will not appear as call sites — and this
      blindness compounds across hops, so transitive reachability evidence carries lower confidence
      than direct analysis. De-escalating a transitive always requires explicit sign-off.</li>
      <li>Ratings come from published, app-agnostic delta reports; only the intersection ran here — your code never left this machine.</li>
      <li>A behavior change with no structural fingerprint is invisible; canary and rollback stay in every lane.</li>
    </ul></div>
  </details>
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

    # Optional: mark libraries this PR / pipeline bumped so coverage stays
    # whole-app but highlights what CAB/scorecard are talking about.
    this_change = []
    change_path = getattr(args, "this_change", None)
    if change_path and os.path.isfile(change_path):
        try:
            raw = json.load(open(change_path))
            entries = []
            if isinstance(raw, dict):
                entries = list(raw.get("changed") or []) + list(raw.get("added") or [])
            elif isinstance(raw, list):
                entries = raw
            for c in entries:
                g = c.get("group") or c.get("groupId") or ""
                a = c.get("artifact") or c.get("artifactId") or ""
                if not a:
                    continue
                this_change.append({
                    "group": g, "artifact": a,
                    "old_version": c.get("old_version") or c.get("fromVersion") or "",
                    "new_version": c.get("new_version") or c.get("toVersion") or "",
                })
        except (OSError, json.JSONDecodeError, TypeError) as e:
            print(f"  ! could not load --this-change {change_path}: {e}")
    change_keys = set()
    if this_change:
        change_keys = {(x["group"], x["artifact"]) for x in this_change}
        result["this_change"] = this_change
        for bucket in ("exact", "serviced_other_version", "uncovered"):
            for e in result[bucket]:
                e["in_this_change"] = (e.get("group"), e.get("artifact")) in change_keys

    print(f"\n== Lightwell coverage :: {app_name} ==")
    print(f"   {total} dependencies checked against {result['catalog']}")
    print(f"   {len(exact)}/{total} drop-in ready — {len(exact)} covered, "
          f"{len(near)} serviced at another version, {len(uncovered)} not covered")
    if this_change:
        print(f"   THIS CHANGE — highlighting {len(this_change)} libraries "
              f"from {change_path}\n")
    else:
        print()
    print(f"   COVERED ({len(exact)}) — drop-in remediated build, no upgrade needed:")
    for g, n, v, rv in sorted(exact):
        mark = "  <- this PR" if (g, n) in change_keys else ""
        print(f"     {g}:{n}  {v} -> {rv}{mark}")
    if near:
        print(f"\n   SERVICED AT ANOTHER VERSION ({len(near)}) — upgrade, or request your version:")
        for g, n, v, sv in sorted(near):
            mark = "  <- this PR" if (g, n) in change_keys else ""
            print(f"     {g}:{n}  you run {v}  |  serviced: {', '.join(sv)}{mark}")
    if uncovered:
        print(f"\n   NOT COVERED ({len(uncovered)}) — no remediated build; full regression on any upgrade:")
        for g, n, v in sorted(uncovered):
            mark = "  <- this PR" if (g, n) in change_keys else ""
            print(f"     {g}:{n}  {v}{mark}")

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
    total = t["dependencies"] or 0
    exact_n = t["exact"]
    near_n = t["serviced_other_version"]
    unc_n = t["uncovered"]
    # Stamp color: majority drop-in → green, otherwise watch.
    stamp_ok = (exact_n * 2 >= total) if total else False
    this_change = r.get("this_change") or []

    def gav(e):
        g = esc(e["group"] or "")
        return f'{g}:{esc(e["artifact"])}' if g else esc(e["artifact"])

    def bump_badge(e):
        if not e.get("in_this_change"):
            return ""
        return ' <span class="bump">In this PR</span>'

    def row_class(e):
        return ' class="this-change"' if e.get("in_this_change") else ""

    def sorted_bucket(rows):
        # PR bumps first within each catalog bucket so the eye lands on them.
        return sorted(rows, key=lambda e: (0 if e.get("in_this_change") else 1,
                                           e.get("group") or "", e.get("artifact") or ""))

    covered_rows = "".join(
        f'<tr{row_class(e)}><td class="dep">{gav(e)}{bump_badge(e)}</td>'
        f'<td class="ver">{esc(e["version"])}</td>'
        f'<td class="ver arrow">{esc(e["remediated"])}</td>'
        f'<td class="act">{"Already on the Red Hat remediated build." if e["version"] == e["remediated"] else "Swap the version suffix. No code change."}</td></tr>'
        for e in sorted_bucket(r["exact"]))
    near_rows = "".join(
        f'<tr{row_class(e)}><td class="dep">{gav(e)}{bump_badge(e)}</td>'
        f'<td class="ver">{esc(e["version"])}</td>'
        f'<td class="ver">{esc(", ".join(e["serviced_versions"]))}</td>'
        f'<td class="act">Move to a serviced version, or request your version.</td></tr>'
        for e in sorted_bucket(r["serviced_other_version"]))
    unc_rows = "".join(
        f'<tr{row_class(e)}><td class="dep">{gav(e)}{bump_badge(e)}</td>'
        f'<td class="ver">{esc(e["version"])}</td>'
        f'<td class="ver dash">not serviced</td>'
        f'<td class="act">No remediated build. Full regression on any upgrade.</td></tr>'
        for e in sorted_bucket(r["uncovered"]))

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
                "change, not an upgrade.", exact_n, covered_rows, "Remediated build") +
        section("watch", "var(--pass)", "Serviced — at a different version",
                "Red Hat services this library at a newer or matching version. A real "
                "upgrade, or a request for your exact version.", near_n, near_rows,
                "Serviced versions") +
        section("stop", "var(--stop)", "Not covered",
                "No remediated build exists. Any upgrade here carries the full, unscoped test "
                "burden — the situation this tool exists to remove.", unc_n,
                unc_rows, "Status"))

    change_banner = ""
    if this_change:
        items = "".join(
            f'<li><code>{esc(c["group"])}:{esc(c["artifact"])}</code> '
            f'{esc(c.get("old_version") or "?")} → <b>{esc(c.get("new_version") or "?")}</b></li>'
            for c in this_change)
        change_banner = f'''<div class="change-banner">
    <div class="change-h">This PR / pipeline bumps {len(this_change)} librar{"y" if len(this_change) == 1 else "ies"}</div>
    <p class="change-s">Coverage stays the whole-app catalog meter. Rows tagged
    <span class="bump">In this PR</span> are the same bumps graded on
    <a href="scorecard.html">scorecard.html</a> (and its catalog-grades section) and
    summarized in the CAB PR comment.</p>
    <ul class="change-list">{items}</ul>
  </div>'''

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(r['app'])} — Lightwell coverage</title>{FONTS}<style>{CSS}
.cov-sub{{color:var(--ink-soft);max-width:70ch;margin:2px 0 22px;font-size:14px;line-height:1.55}}
.legend{{display:flex;gap:26px;margin:0 0 26px;flex-wrap:wrap}}
.legend .li{{display:flex;align-items:baseline;gap:9px}}
.legend .n{{font:700 22px/1 var(--head,inherit)}}
.legend .t{{font-size:12.5px;color:var(--ink-soft)}}
.legend .dot{{width:9px;height:9px;border-radius:50%;align-self:center}}
.stamp .g{{font-size:clamp(28px,4vw,42px);letter-spacing:-0.02em}}
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
tr.this-change td{{background:rgba(0,102,204,.06)}}
tr.this-change td.dep{{box-shadow:inset 3px 0 0 var(--watch,#f0ab00)}}
.bump{{display:inline-block;margin-left:8px;padding:1px 7px;border-radius:4px;
  font:600 10px/1.4 var(--head,inherit);letter-spacing:.04em;text-transform:uppercase;
  background:var(--watch,#f0ab00);color:#1f1f1f;vertical-align:middle}}
.change-banner{{margin:0 0 22px;padding:14px 16px;border:1px solid var(--watch,#f0ab00);
  border-left:4px solid var(--watch,#f0ab00);background:rgba(240,171,0,.08);border-radius:6px}}
.change-h{{font:700 14px/1.3 var(--head,inherit);margin:0 0 6px}}
.change-s{{font-size:12.5px;color:var(--ink-soft);margin:0 0 10px;line-height:1.5;max-width:72ch}}
.change-list{{margin:0;padding-left:18px;font-size:12.5px}}
.change-list code{{font-size:12px}}
td.dep{{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px;color:var(--ink);white-space:nowrap}}
td.ver{{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px;color:var(--ink-soft);white-space:nowrap}}
td.ver.arrow{{color:var(--pass);font-weight:600}}
td.ver.arrow::before{{content:"\2192  ";color:var(--ink-soft);font-weight:400}}
td.ver.dash{{color:var(--stop)}}
td.act{{color:var(--ink);font-size:12.5px}}
</style></head><body>
<div class="sheet" style="--stamp-c:{'var(--pass)' if stamp_ok else 'var(--watch)'}">
  <div class="stamp"><span class="g">{exact_n}/{total}</span><span class="l">drop-in ready</span></div>
  <div class="eyebrow">Lightwell coverage meter</div>
  <h1>{esc(r['app'])}</h1>
  <div class="vers">{total} dependencies checked against {esc(r['catalog'])}</div>
  <p class="cov-sub">How many of this application's dependencies Red Hat Lightwell can
  remediate <b>without an upgrade</b> — today, for the exact versions in production.
  <b>This is not the project scorecard.</b> The scorecard grades only libraries with
  <b>published delta evidence</b> your app reaches (often a small subset). The
  <span class="m">{exact_n}/{total}</span> drop-in rows below are usually a version-suffix
  swap — they belong here, not as extra graded rows on scorecard.html.
  See also <a href="scorecard.html">scorecard.html</a> for this PR's graded bumps
  and the <a href="scorecard.html#lightwell-catalog-grades">Lightwell catalog grades</a>
  (validated all-B / remidiated same-base context).</p>
  {change_banner}
  <div class="legend">
    <div class="li"><span class="dot" style="background:var(--pass)"></span>
      <span class="n" style="color:var(--pass)">{exact_n}</span>
      <span class="t">drop-in remediated<br>of {total} deps</span></div>
    <div class="li"><span class="dot" style="background:var(--pass)"></span>
      <span class="n" style="color:var(--pass)">{near_n}</span>
      <span class="t">serviced, other version<br>of {total} deps</span></div>
    <div class="li"><span class="dot" style="background:var(--stop)"></span>
      <span class="n" style="color:var(--stop)">{unc_n}</span>
      <span class="t">not covered<br>of {total} deps</span></div>
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

def record_test_results_cmd(args):
    sel = None
    if args.selection and os.path.isfile(args.selection):
        with open(args.selection) as f:
            sel = json.load(f)
    routing = None
    if getattr(args, "routing", None) and os.path.isfile(args.routing):
        with open(args.routing) as f:
            routing = json.load(f)
    coverage = None
    if getattr(args, "coverage", None) and os.path.isfile(args.coverage):
        with open(args.coverage) as f:
            coverage = json.load(f)
    lib_names = []
    if args.scorecard and os.path.isfile(args.scorecard):
        with open(args.scorecard) as f:
            sc = json.load(f)
        lib_names = [l["library"] for l in sc.get("libraries") or [] if l.get("library")]
    result = compose_test_results(
        methods_passed=args.passed, methods_failed=args.failed,
        summary=args.summary, status=args.status,
        failed_names=args.failed_name, selection_report=sel,
        library_names=lib_names, routing=routing, coverage=coverage)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(result, f, indent=2)
    print(f"  test-results: {args.out} "
          f"(status={result['status']} passed={result['methods_passed']} "
          f"failed={result['methods_failed']})")


def render_scorecard_cmd(args):
    with open(args.scorecard_json) as f:
        sc = json.load(f)
    tr = None
    if args.test_results:
        if os.path.isfile(args.test_results):
            with open(args.test_results) as f:
                tr = json.load(f)
        else:
            print(f"  ! {args.test_results} missing — rendering with tests-not-run note")
            tr = compose_test_results(status="not_run", summary="tests not run",
                                      library_names=[l["library"] for l in sc.get("libraries") or []])
    else:
        tr = sc.get("test_results")
    html = render_scorecard(sc, test_results=tr)
    os.makedirs(os.path.dirname(args.html) or ".", exist_ok=True)
    with open(args.html, "w") as f:
        f.write(html)
    print(f"  scorecard html: {args.html}")


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
                   "so upgrade-delta-summary/upgrade-delta-pr-comment work unchanged. If this "
                   "file already exists, the new library is APPENDED to it instead of "
                   "overwriting -- lets a direct dependency and its transitive dependencies "
                   "land in the same scorecard/PR comment.")
    a.add_argument("--transitive-of", help="GROUP:ARTIFACT of the DIRECT dependency that pulls "
                   "this one in. Switches to two-hop reachability: --app must reach this "
                   "library only THROUGH --parent-jar, not directly.")
    a.add_argument("--parent-jar", help="the direct dependency's OLD jar (already resolved) -- "
                   "required with --transitive-of, used as the two-hop BFS starting point")
    a.add_argument("--accept-transitive-scope", action="store_true", help="sign off on "
                   "de-escalating a transitive whose changed members are all unreachable "
                   "through the app's call paths into the parent")
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
    s.add_argument("--osv-dir", help="local directory of Lightwell OSV JSON advisories "
                   "(offline/CI mirror of …/osv/java/remediated/). When set, these "
                   "are preferred; live fetch still fills gaps unless --no-osv-fetch")
    s.add_argument("--osv-url", default=None,
                   help="Lightwell OSV index URL (default: public-lightwell-demo "
                   "osv/java/remediated). Ignored with --no-osv-fetch")
    s.add_argument("--no-osv-fetch", action="store_true",
                   help="do not contact the network for OSV advisories; use --osv-dir only")
    s.add_argument("--coverage", help="coverage.json from a prior `coverage` run — "
                   "embeds catalog totals on the scorecard so 16/27 drop-in vs 3 graded "
                   "rows is explained, not contradictory")
    s.set_defaults(fn=scan)

    cv = sub.add_parser("coverage", help="match an app SBOM against the Lightwell "
                        "remediated catalog: exact drop-in builds vs blind spots")
    cv.add_argument("--sbom", required=True, help="the application's CycloneDX SBOM")
    cv.add_argument("--catalog", required=True,
                    help="Lightwell catalog SBOM (e.g. catalogs/lightwell-remediated-java-sbom.json)")
    cv.add_argument("--json"); cv.add_argument("--html")
    cv.add_argument("--this-change",
                    help="changed-deps.json from detect-pom-changes — highlight "
                         "libraries this PR/pipeline bumped on the coverage card")
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

    rs = sub.add_parser("render-scorecard",
                        help="regenerate scorecard.html from scorecard.json "
                             "(optionally with test outcomes)")
    rs.add_argument("scorecard_json", help="path to scorecard.json")
    rs.add_argument("--html", required=True, help="write scorecard HTML here")
    rs.add_argument("--test-results",
                    help="optional upgrade-delta/test-results/v1 JSON "
                         "(from record-test-results)")
    rs.set_defaults(fn=render_scorecard_cmd)

    rt = sub.add_parser("record-test-results",
                        help="write out/test-results.json joining selection "
                             "with pass/fail counts for scorecard regeneration")
    rt.add_argument("--out", required=True)
    rt.add_argument("--passed", type=int, default=0)
    rt.add_argument("--failed", type=int, default=0)
    rt.add_argument("--summary", default="")
    rt.add_argument("--status", default="ran",
                    choices=["ran", "not_run", "reachability_only"])
    rt.add_argument("--failed-name", action="append", default=[],
                    help="Class or Class.method that failed (repeatable)")
    rt.add_argument("--selection", help="selection-report.json path")
    rt.add_argument("--scorecard", help="scorecard.json for library name list")
    rt.add_argument("--routing", help="routing.json for full-suite test attribution")
    rt.add_argument("--coverage", help="coverage.json for full-suite test attribution")
    rt.set_defaults(fn=record_test_results_cmd)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
