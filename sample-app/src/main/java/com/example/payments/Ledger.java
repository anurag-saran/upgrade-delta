package com.example.payments;

import java.util.LinkedHashMap;
import java.util.Map;

public class Ledger {
    private final Map<String, Long> balances = new LinkedHashMap<>();
    public void post(String orderId, long deltaCents) {
        balances.merge(orderId, deltaCents, Long::sum);
    }
    public long balance(String orderId) { return balances.getOrDefault(orderId, 0L); }
}
