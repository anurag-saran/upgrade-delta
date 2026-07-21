package com.example.payments;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.core.JsonProcessingException;
import org.springframework.stereotype.Service;

/** Core service. Uses jackson-databind's ObjectMapper directly — this is the call
 *  site upgrade-delta's app-intersection measures against the Lightwell rebuild. */
@Service
public class PaymentService {
    private final ObjectMapper mapper = new ObjectMapper();
    private final Ledger ledger = new Ledger();

    public String process(PaymentRequest req) throws JsonProcessingException {
        if (req.getAmountCents() <= 0) {
            throw new IllegalArgumentException("amount must be positive");
        }
        ledger.post(req.getOrderId(), req.getAmountCents());
        // serialize a receipt via jackson — real ObjectMapper.writeValueAsString
        return mapper.writeValueAsString(new Receipt(req.getOrderId(), "PROCESSED",
                ledger.balance(req.getOrderId())));
    }

    public PaymentRequest parse(String json) throws JsonProcessingException {
        // real ObjectMapper.readValue — the deserialization path jackson CVEs target
        return mapper.readValue(json, PaymentRequest.class);
    }

    public static class Receipt {
        public String orderId; public String status; public long balanceCents;
        public Receipt() {}
        public Receipt(String o, String s, long b) { orderId=o; status=s; balanceCents=b; }
    }
}
