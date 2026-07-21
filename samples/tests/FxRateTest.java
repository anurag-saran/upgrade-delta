package com.acme.payments;

import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

public class FxRateTest {
    @Test void sameCurrencyIsIdentity() {
        assertEquals(500L, new FxRates().convert(500, "USD", "USD"));
    }
    @Test void crossCurrencyAppliesRate() {
        assertEquals(540L, new FxRates().convert(500, "EUR", "USD"));
    }
}
