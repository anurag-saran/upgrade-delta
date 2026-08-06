package com.example.payments;

import org.springframework.stereotype.Component;
import org.yaml.snakeyaml.TypeDescription;
import org.yaml.snakeyaml.Yaml;
import org.yaml.snakeyaml.constructor.Constructor;
import java.io.InputStream;
import java.util.Collection;
import java.util.Collections;
import java.util.Map;

/** Loads service config with snakeyaml. Uses Constructor(TypeDescription, Collection) —
 *  the exact constructor removed in 1.33 (CVE-2022-1471 hardening). Deliberate reachable
 *  call site so upgrade-delta's app-intersection flags a touched incompatible change. */
@Component
public class ConfigLoader {
    public Map<String, Object> load(InputStream in) {
        TypeDescription root = new TypeDescription(Map.class);
        Collection<TypeDescription> extras = Collections.emptyList();
        // Constructor(TypeDescription, Collection) — removed in snakeyaml 1.33
        Yaml yaml = new Yaml(new Constructor(root, extras));
        return yaml.load(in);
    }
}
