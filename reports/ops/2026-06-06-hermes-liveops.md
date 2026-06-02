
## 2026-06-06T14:49:39.453889+00:00Z: Compression Infinite Loop Fix

**Symptom:**
In both `default` and `producers` profiles, the agent entered an infinite compaction loop with `context compression started` happening constantly (up to 312 occurrences in 12,000 lines). The compressor was returning unchanged lengths (e.g. `276->276` or `143->143`), causing `conversation_loop` to immediately retry compression on the next turn. Concurrently, the proxy models were throwing 502/503 errors on custom CLIProxy endpoints causing cascades of retries and fallbacks. 

**Root Cause:**
The `_find_tail_cut_by_tokens` in `agent/context_compressor.py` calculated `cut_idx = max(fallback_cut, head_end + 1)` conditionally only if `cut_idx <= head_end`. But if the `tail_token_budget` was extremely large relative to a token-heavy but short conversation (e.g., full 1M context limit passed to a 200k threshold), the loop exhausted but left `cut_idx` at 0 (or lower than the total messages), consuming the entire message list. Because it was technically `> head_end`, it wasn't bounded by `fallback_cut`, so no messages were left in the compressible middle.

**Fix:**
Bounded `cut_idx` unconditionally at the end of the tail cut resolution:
```python
cut_idx = max(head_end + 1, min(cut_idx, fallback_cut))
```
This strictly enforces that the tail cut cannot swallow the entire session past the head, leaving at least 1 message to compress.

**Verification:**
`pytest tests/agent/test_context_compressor.py -q` now passes (91 passed, 0 failures), confirming that the bug (`TestTokenBudgetTailProtection.test_small_conversation_still_compresses`) is resolved. 
