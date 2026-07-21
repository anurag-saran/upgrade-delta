package com.acme.payments;

import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

public class MetricsTest {
    @Test void counterIncrements() {
        Metrics m = new Metrics();
        m.increment();
        assertEquals(2L, m.increment());
    }
}
