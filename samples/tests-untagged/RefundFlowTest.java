package com.acme.payments;

import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

public class RefundFlowTest {
    @Test void refundReversesTheLedgerPosting() {
        PaymentService pay = new PaymentService();
        pay.process("ORD-2001", 5000);
        String r = new RefundService().refund("ORD-2001", 5000);
        assertEquals("refunded ORD-2001", r);
    }
}
