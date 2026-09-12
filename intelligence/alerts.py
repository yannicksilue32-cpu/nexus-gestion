def safe_float(value, default=0):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return default


def generate_alerts(products, analysis):
    alerts = []

    # Stock faible
    for product in products:
        stock = safe_float(product.get("stock"))
        minimum = safe_float(product.get("min_stock"), 5)

        if stock <= minimum:
            alerts.append({
                "type": "stock",
                "level": "warning",
                "title": "Stock faible",
                "message": (
                    f"Le produit « {product.get('name', 'Produit')} » "
                    f"a seulement {stock:g} unité(s) en stock."
                ),
                "product": product.get("name", "Produit")
            })

    # Stock nul
    for product in products:
        stock = safe_float(product.get("stock"))

        if stock <= 0:
            alerts.append({
                "type": "stock",
                "level": "danger",
                "title": "Rupture de stock",
                "message": (
                    f"Le produit « {product.get('name', 'Produit')} » "
                    "est actuellement en rupture de stock."
                ),
                "product": product.get("name", "Produit")
            })

    # Marge faible
    margin = safe_float(analysis.get("margin"))

    if analysis.get("revenue", 0) > 0 and margin < 10:
        alerts.append({
            "type": "finance",
            "level": "warning",
            "title": "Marge faible",
            "message": (
                f"La marge estimée est de {margin:.1f} %. "
                "Les coûts doivent être surveillés."
            )
        })

    # Dépenses élevées
    revenue = safe_float(analysis.get("revenue"))
    expenses = safe_float(analysis.get("expenses"))

    if revenue > 0 and expenses > revenue * 0.5:
        alerts.append({
            "type": "finance",
            "level": "warning",
            "title": "Dépenses importantes",
            "message": (
                "Les dépenses représentent plus de 50 % "
                "du chiffre d'affaires analysé."
            )
        })

    return alerts