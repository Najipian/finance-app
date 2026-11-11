# 4. Transaction deduplication and pending transactions

Date: 2026-11-11 · Status: Accepted

## Context

BR-06: transactions sync automatically and never appear twice, and a pending
transaction that later books updates in place. The design proposed a unique
`(account_id, dedup_key)` with `dedup_key` = provider ID, else a SHA-256 of account,
date, amount and description, upserted with `ON CONFLICT DO UPDATE`.

Two real-world cases break that alone:

1. **Pending transactions often get a new ID when they book** (common in UK Open
   Banking). The booked row is inserted under a new key and the pending row stays:
   the transaction now appears twice.
2. **Identical transactions without an ID** (two £3.20 coffees from the same shop on
   one day) hash to the same key, so the second silently replaces the first.

The design also listed a `raw_json` column for raw provider payloads.

## Decision

- Keep the unique key and upsert. A pending → booked change under the same ID updates
  in place.
- **Pending cleanup:** after upserting an account's transactions for the sync window,
  delete *pending* rows in that window whose keys the bank no longer returns. They
  have either booked under a new ID (and the booked row is now present) or been
  dropped by the bank. Booked rows are never deleted this way.
- **Occurrence number** in the fallback key: the n-th identical transaction in a
  response gets `…|n`. Banks return transactions in a stable order, so each keeps its
  key across syncs.
- Sync window: from `last_synced_at` minus 3 days (first sync: 12 months), so late
  postings are caught and the cleanup only ever looks at recent data.
- **No `raw_json`**: raw bank payloads contain personal data the features don't need
  (NFR-05). The mapped columns are enough.

## Consequences

- No duplicates in either case; both are covered by integration tests on Postgres
  (`test_pending_that_books_under_a_new_id_is_not_duplicated_br06`,
  `test_identical_transactions_without_ids_are_both_kept_br06`).
- A pending transaction that books under a new ID gets a new row ID. Week 4's manual
  category changes on pending transactions would be lost when they book; mitigate
  then by carrying the category over when a matching booked row appears (same
  account, amount, description).
- Without `raw_json`, new fields need a re-sync to backfill. Acceptable for a demo
  dataset.
