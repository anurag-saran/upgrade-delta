package com.example.payments;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class LedgerTest {
    @Test void postingsAccumulate() {
        Ledger l = new Ledger();
        l.post("A", 1000); l.post("A", 250);
        assertEquals(1250L, l.balance("A"));
    }
    @Test void unknownOrderIsZero() {
        assertEquals(0L, new Ledger().balance("X"));
    }
}
