# ChatGPT web API findings

How the ChatGPT web app's internal endpoints behave, gathered with the
discovery kit in [`discovery/`](../discovery/README.md). chatctl code should
only depend on behaviour recorded here with evidence.

These are undocumented internal APIs and can change without notice. Date
every observation.

Do not paste tokens, titles or full conversation IDs into this file. Use
placeholders such as `<conversation-id>`.

## How these findings were gathered

- Date:
- Browser and version:
- Probe report file (local, not committed):
- Method (probe, Network tab, or both):

## Questions

### 1. What endpoint supplies the sidebar/history conversation list?

Finding:

Evidence:

### 2. How does pagination work?

Finding:

Evidence:

### 3. Is there a practical maximum page size?

Finding:

Evidence:

### 4. What fields are returned for creation/update time?

Finding:

Evidence:

### 5. How are project conversations identified?

Finding:

Evidence:

### 6. Are project conversations excluded from the ordinary conversation listing, or merely annotated?

Finding:

Evidence:

### 7. What operation does the current UI use for Archive?

Finding:

Evidence:

### 8. What operation does it use for Unarchive?

Finding:

Evidence:

### 9. How is authentication performed?

Finding:

Evidence:

### 10. Does a session credential work cleanly from a local process?

Finding:

Evidence:

### 11. Are there CSRF/origin checks that make browser-context execution preferable?

Finding:

Evidence:

### 12. What happens under rate limiting?

Finding:

Evidence:

### 13. Does changing archive state immediately remove a conversation from the normal history endpoint?

Finding:

Evidence:

### 14. Is there any starred/pinned metadata worth supporting?

Finding:

Evidence:
