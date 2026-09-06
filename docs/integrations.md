# Integrations and network work

Manual file import is permanent and needs no provider account. Its supported formats and templates
live in [Data sources](data-source-strategy.md). This guide describes the implemented connector,
not current provider eligibility or pricing.

## Plaid boundary

[`plaid_client.py`](../src/paycheck_map/plaid_client.py) implements sandbox and production HTTP
clients. The ordinary UI offers production setup. The SoFi connection target requests Transactions,
including a request for 730 days of history; the Fidelity target requests Investments. Actual data
availability is provider-dependent. Balance, transaction, holding, item-status, Link and item-removal
calls are supported; payment, trading, Auth and Identity products are not requested.

[`api_plaid.py`](../src/paycheck_map/api_plaid.py) routes configuration, Link, exchange, update and
removal. Native macOS prompts collect client credentials outside React. Keychain stores credentials,
client identity and per-connection access tokens. Link's temporary public token crosses the browser
API during exchange; it is distinct from the long-lived access token. Do not substitute `.env`
secrets or a browser credential form for this boundary.

[`plaid_service.py`](../src/paycheck_map/plaid_service.py) owns provider workflow and transactional
persistence; [`plaid_records.py`](../src/paycheck_map/plaid_records.py) parses and classifies records.
Sync keeps endpoint response hashes and normalized evidence, not raw HTTP response bodies. A failed
normalization rolls back that connection's financial writes; sync status can still record failure.
Disconnect attempts remote item removal and local secret/data removal through this service.

The React application loads Plaid Link from its CDN when a connection is opened. Once configured,
provider traffic also occurs during enabled automatic refresh. The canonical automatic/manual
attempt policy is in [Operations](operations.md); closing a tab is not cancellation of an in-flight
backend operation. Tests use injected clients and secret stores, not owner credentials.

## Unsupported and unverified integration paths

There is no direct Fidelity, SoFi or Akoya connector, webhook receiver, external job queue, or
cloud synchronization service. There is no enforcement of a provider billing ceiling. Provider
account approval, prices, quotas, exact institution/account-type coverage and real consent flows
cannot be established from this repository. Before enabling real connections, validate those with
the actual provider account under a separately authorized workflow. Source tests establish local
normalization and failure handling only.

## Public calculation inputs

The runtime reads the checked-in income benchmark artifact. It does not fetch IRS/BLS data while
projecting. [`scripts/build_income_benchmarks.py`](../scripts/build_income_benchmarks.py) is an
explicit network-using regeneration tool, not a scheduled job. Its output changes reviewed
calculation inputs and requires validation. Contribution limits are also checked-in inputs; see
[Configuration](configuration.md). External reference links open only when selected.
