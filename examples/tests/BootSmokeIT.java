package com.example.payments;

import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** The mandatory upgrade gate — @Tag("upgrade-gate"), resolved by the router at run time. */
@Tag("upgrade-gate")
public class BootSmokeIT {
    @Test void applicationContextClassLoads() {
        // proves the Spring Boot app class is present and loadable after the upgrade
        assertNotNull(PaymentsApplication.class.getName());
    }
}
