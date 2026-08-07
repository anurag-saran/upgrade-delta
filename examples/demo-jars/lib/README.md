# Demo MiniRunner classpath

Runtime jars the fixture `payments-tests` MiniRunner needs so pass/fail is about
the upgrade under test, not `ClassNotFoundException` / missing transitive deps.

Included: snakeyaml, jackson-*, json-path (+ smart/accessors/asm), httpclient /
httpcore (+ codec/logging), spring-core / spring-jcl.

Wired into `demo.sh` and `upgrade-delta-run-tests` as
`examples/demo-jars/*.jar` + `examples/demo-jars/lib/*.jar`.
