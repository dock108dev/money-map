# Financial-data API roadmap

Research date: 2026-07-25. Manual imports remain the source-of-truth fallback.

## Fidelity Access

[Fidelity Access](https://www.fidelity.com/security/fidelity-access-data-security) is a
consumer-authorized secure connection used by integrated third-party applications and
their aggregators; consumers do not give those services their Fidelity password.
Fidelity’s public consumer material does not present it as a self-service API for a
single-user local application and does not publish direct developer pricing or an open
approval path. The practical route is an approved aggregator or data-recipient
relationship, not direct retail credentials.

Decision: do not store Fidelity credentials or build a direct Fidelity connector.
The implemented optional path uses Plaid Link and Investments, while keeping manual
PDF/CSV/XLSX imports. Production use still depends on Plaid plan approval and the exact
Fidelity account types available to this Plaid application.

## SoFi retail-member access

No public official SoFi retail-member account-data developer API, production approval
path, or pricing page was found during this review. That absence is a research finding,
not proof that private partner APIs do not exist.

Decision: do not claim or emulate a direct SoFi API. The implemented optional path uses
Plaid Transactions and current balances; manual checking/savings exports remain
supported.

## Plaid

[Transactions](https://plaid.com/docs/transactions/) supports up to 24 months of
depository transaction history. [Investments](https://plaid.com/docs/investments/)
supports holdings and up to 24 months of investment transactions. Its documentation
states that Fidelity access has plan- and approval-specific restrictions. Plaid’s
[Statements](https://plaid.com/docs/statements/) retrieves bank-branded depository PDFs
but supports a limited institution set and is not an investment-statement product.

Plaid offers synthetic Sandbox testing. Its
[billing documentation](https://plaid.com/docs/account/billing/) distinguishes Trial
production items from paid use. The current Plaid material describes Trial as free for
up to 10 live Items, while product availability and institution access can still be
plan- or approval-specific. Exact paid pricing requires a production request or sales
contact. Financial data passes through Plaid, so the interface makes that transit
explicit before connection.

Decision: expose only the Production/Trial connector in the normal UI because Sandbox
contains synthetic data. The supplied screenshot revealed the Client ID but masked the
Sandbox secret and showed no Production secret, so real connections remain unavailable
until Plaid Trial is activated and its Production secret is saved. Fidelity coverage
can still require plan-specific institution access.

## Akoya

Akoya documents a free synthetic
[sandbox](https://docs.akoya.com/guides/sandbox-overview) with a mock provider.
[Production access](https://docs.akoya.com/guides/guide-for-production-access) requires
an onboarding questionnaire, security/risk review, and legal agreement. Akoya’s
[pricing page](https://akoya.com/pricing) describes a Standard tier below 10,000 monthly
connections and possible setup fees, but does not publish a simple free-real-account
offer.

Decision: it is technically credible for consumer-permissioned API data, but materially
heavier than this solo local use case. Revisit only if manual exports become
unacceptable and exact SoFi/Fidelity provider coverage is confirmed.

## Implemented connector contract

The connector:

- be opt-in and never replace manual import;
- store no provider username or password;
- record provider Item IDs only in the private database and persist
  account/transaction identifiers as Item-namespaced hashes;
- retain raw-response hashes, retrieval time, consent state, and parser version;
- normalize through the existing transaction/evidence contracts;
- support revocation, deletion, retry idempotency, and a documented cost ceiling;
- never enable transfers, trading, or payroll changes.

Production readiness additionally requires a granted Production/Trial secret, a
successful real SoFi authorization, a successful real Fidelity authorization for the
intended account types, and a review of the then-current Plaid product eligibility and
billing terms.
