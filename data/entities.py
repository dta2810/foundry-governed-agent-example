"""Shared fictitious entities for Acme Beverages (used by the data generator)."""

MARKETS = [
    # market_id, market_name, region, currency
    ("CA", "California", "West", "USD"),
    ("TX", "Texas", "South Central", "USD"),
    ("IL", "Illinois", "Midwest", "USD"),
    ("GA", "Georgia", "Southeast", "USD"),
    ("NY", "New York", "Northeast", "USD"),
    ("AZ", "Arizona", "Southwest", "USD"),
    ("FL", "Florida", "Southeast", "USD"),
    ("NC", "North Carolina", "Southeast", "USD"),
]

BRANDS = {
    "Fizzo": "Carbonated soft drinks",
    "Aqua Pura": "Water",
    "Sunny Grove": "Juices",
    "Volt": "Energy drinks",
}

# sku, brand, product_name, pack_type, pack_size_ml, units_per_case, list_price_per_case_usd
PRODUCTS = [
    ("FZ-COLA-355C", "Fizzo", "Fizzo Cola 355ml Can", "Can", 355, 24, 11.50),
    ("FZ-COLA-600P", "Fizzo", "Fizzo Cola 600ml PET", "PET", 600, 12, 9.80),
    ("FZ-COLA-2000P", "Fizzo", "Fizzo Cola 2L PET", "PET", 2000, 6, 10.40),
    ("FZ-ZERO-355C", "Fizzo", "Fizzo Zero 355ml Can", "Can", 355, 24, 11.90),
    ("FZ-LIME-600P", "Fizzo", "Fizzo Lime 600ml PET", "PET", 600, 12, 9.60),
    ("AP-STILL-500P", "Aqua Pura", "Aqua Pura Still 500ml PET", "PET", 500, 24, 6.20),
    ("AP-STILL-1500P", "Aqua Pura", "Aqua Pura Still 1.5L PET", "PET", 1500, 12, 6.90),
    ("AP-SPARK-500G", "Aqua Pura", "Aqua Pura Sparkling 500ml Glass", "Glass", 500, 12, 12.80),
    ("SG-ORNG-1000T", "Sunny Grove", "Sunny Grove Orange 1L Tetra", "Tetra", 1000, 12, 14.40),
    ("SG-MANGO-330T", "Sunny Grove", "Sunny Grove Mango 330ml Tetra", "Tetra", 330, 24, 13.20),
    ("SG-APPL-1000T", "Sunny Grove", "Sunny Grove Apple 1L Tetra", "Tetra", 1000, 12, 14.10),
    ("VT-ORIG-473C", "Volt", "Volt Original 473ml Can", "Can", 473, 24, 26.40),
    ("VT-ZERO-473C", "Volt", "Volt Zero Sugar 473ml Can", "Can", 473, 24, 26.90),
    ("VT-TROP-250C", "Volt", "Volt Tropical 250ml Can", "Can", 250, 24, 19.20),
]

# Three distributors per market: one modern trade, one traditional trade, one on-premise
DISTRIBUTOR_TEMPLATES = [
    ("D1", "Modern Trade", "{city} Retail Partners"),
    ("D2", "Traditional Trade", "{city} Convenience Network"),
    ("D3", "On-Premise", "{city} HoReCa Supply"),
]
