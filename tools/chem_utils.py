from typing import Any, Dict, List, Optional

from pymatgen.core import Composition, Element


def parse_formula_stoichiometry(formula: str) -> Dict[str, float]:
    """Return element-to-amount map from a chemical formula."""
    comp = Composition(formula)
    return {str(symbol): float(amount) for symbol, amount in comp.get_el_amt_dict().items()}


def check_charge_balance(formula: str, oxidation_states: Dict[str, int]) -> Dict[str, Any]:
    """Check charge balance for a formula using user-provided oxidation states."""
    stoich = parse_formula_stoichiometry(formula)
    total_charge = 0.0

    for symbol, amount in stoich.items():
        if symbol not in oxidation_states:
            raise ValueError(f"Missing oxidation state for element: {symbol}")
        total_charge += amount * oxidation_states[symbol]

    return {
        "formula": formula,
        "total_charge": total_charge,
        "is_balanced": abs(total_charge) < 1e-8,
    }


def suggest_common_oxidation_states(formula: str) -> Dict[str, List[int]]:
    """List common oxidation states for each element in the formula."""
    stoich = parse_formula_stoichiometry(formula)
    suggestions: Dict[str, List[int]] = {}

    for symbol in stoich:
        el = Element(symbol)
        suggestions[symbol] = list(el.common_oxidation_states)

    return suggestions


def lookup_ionic_radius(symbol: str, oxidation_state: int) -> Optional[float]:
    """Get ionic radius (angstrom) from pymatgen if available."""
    el = Element(symbol)
    try:
        radius = el.ionic_radii.get(oxidation_state)
        return float(radius) if radius is not None else None
    except Exception:
        return None
