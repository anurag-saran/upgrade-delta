package com.example.payments;
import org.junit.jupiter.api.Test;
import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import static org.junit.jupiter.api.Assertions.*;
public class ConfigLoaderTest {
    @Test public void loadsYamlMap() {
        byte[] yaml = "orderId: ORD-9\n".getBytes(StandardCharsets.UTF_8);
        Map<String, Object> m = new ConfigLoader().load(new ByteArrayInputStream(yaml));
        assertEquals("ORD-9", String.valueOf(m.get("orderId")));
    }
}
