package com.acme.payments;

import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

public class CheckoutIT {
    @Test void endToEndCheckout() {
        String receipt = new PaymentService().process("ORD-3001", 199_99);
        String gw = new GatewayClient().send("https://gw.example/capture", receipt);
        assertTrue(gw.startsWith("GET "));
    }
}
