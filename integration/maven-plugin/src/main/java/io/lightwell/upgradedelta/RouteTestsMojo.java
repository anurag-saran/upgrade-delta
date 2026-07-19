package io.lightwell.upgradedelta;

import org.apache.maven.plugin.AbstractMojo;
import org.apache.maven.plugin.MojoFailureException;
import org.apache.maven.plugins.annotations.LifecyclePhase;
import org.apache.maven.plugins.annotations.Mojo;
import org.apache.maven.plugins.annotations.Parameter;
import org.junit.platform.engine.discovery.DiscoverySelectors;
import org.junit.platform.launcher.*;
import org.junit.platform.launcher.core.LauncherFactory;
import org.junit.platform.launcher.TagFilter;

import java.io.File;
import java.nio.file.*;
import java.util.*;

/**
 * SCAFFOLD of the production router. Behavior contract is defined by the Python
 * reference implementation (test_router.py) and its three schemas:
 * routing/v1 in, selection-report/v1 + deploy-gate/v1 out.
 *
 * What replaces the mock's shortcuts here:
 *  - mandatory-test resolution uses REAL JUnit Platform discovery (TagFilter),
 *    not a source-file regex;
 *  - HEAD sha and changed-classes-since-map come from JGit, not CLI args;
 *  - the includes file is handed to Surefire natively via
 *    {@code <includesFile>${project.build.directory}/upgrade-delta/surefire-includes.txt}.
 *
 * Fail-closed rules carried over verbatim: unknown test runs; stale/absent
 * coverage -> full suite; Partial/Full lanes never shrink; a declared obligation
 * resolving to zero tests throws MojoFailureException (build fails).
 */
@Mojo(name = "route-tests", defaultPhase = LifecyclePhase.PROCESS_TEST_CLASSES)
public class RouteTestsMojo extends AbstractMojo {

    @Parameter(property = "upgradeDelta.routingPayload", required = true)
    private File routingPayload;

    @Parameter(property = "upgradeDelta.coverageMap")
    private File coverageMap;

    @Parameter(property = "upgradeDelta.maxDriftCommits", defaultValue = "25")
    private int maxDriftCommits;

    @Parameter(defaultValue = "${project.build.testOutputDirectory}", readonly = true)
    private File testClassesDir;

    @Parameter(defaultValue = "${project.build.directory}/upgrade-delta", readonly = true)
    private File outDir;

    @Override
    public void execute() throws MojoFailureException {
        try {
            // 1) resolve mandatory obligations via genuine JUnit Platform discovery
            List<String> mandatory = discoverTagged("upgrade-gate");
            getLog().info("mandatory (upgrade-gate): " + mandatory);
            if (mandatory.isEmpty()) {
                throw new MojoFailureException(
                    "Declared obligation 'boot-test' (tag upgrade-gate) resolved to ZERO tests. "
                    + "The declaration is stale — refusing to emit a plan that silently omits the gate.");
            }
            // 2..4) payload parse, coverage join with staleness/widening, lane
            // enforcement, includes/report/gate emission — port of test_router.py.
            // (Omitted in scaffold; the Python file is the executable spec.)
            Files.createDirectories(outDir.toPath());
        } catch (MojoFailureException e) {
            throw e;
        } catch (Exception e) {
            throw new MojoFailureException("route-tests failed", e);
        }
    }

    private List<String> discoverTagged(String tag) {
        LauncherDiscoveryRequest req = LauncherDiscoveryRequestBuilder.request()
            .selectors(DiscoverySelectors.selectClasspathRoots(
                Set.of(testClassesDir.toPath())))
            .filters(TagFilter.includeTags(tag))
            .build();
        TestPlan plan = LauncherFactory.create().discover(req);
        List<String> out = new ArrayList<>();
        plan.getRoots().forEach(root -> plan.getDescendants(root).forEach(id ->
            id.getSource().ifPresent(s -> {
                String n = s.toString();
                if (n.contains("ClassSource")) out.add(n.replaceAll(".*className = '([^']+)'.*", "$1"));
            })));
        return out.stream().distinct().sorted().toList();
    }
}
