package com.acme.payments;

import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

public class ContractRoundTripIT {
    @Test void requestSurvivesARoundTrip() {
        Dtos.PaymentRequest p = Dtos.parse("ORD-6001", 125);
        Dtos.PaymentRequest q = new Dtos.PaymentRequest(p.orderId(), p.amountCents(), p.currency());
        assertEquals(p, q);
    }
}
