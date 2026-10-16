# PagamentoConforme

SaaS B2B for organising subcontractor invoices and compliance documents, assisting human review, and preparing SEPA payment files for companies in Portugal.

## Status

Initial repository setup. The first delivery focuses on a secure, testable MVP foundation. Production integrations and deployment must only be marked complete after credentials, external configuration, and end-to-end tests are verified.

## Intended stack

- Python / FastAPI
- PostgreSQL (Supabase-compatible)
- Private file storage
- Server-rendered responsive interface
- Stripe subscriptions (test mode first)
- Document parsing and validation with human review
- ISO 20022 SEPA XML export, validated against a configured profile

## Guardrails

- No automated bank transfers
- No credentials or secrets committed to source control
- No claim of official AT / Social Security verification without an authorized integration
- Separate data access by company
- Human approval for consequential payment decisions

See `docs/architecture.md`, `docs/security.md` and `.env.example` as implementation develops.
