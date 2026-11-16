# CoBuilt Integrated Telegram System — Development Audit

Status: development-only audit. No production services or databases are modified by this document.

## Selected architecture

- Keep the existing Concrete Logistics Telegram bot and its original token/interface.
- Keep the existing Cement Stock Telegram bot and its original token/interface.
- Run both bot runtimes under one supervised Render worker after integration tests pass.
- Use one PostgreSQL database, keeping the applications' tables isolated.
- Do not deploy or cut over production until a verified backup, migration plan, and rollback procedure exist.

## Concrete Logistics source facts inspected

- Main entry point: `concrete_logistics_bot.py`.
- Telegram framework: `python-telegram-bot==21.9`.
- Database driver: `psycopg2`; connection pool is `ThreadedConnectionPool`.
- Required environment variables currently include `BOT_TOKEN` and `DATABASE_URL`.
- Existing tables created by `init_db()`: `users`, `jobs`, `trucks`, `trips`.
- Trip persistence is currently performed by `save_trip(uid, job, grade, plate, vol)`.
- Current trip save inserts the trip and commits through the generic `db()` helper.
- The current report deletion callback permanently deletes trips through `delete_trips()`.
- Current startup uses `drop_pending_updates=True` in webhook and polling paths. This must not be carried into the integrated production startup because it can discard queued updates.

## Integration constraints

1. Do not reuse the Cement Stock table names for Concrete Logistics.
2. Prefer placing Concrete Logistics tables in a dedicated PostgreSQL schema (for example, `concrete`) while retaining Cement Stock's existing public-schema tables. Verify PostgreSQL permissions and migration behavior in an isolated test database before adopting this.
3. The trip row and its automatic cement-consumption ledger row, plus the stock balance update, must commit atomically in one database transaction.
4. Add a unique source reference to the Cement Stock consumption ledger (for example, source system + concrete trip ID) and enforce uniqueness in PostgreSQL. Application-level duplicate checks alone are insufficient.
5. Store the cement factor and calculated quantity on the trip/consumption record at trip creation time. Later factor changes must not rewrite historical deductions.
6. Do not invent cement factors. They must be supplied/approved by the business and stored as effective-dated configuration or an explicit grade-factor table.
7. Manual consumption must warn about possible overlap with a Concrete Logistics trip; exact duplicate prevention must rely on source references, not fuzzy project-name matching.
8. Insufficient-stock behavior must be explicit. The integrated transaction must not silently create negative stock or save an unpaired trip.
9. Keep the existing bot tokens, role systems, commands, and user-facing flows.
10. Use a supervisor that starts both bot runtimes and shuts both down if either fails. Verify framework compatibility and polling lifecycle in tests before using this design.

## Risks found for follow-up

- The generic Concrete Logistics `db()` helper commits each call independently. Cross-application trip + stock updates cannot safely be implemented as separate helper calls; a transaction-scoped connection API is required.
- The current trip-save function has no idempotency key for Telegram retries or duplicate submissions.
- Permanent trip deletion would orphan linked cement deductions. Introduce soft-delete/void semantics and a compensating stock-ledger entry; do not physically delete integrated trips.
- The current startup discards pending Telegram updates. Preserve pending updates and document polling handover.
- Concrete Logistics and Cement Stock both define a `users` table. Schema isolation avoids collisions without renaming historical Cement Stock tables.
- Cement Stock currently uses SQLAlchemy async sessions and supports SQLite/PostgreSQL URLs. Production database type and current Render environment must be verified before migration.
- Cement Stock's current manual consumption path reads stock, then updates stock in separate operations. The integrated path must use a row lock or atomic conditional update and a single transaction.

## Development-only validation checklist

- [ ] Obtain a sanitized inventory of current Render service types and environment-variable names (never token/password values).
- [ ] Verify the production database engine and schema using read-only inspection; do not connect development code to production.
- [ ] Create isolated test databases from user-authorized backups/copies.
- [ ] Add migration scripts that are repeatable and refuse to run against production unless explicitly configured.
- [ ] Test rollback and compare row counts, IDs, totals, stock balance, and ledger sums.
- [ ] Test concurrent trip submissions, retries, insufficient stock, and manual consumption.
- [ ] Test both bots' existing commands and permissions unchanged.
- [ ] Test date-range reports and Excel export.
- [ ] Test restart/shutdown behavior without dropping Telegram updates.

## Production protection

This branch is a development workspace only. Do not change production Render services, production databases, tokens, or webhooks as part of the audit or development work.