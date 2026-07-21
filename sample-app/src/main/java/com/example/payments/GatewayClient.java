package com.example.payments;

import org.apache.http.client.methods.HttpGet;
import org.springframework.stereotype.Component;

/** Uses Apache HttpClient (a Lightwell-serviced dependency) — another real call site. */
@Component
public class GatewayClient {
    public String describe(String url) {
        // reference org.apache.http types so httpclient is a real, reachable dependency
        HttpGet get = new HttpGet(url);
        return get.getMethod() + " " + get.getURI();
    }
}
