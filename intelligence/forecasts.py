from statistics import mean


def safe_float(value, default=0):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return default


def forecast_sales(sales, periods=7):
    """
    Prévision simple basée sur la moyenne
    des ventes disponibles.

    Ce n'est pas encore un modèle IA avancé.
    C'est volontairement une première version
    robuste et sans API payante.
    """

    if not sales:
        return {
            "average_sale": 0,
            "forecast": 0,
            "confidence": "faible",
            "message": "Pas assez de données pour établir une prévision."
        }

    values = [
        safe_float(s.get("total"))
        for s in sales
    ]

    values = [v for v in values if v >= 0]

    if not values:
        return {
            "average_sale": 0,
            "forecast": 0,
            "confidence": "faible",
            "message": "Pas assez de données."
        }

    average_sale = mean(values)

    forecast = average_sale * periods

    if len(values) >= 30:
        confidence = "élevée"
    elif len(values) >= 10:
        confidence = "moyenne"
    else:
        confidence = "faible"

    return {
        "average_sale": round(average_sale, 2),
        "forecast": round(forecast, 2),
        "confidence": confidence,
        "message": (
            f"Le chiffre d'affaires prévisionnel sur "
            f"{periods} périodes est d'environ "
            f"{forecast:,.0f} FCFA."
        )
    }