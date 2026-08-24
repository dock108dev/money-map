from fastapi import APIRouter
from fastapi.routing import APIRoute

from paycheck_map import services
from paycheck_map.api import router as core_router
from paycheck_map.api_life_plan import router as life_plan_router
from paycheck_map.api_plaid import router as plaid_router
from paycheck_map.api_v2 import router as v2_router
from paycheck_map.service_accounts import account_detail, accounts_dashboard
from paycheck_map.service_overview import overview
from paycheck_map.service_payroll import payroll_history
from paycheck_map.service_summaries import fidelity_summary
from paycheck_map.service_wealth import wealth_dashboard


def _operations(router: APIRouter) -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in router.routes
        if isinstance(route, APIRoute)
        for method in route.methods or set()
    }


def test_domain_router_operations_are_disjoint() -> None:
    groups = [
        _operations(core_router),
        _operations(v2_router),
        _operations(life_plan_router),
        _operations(plaid_router),
    ]
    assert all(path.startswith("/api/") for group in groups for _, path in group)
    assert all(
        left.isdisjoint(right) for index, left in enumerate(groups) for right in groups[index + 1 :]
    )


def test_service_facade_preserves_current_public_callers() -> None:
    assert services.account_detail is account_detail
    assert services.accounts_dashboard is accounts_dashboard
    assert services.overview is overview
    assert services.payroll_history is payroll_history
    assert services.fidelity_summary is fidelity_summary
    assert services.wealth_dashboard is wealth_dashboard
