#!/usr/bin/env python3
"""Churn-normalization verification. Run: python3 samples/verify_churn.py"""
import os, subprocess, sys, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from upgrade_delta import load_jar, diff_jars                     # noqa: E402
import build_ctx                                                   # noqa: E402
sys.path.insert(0, HERE)
from build_samples import logging_sources, logging_resources, compile_and_jar, JAVAC, ENV, w  # noqa: E402


def build_variant(version, tag, extra_javac):
    """Same sources as acme-logging <version>, different toolchain flags."""
    src_dir = os.path.join(HERE, "work", f"verify-{tag}", "src")
    out_dir = os.path.join(HERE, "work", f"verify-{tag}", "classes")
    import shutil
    shutil.rmtree(os.path.dirname(src_dir), ignore_errors=True)
    for rel, text in logging_sources(version).items():
        w(src_dir, rel, text)
    os.makedirs(out_dir, exist_ok=True)
    files = []
    for root, _, fns in os.walk(src_dir):
        files += [os.path.join(root, f) for f in fns if f.endswith(".java")]
    subprocess.run(JAVAC + extra_javac + ["-d", out_dir] + sorted(files), check=True, env=ENV)
    jar = os.path.join(HERE, "work", f"acme-logging-{version}-{tag}.jar")
    with zipfile.ZipFile(jar, "w") as z:
        for root, _, fns in os.walk(out_dir):
            for f in sorted(fns):
                full = os.path.join(root, f)
                z.writestr(zipfile.ZipInfo(os.path.relpath(full, out_dir)),
                           open(full, "rb").read())
    return jar


def main():
    ok = True

    # 1) noise-only: same source, different -g / -parameters flags
    a = load_jar(build_variant("1.12.1", "dbg", ["-g", "-parameters"]))
    b = load_jar(build_variant("1.12.1", "nodbg", ["-g:none"]))
    raw_diff = sum(1 for c in a["class_hashes"]
                   if a["class_hashes"][c] != b["class_hashes"].get(c))
    d = diff_jars(a, b)
    print(f"[1] same source, different toolchain flags:")
    print(f"    raw byte diffs: {raw_diff}/{len(a['class_hashes'])} classes"
          f"   semantic churn: {d['impl_churn_pct']}%"
          f"   noise classes excluded: {len(d['classes_build_noise'])}")
    if raw_diff == 0:
        print("    WARN: toolchain flags produced identical bytes; noise test inconclusive")
    if d["impl_churn_pct"] != 0.0:
        print("    FAIL: semantic churn should be 0.0% for identical source"); ok = False
    else:
        print("    PASS: build noise fully excluded")

    # 2) the real change is still caught
    old = load_jar(os.path.join(HERE, "jars", "acme-logging-1.12.1.jar"))
    new = load_jar(os.path.join(HERE, "jars", "acme-logging-1.12.2.jar"))
    d2 = diff_jars(old, new)
    changed = [c.split("/")[-1] for c in d2["classes_impl_changed"]]
    print(f"[2] 1.12.1 -> 1.12.2 (one real method-body edit):")
    print(f"    semantic churn: {d2['impl_churn_pct']}%   changed: {changed}")
    if "LookupResolver" in changed and d2["impl_churn_pct"] > 0:
        print("    PASS: real change not normalized away")
    else:
        print("    FAIL: the real edit was lost by normalization"); ok = False

    # 3) fail-safe on unparseable input
    from upgrade_delta import normalized_fingerprint
    import hashlib
    junk = b"\xca\xfe\xba\xbe" + b"\x00" * 3   # truncated class file
    if normalized_fingerprint(junk) == hashlib.sha256(junk).hexdigest():
        print("[3] PASS: unparseable class falls back to raw hash (reports change, never hides it)")
    else:
        print("[3] FAIL: fallback broken"); ok = False

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
