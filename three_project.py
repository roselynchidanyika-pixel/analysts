"""Three-Project Multi-Currency Comparison & Optimization Module.

Process:  SELECT -> CONVERT -> CALCULATE -> OPTIMISE -> COMPARE -> RANK -> EXPLAIN -> RECOMMEND
Integrates the existing capital-budgeting, DCF, returns, risk, scenario and
sensitivity engines. Never assumes USD/ZAR/ZiG superiority — the winner is
decided purely by the computed results and the selected financial methods.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd

import fx_rates as fx
from calculations import ProjectInputs, run_analysis
from risk_analysis import assess_risks

METHODS = [
    "DCF",
    "NPV",
    "IRR",
    "MIRR",
    "ROI",
    "HPR",
    "Annualized Return",
    "Payback",
    "PI",
    "WACC",
]

# Column used in comparison frame and direction (higher better / lower better)
METHOD_COLUMNS = {
    "DCF": ("DCF Value", "higher"),
    "NPV": ("NPV", "higher"),
    "IRR": ("IRR", "higher"),
    "MIRR": ("MIRR", "higher"),
    "ROI": ("ROI", "higher"),
    "HPR": ("Holding Period Return", "higher"),
    "Annualized Return": ("Annualized Return", "higher"),
    "Payback": ("Payback", "lower"),
    "PI": ("Profitability Index", "higher"),
    "WACC": ("WACC", "higher"),
}

RISK_RANK = {"LOW": 1, "MODERATE": 2, "HIGH": 3, "VERY HIGH": 4}


@dataclass
class ProjectSpec:
    name: str
    currency: str  # USD | ZAR | ZWG (ZiG)
    description: str = ""
    initial_investment: float = 1_000_000
    project_life: float = 10
    annual_revenues: float = 350_000
    operating_costs: float = 80_000
    tax_rate: float = 25
    discount_rate: float = 10
    financing_rate: float = 10
    reinvestment_rate: float = 10
    working_capital: float = 0
    terminal_value: float = 0
    revenue_growth_rate: float = 0
    cost_growth_rate: float = 0
    terminal_growth_rate: float = 0

    def monetary_inputs(self) -> dict[str, float]:
        return {
            "initial_investment": self.initial_investment,
            "annual_revenues": self.annual_revenues,
            "operating_costs": self.operating_costs,
            "working_capital": self.working_capital,
            "terminal_value": self.terminal_value,
        }

    def non_monetary_inputs(self) -> dict[str, float]:
        return {
            "project_life": self.project_life,
            "tax_rate": self.tax_rate,
            "discount_rate": self.discount_rate,
            "financing_rate": self.financing_rate,
            "reinvestment_rate": self.reinvestment_rate,
            "revenue_growth_rate": self.revenue_growth_rate,
            "cost_growth_rate": self.cost_growth_rate,
            "terminal_growth_rate": self.terminal_growth_rate,
        }


@dataclass
class ComparisonConfig:
    projects: dict[str, ProjectSpec] = field(default_factory=dict)
    comparison_currency: str = "USD"
    methods: list[str] = field(default_factory=lambda: ["NPV", "IRR", "MIRR", "ROI", "PI", "Payback"])
    include_risk_and_scenarios: bool = True
    investment_type: str = "Divisible"  # Divisible | Indivisible
    budget: float = 0.0
    ratemap: dict[str, fx.FxRate] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Per-project pipeline
# ---------------------------------------------------------------------------

def execute_project(
    spec: ProjectSpec,
    comparison_currency: str,
    ratemap: dict[str, fx.FxRate],
) -> dict[str, Any]:
    monetary = spec.monetary_inputs()
    converted, note = fx.convert_inputs_for_comparison(
        spec.currency, comparison_currency, ratemap, monetary
    )
    merged = {**spec.non_monetary_inputs(), **converted}
    inputs = ProjectInputs(
        project_name=spec.name,
        project_description=spec.description,
        initial_investment=merged["initial_investment"],
        project_life=merged["project_life"],
        annual_revenues=merged["annual_revenues"],
        revenue_growth_rate=merged["revenue_growth_rate"],
        operating_costs=merged["operating_costs"],
        cost_growth_rate=merged["cost_growth_rate"],
        tax_rate=merged["tax_rate"],
        working_capital=merged["working_capital"],
        terminal_value=merged["terminal_value"],
        terminal_growth_rate=merged["terminal_growth_rate"],
        discount_rate=merged["discount_rate"],
        financing_rate=merged["financing_rate"],
        reinvestment_rate=merged["reinvestment_rate"],
    )
    results = run_analysis(inputs)
    risks = assess_risks(results)
    return {
        "spec": spec,
        "conversion_note": note,
        "results": results,
        "risks": risks,
        "converted_inputs": converted,
    }


def compare_projects(config: ComparisonConfig) -> dict[str, Any]:
    """Full comparison pipeline. Returns a rich dict consumed by the UI/report."""
    executed: dict[str, dict[str, Any]] = {}
    rows = []
    for key in ("A", "B", "C"):
        spec = config.projects[key]
        bundle = execute_project(spec, config.comparison_currency, config.ratemap)
        executed[key] = bundle
        m = bundle["results"]["metrics"]
        rows.append(
            {
                "Project": key,
                "Name": spec.name,
                "Currency": spec.currency,
                "DCF Value": m["total_project_value"],
                "NPV": m["npv"],
                "IRR": m["irr"],
                "MIRR": m["mirr"],
                "ROI": m["roi"],
                "Holding Period Return": m["holding_period_return"],
                "Annualized Return": m["annualized_return"],
                "Payback": m["payback"],
                "Profitability Index": m["pi"],
                "WACC": spec.discount_rate,
                "Risk": bundle["risks"]["overall_risk"],
                # Scenarios
                "Best Case NPV": _scenario_value(bundle, "best"),
                "Base Case NPV": _scenario_value(bundle, "base"),
                "Worst Case NPV": _scenario_value(bundle, "worst"),
            }
        )
    comp_df = pd.DataFrame(rows)

    ranking = rank_projects(comp_df, config.methods, config.include_risk_and_scenarios)

    optimisation = optimise(
        comp_df, config.investment_type, config.budget, executed
    )

    recommendation = build_recommendation(ranking["ranking_df"], ranking, config, executed, optimisation)

    return {
        "config": config,
        "comparison_df": comp_df,
        "ranking_df": ranking["ranking_df"],
        "composite_scores": ranking["composite_scores"],
        "optimisation": optimisation,
        "recommendation": recommendation,
        "executed": executed,
        "rates": config.ratemap,
        "rates_text": fx.rates_summary_text(config.ratemap),
    }


def _scenario_value(bundle: dict[str, Any], key: str) -> float:
    from scenario_analysis import build_scenarios

    sc = build_scenarios(bundle["results"])
    return sc[key]["summary"]["npv"]


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

def _safe_num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def rank_projects(
    comp_df: pd.DataFrame,
    methods: list[str],
    include_risk_and_scenarios: bool = True,
) -> dict[str, Any]:
    """Rank 1st/2nd/3rd with composite scores and tailored explanations."""
    terms: dict[str, tuple[str, str]] = {}
    for meth in methods:
        if meth in METHOD_COLUMNS:
            col, direction = METHOD_COLUMNS[meth]
            terms[f"method::{meth}"] = (col, direction)
    if include_risk_and_scenarios:
        terms["risk"] = ("Risk", "lower")
        terms["base"] = ("Base Case NPV", "higher")

    n = len(comp_df)
    comp = pd.Series([0.0] * n, index=comp_df.index)
    details = {i: [] for i in comp_df.index}
    used = 0

    for key, (col, direction) in terms.items():
        col_vals = [_safe_num(v) for v in comp_df[col]]
        if all(v is None for v in col_vals):
            continue
        if key == "risk":
            col_vals = [RISK_RANK.get(str(v), 2) for v in comp_df[col]]
        vmax = max(v for v in col_vals if v is not None)
        vmin = min(v for v in col_vals if v is not None)
        span = vmax - vmin
        for i in comp_df.index:
            v = col_vals[i]
            if v is None or span == 0:
                norm = 0.5
            else:
                norm = (v - vmin) / span
                if direction == "lower":
                    norm = 1 - norm
            comp.loc[i] += norm
            details[i].append(f"{col}:{'' if v is None else round(v, 3)}")
            used += 1

    if used:
        comp = comp / max(used // n, 1)

    comp_df = comp_df.copy()
    comp_df["Composite Score"] = comp.round(4)
    comp_df["Rank"] = comp.rank(ascending=False, method="min").astype(int)
    comp_df = comp_df.sort_values("Rank").reset_index(drop=True)

    rank_explanations: dict[int, str] = {}
    maxmet = len(terms)
    for _, row in comp_df.iterrows():
        rk = int(row["Rank"])
        positives = []
        negatives = []
        for meth in methods:
            col, direction = METHOD_COLUMNS[meth]
            v = _safe_num(row[col])
            if v is None:
                continue
            if direction == "higher":
                (positives if v >= _median(comp_df, col) else negatives).append(f"{col} {v:.2f}")
            else:
                (positives if v <= 0 else negatives).append(f"{col} {v:.2f}")
        risk_line = f"Risk {row['Risk']}"

        med = _median(comp_df, "Base Case NPV")
        scen = "Base Case NPV " + (f"{row['Base Case NPV']:,.0f}" if row["Base Case NPV"] == row["Base Case NPV"] else "N/A")
        pos = ", ".join(positives[:4])
        neg = (", ".join(negatives[:3])) if negatives else "no material weaknesses"
        txt = (
            f"Ranks {rk}{_ordinal_suffix(rk)} with composite score {row['Composite Score']:.3f}. "
            f"Leads on {pos}.  Weighs on {neg}.  {scen}; {risk_line}."
        )
        rank_explanations[rk] = txt

    return {
        "ranking_df": comp_df,
        "composite_scores": dict(zip(comp_df["Project"], comp_df["Composite Score"])),
        "rank_explanations": rank_explanations,
    }


def _median(df: pd.DataFrame, col: str) -> float:
    vals = [_safe_num(v) for v in df[col]]
    vals = [v for v in vals if v is not None]
    return sorted(vals)[len(vals) // 2] if vals else 0.0


def _ordinal_suffix(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


# ---------------------------------------------------------------------------
# Optimisation
# ---------------------------------------------------------------------------

def optimise(
    comp_df: pd.DataFrame,
    investment_type: str,
    budget: float,
    executed: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    projs = ["A", "B", "C"]
    investment = {
        p: executed[p]["results"]["metrics"]["initial_investment"] for p in projs
    }
    npv = {p: executed[p]["results"]["metrics"]["npv"] for p in projs}

    if investment_type.lower() == "indivisible":
        return _optimise_indivisible(comp_df, budget, investment, npv, executed)

    return _optimise_divisible(budget, investment, npv, executed)


def _optimise_divisible(
    budget: float,
    investment: dict[str, float],
    npv: dict[str, float],
    executed: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    rows = []
    remaining = budget
    order = sorted(["A", "B", "C"], key=lambda p: _pi(p, investment, npv), reverse=True)
    allocations: dict[str, float] = {}
    contribution = 0.0
    for p in order:
        inv = investment[p]
        if remaining <= 0:
            portion = 0.0
        elif inv <= 0:
            portion = 1.0 if npv[p] > 0 else 0.0
        else:
            portion = min(1.0, remaining / inv)
        alloc = inv * portion
        allocations[p] = alloc
        remaining -= alloc
        contribution += npv[p] * portion
        rows.append(
            {
                "Project": p,
                "NPV": npv[p],
                "Investment": inv,
                "Allocated": alloc,
                "Portion %": portion * 100,
                "NPV Contribution": npv[p] * portion,
            }
        )
    alloc_df = pd.DataFrame(rows).sort_values("Project").reset_index(drop=True)

    if budget <= 0:
        explanation = (
            "No investment budget was entered, so no capital can be allocated. "
            "Enter a budget in the comparison currency to run the optimisation."
        )
    else:
        explanation = (
            f"With a {budget:,.0f} budget in the comparison currency, projects were ranked by "
            "NPV per unit of investment (profitability per ZAR/USD/ZiG of capital). Shares were "
            "allocated fractionally until the budget was fully used (divisible project rule, "
            "capital-rationing). The combined NPV contribution is "
            f"{contribution:,.0f}. Negative-NPV projects receive no allocation unless required."
        )
    return {
        "type": "Divisible",
        "allocation_parts": order,
        "allocations": allocations,
        "allocation_df": alloc_df,
        "total_invested": sum(allocations.values()),
        "total_npv": contribution,
        "explanation": explanation,
    }


def _optimise_indivisible(
    comp_df: pd.DataFrame,
    budget: float,
    investment: dict[str, float],
    npv: dict[str, float],
    executed: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    from itertools import combinations

    names = ["A", "B", "C"]
    results = []
    for r in range(1, 4):
        for combo in combinations(names, r):
            inv = sum(investment[p] for p in combo)
            value = sum(npv[p] for p in combo)
            feasible = budget <= 0 or inv <= budget + 1e-6
            results.append(
                {
                    "Combination": "+".join(combo),
                    "Projects": combo,
                    "Investment": inv,
                    "Total NPV": value,
                    "Feasible": feasible,
                }
            )
    comb_df = pd.DataFrame(results)
    feasible_df = comb_df[comb_df["Feasible"]].copy() if len(comb_df) else comb_df
    if feasible_df.empty:
        best = None
        best_val = float("-inf")
        recommendation = (
            "No combination fits within the budget. Review either the budget or the "
            "individual investment requirements before proceeding."
        )
    else:
        best_idx = feasible_df["Total NPV"].idxmax()
        best = feasible_df.loc[best_idx]
        best_val = float(best["Total NPV"])
        recommendation = (
            f"The optimal indivisible combination is {best['Combination']} with total NPV "
            f"{best['Total NPV']:,.0f} at a combined investment of {best['Investment']:,.0f}, "
            "which is the highest-NPV feasible set within the budget. All feasible "
            "combinations were enumerated (indivisible project rule)."
        )
    return {
        "type": "Indivisible",
        "combinations_df": comb_df,
        "best_combination": best["Combination"] if best is not None else None,
        "best_investment": float(best["Investment"]) if best is not None else None,
        "best_npv": best_val if best is not None else 0.0,
        "explanation": recommendation,
    }


def _pi(p: str, investment: dict[str, float], npv: dict[str, float]) -> float:
    inv = investment[p]
    if inv <= 0:
        return 1.0
    return npv[p] / inv


# ---------------------------------------------------------------------------
# Recommendation
# ---------------------------------------------------------------------------

def build_recommendation(
    comp_df: pd.DataFrame,
    ranking: dict[str, Any],
    config: ComparisonConfig,
    executed: dict[str, dict[str, Any]],
    optimisation: dict[str, Any],
) -> dict[str, str]:
    first = comp_df[comp_df["Rank"] == 1].iloc[0]
    winner_project = first["Project"]
    winner_name = first["Name"]
    winner_ccy = first["Currency"]

    if winner_project == "A":
        second, third = "B", "C"
    elif winner_project == "B":
        second, third = "A", "C"
    else:
        second, third = "A", "B"

    evidence = []
    for meth in config.methods:
        col, direction = METHOD_COLUMNS[meth]
        win_v = first[col]
        sec_v = comp_df[comp_df["Project"] == second].iloc[0][col]
        win_txt = _fmt_val(win_v, col)
        sec_txt = _fmt_val(sec_v, col)
        w = _safe_num(win_v)
        s = _safe_num(sec_v)
        if w is not None and s is not None:
            leads = w > s if direction == "higher" else w < s
            verb = "leads" if leads else "trails"
            evidence.append(f"{col}: {win_txt} ({verb} {second} {sec_txt})")
        else:
            evidence.append(f"{col}: {win_txt} (second {second}: {sec_txt})")

    risk = first["Risk"]
    risks_list = []
    if risk in ("HIGH", "VERY HIGH"):
        risks_list.append(f"risk is {risk}")
    worst = first["Worst Case NPV"]
    if worst == worst and worst < 0:
        risks_list.append(f"worst-case NPV is {worst:,.0f}")
    base = first["Base Case NPV"]
    base_txt = f"{base:,.0f}" if base == base else "N/A"
    if not risks_list:
        risks_list.append("no dominant downside beyond standard market exposure")

    why_bits = []
    for meth in ["NPV", "IRR", "MIRR", "ROI", "PI", "DCF"]:
        col, _ = METHOD_COLUMNS.get(meth, (meth, "higher"))
        if meth in config.methods and first[col] == first[col]:
            why_bits.append(f"{col} {_fmt_val(first[col], col)}")
    why_line = (
        f"{winner_name} ranks first because it produces the strongest overall result on "
        + (", ".join(why_bits[:4]) if why_bits else "the selected financial methods")
        + f", with the highest composite score ({first['Composite Score']:.3f}) across the "
        f"selected methods and a base-case NPV of {base_txt}. This is decided by the computed "
        "results, exchange rates, risk, scenarios and the selected financial methods — "
        "no currency (USD, ZAR or ZiG) is treated as automatically superior."
    )

    what = f"Project {winner_project} ({winner_name}) — {fx.CCY_LABELS.get(winner_ccy, winner_ccy)}"
    return {
        "winner": winner_project,
        "winner_name": winner_name,
        "winner_currency": winner_ccy,
        "rank_order": [first["Project"], second, third],
        "what": what,
        "why": why_line,
        "evidence": evidence,
        "risks": "; ".join(risks_list),
        "action": (
            f"Recommendation for management: proceed with Project {winner_project} "
            f"({winner_name}, denominated in {fx.CCY_LABELS.get(winner_ccy, winner_ccy)}) under "
            f"the current exchange-rate, financial and risk assumptions, subject to normal "
            f"governance. {_optimisation_advice(optimisation)} Re-run this comparison whenever "
            "the USD/ZAR/ZiG exchange rates change or when project assumptions are updated."
        ),
        "score": float(first["Composite Score"]),
        "risk": risk,
        "base_case_npv": base_txt,
        "explanation_rank1": ranking["rank_explanations"].get(1, ""),
        "explanation_rank2": ranking["rank_explanations"].get(2, ""),
        "explanation_rank3": ranking["rank_explanations"].get(3, ""),
    }


def _fmt_val(v: Any, col: str) -> str:
    if v is None or v != v:
        return "N/A"
    if col in ("NPV", "DCF Value", "Base Case NPV", "Worst Case NPV", "Best Case NPV"):
        return f"{v:,.0f}"
    if col in ("Payback",):
        return f"{v:.2f} yr"
    if col in ("Profitability Index",):
        return f"{v:.3f}"
    return f"{v:.2f}"


def _optimisation_advice(optimisation: dict[str, Any]) -> str:
    typ = optimisation["type"]
    if typ == "Divisible":
        parts = optimisation.get("allocation_parts", [])
        return (
            f"For the available budget, the optimal divisible split invests Projects "
            + ", ".join(p for p in parts)
            + " in order of profitability index, yielding a combined NPV contribution of "
            f"{optimisation.get('total_npv', 0):,.0f}."
        )
    best = optimisation.get("best_combination")
    if best:
        return (
            f"The optimal indivisible combination is {best} (combined NPV "
            f"{optimisation.get('best_npv', 0):,.0f})."
        )
    return optimisation.get("explanation", "")