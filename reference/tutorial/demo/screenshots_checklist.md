# Screenshots Checklist

Take these during a test run before the actual showcase. Capture them in order — they tell a story.

---

## The Core Flow (must-have)

- [ ] **1. The trigger** — #incidents channel showing a #log message as posted by the engineer (before the bot replies)

- [ ] **2. The structured reply** — bot's thread reply expanded, showing:
  - Record ID (REC-XXXXXXXX)
  - Severity with emoji
  - Category
  - Entity
  - Summary paragraph
  - Tags
  - "Reply in this thread..." prompt

- [ ] **3. The conversation** — thread with a follow-up question + Claude's answer directly below it

---

## The Escalation (high impact)

- [ ] **4. #escalations channel** — showing the cross-post for a High or Critical record, with the orange or red emoji visible

- [ ] **5. Side-by-side** — #incidents and #escalations both visible, showing the same incident appeared in both (if your screen allows it)

---

## The Knowledge Base (the "aha" moment)

- [ ] **6. History question** — a thread reply asking about patterns + Claude's response that references prior records from the same entity

---

## Optional (nice to have)

- [ ] **7. Multiple records in #incidents** — the channel scrolled to show several #log messages and bot replies, demonstrating volume

- [ ] **8. SNS email** — if you configured an escalation email, a screenshot of the alert email in your inbox

- [ ] **9. AWS Console — DynamoDB** — table view showing structured records stored (good for technical audiences)

- [ ] **10. AWS Console — S3** — bucket showing the markdown files stored under `records/`

---

## Screenshot Tips

- Use Slack's desktop app for cleaner screenshots (not the browser)
- Expand the bot reply fully before capturing — collapse any unrelated threads
- If demoing live, use a second monitor so the audience sees Slack full-screen
- Dark mode or light mode — pick one and be consistent across all shots
- Crop out any personal info (workspace URL, real names if needed)

---

## Folder Organization

Save screenshots here:
```
demo/
  screenshots/
    01_trigger_message.png
    02_structured_reply.png
    03_thread_conversation.png
    04_escalations_channel.png
    05_side_by_side.png
    06_history_pattern.png
    07_multiple_records.png
    08_sns_email.png
    09_dynamodb_table.png
    10_s3_bucket.png
```
