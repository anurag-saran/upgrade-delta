package com.acme.payments;

import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

public class LedgerTest {
    @Test void postingsAccumulatePerOrder() {
        Ledger l = new Ledger();
        l.post("ORD-4001", 1000);
        l.post("ORD-4001", 250);
        assertEquals(1250L, l.balance("ORD-4001"));
    }
    @Test void unknownOrderBalancesToZero() {
        assertEquals(0L, new Ledger().balance("ORD-NONE"));
    }
}
