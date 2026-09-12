# ============================================================
# NEXUS PRIX - moteur de calcul indépendant
# ============================================================
"""Moteur de calcul du prix conseillé de Nexus Gestion.

Le moteur ne dépend ni de Flask ni de SQLite : il peut donc être testé
séparément et réutilisé par Nexus Intelligence ou une future IA.
"""

from __future__ import annotations

from math import isfinite


def _number(value, name, minimum=0.0):
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        raise ValueError(f"{name} doit être un nombre valide.")
    if not isfinite(number):
        raise ValueError(f"{name} doit être un nombre fini.")
    if number < minimum:
        raise ValueError(f"{name} ne peut pas être inférieur à {minimum}.")
    return number


def calculate_nexus_price(
    purchase_price=0,
    target_margin=30,
    fixed_cost=0,
    variable_cost_percent=0,
    current_price=0,
    market_price=0,
    quantity=1,
):
    """Calcule un prix de vente conseillé.

    target_margin et variable_cost_percent sont des pourcentages du prix
    de vente. La formule évite donc le classique calcul incorrect du type
    coût * (1 + marge) lorsqu'on parle réellement de marge nette sur prix.
    """
    purchase = _number(purchase_price, "Le prix d'achat")
    margin = _number(target_margin, "La marge cible")
    fixed = _number(fixed_cost, "Les frais fixes")
    variable = _number(variable_cost_percent, "Les frais variables")
    current = _number(current_price, "Le prix actuel")
    market = _number(market_price, "Le prix du marché")
    qty = int(_number(quantity, "La quantité", 1))

    if margin >= 100:
        raise ValueError("La marge cible doit être strictement inférieure à 100 %.")
    if variable >= 100:
        raise ValueError("Les frais variables doivent être strictement inférieurs à 100 %.")
    if margin + variable >= 100:
        raise ValueError("Marge cible + frais variables doivent être inférieurs à 100 %.")

    # Coût fixe réparti sur les unités analysées.
    fixed_per_unit = fixed / qty
    total_cost = purchase + fixed_per_unit

    # Prix P tel que : P - coûts - frais variables(P) = marge(P).
    denominator = 1 - (variable / 100) - (margin / 100)
    recommended = total_cost / denominator if denominator > 0 else 0

    gross_profit = recommended - purchase
    contribution_profit = recommended * (1 - variable / 100) - total_cost
    actual_margin = (contribution_profit / recommended * 100) if recommended else 0

    markup = (gross_profit / purchase * 100) if purchase else 0

    current_profit = 0
    current_margin = 0
    if current > 0:
        current_profit = current * (1 - variable / 100) - total_cost
        current_margin = current_profit / current * 100

    price_gap_current = recommended - current if current > 0 else None
    price_gap_market = recommended - market if market > 0 else None

    if market > 0:
        market_position_percent = (recommended - market) / market * 100
        if recommended < market * 0.95:
            market_position = "Compétitif"
        elif recommended <= market * 1.05:
            market_position = "Aligné"
        else:
            market_position = "Au-dessus du marché"
    else:
        market_position_percent = None
        market_position = "Marché non renseigné"

    if current <= 0:
        price_action = "Définir un prix de vente"
    elif current < recommended * 0.95:
        price_action = "Augmenter le prix"
    elif current > recommended * 1.05:
        price_action = "Vérifier le risque de baisse des ventes"
    else:
        price_action = "Prix proche de l'objectif"

    return {
        "purchase_price": round(purchase, 2),
        "target_margin_percent": round(margin, 2),
        "fixed_cost": round(fixed, 2),
        "fixed_cost_per_unit": round(fixed_per_unit, 2),
        "variable_cost_percent": round(variable, 2),
        "total_cost_per_unit": round(total_cost, 2),
        "current_price": round(current, 2),
        "market_price": round(market, 2),
        "quantity": qty,
        "recommended_price": round(recommended, 2),
        "recommended_price_rounded": round(recommended),
        "gross_profit_per_unit": round(gross_profit, 2),
        "contribution_profit_per_unit": round(contribution_profit, 2),
        "target_margin_achieved_percent": round(actual_margin, 2),
        "markup_percent": round(markup, 2),
        "current_profit_per_unit": round(current_profit, 2),
        "current_margin_percent": round(current_margin, 2),
        "price_gap_current": round(price_gap_current, 2) if price_gap_current is not None else None,
        "price_gap_market": round(price_gap_market, 2) if price_gap_market is not None else None,
        "market_position_percent": round(market_position_percent, 2) if market_position_percent is not None else None,
        "market_position": market_position,
        "price_action": price_action,
        "recommended_total_revenue": round(recommended * qty, 2),
        "recommended_total_profit": round(contribution_profit * qty, 2),
    }


def build_nexus_price_recommendation(result):
    """Transforme le calcul en recommandation lisible pour Nexus Intelligence."""
    price = result["recommended_price_rounded"]
    margin = result["target_margin_percent"]
    action = result["price_action"]

    messages = [
        f"Prix conseillé : {price:,.0f} FCFA pour viser environ {margin:.1f} % de marge cible.".replace(",", " "),
        f"Coût total estimé par unité : {result['total_cost_per_unit']:,.0f} FCFA.".replace(",", " "),
        f"Bénéfice contributif estimé : {result['contribution_profit_per_unit']:,.0f} FCFA/unité.".replace(",", " "),
    ]

    if result["current_price"] > 0:
        gap = abs(result["price_gap_current"])
        if result["price_gap_current"] > 0:
            messages.append(f"Le prix actuel est environ {gap:,.0f} FCFA sous le prix conseillé.".replace(",", " "))
        elif result["price_gap_current"] < 0:
            messages.append(f"Le prix actuel est environ {gap:,.0f} FCFA au-dessus du prix conseillé.".replace(",", " "))
        else:
            messages.append("Le prix actuel correspond au prix conseillé.")

    if result["market_price"] > 0:
        if result["market_position"] == "Au-dessus du marché":
            messages.append("Attention : le prix conseillé dépasse le prix du marché renseigné. Vérifier la valeur perçue avant une hausse.")
        elif result["market_position"] == "Compétitif":
            messages.append("Le prix conseillé reste inférieur au prix du marché renseigné.")
        else:
            messages.append("Le prix conseillé est globalement aligné sur le marché renseigné.")

    return {
        "title": action,
        "summary": " ".join(messages),
        "priority": "high" if result["current_price"] > 0 and result["current_price"] < result["recommended_price"] * 0.90 else "normal",
    }
