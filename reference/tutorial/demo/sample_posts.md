# Sample Posts — Copy/Paste Ready
*All posts go in #incidents. Use these verbatim for consistent demo results.*

---

## Low Severity

```
#log noticed a minor UI glitch on the dashboard — the activity graph fails to render on first load but refreshes fine on page reload, not impacting any core functionality
```

```
#log SSL certificate for staging environment expires in 14 days — no immediate impact, renewal ticket should be filed
```

```
#log disk usage on logging server at 72% — not critical yet but worth monitoring, normal threshold is 85%
```

---

## Medium Severity

```
#log authentication service is throwing intermittent 401s on /api/login — about 1 in 20 requests failing, started roughly 30 minutes ago
```

```
#log elevated latency on the search endpoint — p99 response times up from 200ms to 1.4 seconds, users are noticing slowness, no errors yet
```

```
#log scheduled nightly backup job failed to complete — backup process timed out at 3:12 AM, last successful backup was 48 hours ago
```

```
#log memory usage on app server 02 is climbing steadily — sitting at 78% and hasn't dropped in 6 hours, likely a slow leak
```

---

## High Severity

```
#log payment processing is completely down — all transactions failing with 500 errors, no successful charges in the last 10 minutes, customers are reporting it on social
```

```
#log primary cache cluster is unreachable — all services falling back to database queries, load on the DB is 4x normal, response times degrading fast
```

```
#log user account creation is broken — new signups hitting an unhandled exception, error rate at 100% for the last 20 minutes, affecting all new user registrations
```

```
#log data pipeline has stalled — no records processed in the last 2 hours, downstream reports are stale, root cause unknown
```

---

## Critical Severity

```
#log CRITICAL — primary database cluster is unresponsive, read and write operations timing out across all services, automated failover has not triggered, full service outage in progress
```

```
#log CRITICAL — security alert, unauthorized access detected on admin console, IP 185.234.xx.xx made 47 requests to /admin/users in the last 5 minutes, account lockout has been triggered
```

```
#log CRITICAL — production deployment at 14:32 introduced a regression, checkout flow is throwing unhandled exceptions for all users, rollback has been initiated but not yet complete
```

---

## Thread Follow-Up Questions
*Use these as replies inside an incident thread*

```
what's the most likely cause based on what was reported?
```

```
is this something that would resolve on its own or does it need a manual fix?
```

```
has this entity had similar issues before?
```

```
what's the recommended next step?
```

```
how urgent is this compared to other open records?
```

```
who should be looped in on this?
```

```
what information would be helpful to gather right now?
```

---

## Sequence for Best Demo Results

For the entity history feature to shine, post these **in order** before asking a pattern question:

**Post 1** (Medium):
```
#log elevated error rate on /api/checkout — 5xx responses spiking to 8%, latency up 3x from baseline, started about 15 minutes ago
```

**Post 2** (Medium):
```
#log checkout service recovered but now seeing slow response times again — p95 latency at 2.1 seconds, up from a 300ms baseline, no errors yet
```

**Post 3** (High):
```
#log checkout is down again — full 503s on all /api/checkout requests, payment processor also unreachable, third time today
```

**Then reply in Post 3's thread:**
```
based on what's been logged today, is there a pattern here?
```

Claude will reference all three records and note the recurring checkout issues.
