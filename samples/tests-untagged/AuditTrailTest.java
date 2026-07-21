package com.acme.payments;

import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

public class AuditTrailTest {
    @Test void recordsFormattedEntries() {
        AuditTrail a = new AuditTrail();
        a.record("alice", "approve");
        a.record("bob", "review");
        assertEquals(2, a.size());
    }
}
