package com.example.payments;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class GatewayClientTest {
    @Test void buildsGetRequest() {
        String d = new GatewayClient().describe("https://gw.example/pay");
        assertTrue(d.startsWith("GET"));
        assertTrue(d.contains("gw.example"));
    }
}
