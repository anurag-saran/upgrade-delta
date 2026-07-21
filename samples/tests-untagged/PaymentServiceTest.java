package com.acme.payments;

import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

public class PaymentServiceTest {
    @Test void processesAValidOrder() {
        String r = new PaymentService().process("ORD-1001", 2599);
        assertTrue(r.startsWith("done"));
    }
    @Test void rejectsNonPositiveAmounts() {
        assertThrows(IllegalArgumentException.class,
            () -> new PaymentService().process("ORD-1002", 0));
    }
}
