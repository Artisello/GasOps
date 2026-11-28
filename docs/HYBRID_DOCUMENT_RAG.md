# Hybrid document RAG (P1)

Conversational PDF lookup and document QA now use two local candidate channels: existing TF-IDF over the original question and, when a controlled technical concept is recognized, TF-IDF over its aliases. No new index, embedding model, external vector service or generated query. The 14 concept groups are bilingual retrieval hints only, never evidence.

Each channel returns at most 24 chunk candidates. Rank by original token coverage, matched concepts, literal phrase, document-title tie-break and reciprocal local rank. Compare scores based on actual text across public and personal indexes, then deduplicate by digest-bearing document title and PDF page; retain alternative revisions. Explicit article/chapter/section and page references constrain candidates. No claim is made that every reference style or every occurrence can be retrieved. Exact search and manual keyword search retain their behavior.

The document QA model receives at most six original excerpts (maximum 1,200 characters per excerpt and 6,000 total), with anonymous D IDs. Exact quote validation and original PDF citation mapping remain intact. Distinguish editions in the prompt. No claim of current legal validity or proof of semantic entailment is made by quote validation alone.

Private/uploaded archives and indexes stay session-local; chat never sends their excerpts or PDF questions to a remote model. Existing explicit consent and quota checks in document QA remain in force. No new API or LLM calls, no new menu or dependencies.

Synthetic PDF regression tests cover synonyms, literal references, page and document isolation, irrelevant requests, duplicate copies versus revisions and context budgets. Real-document relevance, recall and latency require an evaluation corpus; this is a deterministic lexical/concept hybrid, not dense embedding retrieval.
