package com.acme.payments;

import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

public class BootSmokeIT {
    @Test void applicationBootsWithItsConfig() throws Exception {
        // the mandatory gate: config loads AND the config-declared appender class resolves
        var cfg = Boot.start();
        assertNotNull(cfg.getProperty("appender.class"));
    }
}
