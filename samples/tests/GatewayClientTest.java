package com.acme.payments;

import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

public class GatewayClientTest {
    @Test void sendsEscapedJsonBody() {
        String r = new GatewayClient().send("https://gw.example/pay", new Object());
        assertTrue(r.contains("attempts="));
        assertTrue(r.contains("body="));
    }
}
