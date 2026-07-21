package com.example.payments;

import org.springframework.stereotype.Service;

@Service
public class RefundService {
    private final Ledger ledger = new Ledger();
    public String refund(String orderId, long amountCents) {
        ledger.post(orderId, -amountCents);
        return "refunded " + orderId;
    }
}
