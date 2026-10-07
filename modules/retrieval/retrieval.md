# Retrieval Module

## 1. Features

* Implement hybrid retrieval: vector search + keyword search.
* Use PostgreSQL + pgvector.
* Use RRF (Reciprocal Rank Fusion) to merge results.
* Return relevant chunks and source metadata to the Chatting Interface.

## 2. Retrieval Pipeline

1. Run vector search and keyword search in parallel, retrieving Top 20 each.
2. Deduplicate by chunk ID and merge rankings using RRF (`k=60`).
3. Return the final Top 5–10 chunks.

## 3. Requirements

* Choose a keyword-search solution suitable for Chinese documents; verify available extensions before implementation.
* Reuse existing embedding models, database schema, and connection management.
* Use parameterized SQL.
* Return an empty result when no relevant chunks are found.
* Do not generate answers in this module，The Chatting Interface is responsible for generating the final answer.
