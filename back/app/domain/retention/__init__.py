"""Bounded retention for high-growth, append-only tables that have no natural
cap of their own (idempotency replays, webhook replay guards, deduplicated
system logs, replayable job event streams).

Deliberately excludes `AuditLog` and `CreditLedgerEntry` — those are the
durable compliance/financial record and are kept indefinitely; see
`zaolang-compliance-audit` and `zaolang-credits-billing`.
"""
