# app/plans.py
# Configuration des forfaits pour Fedapay
FEDAPAY_PLANS = {
    'pro_monthly': {'amount': 3300, 'plan_name': 'pro', 'duration_days': 30},
    'pro_annual': {'amount': 32800, 'plan_name': 'pro', 'duration_days': 365},
    'business_monthly': {'amount': 6600, 'plan_name': 'business', 'duration_days': 30},
    'business_annual': {'amount': 65600, 'plan_name': 'business', 'duration_days': 365}
}
