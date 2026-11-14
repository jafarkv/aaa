# Supplier Data Hub

Standalone, PromoStandards-native catalog hub for the web4half brands. It owns supplier
connections, the normalized catalog, duplicate detection, sync schedules and (later) purchase
orders. OpenCart and BIA consume it; they never shape supplier data. Built by Engineering,
owned and operated by the Catalog team.

The full plan (architecture, data model, roadmap, Catalog and Marketing features) lives in the
"Supplier Data Hub — Master Plan" doc. This repo is built phase by phase; each phase has a gate.

## Status: Phase 0 (Foundations)

| Done | Item |
| --- | --- |
| Yes | Laravel app, `supplier_hub` schema migrations (suppliers, credentials, endpoints, mapping rules, raw payloads, sync runs, sync errors) |
| Yes | Credential vault: username and password encrypted at rest, hidden from array/JSON output, scrubbed from error messages |
| Yes | PromoStandards service registry (10 services) and read-only probe definitions |
| Yes | Endpoint directory importer (idempotent, manual endpoints survive re-import) |
| Yes | Connection tester: one safe probe per service, Product Data first to learn a sample product id, raw responses stored gzipped |
| Yes | Commands: `hub:directory:import`, `hub:supplier:add`, `hub:supplier:test` |
| No | Admin UI (Filament). Phase 0 is command-line only; screens arrive with Phase 1 |
| No | **Gate:** 3 real suppliers pass test calls on every readable service. Needs real credentials |

## Must be verified before first real supplier call

The build environment could not reach promostandards.org, so these were written from memory
and are covered only by fixture-based tests:

1. **Service versions, SOAP namespaces, request element names, probe methods and parameters**:
   `app/PromoStandards/Service.php`, `SoapEnvelope.php`. Compare with each supplier's WSDL.
2. **Directory URL and JSON shape**: `config/promostandards.php`, `DirectoryImporter::parseJson()`.
3. **MySQL 8**: migrations were tested on SQLite only. Run `php artisan migrate` on MySQL before relying on them.

Purchase Order, Order Status, Shipment, Invoice, Company Data and Remittance Advice are never
probed: the hub will not send a PO to test a connection, and the others need real document numbers.
So the Phase 0 gate reads "every readable service", and those six are verified on first real use.

## Setup

```bash
composer install
cp .env.example .env
php artisan key:generate      # generates the key that encrypts supplier credentials
# create the MySQL database `supplier_hub`, set DB_* in .env
php artisan migrate
php artisan test
```

**Back up APP_KEY.** Losing or changing it makes every saved supplier credential unreadable.

## Onboarding a supplier (Phase 0, command line)

```bash
php artisan hub:directory:import --file=directory.json --code=ACME   # endpoints from the directory export
php artisan hub:supplier:add "Acme Promo" --code=ACME --account=12345 # prompts for username, hidden password
php artisan hub:supplier:test acme-promo                             # safe read-only test per service
```

## Rules the code follows

- Suppliers are deactivated, never deleted.
- Supplier responses are stored raw before anything is normalized.
- Credentials never appear in logs, errors, raw payload records or request hashes.
- Nothing calls a supplier's Purchase Order service outside the ordering flow (Phase 6).
