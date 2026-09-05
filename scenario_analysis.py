"""Scenario and sensitivity analysis engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from calculations import ProjectInputs, run_analysis


@dataclass
class ScenarioDefinition:
    name: str
    label: str
    description: str
    revenue_factor: float = 1.0
    cost_factor: float = 1.0
    wacc_adjustment: float = 0.0
    extra: dict[str, float] | None = None

    def apply(self, base: ProjectInputs) -> ProjectInputs:
        import copy

        p = copy.deepcopy(base)
        p.annual_revenues = base.annual_revenues * self.revenue_factor
        p.operating_costs = base.operating_costs * self.cost_factor
        p.discount_rate = base.discount_rate + self.wacc_adjustment
        p.financing_rate = base.financing_rate + self.wacc_adjustment
        p.reinvestment_rate = base.reinvestment_rate + self.wacc_adjustment
        if self.extra:
            for k, v in self.extra.items():
                setattr(p, k, getattr(base, k) * v)
        return p


def scenario_summary(result: dict[str, Any]) -> dict[str, Any]:
    m = result["metrics"]
    d = result["decisions"]
    decision_status = _aggregate_decision(d)

    return {
        "npv": m["npv"],
        "irr": m["irr"],
        "mirr": m["mirr"],
        "roi": m["roi"],
        "payback": m["payback"],
        "pi": m["pi"],
        "decision": decision_status["status"],
        "explanation": decision_status["reason"],
        "life": m["project_life"],
    }


def _aggregate_decision(decisions: dict[str, Any]) -> dict[str, str]:
    """Combine per-metric decisions into one overall verdict logic."""
    statuses = [v["status"] for v in decisions.values()]
    accepts = statuses.count("ACCEPT")
    rejects = statuses.count("REJECT")
    total = len(statuses)

    if accepts == total:
        status = "ACCEPT"
        reason = (
            "All primary financial metrics meet or exceed their required thresholds. The project "
            "is expected to create value after accounting for the cost of capital, timing, "
            "recovery and return on investment."
        )
    elif rejects == total:
        status = "REJECT"
        reason = (
            "All primary financial metrics fail their required thresholds. The project is expected "
            "to destroy value or fail to recover capital under the current assumptions."
        )
    elif accepts > rejects:
        status = "ACCEPT"
        reason = (
            f"Most financial metrics ({accepts} of {total}) are favourable. The preponderance of "
            "evidence supports proceeding, although full alignment across all indicators is absent."
        )
    elif rejects > accepts:
        status = "REJECT"
        reason = (
            f"Most financial metrics ({rejects} of {total}) are unfavourable. The preponderance of "
            "evidence argues against proceeding under the current assumptions."
        )
    else:
        status = "REVIEW"
        reason = (
            "Financial evidence is mixed with a balanced split between favourable and unfavourable "
            "metrics. The decision requires additional qualitative and risk review."
        )
    return {"status": status, "reason": reason}


def build_scenarios(results: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Compute Best / Base / Worst cases."""
    base_result = results
    base_inputs: ProjectInputs = base_result["inputs"]

    scenarios = {}
    out = {}

    for name, label, desc, rev_fac, cost_fac, wacc_adj in [
        ("best", "Best Case", "Optimistic assumptions: revenues 15% above base, costs 10% below base.",
         1.15, 0.90, -1.0),
        ("base", "Base Case", "Central assumptions exactly as entered by the user.", 1.0, 1.0, 0.0),
        ("worst", "Worst Case", "Pessimistic assumptions: revenues 20% below base, costs 15% above base.",
         0.80, 1.15, +1.5),
    ]:
        sc = ScenarioDefinition(name, label, desc, rev_fac, cost_fac, wacc_adj)
        scenarios[name] = sc
        p = sc.apply(base_inputs)
        res = run_analysis(p)
        out[name] = {
            "inputs": p,
            "result": res,
            "summary": scenario_summary(res),
            "label": label,
            "description": desc,
        }

    return out


def scenario_decision_text(name: str, s: dict[str, Any]) -> str:
    summary = s["summary"]
    label = s["label"]
    npv = summary["npv"]
    decision = summary["decision"]

    if decision == "ACCEPT":
        return (
            f"{label} NPV = ${npv:,.0f}. The project generates positive value after discounting "
            "expected cash flows at the applicable discount rate. Under these assumptions the "
            "investment is financially attractive."
        )
    if decision == "REJECT":
        return (
            f"{label} NPV = ${npv:,.0f}. Under the {label.lower()} assumptions, the project's "
            "discounted cash flows are insufficient to recover the initial investment, resulting "
            "in negative value creation."
        )
    return (
        f"{label} NPV = ${npv:,.0f}. The {label.lower()} outcome is mixed and requires "
        "additional judgement before proceeding."
    )


def run_sensitivity(
    base: ProjectInputs,
    results: dict[str, Any],
    steps: int = 9,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Tornado-style sensitivity of NPV around base assumptions."""
    vars_specs = [
        ("wacc", "Discount Rate (WACC)", -0.3, 0.3, "percent", 1.0),
        ("revenue", "Annual Revenues", -0.3, 0.3, "scalar", 1.0),
        ("costs", "Operating Costs", -0.3, 0.3, "scalar", 1.0),
        ("investment", "Initial Investment", -0.3, 0.3, "scalar", 1.0),
    ]

    npv_base = results["metrics"]["npv"]
    rows = []
    for key, label, lo_frac, hi_frac, kind, scale in vars_specs:
        if kind == "percent":
            lo_npv = _npv_for_perturbation(base, key, base.discount_rate + lo_frac * 100)
            hi_npv = _npv_for_perturbation(base, key, base.discount_rate + hi_frac * 100)
        else:
            lo_npv = _npv_for_perturbation(base, key, (1 + lo_frac) * scale)
            hi_npv = _npv_for_perturbation(base, key, (1 + hi_frac) * scale)
        rows.append(
            {
                "Variable": label,
                "Id": key,
                "NPV at -30%": lo_npv,
                "NPV at Base": npv_base,
                "NPV at +30%": hi_npv,
                "Spread": abs(hi_npv - lo_npv),
            }
        )

    sensitivities = []
    for r in rows:
        var_label = r["Variable"]
        lo = r["NPV at -30%"]
        hi = r["NPV at +30%"]
        base_npv = r["NPV at Base"]
        # Determine direction of effect
        direction = "negative" if (base_npv - lo) < 0 else "positive"
        impact_desc = _interpret_variable(var_label, lo, hi, base_npv)
        sensitivities.append(
            {
                "variable": var_label,
                "npv_low": lo,
                "npv_base": base_npv,
                "npv_high": hi,
                "explanation": impact_desc,
            }
        )

    df = pd.DataFrame(rows).sort_values("Spread", ascending=False)
    ranked = df["Variable"].tolist()

    most_sensitive = df.iloc[0]["Variable"] if len(df) else None
    least_sensitive = df.iloc[-1]["Variable"] if len(df) else None

    return df, {
        "sensitivities": sensitivities,
        "most_sensitive": most_sensitive,
        "least_sensitive": least_sensitive,
        "npv_base": npv_base,
    }


def _npv_for_perturbation(base: ProjectInputs, key: str, value: float) -> float:
    import copy

    p = copy.deepcopy(base)
    if key == "wacc":
        p.discount_rate = value
        p.financing_rate = value
        p.reinvestment_rate = value
    elif key == "revenue":
        p.annual_revenues = base.annual_revenues * value
    elif key == "costs":
        p.operating_costs = base.operating_costs * value
    elif key == "investment":
        p.initial_investment = base.initial_investment * value
    return run_analysis(p)["metrics"]["npv"]


def _interpret_variable(var: str, lo: float, hi: float, base_npv: float) -> str:
    if var == "Discount Rate (WACC)":
        return (
            "Raising the WACC reduces the present value of future cash flows, lowering NPV "
            "(discounting effect); lowering it does the reverse. This reflects how expensive "
            "the project's capital is."
        )
    if var == "Annual Revenues":
        return (
            "Revenues are the primary inflow driver. Higher revenue raises cash flows and NPV; "
            "lower revenue erodes them, and the effect compounds over the project life."
        )
    if var == "Operating Costs":
        return (
            "Operating costs subtract directly from cash flows. Higher costs depress NPV and "
            "lower costs improve it, with the swing persisting across every year of the project."
        )
    if var == "Initial Investment":
        return (
            "The initial investment sets the baseline outlay. A larger outlay reduces NPV "
            "one-for-one in present-value terms; a smaller one improves it."
        )
    return "This variable shifts the base-case cash-flow stream, moving NPV in the direction described."


def sensitivity_interpretation(summary: dict[str, Any]) -> str:
    most = summary["most_sensitive"]
    least = summary["least_sensitive"]
    return (
        f"The most sensitive variable is {most} and the least sensitive is {least}. "
        "Management should prioritise review, hedging and control of the most sensitive "
        "variable because small deviations from the assumption have the largest impact on "
        "project value and on the investment decision."
    )