#!/usr/bin/env python3
"""Build the sample corpus: three libraries in multiple versions + one consumer app.

The libraries deliberately mirror real upgrade shapes:
  acme-logging 1.12.1 -> 1.12.2   a disciplined z-stream backport (one class changes)
  acme-logging 1.14.1 -> 1.17.1   the community forward-upgrade (API breaks, churn, defaults flip)
  acme-http-client 4.5.13 -> 4.5.14  a noisy z-stream (no API change, heavy internal rewrite)
  acme-json 2.13.4 -> 2.13.4.2    a z-stream that adds surface (new public API + blocklist)

Everything is compiled with javac and zipped without timestamps so unchanged
classes are byte-identical across versions (honest churn numbers).
"""
import os, shutil, subprocess, sys, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
JAVA_HOME = os.environ.get("SAMPLES_JDK", "/home/claude/jdk/usr/lib/jvm/java-21-openjdk-amd64")
JAVAC = [os.path.join(JAVA_HOME, "bin", "javac")]
ENV = dict(os.environ, LD_LIBRARY_PATH="/usr/lib/jvm/java-21-openjdk-amd64/lib")

def w(root, path, text):
    p = os.path.join(root, path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(text)

# --------------------------------------------------------------- acme-logging

def logging_sources(version):
    """Return {relpath: source} for a given acme-logging version."""
    forward = version == "1.17.1"       # the breaking community upgrade
    patched = version in ("1.12.2", "1.17.1")  # interpolation disabled
    s = {}
    P = "com/acme/logging"

    s[f"{P}/Logger.java"] = f"""package com.acme.logging;
import com.acme.logging.core.MessageFormatter;
public class Logger {{
    private final String name;
    private Logger(String name) {{ this.name = name; }}
    public static Logger getLogger(String name) {{ return new Logger(name); }}
    public void info(String msg) {{ emit("INFO", msg); }}
    public void warn(String msg) {{ emit("WARN", msg); }}
    public void error(String msg, Throwable t) {{ emit("ERROR", msg + ": " + t); }}
    public void log(String msg) {{ emit("LOG", msg); }}
{'''    public LogBuilder atLevel(String level) { return new LogBuilder(this, level); }
''' if forward else ''}    private void emit(String level, String msg) {{
        System.out.println("[" + level + "] " + name + " - " +
            MessageFormatter.format({'(CharSequence)' if forward else ''}msg, new Object[0]));
    }}
}}
"""
    if forward:
        s[f"{P}/LogBuilder.java"] = """package com.acme.logging;
public class LogBuilder {
    private final Logger logger; private final String level;
    LogBuilder(Logger logger, String level) { this.logger = logger; this.level = level; }
    public void log(String msg) { logger.log("[" + level + "] " + msg); }
}
"""
    s[f"{P}/LogManager.java"] = f"""package com.acme.logging;
public class LogManager {{
    public static String getContext() {{ return "default{'-v2' if forward else ''}"; }}
}}
"""
    if not forward:
        # The dangerous interpolation entry point. Removed entirely in 1.17.1,
        # neutered (but API-identical) in the 1.12.2 backport.
        body = ('        return "${" + expr + "}"; // interpolation disabled (security backport)'
                if patched else
                '        return Interp.eval(expr); // DANGER: evaluates ${...} expressions')
        s[f"{P}/core/LookupResolver.java"] = f"""package com.acme.logging.core;
import com.acme.logging.internal.Interp;
public class LookupResolver {{
    public String resolve(String expr) {{
{body}
    }}
}}
"""
    if forward:
        s[f"{P}/core/StrSubstitutor.java"] = """package com.acme.logging.core;
public class StrSubstitutor {
    public String replace(String template) { return template; } // lookups removed by design
}
"""
    fmt_param = "CharSequence" if forward else "String"
    fmt_extra = "\n        if (template == null) return \"\";" if forward else ""
    s[f"{P}/core/MessageFormatter.java"] = f"""package com.acme.logging.core;
public class MessageFormatter {{
    public static String format({fmt_param} template, Object[] args) {{{fmt_extra}
        return String.valueOf(template);
    }}
}}
"""
    s[f"{P}/core/PatternParser.java"] = f"""package com.acme.logging.core;
public class PatternParser {{
    public String parse(String pattern) {{ return pattern{'.trim()' if forward else ''}; }}
}}
"""
    s[f"{P}/core/Configurator.java"] = f"""package com.acme.logging.core;
public class Configurator {{
    public void reconfigure() {{ /* reload defaults{' v2' if forward else ''} */ }}
}}
"""
    s[f"{P}/spi/Appender.java"] = """package com.acme.logging.spi;
public interface Appender { void append(String event); }
"""
    s[f"{P}/appenders/ConsoleAppender.java"] = f"""package com.acme.logging.appenders;
import com.acme.logging.spi.Appender;
public class ConsoleAppender implements Appender {{
    public void append(String event) {{ System.out.println(event{' + "\\n"' if forward else ''}); }}
}}
"""
    if forward:
        s[f"{P}/appenders/FileAppender.java"] = """package com.acme.logging.appenders;
import com.acme.logging.spi.Appender;
public class FileAppender implements Appender {
    public void append(String event) { /* write to file */ }
}
"""
    # internals — churn ballast; note 1.17.1 touches most of them
    internals = {
        "Interp":     "public static String eval(String e){ return \"resolved:\" + e; }",
        "BufferPool": "public byte[] take(){ return new byte[64]; }",
        "Clock":      "public long now(){ return System.currentTimeMillis(); }",
        "Levels":     "public int of(String s){ return s.length(); }",
        "Throwables": "public String print(Throwable t){ return String.valueOf(t); }",
        "Chars":      "public boolean ws(char c){ return c == ' '; }",
        "Strings":    "public String join(String a, String b){ return a + b; }",
        "Loader":     "public ClassLoader get(){ return getClass().getClassLoader(); }",
    }
    for name, body in internals.items():
        touched = forward and name not in ("Chars", "Strings")  # most rewritten in 1.17.1
        s[f"{P}/internal/{name}.java"] = f"""package com.acme.logging.internal;
public class {name} {{
    {'// rewritten in 1.17.x line' if touched else ''}
    {body}
    {'public int version(){ return 17; }' if touched else ''}
}}
"""
    return s


def logging_resources(version):
    forward = version == "1.17.1"
    res = {
        "acme-logging-defaults.properties":
            f"lookup.enabled={'false' if forward else 'true'}\n"
            + ("substitutor.enabled=true\n" if forward else ""),
        "META-INF/services/com.acme.logging.spi.Appender":
            "com.acme.logging.appenders.ConsoleAppender\n"
            + ("com.acme.logging.appenders.FileAppender\n" if forward else ""),
    }
    return res

# ------------------------------------------------------------ acme-http-client

def http_sources(version):
    new = version == "4.5.14"
    P = "com/acme/http"
    s = {}
    s[f"{P}/HttpClient.java"] = """package com.acme.http;
import com.acme.http.internal.Retry;
import com.acme.http.internal.Wire;
public class HttpClient {
    public String execute(String url) { return new Retry().run(url); }
    public String debugDump() { new Wire().trace("dump"); return "ok"; }
    public void close() { }
}
"""
    s[f"{P}/RequestConfig.java"] = """package com.acme.http;
public class RequestConfig {
    public int timeoutMillis() { return Integer.getInteger("acme.http.timeout", 30000); }
}
"""
    s[f"{P}/ConnectionManager.java"] = f"""package com.acme.http;
import com.acme.http.internal.Wire;
public class ConnectionManager {{
    {'// connection validation rewritten for stale-check fix' if new else ''}
    public void release() {{ new Wire().trace("released"); {'validate();' if new else ''} }}
    {'private void validate() { /* stale connection check */ }' if new else ''}
}}
"""
    s[f"{P}/internal/Retry.java"] = f"""package com.acme.http.internal;
import com.acme.codec.Base64Codec;
public class Retry {{
    public String run(String url) {{
        {'int attempts = 3; // backoff rewritten' if new else 'int attempts = 1;'}
        String auth = new Base64Codec().encode(new byte[0]);
        return "GET " + url + " attempts=" + attempts + " auth=" + auth;
    }}
}}
"""
    s[f"{P}/internal/IOBuffers.java"] = f"""package com.acme.http.internal;
public class IOBuffers {{
    public byte[] alloc() {{ return new byte[{'8192' if new else '4096'}]; }}
}}
"""
    if new:
        # 4.5.14 migrated off the removed Hex API
        s[f"{P}/internal/Wire.java"] = """package com.acme.http.internal;
import com.acme.codec.Base64Codec;
public class Wire { public void trace(String s) { new Base64Codec().encode(s.getBytes()); } }
"""
    else:
        s[f"{P}/internal/Wire.java"] = """package com.acme.http.internal;
import com.acme.codec.Hex;
public class Wire { public void trace(String s) { Hex.encode(s.getBytes()); } }
"""
    return s


def http_resources(version):
    new = version == "4.5.14"
    return {"acme-http-defaults.properties":
            f"stale.check={'true' if new else 'false'}\nkeepalive=60\n"}

# ---------------------------------------------------------------- acme-json

def json_sources(version):
    new = version == "2.13.4.2"
    P = "com/acme/json"
    s = {}
    s[f"{P}/JsonMapper.java"] = f"""package com.acme.json;
public class JsonMapper {{
    public String write(Object o) {{ return "{{}}"; }}
    public Object read(String s) {{ return new Object(); }}
{'    public JsonMapper enableSafeDefaults() { return this; } // gadget-class blocklist on by default' if new else ''}
}}
"""
    if new:
        s[f"{P}/SafeTypeValidator.java"] = """package com.acme.json;
public class SafeTypeValidator {
    public boolean allow(String className) { return !className.startsWith("evil."); }
}
"""
    s[f"{P}/internal/Tokens.java"] = """package com.acme.json.internal;
public class Tokens { public char open() { return '{'; } }
"""
    return s


def json_resources(version):
    new = version == "2.13.4.2"
    res = {}
    if new:
        res["acme-json-blocklist.txt"] = "evil.Gadget\nevil.Ldap\n"
    return res

# ---------------------------------------------------------------- acme-codec (transitive)

def codec_sources(version):
    new = version == "1.15"
    P = "com/acme/codec"
    s = {}
    s[f"{P}/Base64Codec.java"] = """package com.acme.codec;
public class Base64Codec {
    public String encode(byte[] data) { return java.util.Base64.getEncoder().encodeToString(data); }
}
"""
    if not new:
        s[f"{P}/Hex.java"] = """package com.acme.codec;
public class Hex {
    public static String encode(byte[] data) { return java.util.HexFormat.of().formatHex(data); }
}
"""
    else:
        s[f"{P}/CodecPolicy.java"] = """package com.acme.codec;
public class CodecPolicy {
    public boolean strict() { return true; }
}
"""
    s[f"{P}/internal/Pad.java"] = f"""package com.acme.codec.internal;
public class Pad {{
    public char pad() {{ return {"'='" if not new else "'='"}; }}
    {'public int block() { return 4; } // rewritten in 1.15' if new else ''}
}}
"""
    return s


# ---------------------------------------------------------------- app

LEGACY_XML_SOURCES = {
    "com/acme/xml/XmlUtil.java": """package com.acme.xml;
public class XmlUtil {
    public static String escape(String s) { return s.replace("<", "&lt;"); }
}
""",
}

APP_SOURCES = {
    "com/acme/payments/PaymentService.java": """package com.acme.payments;
import com.acme.logging.Logger;
import com.acme.logging.core.LookupResolver;
import com.acme.logging.core.MessageFormatter;
public class PaymentService {
    private static final String APPENDER = "com.acme.logging.appenders.ConsoleAppender";
    private static final Logger LOG = Logger.getLogger("payments");
    public String process(String order) {
        LOG.info("processing " + order);
        // the vulnerable pattern: user-influenced string through the resolver
        String tag = new LookupResolver().resolve(order);
        return MessageFormatter.format("done " + tag, new Object[0]);
    }
}
""",
    "com/acme/payments/GatewayClient.java": """package com.acme.payments;
import com.acme.http.HttpClient;
import com.acme.json.JsonMapper;
import com.acme.xml.XmlUtil;
public class GatewayClient {
    public String send(String url, Object payload) {
        String body = XmlUtil.escape(new JsonMapper().write(payload));
        return new HttpClient().execute(url) + " body=" + body;
    }
}
""",
}

# ---------------------------------------------------------------- build

def compile_and_jar(name, version, sources, resources, classpath=None):
    src = os.path.join(HERE, "work", f"{name}-{version}", "src")
    out = os.path.join(HERE, "work", f"{name}-{version}", "classes")
    shutil.rmtree(os.path.dirname(src), ignore_errors=True)
    for rel, text in sources.items():
        w(src, rel, text)
    os.makedirs(out, exist_ok=True)
    files = []
    for root, _, fns in os.walk(src):
        files += [os.path.join(root, f) for f in fns if f.endswith(".java")]
    cmd = JAVAC + ["-d", out] + (["-cp", classpath] if classpath else []) + sorted(files)
    subprocess.run(cmd, check=True, env=ENV)
    jar_path = os.path.join(HERE, "jars", f"{name}-{version}.jar")
    os.makedirs(os.path.dirname(jar_path), exist_ok=True)
    with zipfile.ZipFile(jar_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, fns in os.walk(out):
            for f in sorted(fns):
                full = os.path.join(root, f)
                rel = os.path.relpath(full, out)
                zi = zipfile.ZipInfo(rel)  # no timestamp -> reproducible
                with open(full, "rb") as fh:
                    z.writestr(zi, fh.read())
        for rel, text in sorted(resources.items()):
            z.writestr(zipfile.ZipInfo(rel), text)
    print("built", jar_path)
    return jar_path, out


SBOM = {
  "bomFormat": "CycloneDX", "specVersion": "1.5",
  "metadata": {"component": {"type": "application", "name": "payments-service", "version": "1.0.0"}},
  "components": [
    {"type": "library", "name": "acme-logging", "version": "1.14.1", "scope": "direct"},
    {"type": "library", "name": "acme-http-client", "version": "4.5.13", "scope": "direct"},
    {"type": "library", "name": "acme-json", "version": "2.13.4", "scope": "direct"},
    {"type": "library", "name": "legacy-xml", "version": "1.0", "scope": "direct"},
    {"type": "library", "name": "acme-codec", "version": "1.11", "scope": "transitive"}
  ],
  "dependencies": [
    {"ref": "payments-service@1.0.0",
     "dependsOn": ["acme-logging@1.14.1", "acme-http-client@4.5.13",
                    "acme-json@2.13.4", "legacy-xml@1.0"]},
    {"ref": "acme-http-client@4.5.13", "dependsOn": ["acme-codec@1.11"]}
  ]
}


def main():
    jars = {}
    for v in ("1.12.1", "1.12.2", "1.14.1", "1.17.1"):
        jars[f"log-{v}"], _ = compile_and_jar(
            "acme-logging", v, logging_sources(v), logging_resources(v))
    for v in ("1.11", "1.15"):
        jars[f"codec-{v}"], _ = compile_and_jar(
            "acme-codec", v, codec_sources(v), {})
    for v in ("4.5.13", "4.5.14"):
        codec = jars["codec-1.11"] if v == "4.5.13" else jars["codec-1.15"]
        jars[f"http-{v}"], _ = compile_and_jar(
            "acme-http-client", v, http_sources(v), http_resources(v), classpath=codec)
    for v in ("2.13.4", "2.13.4.2"):
        jars[f"json-{v}"], _ = compile_and_jar(
            "acme-json", v, json_sources(v), json_resources(v))

    legacy, _ = compile_and_jar("legacy-xml", "1.0", LEGACY_XML_SOURCES, {})
    cp = os.pathsep.join([jars["log-1.14.1"], jars["http-4.5.13"], jars["json-2.13.4"], legacy])
    app_res = {"app-config.properties":
               "appender.class=com.acme.logging.appenders.ConsoleAppender\n"}
    _, app_classes = compile_and_jar("payments-service", "1.0.0", APP_SOURCES, app_res, classpath=cp)

    # (c) reactor modules: same app split across two jars
    import zipfile as _zf
    for mod, pick in (("payments-core", "PaymentService"), ("payments-gateway", "GatewayClient")):
        jp = os.path.join(HERE, "jars", f"{mod}-1.0.0.jar")
        with _zf.ZipFile(jp, "w") as z:
            for root, _, fns in os.walk(app_classes):
                for f in sorted(fns):
                    if pick in f:
                        full = os.path.join(root, f)
                        z.writestr(_zf.ZipInfo(os.path.relpath(full, app_classes)),
                                   open(full, "rb").read())
            if mod == "payments-core":
                z.writestr(_zf.ZipInfo("app-config.properties"), app_res["app-config.properties"])
        print("built", jp)

    # (d) uber jar: app + all deps + maven fingerprints + a RELOCATED codec copy;
    #     legacy-xml deliberately declared-in-SBOM but NOT shipped (drift demo)
    uber = os.path.join(HERE, "jars", "payments-uber-1.0.0.jar")
    dep_meta = [("com.acme", "acme-logging", "1.14.1", jars["log-1.14.1"]),
                ("com.acme", "acme-http-client", "4.5.13", jars["http-4.5.13"]),
                ("com.acme", "acme-json", "2.13.4", jars["json-2.13.4"]),
                ("com.acme", "acme-codec", "1.11", jars["codec-1.11"])]
    with _zf.ZipFile(uber, "w") as z:
        for root, _, fns in os.walk(app_classes):
            for f in sorted(fns):
                full = os.path.join(root, f)
                z.writestr(_zf.ZipInfo(os.path.relpath(full, app_classes)), open(full, "rb").read())
        z.writestr(_zf.ZipInfo("app-config.properties"), app_res["app-config.properties"])
        for grp, art, ver, jar in dep_meta:
            with _zf.ZipFile(jar) as dz:
                for info in dz.infolist():
                    if not info.is_dir():
                        z.writestr(_zf.ZipInfo(info.filename), dz.read(info))
            z.writestr(_zf.ZipInfo(f"META-INF/maven/{grp}/{art}/pom.properties"),
                       f"groupId={grp}\nartifactId={art}\nversion={ver}\n")
        with _zf.ZipFile(jars["codec-1.11"]) as dz:      # shaded/relocated duplicate
            for info in dz.infolist():
                if info.filename.endswith(".class"):
                    z.writestr(_zf.ZipInfo("shaded/" + info.filename), dz.read(info))
    print("built", uber)
    import json as _json
    with open(os.path.join(HERE, "jars", "payments-service.sbom.json"), "w") as f:
        _json.dump(SBOM, f, indent=2)
    print("wrote payments-service.sbom.json")
    print("\nsample corpus ready in", os.path.join(HERE, "jars"))


if __name__ == "__main__":
    main()
