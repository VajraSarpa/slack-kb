# Slack KB — Demo Script
**Duration:** ~10 minutes  
**Participants:** You (presenter) + friend (second Slack user)  
**Channels needed:** #incidents, #escalations

---

## Before You Start

- Both of you are in #incidents and #escalations
- Have this doc open on a second screen — copy/paste from it
- Open #incidents and #escalations side by side if possible
- Remind your audience: there's a ~5 second delay while Claude processes

---

## Demo Flow

### Scene 1 — Basic Log + Structured Reply (Medium severity)
*Goal: Show that a casual Slack message becomes a structured record*

**You post in #incidents:**
```
#log authentication service is throwing intermittent 401s on /api/login — about 1 in 20 requests failing, started roughly 30 minutes ago
```

**Wait for the bot reply. Point out:**
- Record ID (REC-XXXXXXXX)
- Severity and Category inferred by Claude
- Tags extracted automatically
- "Reply in this thread to ask Claude about this record"

---

### Scene 2 — Thread Follow-Up (Conversational Q&A)
*Goal: Show the knowledge base layer — Claude answers questions in context*

**You reply in that same thread:**
```
what's the most likely cause based on what was reported?
```

**Wait for Claude's response. Point out:**
- Claude is answering from the record context, not making things up
- This works for anyone on the team — your friend can try it too

**Friend replies in the same thread:**
```
is this something that would resolve on its own or does it need a manual fix?
```

---

### Scene 3 — High Severity + Escalation
*Goal: Show the escalation routing*

**Friend posts in #incidents:**
```
#log payment processing is completely down — all transactions failing with 500 errors, no successful charges in the last 10 minutes, customers are reporting it on social
```

**Switch to #escalations and point out:**
- The bot automatically cross-posted there
- High/Critical severity triggers this without anyone doing anything

**Back in #incidents thread, you reply:**
```
has ENTITY-POC-001 had payment issues before?
```

*(Claude will answer — since this is the first run it'll say no prior history, which is expected)*

---

### Scene 4 — Critical Severity + SNS (if email configured)
*Goal: Show the full escalation chain*

**You post in #incidents:**
```
#log CRITICAL — primary database cluster is unresponsive, read and write operations timing out across all services, automated failover has not triggered, full service outage in progress
```

**Point out:**
- Red circle emoji, Critical severity
- Immediate post to #escalations
- If SNS email is configured: check inbox — an alert email should arrive within ~30 seconds

---

### Scene 5 — Entity History (Back Story)
*Goal: Show that records build up over time and Claude surfaces patterns*

*This works best after Scenes 1–4 have run, since there are now multiple records for ENTITY-POC-001*

**You post in #incidents:**
```
#log elevated error rate on /api/checkout — 5xx responses spiking to 8%, latency up 3x from baseline, started about 15 minutes ago
```

**Reply in the thread:**
```
based on what's been logged today, is there a pattern here?
```

**Point out:**
- Claude pulls the entity's prior records from DynamoDB
- The answer will reference earlier incidents from the same session
- This is the knowledge base feature — institutional memory that persists

---

## Talking Points

**"Why Slack?"**
The team is already there. No new tool, no context switch. An engineer on the floor just types what they see — the system handles the rest.

**"What does Claude actually do?"**
Two things: it structures the raw message (severity, category, tags, clean description) and it answers follow-up questions grounded in the record. It doesn't guess — if the information isn't in the record, it says so.

**"Where does the data go?"**
Full markdown notes in S3, structured metadata in DynamoDB. Fully queryable, fully auditable.

**"What's Phase 2?"**
QR codes on physical assets — scan a code, Slack opens pre-populated with the asset context. The engineer just adds what they observed and hits send.

---

## Screenshots to Capture

Take these during the demo or a test run beforehand:

- [ ] #incidents channel showing the #log message + bot thread reply
- [ ] Bot reply expanded — showing Record ID, Severity, Category, Tags, Summary
- [ ] Thread with a follow-up question + Claude's answer
- [ ] #escalations channel showing the High/Critical cross-post
- [ ] SNS email alert (if configured)
- [ ] Scene 5 thread showing Claude referencing prior records

---

## If Something Goes Wrong Live

| Problem | Recovery |
|---|---|
| Bot doesn't reply after 15s | Say "give it a moment — Lambda cold start on first use" — try again |
| Wrong severity inferred | That's actually a good demo moment — "the prompt is tunable, this is a POC" |
| Thread reply not working | Check that you're replying in the thread, not posting a new message |
| Escalation didn't post to #escalations | Confirm bot is invited to that channel |
