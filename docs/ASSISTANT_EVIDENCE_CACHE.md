# Assistant evidence cache (P1)

The existing SQLite raw cache remains the authoritative source. The chat can reuse a validated point-lookup projection in the same session for at most 90 seconds, capped at 16 entries. No final LLM answer, question, private PDF, credential, GME observation or user upload is stored in this layer.

Eligible: Eurostat national monthly balance with its ARERA companion, standalone ARERA CMEM,m, ACER LNG and explicit-day ENTSOG SRG lookups. Each group uses exact raw cache keys and a SHA-256 content fingerprint, source TTL, acquisition timestamp, period and local civil/gas-day boundaries. Same-timestamp revisions invalidate the affected group; failed or review-marked manual refreshes disable reuse. Stale, partial, missing, quality-review or mismatched evidence is not cached. Nested price/ACER evidence must also pass the checks. The original acquisition timestamp is preserved.

The first cold acquisition can change raw dependencies; in that case no projection is cached until a subsequent stable read. Mixed-source requests recheck reused evidence after the remaining acquisitions and fall back to the normal path if invalidated. No network request is introduced by the cache itself; a rare invalidation during a mixed request can cause a normal acquisition to repeat. The layer does not change underlying provider TTLs, access policy, or how failed refreshes in other sessions are reported.

Excluded for now: latest SRG multi-window series, authenticated GIE/Terna, weather-derived evidence, network/map, historical query engine, full briefings, selected bundles and non-Italian scopes. These use their existing loaders/caches. No token reduction is guaranteed: synthesis still receives the required evidence, and no model answer is reused. Gains are avoidance of duplicate projection/validation work and possible latency reductions, not a measured live speedup or a replacement for raw caching.

Tests use local synthetic fixtures. Live latency, actual hit rate and model token savings remain unmeasured.
