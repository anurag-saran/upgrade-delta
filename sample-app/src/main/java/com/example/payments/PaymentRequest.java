package com.example.payments;

/** A payment request, (de)serialized with jackson-databind — the CVE-relevant leaf. */
public class PaymentRequest {
    private String orderId;
    private long amountCents;
    private String currency;

    public PaymentRequest() {}
    public PaymentRequest(String orderId, long amountCents, String currency) {
        this.orderId = orderId; this.amountCents = amountCents; this.currency = currency;
    }
    public String getOrderId() { return orderId; }
    public void setOrderId(String orderId) { this.orderId = orderId; }
    public long getAmountCents() { return amountCents; }
    public void setAmountCents(long amountCents) { this.amountCents = amountCents; }
    public String getCurrency() { return currency; }
    public void setCurrency(String currency) { this.currency = currency; }
}
