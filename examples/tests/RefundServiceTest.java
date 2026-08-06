package com.example.payments;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

public class RefundServiceTest {
    @Test void refundReturnsConfirmation() {
        assertEquals("refunded ORD-9", new RefundService().refund("ORD-9", 100));
    }
}
