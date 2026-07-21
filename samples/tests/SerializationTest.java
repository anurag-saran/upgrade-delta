package com.acme.payments;

import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

public class SerializationTest {
    @Test void parseFillsDefaults() {
        Dtos.PaymentRequest p = Dtos.parse("ORD-5001", 750);
        assertEquals("USD", p.currency());
        assertEquals(750L, p.amountCents());
    }
}
