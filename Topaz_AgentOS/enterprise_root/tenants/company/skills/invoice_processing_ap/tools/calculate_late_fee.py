"""
Calculate late payment fee for overdue AP invoices.

Formula: late_fee = amount × (annual_rate / 365) × days_overdue

Reads JSON from stdin, writes JSON to stdout.
"""

TOOL_SPEC = {
    "name": "calculate_late_fee",
    "description": "Calculate the late payment penalty fee for an overdue invoice. Uses simple interest: amount × (annual_rate_pct / 100 / 365) × days_overdue. Returns the fee amount, daily rate, and total payable.",
    "parameters": {
        "amount": {
            "type": "float",
            "description": "Invoice amount in the original currency (e.g. 45000.0)"
        },
        "days_overdue": {
            "type": "int",
            "description": "Number of calendar days past the due date"
        },
        "annual_rate_pct": {
            "type": "float",
            "description": "Annual penalty interest rate as a percentage (e.g. 8.0 for 8%). Default: 8.0"
        }
    },
    "timeout": 10
}

import sys
import json

def main():
    data = json.load(sys.stdin)

    amount = float(data.get("amount", 0))
    days_overdue = int(data.get("days_overdue", 0))
    annual_rate_pct = float(data.get("annual_rate_pct", 8.0))

    if amount <= 0:
        json.dump({"error": "amount must be positive"}, sys.stdout)
        return
    if days_overdue < 0:
        json.dump({"error": "days_overdue cannot be negative"}, sys.stdout)
        return

    daily_rate = annual_rate_pct / 100.0 / 365.0
    late_fee = round(amount * daily_rate * days_overdue, 2)
    total_payable = round(amount + late_fee, 2)

    json.dump({
        "invoice_amount": amount,
        "days_overdue": days_overdue,
        "annual_rate_pct": annual_rate_pct,
        "daily_rate": round(daily_rate, 8),
        "late_fee": late_fee,
        "total_payable": total_payable,
        "currency_note": "Same currency as the input amount"
    }, sys.stdout)

if __name__ == "__main__":
    main()
