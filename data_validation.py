"""Data validation engine for the Financial Engineering Investment Decision Agent."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidationResult:
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


_FRIENDLY_HEADERS = {
    "project_name": ["Project Name", "Project Title", "Name", "Project"],
    "project_life": ["Project Life", "Life (years)", "Duration", "Horizon", "Years"],
    "initial_investment": ["Initial Investment", "Initial_Investment", "Capex", "Investment", "Capital Expenditure (USD)"],
    "annual_revenues": ["Annual Revenues", "Revenue", "Revenues", "Sales", "Turnover", "Annual Revenue (USD)"],
    "operating_costs": ["Operating Costs", "Costs", "Opex", "Operating Expenses", "COGS"],
    "tax_rate": ["Tax Rate", "Tax (%)"],
    "discount_rate": ["Discount Rate", "WACC", "Required Return", "Hurdle Rate"],
    "working_capital": ["Working Capital", "NWC", "Net Working Capital"],
    "terminal_value": ["Terminal Value", "Salvage Value", "TV"],
    "financing_rate": ["Financing Rate"],
    "reinvestment_rate": ["Reinvestment Rate"],
    "growth_rate": ["Growth Rate", "Revenue Growth", "Growth"],
}

_FIELD_KEYWORDS = {
    "project_name": ["project", "name", "title"],
    "project_life": ["life", "year", "years", "duration", "horizon"],
    "initial_investment": ["initial", "investment", "invest", "capex", "capital", "outlay"],
    "annual_revenues": ["revenue", "revenues", "sales", "income", "turnover"],
    "operating_costs": ["operating", "cost", "costs", "opex", "expense", "expenditure"],
    "tax_rate": ["tax"],
    "discount_rate": ["discount", "wacc", "required return", "hurdle", "required"],
    "working_capital": ["working capital", "nwc", "net working"],
    "terminal_value": ["terminal", "salvage", "residual"],
    "financing_rate": ["financing", "finance"],
    "reinvestment_rate": ["reinvestment", "reinvest"],
    "growth_rate": ["growth", "grow"],
}

_FIELD_PRIORITY = [
    "initial_investment",
    "annual_revenues",
    "operating_costs",
    "project_life",
    "tax_rate",
    "discount_rate",
    "financing_rate",
    "reinvestment_rate",
    "project_name",
    "working_capital",
    "terminal_value",
    "growth_rate",
]


def _normalize_header(name: Any) -> str:
    s = str(name).lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _match_columns(df, column_map: dict[str, list[str]]) -> dict[str, str]:
    """Fuzzy column matching.

    Handles headers such as 'Initial Investment (USD)', 'initial_investment',
    'Capex', 'Annual Revenue' etc., by scoring keyword overlap after
    normalising punctuation. Each column can be assigned to only one field.
    """
    cols_norm = {col: _normalize_header(col) for col in df.columns}

    # 1) Score-based matching using semantic keywords.
    found: dict[str, str] = {}
    used: set[str] = set()
    for field in _FIELD_PRIORITY:
        keywords = _FIELD_KEYWORDS.get(field, [])
        best_col = None
        best_score = 0
        for col, norm in cols_norm.items():
            if col in used:
                continue
            score = sum(1 for kw in keywords if kw in norm)
            if score > best_score:
                best_score = score
                best_col = col
        if best_col is not None:
            found[field] = best_col
            used.add(best_col)

    # 2) Fill any remaining gaps using exact alias matches.
    cols_lower_flat = {c.lower().strip(): c for c in df.columns}
    for field_name, aliases in column_map.items():
        if field_name in found:
            continue
        for alias in aliases:
            if alias in cols_lower_flat:
                found[field_name] = cols_lower_flat[alias]
                break

    return found


def _fmt_currency(val: float) -> str:
    if val < 0:
        return f"(${abs(val):,.0f})"
    return f"${val:,.0f}"


def validate_project_inputs(data: dict[str, Any]) -> ValidationResult:
    result = ValidationResult(is_valid=True)

    required_fields = [
        "project_name",
        "project_life",
        "initial_investment",
        "annual_revenues",
        "operating_costs",
        "tax_rate",
        "discount_rate",
    ]

    for f in required_fields:
        if f not in data or data[f] is None:
            result.errors.append(f"Missing required field: '{f}'.")
            result.is_valid = False

    if not result.is_valid:
        return result

    name = str(data.get("project_name", "")).strip()
    if not name:
        result.errors.append("Project name cannot be empty.")
        result.is_valid = False

    life = data.get("project_life")
    if not isinstance(life, (int, float)) or life <= 0:
        result.errors.append(
            f"Project life must be a positive number. Received: {life}"
        )
        result.is_valid = False
    elif life > 100:
        result.warnings.append(
            f"Project life of {life} years is unusually long. Please verify."
        )
    elif life < 1:
        result.errors.append(
            f"Project life must be at least 1 year. Received: {life}"
        )
        result.is_valid = False

    investment = data.get("initial_investment")
    if not isinstance(investment, (int, float)):
        result.errors.append(
            f"Initial investment must be a number. Received: {investment}"
        )
        result.is_valid = False
    elif investment <= 0:
        result.errors.append(
            f"Initial investment must be positive. Received: {_fmt_currency(investment)}"
        )
        result.is_valid = False
    elif investment > 1e12:
        result.warnings.append(
            f"Initial investment of {_fmt_currency(investment)} is extremely large. Please verify."
        )

    revenues = data.get("annual_revenues")
    if not isinstance(revenues, (int, float)):
        result.errors.append(
            f"Annual revenues must be a number. Received: {revenues}"
        )
        result.is_valid = False
    elif revenues < 0:
        result.errors.append(
            f"Annual revenues cannot be negative. Received: {_fmt_currency(revenues)}"
        )
        result.is_valid = False
    elif revenues == 0:
        result.warnings.append("Annual revenues are zero. The project generates no income.")

    costs = data.get("operating_costs")
    if not isinstance(costs, (int, float)):
        result.errors.append(
            f"Operating costs must be a number. Received: {costs}"
        )
        result.is_valid = False
    elif costs < 0:
        result.errors.append(
            f"Operating costs cannot be negative. Received: {_fmt_currency(costs)}"
        )
        result.is_valid = False

    if isinstance(revenues, (int, float)) and isinstance(costs, (int, float)):
        if revenues > 0 and costs > revenues * 5:
            result.warnings.append(
                f"Operating costs ({_fmt_currency(costs)}) are more than 5x revenues ({_fmt_currency(revenues)}). Please verify."
            )

    tax_rate = data.get("tax_rate")
    if not isinstance(tax_rate, (int, float)):
        result.errors.append(
            f"Tax rate must be a number. Received: {tax_rate}"
        )
        result.is_valid = False
    elif tax_rate < 0 or tax_rate > 100:
        result.errors.append(
            f"Tax rate must be between 0% and 100%. Received: {tax_rate}%"
        )
        result.is_valid = False
    elif tax_rate > 60:
        result.warnings.append(
            f"Tax rate of {tax_rate}% is unusually high. Please verify."
        )

    discount_rate = data.get("discount_rate")
    if not isinstance(discount_rate, (int, float)):
        result.errors.append(
            f"Discount rate (WACC) must be a number. Received: {discount_rate}"
        )
        result.is_valid = False
    elif discount_rate <= 0:
        result.errors.append(
            f"Discount rate must be positive. Received: {discount_rate}%"
        )
        result.is_valid = False
    elif discount_rate > 100:
        result.errors.append(
            f"Discount rate cannot exceed 100%. Received: {discount_rate}%"
        )
        result.is_valid = False
    elif discount_rate > 50:
        result.warnings.append(
            f"Discount rate of {discount_rate}% is very high. Please verify."
        )

    wc = data.get("working_capital", 0)
    if not isinstance(wc, (int, float)):
        result.errors.append(
            f"Working capital must be a number. Received: {wc}"
        )
        result.is_valid = False

    tv = data.get("terminal_value", 0)
    if not isinstance(tv, (int, float)):
        result.errors.append(
            f"Terminal value must be a number. Received: {tv}"
        )
        result.is_valid = False

    financing_rate = data.get("financing_rate", discount_rate if isinstance(discount_rate, (int, float)) else 10)
    if not isinstance(financing_rate, (int, float)) or financing_rate <= 0:
        result.errors.append(
            f"Financing rate must be a positive number. Received: {financing_rate}"
        )
        result.is_valid = False

    reinvestment_rate = data.get("reinvestment_rate", discount_rate if isinstance(discount_rate, (int, float)) else 10)
    if not isinstance(reinvestment_rate, (int, float)) or reinvestment_rate <= 0:
        result.errors.append(
            f"Reinvestment rate must be a positive number. Received: {reinvestment_rate}"
        )
        result.is_valid = False

    growth_rate = data.get("growth_rate", 0)
    if not isinstance(growth_rate, (int, float)):
        result.errors.append(
            f"Growth rate must be a number. Received: {growth_rate}"
        )
        result.is_valid = False
    elif growth_rate < -50 or growth_rate > 100:
        result.warnings.append(
            f"Growth rate of {growth_rate}% is extreme. Please verify."
        )

    return result


def validate_csv_upload(df) -> tuple[ValidationResult, dict | None]:
    result = ValidationResult(is_valid=True)
    if df is None or df.empty:
        result.errors.append("Uploaded file is empty or could not be read.")
        result.is_valid = False
        return result, None

    column_map = {
        "project_name": ["project_name", "project name", "name"],
        "project_life": ["project_life", "project life", "life", "years", "project_life_years"],
        "initial_investment": ["initial_investment", "initial investment", "investment", "capex", "capital expenditure"],
        "annual_revenues": ["annual_revenues", "annual revenues", "revenues", "revenue"],
        "operating_costs": ["operating_costs", "operating costs", "costs", "operating expenses", "opex"],
        "tax_rate": ["tax_rate", "tax rate", "tax"],
        "discount_rate": ["discount_rate", "discount rate", "wacc", "required return"],
        "working_capital": ["working_capital", "working capital", "nwc", "net working capital"],
        "terminal_value": ["terminal_value", "terminal value", "tv", "salvage value"],
        "financing_rate": ["financing_rate", "financing rate"],
        "reinvestment_rate": ["reinvestment_rate", "reinvestment rate"],
        "growth_rate": ["growth_rate", "growth rate", "growth", "revenue growth"],
    }

    found = _match_columns(df, column_map)

    missing = [
        f
        for f in ("initial_investment", "annual_revenues", "operating_costs")
        if f not in found
    ]
    if missing:
        got = ", ".join(f'"{c}"' for c in df.columns)
        for f in missing:
            expected = ", ".join(_FRIENDLY_HEADERS[f])
            result.errors.append(
                f"Could not find a column for '{f}' in your file. "
                f"Columns present: {got}. "
                f"Recognised header examples: {expected}."
            )
        result.is_valid = False
        return result, None

    if not result.is_valid:
        return result, None

    row = df.iloc[0]
    data = {}

    data["project_name"] = str(row[found.get("project_name", "project_name")]) if "project_name" in found else "Uploaded Project"
    data["project_life"] = _safe_float(row[found["project_life"]]) if "project_life" in found else 10
    data["initial_investment"] = _safe_float(row[found["initial_investment"]])
    data["annual_revenues"] = _safe_float(row[found["annual_revenues"]])
    data["operating_costs"] = _safe_float(row[found["operating_costs"]])
    data["tax_rate"] = _safe_float(row[found.get("tax_rate", "")], default=25) if "tax_rate" in found else 25
    data["discount_rate"] = _safe_float(row[found.get("discount_rate", "")], default=10) if "discount_rate" in found else 10
    data["working_capital"] = _safe_float(row[found.get("working_capital", "")], default=0) if "working_capital" in found else 0
    data["terminal_value"] = _safe_float(row[found.get("terminal_value", "")], default=0) if "terminal_value" in found else 0
    data["financing_rate"] = _safe_float(row[found.get("financing_rate", "")], default=data["discount_rate"]) if "financing_rate" in found else data["discount_rate"]
    data["reinvestment_rate"] = _safe_float(row[found.get("reinvestment_rate", "")], default=data["discount_rate"]) if "reinvestment_rate" in found else data["discount_rate"]
    data["growth_rate"] = _safe_float(row[found.get("growth_rate", "")], default=0) if "growth_rate" in found else 0

    return validate_project_inputs(data), data


def _safe_float(val, default: float = 0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default
