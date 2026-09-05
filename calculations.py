"""Financial Engineering capital budgeting and DCF engine.

Implements standard corporate finance techniques:
  - Operating cash flows (OCF)
  - Net cash flows
  - Discount factors & present values
  - NPV
  - IRR
  - MIRR
  - Payback period
  - Profitability index (PI)
  - ROI
  - DCF valuation with terminal value
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

CURRENCY_TOLERANCE = 1e-9


# ---------------------------------------------------------------------------
# Core decision helpers
# ---------------------------------------------------------------------------

def decision_for_npv(npv: float, label: str = "NPV") -> dict[str, str]:
    if npv > 0:
        return {
            "status": "ACCEPT",
            "label": label,
            "reason": (
                f"The {label} is positive (${npv:,.2f}), meaning the present value of the "
                "project's expected future cash flows exceeds the initial investment. "
                "The project is expected to create value at the specified discount rate and "
                "is financially favourable under the current assumptions."
            ),
        }
    if abs(npv) <= CURRENCY_TOLERANCE:
        return {
            "status": "REVIEW",
            "label": label,
            "reason": (
                f"The {label} is approximately zero (${npv:,.2f}). The project is roughly "
                "value-neutral, producing a return essentially equal to the required return. "
                "The decision may depend on strategic, non-financial factors."
            ),
        }
    return {
        "status": "REJECT",
        "label": label,
        "reason": (
            f"The {label} is negative (${npv:,.2f}). The present value of expected future "
            "cash flows is lower than the initial investment. The project destroys value at "
            "the specified discount rate and is not financially favourable under the current "
            "assumptions."
        ),
    }


def decision_for_irr(irr: float | None, discount_rate: float) -> dict[str, str]:
    if irr is None or (isinstance(irr, complex) and irr.imag != 0) or not np.isfinite(irr):
        return {
            "status": "REVIEW",
            "label": "IRR",
            "reason": (
                "The IRR could not be computed uniquely for this cash-flow stream "
                "(multiple sign changes or non-convergent results). Use NPV as the primary "
                "decision metric."
            ),
        }
    irr_real = float(np.real(irr))
    if irr_real > discount_rate:
        return {
            "status": "ACCEPT",
            "label": "IRR",
            "reason": (
                f"IRR ({irr_real:.2f}%) exceeds the required return / WACC ({discount_rate:.2f}%). "
                "The project is expected to generate a return above the cost of capital, "
                "compensating investors for the risk taken and creating surplus value."
            ),
        }
    return {
        "status": "REJECT",
        "label": "IRR",
        "reason": (
            f"IRR ({irr_real:.2f}%) is below the required return / WACC ({discount_rate:.2f}%). "
            "The project is not expected to generate a return sufficient to compensate for "
            "its required rate of return and would fail to earn its cost of capital."
        ),
    }


def decision_for_mirr(mirr: float | None, discount_rate: float) -> dict[str, str]:
    if mirr is None or not np.isfinite(mirr):
        return {
            "status": "REVIEW",
            "label": "MIRR",
            "reason": "MIRR could not be computed. Treat MIRR with caution and rely on NPV.",
        }
    if mirr > discount_rate:
        return {
            "status": "ACCEPT",
            "label": "MIRR",
            "reason": (
                f"MIRR ({mirr:.2f}%) is above the required return ({discount_rate:.2f}%). "
                "After adjusting for reinvestment of intermediate cash flows at the specified "
                "reinvestment rate, the project still yields a return above the cost of capital."
            ),
        }
    return {
        "status": "REJECT",
        "label": "MIRR",
        "reason": (
            f"MIRR ({mirr:.2f}%) is below the required return ({discount_rate:.2f}%). "
            "The project's reinvestment-adjusted return is insufficient under the specified "
            "financing and reinvestment assumptions."
        ),
    }


def decision_for_pi(pi: float | None) -> dict[str, str]:
    if pi is None or not np.isfinite(pi):
        return {
            "status": "REVIEW",
            "label": "PI",
            "reason": "Profitability index could not be computed reliably.",
        }
    if pi >= 1.0:
        return {
            "status": "ACCEPT",
            "label": "PI",
            "reason": (
                f"Profitability Index ({pi:.3f}) is at or above 1.0, meaning the present value "
                "of future cash inflows equals or exceeds the initial investment. Each dollar "
                "invested is expected to return at least $1.00 in present-value terms."
            ),
        }
    return {
        "status": "REJECT",
        "label": "PI",
        "reason": (
            f"Profitability Index ({pi:.3f}) is below 1.0, meaning the present value of future "
            "cash inflows is less than the initial investment. The project returns less than "
            "$1.00 in present-value terms per dollar invested."
        ),
    }


def decision_for_roi(roi_pct: float | None) -> dict[str, str]:
    if roi_pct is None or not np.isfinite(roi_pct):
        return {
            "status": "REVIEW",
            "label": "ROI",
            "reason": "ROI could not be computed reliably.",
        }
    if roi_pct > 0:
        return {
            "status": "ACCEPT",
            "label": "ROI",
            "reason": (
                f"ROI ({roi_pct:.2f}%) is positive, meaning the project generates more total "
                "value than the initial investment over its lifetime, expressed as a return "
                "on the capital invested."
            ),
        }
    if abs(roi_pct) <= 0.005:
        return {
            "status": "REVIEW",
            "label": "ROI",
            "reason": (
                f"ROI is effectively zero ({roi_pct:.4f}%). The project returns about the same "
                "total value as invested. Value-neutral outcomes require qualitative judgement."
            ),
        }
    return {
        "status": "REJECT",
        "label": "ROI",
        "reason": (
            f"ROI ({roi_pct:.2f}%) is negative. The project generates a negative overall return "
            "relative to the initial investment, meaning the total cash recovered over the "
            "project's life is less than the capital committed."
        ),
    }


def decision_for_payback(payback: float | None, project_life: float) -> dict[str, str]:
    if payback is None or not np.isfinite(payback):
        return {
            "status": "REVIEW",
            "label": "Payback",
            "reason": "Payback could not be computed because cumulative cash flows never turn positive.",
        }
    if payback <= project_life:
        return {
            "status": "ACCEPT",
            "label": "Payback",
            "reason": (
                f"Payback period of {payback:.2f} years is within the project's life of "
                f"{project_life:.0f} years. The initial investment is recovered in time for the "
                "project to generate net value within its operating window."
            ),
        }
    return {
        "status": "REJECT",
        "label": "Payback",
        "reason": (
            f"Payback period of {payback:.2f} years exceeds the project's life of {project_life:.0f} years. "
            "The initial investment is not recovered within the project's expected operating life, "
            "leaving capital permanently at risk."
        ),
    }


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------

@dataclass
class ProjectInputs:
    project_name: str = "Untitled Project"
    project_description: str = ""
    initial_investment: float = 1_000_000
    project_life: float = 10
    annual_revenues: float = 300_000
    revenue_growth_rate: float = 0.0
    operating_costs: float = 100_000
    cost_growth_rate: float = 0.0
    tax_rate: float = 25.0
    working_capital: float = 0.0
    terminal_value: float = 0.0
    terminal_growth_rate: float = 0.0
    discount_rate: float = 10.0
    financing_rate: float = 10.0
    reinvestment_rate: float = 10.0

    def as_dict_annual_revenue_list(self) -> list[float]:
        """Expand annual revenues into a per-year vector (constant or growing)."""
        revs = []
        for y in range(1, int(self.project_life) + 1):
            revs.append(self.annual_revenues * (1 + self.revenue_growth_rate / 100) ** (y - 1))
        return revs

    def as_dict_annual_cost_list(self) -> list[float]:
        costs = []
        for y in range(1, int(self.project_life) + 1):
            costs.append(self.operating_costs * (1 + self.cost_growth_rate / 100) ** (y - 1))
        return costs


def run_analysis(inputs: ProjectInputs) -> dict[str, Any]:
    """Full capital-budgeting + DCF pipeline. Returns a rich results dict."""
    life = int(round(inputs.project_life))
    discount = inputs.discount_rate / 100.0
    tax = inputs.tax_rate / 100.0
    investment = inputs.initial_investment
    wc_init = inputs.working_capital

    revenues = inputs.as_dict_annual_revenue_list()[:life]
    costs = inputs.as_dict_annual_cost_list()[:life]

    cf_rows = []
    for y in range(1, life + 1):
        ebitda = revenues[y - 1] - costs[y - 1]
        depreciation = investment / life
        ebit = ebitda - depreciation
        tax_amt = max(ebit, 0.0) * tax
        nopat = ebitda - tax_amt - depreciation
        ocf = nopat + depreciation
        outflow = wc_init if y == 1 else 0.0
        net_cf = ocf - outflow
        cf_rows.append(
            {
                "year": y,
                "revenue": revenues[y - 1],
                "operating_cost": costs[y - 1],
                "ebitda": ebitda,
                "depreciation": depreciation,
                "ebit": ebit,
                "tax": tax_amt,
                "nopat": nopat,
                "ocf": ocf,
                "working_capital_outflow": outflow,
                "net_cash_flow": net_cf,
            }
        )

    terminal = inputs.terminal_value
    if terminal <= 0 and inputs.terminal_growth_rate > 0:
        last_ocf = cf_rows[-1]["ocf"] if cf_rows else 0.0
        g = inputs.terminal_growth_rate / 100.0
        if discount > g and last_ocf > 0:
            terminal = (last_ocf * (1 + g)) / (discount - g)

    if terminal > 0:
        cf_rows[-1]["net_cash_flow"] += terminal

    net_cfs = [r["net_cash_flow"] for r in cf_rows]
    total_cfs = [-investment] + net_cfs

    discount_factors = [1 / (1 + discount) ** t for t in range(1, life + 1)]
    pvs = [net_cfs[i] * discount_factors[i] for i in range(life)]

    npv = -investment + sum(pvs)
    if terminal > 0:
        pv_terminal = terminal / (1 + discount) ** life
        total_project_value = sum(pvs) + pv_terminal
    else:
        pv_terminal = 0.0
        total_project_value = sum(pvs)

    # IRR (numpy polyfit-based, robust)
    irr = _calc_irr(total_cfs)

    # MIRR
    mirr = _calc_mirr(total_cfs, inputs.financing_rate / 100.0, inputs.reinvestment_rate / 100.0)

    # Payback
    payback, cum_cfs = _calc_payback(total_cfs)

    # PI
    pv_inflows = sum(pvs) if sum(pvs) > 0 else 0.0
    pi = pv_inflows / investment if investment > 0 else None

    # ROI
    total_in = sum(cf for cf in net_cfs if cf > 0)
    roi = (total_in - investment) / investment * 100 if investment > 0 else None

    # Annualized returns
    holding_period_return = (total_in / investment - 1) * 100 if investment > 0 else None
    annualized_return = ((1 + holding_period_return / 100) ** (1 / max(life, 1)) - 1) * 100 if investment > 0 else None

    cumulative_npv = []
    run = -investment
    for pv in pvs:
        run += pv
        cumulative_npv.append(run)

    # Build cash-flow table incl. cumulative, discount factors, PV, cumulative PV
    table_rows = []
    for i, r in enumerate(cf_rows):
        table_rows.append(
            {
                "Year": r["year"],
                "Revenue": r["revenue"],
                "Operating Costs": r["operating_cost"],
                "EBITDA": r["ebitda"],
                "Depreciation": r["depreciation"],
                "EBIT": r["ebit"],
                "Tax": r["tax"],
                "NOPAT": r["nopat"],
                "OCF": r["ocf"],
                "Initial Investment": investment if r["year"] == 1 else 0,
                "Working Capital": -r["working_capital_outflow"],
                "Terminal Value": terminal if r["year"] == life else 0,
                "Net Cash Flow": r["net_cash_flow"],
                "Cumulative Cash Flow": cum_cfs[i + 1],
                "Discount Factor": discount_factors[i],
                "Present Value": net_cfs[i] * discount_factors[i],
                "Cumulative PV": cumulative_npv[i],
            }
        )
    tbl = pd.DataFrame(table_rows)

    dcf_table = pd.DataFrame(
        {
            "Year": [1 + i for i in range(life)],
            "Free Cash Flow": net_cfs,
            "Discount Factor": discount_factors,
            "Present Value": pvs,
            "Cumulative Present Value": cumulative_npv,
        }
    )

    metrics = {
        "npv": npv,
        "irr": float(np.real(irr)) * 100 if irr is not None and np.isfinite(irr) else None,
        "mirr": mirr * 100 if mirr is not None else None,
        "payback": payback,
        "pi": pi,
        "roi": roi,
        "holding_period_return": holding_period_return,
        "annualized_return": annualized_return,
        "initial_investment": investment,
        "project_life": life,
        "discount_rate": inputs.discount_rate,
        "terminal_value": terminal,
        "pv_terminal": pv_terminal,
        "total_project_value": total_project_value,
        "total_cash_outflow": sum(cf for cf in net_cfs if cf < 0) + investment,
        "total_cash_inflow": total_in,
        "total_nominal_returns": total_in - investment,
    }

    decisions = {
        "npv": decision_for_npv(npv),
        "irr": decision_for_irr(metrics["irr"], inputs.discount_rate),
        "mirr": decision_for_mirr(metrics["mirr"], inputs.discount_rate),
        "pi": decision_for_pi(pi),
        "roi": decision_for_roi(roi),
        "payback": decision_for_payback(payback, life),
    }

    return {
        "inputs": inputs,
        "cash_flow_table": tbl,
        "dcf_table": dcf_table,
        "metrics": metrics,
        "decisions": decisions,
        "chart_data": {
            "years": [1 + i for i in range(life)],
            "net_cash_flows": net_cfs,
            "cumulative_cash_flows": cum_cfs[1:],
            "present_values": pvs,
            "cumulative_present_values": cumulative_npv,
        },
    }


def rerun_analysis(params: dict[str, Any]) -> dict[str, Any]:
    """Utility to re-run from a plain dict (used by scenarios/sensitivity)."""
    inputs = ProjectInputs(
        project_name=str(params.get("project_name", "Project")),
        initial_investment=float(params.get("initial_investment")),
        project_life=float(params.get("project_life")),
        annual_revenues=float(params.get("annual_revenues")),
        revenue_growth_rate=float(params.get("revenue_growth_rate", 0)),
        operating_costs=float(params.get("operating_costs")),
        cost_growth_rate=float(params.get("cost_growth_rate", 0)),
        tax_rate=float(params.get("tax_rate")),
        working_capital=float(params.get("working_capital", 0)),
        terminal_value=float(params.get("terminal_value", 0)),
        terminal_growth_rate=float(params.get("terminal_growth_rate", 0)),
        discount_rate=float(params.get("discount_rate")),
        financing_rate=float(params.get("financing_rate", params.get("discount_rate"))),
        reinvestment_rate=float(params.get("reinvestment_rate", params.get("discount_rate"))),
    )
    return run_analysis(inputs)


# ---------------------------------------------------------------------------
# Internal numeric helpers
# ---------------------------------------------------------------------------

def _calc_irr(cfs: list[float]) -> float | None:
    """IRR via Newton-Raphson on NPV, with a Bisection fallback."""
    if not any(cf > 0 for cf in cfs) or not any(cf < 0 for cf in cfs):
        return None
    return _bisection_irr(cfs, -0.9999, 10.0)


def _npv_at(cfs: list[float], rate: float) -> float:
    return sum(cf / (1 + rate) ** t for t, cf in enumerate(cfs))


def _npv_prime_at(cfs: list[float], rate: float) -> float:
    return sum(-t * cf / (1 + rate) ** (t + 1) for t, cf in enumerate(cfs))


def _bisection_irr(cfs: list[float], lo: float, hi: float, iters: int = 400) -> float | None:
    if _npv_at(cfs, lo) * _npv_at(cfs, hi) > 0:
        return None
    for _ in range(iters):
        mid = (lo + hi) / 2
        v = _npv_at(cfs, mid)
        if abs(v) < 1e-8:
            return mid
        if _npv_at(cfs, lo) * v < 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def _calc_mirr(
    cfs: list[float], finance_rate: float, reinvest_rate: float
) -> float | None:
    """MIRR = (FV_pos / PV_neg)^(1/(n-1)) - 1."""
    pv_neg = 0.0
    fv_pos = 0.0
    n = len(cfs) - 1
    for t, cf in enumerate(cfs):
        if cf < 0:
            pv_neg += cf / (1 + finance_rate) ** t
        elif cf > 0:
            fv_pos += cf * (1 + reinvest_rate) ** (n - t)
    if pv_neg >= 0 or fv_pos < 0:
        return None
    return (fv_pos / (-pv_neg)) ** (1 / n) - 1


def _calc_payback(cfs: list[float]) -> tuple[float | None, list[float]]:
    cum = []
    run = 0.0
    for cf in cfs:
        run += cf
        cum.append(run)
    if all(c < 0 for c in cum[1:]):
        return None, cum
    for i in range(0, len(cum) - 1):
        if cum[i] >= 0:
            return float(i), cum
        if cum[i + 1] > 0:
            frac = (0 - cum[i]) / (cum[i + 1] - cum[i])
            return float(i) + frac, cum
    return None, cum