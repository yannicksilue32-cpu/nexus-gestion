from statistics import mean


def safe_float(value, default=0.0):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return default


def analyze_business(data):
    """
    Analyse générale de l'entreprise.

    data doit contenir :
        sales
        purchases
        expenses
        products

    Chaque élément de sales peut contenir :
        total
        date

    Chaque produit peut contenir :
        name
        stock
        price
        cost_price
        sold_quantity
    """

    sales = data.get("sales", [])
    purchases = data.get("purchases", [])
    expenses = data.get("expenses", [])
    products = data.get("products", [])

    revenue = sum(
        safe_float(s.get("total"))
        for s in sales
    )

    purchase_total = sum(
        safe_float(p.get("total"))
        for p in purchases
    )

    expense_total = sum(
        safe_float(e.get("amount", e.get("total")))
        for e in expenses
    )

    estimated_profit = revenue - purchase_total - expense_total

    margin = (
        (estimated_profit / revenue) * 100
        if revenue > 0
        else 0
    )

    stock_value = sum(
        safe_float(p.get("stock")) *
        safe_float(p.get("cost_price"))
        for p in products
    )

    products_low_stock = [
        p for p in products
        if safe_float(p.get("stock")) <=
        safe_float(p.get("min_stock"), 5)
    ]

    products_without_sales = [
        p for p in products
        if safe_float(p.get("sold_quantity")) == 0
    ]

    return {
        "revenue": round(revenue, 2),
        "purchases": round(purchase_total, 2),
        "expenses": round(expense_total, 2),
        "estimated_profit": round(estimated_profit, 2),
        "margin": round(margin, 2),
        "stock_value": round(stock_value, 2),
        "number_of_products": len(products),
        "number_of_sales": len(sales),
        "low_stock_count": len(products_low_stock),
        "unsold_products_count": len(products_without_sales),
    }