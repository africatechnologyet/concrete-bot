# CoBuilt Integration — Database and Runtime Findings

This supplement records additional facts verified from the current GitHub main-branch source. It does not establish the live Render configuration.

## Database engine finding

The two repository deployment configurations currently describe different database arrangements:

- Concrete Logistics source requires `DATABASE_URL` and uses psycopg2, indicating PostgreSQL-compatible deployment.
- Cement Stock's committed `render.yaml` sets `DATABASE_URL=sqlite+aiosqlite:///data/cement_stock.db` and mounts a persistent disk at `/data`.

Therefore, the checked-in configuration does **not** currently describe two bots using the same PostgreSQL database. A future single-PostgreSQL design requires a controlled SQLite-to-PostgreSQL migration for Cement Stock, unless the live Render service has since been configured differently.

The checked-in `render.yaml` is not proof of the currently deployed Render environment. Verify the actual service configuration read-only before selecting the migration path.

## Runtime finding

- Concrete Logistics uses python-telegram-bot 21.9 and its synchronous `Application.run_polling()` lifecycle.
- Cement Stock uses Aiogram 3.13.1 and an asyncio `Dispatcher.start_polling()` lifecycle.
- These should not be combined by calling both polling methods on one event loop/thread.
- The safest initial consolidation design is two supervised child processes within one Render worker, each retaining its own framework lifecycle and bot token. The supervisor must terminate the sibling process if either bot exits unexpectedly and must forward SIGTERM/SIGINT cleanly.
- Test this supervisor in a development worker before any production cutover.

## Identity mapping requirement

Concrete Logistics trip rows store the Telegram user ID in `trips.user_id`. Cement Stock consumption rows require a foreign key to `users.id` (the Cement Stock internal user ID).

The integration must resolve the Cement Stock operator by Telegram ID, not assume the two internal database IDs match. The design must also explicitly handle a Concrete Logistics user who is not registered in Cement Stock. Do not silently attach consumption to an unrelated user or bypass the foreign key.

A dedicated integration service user is one possible approach, but it must be visible, auditable, and approved. Alternatively, the Cement Stock schema can be changed in a reviewed migration to support a nullable/system-origin operator reference. Decide only after reviewing the business audit requirements.

## Cement factor policy

No authoritative cement factors are present in the source code. The Cement Stock operator's manual workflow lets the operator enter kg/m³ for each manual consumption, but that is not an approved grade-factor schedule for automated trips.

Automated trip deduction must use a business-approved grade-to-kg/m³ factor table. Do not reuse example figures or infer factors. A missing factor should not silently result in zero consumption or an invented deduction. During development, test a pending/blocked deduction state and surface it clearly to administrators without losing the concrete trip.

## Recommended transaction contract

For a concrete trip with a configured factor:

1. Validate the grade factor and calculate `quantity_kg = volume_m3 * factor_kg_per_m3`.
2. Begin one PostgreSQL transaction.
3. Insert the concrete trip in its dedicated schema and retain the returned trip ID.
4. Atomically reserve/decrement the Cement Stock balance only if sufficient stock remains.
5. Insert one Cement Stock consumption ledger row with `source_system='concrete_logistics'`, `source_trip_id=<trip id>`, grade, volume, factor, quantity, stock_after, and the approved operator/service identity.
6. Commit both applications' records together.
7. Send the Cement Stock notification after commit. Notification failure must not reverse a committed stock deduction; log and retry separately.

If stock is insufficient, roll back both writes and present a clear failure to the concrete trip flow, or use an explicitly approved pending-trip workflow. Never save a trip as fully consumed when no stock deduction occurred.

## Production remains untouched

All findings and proposed migrations are development-only. No live Render service, Telegram webhook, token, or database has been changed.