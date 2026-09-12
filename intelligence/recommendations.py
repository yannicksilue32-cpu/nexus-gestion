def safe_float(value, default=0):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return default


def generate_recommendations(products, analysis):
    recommendations = []

    # Recommandations concernant les produits
    for product in products:
        name = product.get("name", "Produit")
        stock = safe_float(product.get("stock"))
        sold = safe_float(product.get("sold_quantity"))
        cost = safe_float(product.get("cost_price"))
        price = safe_float(product.get("price"))

        if stock <= safe_float(product.get("min_stock"), 5):
            recommendations.append({
                "type": "stock",
                "priority": "haute",
                "title": "Réapprovisionnement conseillé",
                "message": (
                    f"Envisagez de réapprovisionner « {name} » "
                    "car son stock est faible."
                )
            })

        if sold > 0 and price > cost:
            margin = ((price - cost) / price) * 100

            if margin >= 30:
                recommendations.append({
                    "type": "profitability",
                    "priority": "moyenne",
                    "title": "Produit rentable",
                    "message": (
                        f"« {name} » présente une marge unitaire "
                        f"intéressante d'environ {margin:.1f} %."
                    )
                })

    # Analyse générale
    revenue = safe_float(analysis.get("revenue"))
    expenses = safe_float(analysis.get("expenses"))
    profit = safe_float(analysis.get("estimated_profit"))

    if revenue > 0 and expenses > revenue * 0.5:
        recommendations.append({
            "type": "finance",
            "priority": "haute",
            "title": "Réduire les coûts",
            "message": (
                "Les dépenses sont importantes par rapport au "
                "chiffre d'affaires. Analysez les dépenses "
                "non essentielles."
            )
        })

    if profit > 0:
        recommendations.append({
            "type": "finance",
            "priority": "basse",
            "title": "Entreprise rentable",
            "message": (
                f"L'analyse actuelle indique un bénéfice "
                f"estimé de {profit:,.0f} FCFA."
            )
        })

    elif revenue > 0 and profit <= 0:
        recommendations.append({
            "type": "finance",
            "priority": "haute",
            "title": "Rentabilité à surveiller",
            "message": (
                "Le chiffre d'affaires est positif mais "
                "le résultat estimé est négatif ou nul. "
                "Analysez les coûts et les prix de vente."
            )
        })

    return recommendations