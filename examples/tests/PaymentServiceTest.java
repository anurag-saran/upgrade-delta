package com.example.payments;

import com.fasterxml.jackson.core.JsonProcessingException;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

public class PaymentServiceTest {
    @Test void processesValidPaymentAndSerializesReceipt() throws JsonProcessingException {
        String receipt = new PaymentService().process(new PaymentRequest("ORD-1", 2599, "USD"));
        assertTrue(receipt.contains("\"orderId\":\"ORD-1\""));
        assertTrue(receipt.contains("PROCESSED"));
    }
    @Test void rejectsNonPositiveAmount() {
        assertThrows(IllegalArgumentException.class,
            () -> new PaymentService().process(new PaymentRequest("ORD-2", 0, "USD")));
    }
    @Test void parsesJsonViaJackson() throws JsonProcessingException {
        PaymentRequest r = new PaymentService().parse(
            "{\"orderId\":\"ORD-3\",\"amountCents\":500,\"currency\":\"EUR\"}");
        assertEquals("ORD-3", r.getOrderId());
        assertEquals(500L, r.getAmountCents());
    }
}
