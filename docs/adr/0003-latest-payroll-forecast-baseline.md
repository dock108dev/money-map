# ADR 0003: latest payroll establishes the forecast baseline

**Status:** accepted

Historical reporting uses the latest 12 complete calendar months. Forecasting instead
uses the latest imported payroll statement, even if its payment month is incomplete.
This prevents a recent promotion or allocation change from being omitted from the
future baseline.

For the supplied evidence, the July 3, 2026 statement is therefore the forecast
baseline. No destination-level rates are inferred because its detail page is absent.
