"""
Nexus Simulateur Business - moteur de simulation.
"""


def _float(value, default=0.0):
    """Convertit une valeur en nombre."""
    try:
        if value is None or value == "":
            return default

        return float(
            str(value)
            .strip()
            .replace(" ", "")
            .replace(",", ".")
        )

    except (TypeError, ValueError):
        return default


def _pct(value, default=0.0):
    """Normalise un pourcentage entre 0 et 100."""
    return min(
        100.0,
        max(0.0, _float(value, default))
    )


def simulate_business(
    capital,
    selling_price,
    purchase_cost,
    monthly_sales,
    fixed_costs=0,
    variable_cost_percent=0,
    employees=0,
    salary_per_employee=0,
    growth_rate=0,
    duration_months=12,
):
    """
    Effectue une simulation économique et financière d'un projet.
    """

    # =========================================================
    # NORMALISATION DES DONNEES
    # =========================================================

    capital = max(
        0.0,
        _float(capital)
    )

    selling_price = max(
        0.0,
        _float(selling_price)
    )

    purchase_cost = max(
        0.0,
        _float(purchase_cost)
    )

    monthly_sales = max(
        0.0,
        _float(monthly_sales)
    )

    fixed_costs = max(
        0.0,
        _float(fixed_costs)
    )

    variable_cost_percent = _pct(
        variable_cost_percent
    )

    employees = max(
        0,
        int(_float(employees))
    )

    salary_per_employee = max(
        0.0,
        _float(salary_per_employee)
    )

    growth_rate = _float(
        growth_rate
    )

    # Empêche une croissance inférieure à -100 %.
    growth_rate = max(
        -100.0,
        growth_rate
    )

    duration_months = max(
        1,
        min(
            120,
            int(_float(duration_months, 12))
        )
    )

    # =========================================================
    # VALIDATION
    # =========================================================

    errors = []

    if capital <= 0:
        errors.append(
            "Le capital disponible doit être supérieur à 0."
        )

    if selling_price <= 0:
        errors.append(
            "Le prix de vente doit être supérieur à 0."
        )

    if monthly_sales <= 0:
        errors.append(
            "Les ventes mensuelles prévues doivent être supérieures à 0."
        )

    if selling_price <= purchase_cost:
        errors.append(
            "Le prix de vente doit être supérieur au coût d'achat."
        )

    if not errors:
        contribution_test = (
            selling_price
            - purchase_cost
            - (
                selling_price
                * variable_cost_percent
                / 100
            )
        )

        if contribution_test <= 0:
            errors.append(
                "La marge contributive par unité est nulle ou négative."
            )

    if errors:
        return {
            "success": False,
            "errors": errors,
        }

    # =========================================================
    # COUTS
    # =========================================================

    salary_cost = (
        employees
        * salary_per_employee
    )

    fixed_total = (
        fixed_costs
        + salary_cost
    )

    variable_unit = (
        purchase_cost
        + (
            selling_price
            * variable_cost_percent
            / 100
        )
    )

    contribution = (
        selling_price
        - variable_unit
    )

    # =========================================================
    # RESULTATS MENSUELS
    # =========================================================

    revenue = (
        selling_price
        * monthly_sales
    )

    variable_cost_total = (
        monthly_sales
        * variable_unit
    )

    total_cost = (
        variable_cost_total
        + fixed_total
    )

    profit = (
        revenue
        - total_cost
    )

    margin = (
        contribution
        / selling_price
        * 100
        if selling_price
        else 0
    )

    net_margin = (
        profit
        / revenue
        * 100
        if revenue
        else 0
    )

    # =========================================================
    # SEUIL DE RENTABILITE
    # =========================================================

    break_even_units = (
        fixed_total / contribution
        if contribution > 0
        else None
    )

    break_even_revenue = (
        break_even_units
        * selling_price
        if break_even_units is not None
        else None
    )

    # =========================================================
    # INVESTISSEMENT
    # =========================================================

    payback = (
        capital / profit
        if profit > 0
        else None
    )

    annual_profit = (
        profit * 12
    )

    annual_roi = (
        annual_profit
        / capital
        * 100
        if capital
        else 0
    )

    # =========================================================
    # PROJECTION MENSUELLE
    # =========================================================

    projection = []

    sales = monthly_sales

    cumulative_profit = 0.0

    cash = capital

    for month in range(
        1,
        duration_months + 1
    ):

        if month > 1:
            sales *= (
                1
                + growth_rate / 100
            )

        sales = max(
            0.0,
            sales
        )

        monthly_revenue = (
            selling_price
            * sales
        )

        monthly_cost = (
            sales
            * variable_unit
            + fixed_total
        )

        monthly_profit = (
            monthly_revenue
            - monthly_cost
        )

        cumulative_profit += (
            monthly_profit
        )

        cash += (
            monthly_profit
        )

        projection.append(
            {
                "month": month,

                "sales": round(
                    sales,
                    2
                ),

                "revenue": round(
                    monthly_revenue,
                    2
                ),

                "cost": round(
                    monthly_cost,
                    2
                ),

                "profit": round(
                    monthly_profit,
                    2
                ),

                "cumulative_profit": round(
                    cumulative_profit,
                    2
                ),

                "cash": round(
                    cash,
                    2
                ),
            }
        )

    # =========================================================
    # TOTAUX DE LA SIMULATION
    # =========================================================

    total_revenue = sum(
        row["revenue"]
        for row in projection
    )

    total_cost = sum(
        row["cost"]
        for row in projection
    )

    total_profit = sum(
        row["profit"]
        for row in projection
    )

    projected_roi = (
        total_profit
        / capital
        * 100
        if capital
        else 0
    )

    ending_cash = (
        projection[-1]["cash"]
        if projection
        else capital
    )

    # =========================================================
    # SCENARIOS
    # =========================================================

    scenarios = {}

    for name, factor in (
        ("pessimiste", 0.75),
        ("realiste", 1.00),
        ("optimiste", 1.25),
    ):

        scenario_sales = (
            monthly_sales
            * factor
        )

        scenario_revenue = (
            selling_price
            * scenario_sales
        )

        scenario_variable_cost = (
            scenario_sales
            * variable_unit
        )

        scenario_profit = (
            scenario_revenue
            - scenario_variable_cost
            - fixed_total
        )

        scenarios[name] = {
            "monthly_sales": round(
                scenario_sales,
                2
            ),

            "monthly_revenue": round(
                scenario_revenue,
                2
            ),

            "monthly_profit": round(
                scenario_profit,
                2
            ),

            "annual_profit": round(
                scenario_profit * 12,
                2
            ),
        }

    # =========================================================
    # EVALUATION
    # =========================================================

    if profit <= 0:

        status = "NON RENTABLE"
        risk = "ÉLEVÉ"
        score = 25

    elif payback is not None and payback <= 6:

        status = "TRÈS RENTABLE"
        risk = "FAIBLE"
        score = 90

    elif (
        payback is not None
        and payback <= duration_months
    ):

        status = "RENTABLE"
        risk = "FAIBLE À MOYEN"
        score = 78

    else:

        status = "RENTABLE MAIS LENT"
        risk = "MOYEN"
        score = 60

    # =========================================================
    # AJUSTEMENT DU SCORE
    # =========================================================

    if margin >= 40:
        score += 5

    elif margin < 15:
        score -= 10

    if projected_roi >= 100:
        score += 5

    elif projected_roi < 20:
        score -= 10

    score = max(
        0,
        min(
            100,
            score
        )
    )

    # =========================================================
    # RECOMMANDATIONS
    # =========================================================

    recommendations = []

    if profit <= 0:

        recommendations.append(
            "Le modèle actuel n'est pas rentable : "
            "augmentez la marge, réduisez les coûts "
            "ou augmentez les ventes."
        )

    if margin < 20:

        recommendations.append(
            "La marge commerciale est faible : "
            "étudiez le prix de vente et le coût d'achat."
        )

    elif margin >= 40:

        recommendations.append(
            "La marge commerciale est intéressante."
        )

    if payback is not None:

        if payback <= 6:

            recommendations.append(
                "Le capital initial est récupéré rapidement."
            )

        elif payback <= 12:

            recommendations.append(
                "Le délai de récupération du capital "
                "reste raisonnable."
            )

        else:

            recommendations.append(
                "Le délai de récupération du capital "
                "doit être surveillé."
            )

    if growth_rate != 0:

        recommendations.append(
            "La projection intègre une variation "
            f"mensuelle des ventes de {growth_rate:.1f}%."
        )

    if employees:

        recommendations.append(
            "Le coût salarial simulé est de "
            f"{salary_cost:,.0f} par mois."
        )

    if monthly_sales < (
        break_even_units
        if break_even_units is not None
        else 0
    ):

        recommendations.append(
            "Le volume de ventes prévu est inférieur "
            "au seuil de rentabilité."
        )

    if not recommendations:

        recommendations.append(
            "La structure financière simulée est cohérente."
        )

    # =========================================================
    # RESULTAT FINAL
    # =========================================================

    return {

        "success": True,

        "inputs": {

            "capital": round(
                capital,
                2
            ),

            "selling_price": round(
                selling_price,
                2
            ),

            "purchase_cost": round(
                purchase_cost,
                2
            ),

            "monthly_sales": round(
                monthly_sales,
                2
            ),

            "fixed_costs": round(
                fixed_costs,
                2
            ),

            "variable_cost_percent": round(
                variable_cost_percent,
                2
            ),

            "employees": employees,

            "salary_per_employee": round(
                salary_per_employee,
                2
            ),

            "growth_rate": round(
                growth_rate,
                2
            ),

            "duration_months": duration_months,
        },

        "monthly": {

            "revenue": round(
                revenue,
                2
            ),

            "total_cost": round(
                total_cost,
                2
            ),

            "profit": round(
                profit,
                2
            ),

            "margin_rate": round(
                margin,
                2
            ),

            "net_margin_rate": round(
                net_margin,
                2
            ),

            "salary_cost": round(
                salary_cost,
                2
            ),
        },

        "break_even": {

            "units": (
                round(
                    break_even_units,
                    2
                )
                if break_even_units is not None
                else None
            ),

            "revenue": (
                round(
                    break_even_revenue,
                    2
                )
                if break_even_revenue is not None
                else None
            ),
        },

        "investment": {

            "payback_months": (
                round(
                    payback,
                    2
                )
                if payback is not None
                else None
            ),

            "annual_profit": round(
                annual_profit,
                2
            ),

            "annual_roi": round(
                annual_roi,
                2
            ),
        },

        "simulation": {

            "duration_months": duration_months,

            "total_revenue": round(
                total_revenue,
                2
            ),

            "total_cost": round(
                total_cost,
                2
            ),

            "total_profit": round(
                total_profit,
                2
            ),

            "projected_roi": round(
                projected_roi,
                2
            ),

            "ending_cash": round(
                ending_cash,
                2
            ),
        },

        "projection": projection,

        "scenarios": scenarios,

        "analysis": {

            "status": status,

            "risk": risk,

            "score": int(score),

            "recommendations": recommendations,
        },
    }


def build_business_report(result):
    """
    Génère un résumé texte exploitable par
    Nexus Intelligence et Rapport Nexus.
    """

    if not result.get("success"):

        return (
            "Simulation impossible : "
            "données invalides."
        )

    monthly = result["monthly"]

    investment = result["investment"]

    simulation = result["simulation"]

    analysis = result["analysis"]

    payback = investment.get(
        "payback_months"
    )

    payback_text = (
        f"{payback:.1f} mois"
        if payback is not None
        else "Non récupérable"
    )

    return (
        "RAPPORT NEXUS SIMULATEUR BUSINESS\n\n"

        f"Statut : {analysis['status']}\n"

        f"Risque : {analysis['risk']}\n"

        f"Score Nexus : "
        f"{analysis['score']}/100\n\n"

        f"CA mensuel : "
        f"{monthly['revenue']:,.0f}\n"

        f"Bénéfice mensuel : "
        f"{monthly['profit']:,.0f}\n"

        f"Marge : "
        f"{monthly['margin_rate']:.1f}%\n"

        f"Marge nette : "
        f"{monthly['net_margin_rate']:.1f}%\n"

        f"ROI annuel estimé : "
        f"{investment['annual_roi']:.1f}%\n"

        f"Bénéfice simulé : "
        f"{simulation['total_profit']:,.0f}\n"

        f"CA simulé : "
        f"{simulation['total_revenue']:,.0f}\n"

        f"Trésorerie finale : "
        f"{simulation['ending_cash']:,.0f}\n"

        f"Récupération du capital : "
        f"{payback_text}\n"
    )