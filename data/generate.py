"""Generate the synthetic Acme Beverages pricing domain as local parquet files (dimensions + pricing facts + playbook)."""
import argparse
import os
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from entities import DISTRIBUTOR_TEMPLATES, MARKETS, PRODUCTS  # noqa: E402

SEED = 7
WEEKS = 52
END_WEEK = date(2026, 11, 2)  # Monday
CHANGE_IDX = WEEKS - 13      # planted stories start here: last 13 weeks vs the prior 13

SKUS = list(PRODUCTS)
CATEGORY = {"Fizzo": "Carbonated soft drinks", "Aqua Pura": "Water", "Sunny Grove": "Juices", "Volt": "Energy drinks"}
CHANNELS = [(code, ch) for code, ch, _ in DISTRIBUTOR_TEMPLATES]
RETAILER = {"Modern Trade": "BrightCart Supermarkets", "Traditional Trade": "QuickCorner Stores",
            "On-Premise": "Tablefare Restaurant Group"}
MARKUP = {"Modern Trade": 1.30, "Traditional Trade": 1.45, "On-Premise": 2.20}
MARKET_SCALE = {"CA": 3.0, "NY": 1.8, "AZ": 1.4, "TX": 1.0, "FL": 0.9, "IL": 0.8, "GA": 0.6, "NC": 0.5}
MARKET_PRICE = {"CA": 1.08, "NY": 1.10, "AZ": 0.98, "TX": 0.97, "FL": 1.00, "IL": 1.02, "GA": 0.96, "NC": 0.95}
CHANNEL_SCALE = {"Modern Trade": 1.0, "Traditional Trade": 1.3, "On-Premise": 0.5}
COGS_RATIO = {"Can": 0.50, "PET": 0.46, "Glass": 0.58, "Tetra": 0.55}  # of the Acme net price per unit

# true demand parameters by category; channel multiplies own elasticity
OWN_ELAST = {"Carbonated soft drinks": -1.9, "Water": -1.1, "Juices": -1.5, "Energy drinks": -1.3}
CROSS_ELAST = {"Carbonated soft drinks": 0.6, "Water": 0.8, "Juices": 0.4, "Energy drinks": 0.3}
CHANNEL_ELAST = {"Modern Trade": 1.1, "Traditional Trade": 0.9, "On-Premise": 0.6}
PROMO_VISIBILITY = 1.15
PROMO_FIXED_FEE = 40.0  # USD per market-week of feature/display, scaled by market size

# fictitious competitor brands, one per category
COMPETITOR = {"Fizzo": ("Northwind Fizz", "NW"), "Aqua Pura": ("Clearbrook Springs", "CB"),
              "Sunny Grove": ("Orchard Lane", "OL"), "Volt": ("Kinetic Charge", "KC")}
BAND = {"Carbonated soft drinks": (95, 105), "Water": (100, 110), "Juices": (98, 108), "Energy drinks": (95, 103)}

# guardrails by pack (market_id 'ALL' = company standard; market rows override)
GUARDRAILS = [
    ("GR-001", "ALL", "Can", 0.35, 0.42, 0.25),
    ("GR-002", "ALL", "PET", 0.35, 0.42, 0.25),
    ("GR-003", "ALL", "Glass", 0.30, 0.38, 0.20),
    ("GR-004", "ALL", "Tetra", 0.30, 0.37, 0.20),
    ("GR-005", "FL", "PET", 0.33, 0.40, 0.20),
]

# planted stories
STORY_INDEX = {"market_id": "TX", "sku": "FZ-COLA-355C", "price_step": 0.10}             # index drifts above band
STORY_PROMO = {"market_id": "GA", "sku": "FZ-ZERO-355C", "depth": 0.35, "start_idx": CHANGE_IDX + 3, "dur": 3}
STORY_MARGIN = {"market_id": "NY", "pack_type": "Glass", "cogs_step": 0.40}             # glass cost shock
STORY_HEADROOM = {"market_id": "CA", "sku": "AP-STILL-500P", "index_target": 0.88}      # priced below band

SECTIONS = [
    ("S1", 1, "Situational assessment", "Establish where volume, NSV and gross profit are moving and which packs breach margin guardrails."),
    ("S2", 2, "Competition & price positioning", "Check the price index against each competitive pair and its target band, and link drift to volume."),
    ("S3", 3, "Promo effectiveness", "Separate promotions that build gross profit from those that only buy volume."),
    ("S4", 4, "Scenarios & recommendation", "Quantify price moves with elasticities and land one evidence-backed recommendation."),
]
QUESTIONS = [
    ("Q01", "S1", 1, "How did volume, NSV and gross profit move in the last 13 weeks vs the prior 13 weeks?",
     "Direction and size of change per KPI, with the biggest contributing SKUs",
     "kpi_13w_vs_prior market total row (is_total) and SKU x pack x channel rows", "kpi_13w_vs_prior"),
    ("Q02", "S1", 2, "Which packs and SKUs explain the gross margin change?",
     "Ranked list of packs/SKUs by GP change and GM% change", "kpi_13w_vs_prior (gp_change_usd, gm_change_pts), pricing_kpis by pack_type, sku",
     "kpi_13w_vs_prior, pricing_kpis"),
    ("Q03", "S1", 3, "Is any pack below its margin guardrail?",
     "Packs below minimum or target GM% with the gap in points", "margin_guardrails output, guardrail thresholds", "margin_guardrails"),
    ("Q04", "S2", 1, "Where is our price index outside the target band of its competitive pair?",
     "Pairs above or below band, per channel, with current index", "price_index_vs_pairs output", "price_index_vs_pairs"),
    ("Q05", "S2", 2, "Did volume change where the price index drifted?",
     "Index change vs volume change for drifting pairs", "price_index_vs_pairs (index and volume, last vs prior 13 weeks)", "price_index_vs_pairs"),
    ("Q06", "S2", 3, "Where do we have price headroom against the pair?",
     "Pairs priced below band with stable volume", "price_index_vs_pairs output, pricing_kpis volume trend", "price_index_vs_pairs"),
    ("Q07", "S3", 1, "Which promotion depths build gross profit and which destroy it?",
     "GP uplift and ROI by depth band", "promo_depth_roi output", "promo_depth_roi"),
    ("Q08", "S3", 2, "Which promotions exceeded the maximum promo depth guardrail?",
     "Promotions above the pack maximum depth and their GP result", "promo_depth_roi output (max_promo_depth_pct)", "promo_depth_roi"),
    ("Q09", "S3", 3, "How much promoted volume was incremental vs subsidised baseline?",
     "Incremental share of promoted units per promotion", "promo_depth_roi output (baseline vs incremental units)", "promo_depth_roi"),
    ("Q10", "S4", 1, "What is the projected volume, NSV and GP impact of the proposed price change?",
     "Projected weekly change per market and channel",
     "price_scenario_grid (steps -10% to +5%), price_scenario_impact for one specific proposed change, elasticity estimates",
     "price_scenario_grid, price_scenario_impact"),
    ("Q11", "S4", 2, "Which price move brings the index back into band with the smallest GP loss?",
     "Compared scenarios with resulting index and GP change", "price_scenario_grid (is_min_cut_into_band, projected index, gp_change_usd_13w)",
     "price_scenario_grid"),
    ("Q12", "S4", 3, "What do we recommend, and what evidence supports it?",
     "One recommendation with evidence, expected impact and risks", "Answers to Q01-Q11; playbook_evidence covers all 12 questions in one call",
     "playbook_evidence, price_index_vs_pairs, margin_guardrails, promo_depth_roi, price_scenario_grid"),
]


def week_starts():
    return [END_WEEK - timedelta(weeks=WEEKS - 1 - i) for i in range(WEEKS)]


def comp_sku(sku):
    brand = next(p[1] for p in SKUS if p[0] == sku)
    return f"{COMPETITOR[brand][1]}-{sku.split('-', 1)[1]}"


def build(out_dir):
    rng = np.random.default_rng(SEED)
    os.makedirs(out_dir, exist_ok=True)
    weeks = week_starts()
    obs, cobs, pnl, promo_rows = [], [], [], []
    pairs, elast = [], []
    pair_id, promo_id = 1, 1

    # elasticity estimates: true value + estimation noise, sku x channel
    true_el = {}
    for sku, brand, *_ in SKUS:
        cat = CATEGORY[brand]
        for _, ch in CHANNELS:
            own = OWN_ELAST[cat] * CHANNEL_ELAST[ch] * rng.uniform(0.9, 1.1)
            cross = CROSS_ELAST[cat] * rng.uniform(0.85, 1.15)
            true_el[(sku, ch)] = (own, cross)
            elast.append((sku, ch, comp_sku(sku), round(own * rng.normal(1, 0.04), 2), round(cross * rng.normal(1, 0.06), 2),
                          round(float(rng.uniform(0.62, 0.88)), 2), WEEKS, "Log-log regression, 52 weekly obs", END_WEEK))

    for m, *_ in MARKETS:
        for sku, brand, pname, pack, size_ml, upc, list_case in SKUS:
            cat = CATEGORY[brand]
            low, high = BAND[cat]
            cbrand, _ = COMPETITOR[brand]
            csku = comp_sku(sku)
            pairs.append((f"CP-{pair_id:03d}", m, sku, cbrand, csku, f"{cbrand} {pname[len(brand) + 1:]}", low, high,
                          "Same category and pack size"))
            pair_id += 1

            # promo calendar for this market x sku (MT + TT only)
            promo_wk = {}
            events = []
            for _ in range(int(rng.integers(2, 4))):
                s = int(rng.integers(0, WEEKS - 5))
                d = int(rng.integers(2, 4))
                depth = float(rng.choice([0.10, 0.15, 0.20, 0.25]))
                if any(abs(s - e[0]) < 6 for e in events):
                    continue
                events.append((s, d, depth))
            if (m, sku) == (STORY_PROMO["market_id"], STORY_PROMO["sku"]):
                events = [(CHANGE_IDX - 20, 3, 0.15), (STORY_PROMO["start_idx"], STORY_PROMO["dur"], STORY_PROMO["depth"])]
            if (m, sku) == (STORY_INDEX["market_id"], STORY_INDEX["sku"]):
                events = [e for e in events if e[0] + e[1] < CHANGE_IDX]  # keep the drift window clean
            for s, d, depth in events:
                for k in range(s, min(s + d, WEEKS)):
                    promo_wk[k] = depth
            acc = {e[0]: {"base": 0.0, "units": 0.0, "cost": 0.0, "gp": 0.0, "base_gp": 0.0} for e in events}
            ev_of = {k: e[0] for e in events for k in range(e[0], min(e[0] + e[1], WEEKS))}

            unit_net = list_case / upc * MARKET_PRICE[m]
            for code, ch in CHANNELS:
                own, cross = true_el[(sku, ch)]
                base = 40 * MARKET_SCALE[m] * CHANNEL_SCALE[ch] * upc * rng.uniform(0.7, 1.3)
                ref_shelf = unit_net * MARKUP[ch]
                idx0 = rng.uniform(low + 1, high - 1) / 100
                if (m, sku) == (STORY_HEADROOM["market_id"], STORY_HEADROOM["sku"]):
                    idx0 = STORY_HEADROOM["index_target"]
                comp_ref = ref_shelf / idx0
                for i, ws in enumerate(weeks):
                    season = 1 + 0.04 * np.sin(2 * np.pi * (ws.timetuple().tm_yday / 365.0) - 1.2)
                    step = 1.0
                    if (m, sku) == (STORY_INDEX["market_id"], STORY_INDEX["sku"]) and i >= CHANGE_IDX:
                        step = 1 + STORY_INDEX["price_step"]
                    shelf = round(ref_shelf * step * rng.normal(1, 0.006), 2)
                    depth = promo_wk.get(i, 0.0) if ch != "On-Premise" else 0.0
                    promo = round(shelf * (1 - depth), 2) if depth else None
                    eff = promo if promo is not None else shelf
                    c_shelf = round(comp_ref * rng.normal(1, 0.006), 2)
                    c_promo = round(c_shelf * 0.85, 2) if ch != "On-Premise" and rng.random() < 0.06 else None
                    c_eff = c_promo if c_promo is not None else c_shelf

                    vol_reg = base * season * (shelf / ref_shelf) ** own * (c_eff / comp_ref) ** cross
                    vol = vol_reg * ((eff / shelf) ** own * PROMO_VISIBILITY if depth else 1.0)
                    units = int(max(0, round(vol * rng.normal(1, 0.05))))

                    cogs_unit = unit_net * COGS_RATIO[pack] / MARKET_PRICE[m]
                    if (m, pack) == (STORY_MARGIN["market_id"], STORY_MARGIN["pack_type"]) and i >= CHANGE_IDX:
                        cogs_unit *= 1 + STORY_MARGIN["cogs_step"]
                    nsv_unit = eff / MARKUP[ch]
                    nsv, cogs = units * nsv_unit, units * cogs_unit
                    did = f"{m}-{code}"
                    obs.append((ws, m, ch, did, RETAILER[ch], sku, pack, shelf, promo, units))
                    cobs.append((ws, m, ch, csku, c_shelf, c_promo))
                    pnl.append((ws, m, ch, sku, pack, units, round(nsv, 2), round(cogs, 2), round(nsv - cogs, 2)))

                    if depth:
                        a = acc[ev_of[i]]
                        a["base"] += vol_reg
                        a["units"] += units
                        a["cost"] += units * (shelf - eff) / MARKUP[ch]
                        a["gp"] += nsv - cogs
                        a["base_gp"] += vol_reg * (shelf / MARKUP[ch] - cogs_unit)

            for s, d, depth in events:
                a = acc[s]
                fee = PROMO_FIXED_FEE * MARKET_SCALE[m] * d
                promo_rows.append((f"PE-{promo_id:04d}", m, sku, pack, weeks[s], weeks[min(s + d, WEEKS) - 1], depth,
                                   "Modern Trade|Traditional Trade", int(round(a["base"])), int(round(a["units"] - a["base"])),
                                   round(a["cost"] + fee, 2), round(a["gp"] - a["base_gp"] - fee, 2)))
                promo_id += 1

    tables = {
        "dim_market": pd.DataFrame(MARKETS, columns=["market_id", "market_name", "region", "currency"]),
        "dim_product": pd.DataFrame([p + (CATEGORY[p[1]],) for p in PRODUCTS],
                                    columns=["sku", "brand", "product_name", "pack_type", "pack_size_ml", "units_per_case",
                                             "list_price_per_case_usd", "category"]),
        "price_observations": pd.DataFrame(obs, columns=["week_start", "market_id", "channel", "distributor_id", "retailer", "sku",
                                                         "pack_type", "shelf_price", "promo_price", "units"]),
        "competitor_prices": pd.DataFrame(cobs, columns=["week_start", "market_id", "channel", "competitor_sku", "shelf_price",
                                                         "promo_price"]),
        "competitor_pairs": pd.DataFrame(pairs, columns=["pair_id", "market_id", "sku", "competitor_brand", "competitor_sku",
                                                         "competitor_product_name", "target_price_index_low",
                                                         "target_price_index_high", "pair_basis"]),
        "promo_events": pd.DataFrame(promo_rows, columns=["promo_event_id", "market_id", "sku", "pack_type", "start_week",
                                                          "end_week", "discount_depth_pct", "channels", "baseline_units",
                                                          "incremental_units", "promo_cost", "gp_uplift"]),
        "elasticity_estimates": pd.DataFrame(elast, columns=["sku", "channel", "competitor_sku", "own_elasticity",
                                                             "cross_elasticity_vs_pair", "r_squared", "n_weeks", "method",
                                                             "estimated_at"]),
        "sku_pnl": pd.DataFrame(pnl, columns=["week_start", "market_id", "channel", "sku", "pack_type", "units", "nsv", "cogs", "gp"]),
        "margin_guardrail_thresholds": pd.DataFrame(
            [g + (date(2026, 1, 1), "Revenue Growth Management", "Commercial Guardrails.xlsx") for g in GUARDRAILS],
            columns=["guardrail_id", "market_id", "pack_type", "min_gm_pct", "target_gm_pct", "max_promo_depth_pct",
                     "effective_from", "owner_role", "source_file"]),
        "playbook_section": pd.DataFrame(SECTIONS, columns=["section_id", "section_order", "title", "objective"]),
        "playbook_question": pd.DataFrame(QUESTIONS, columns=["question_id", "section_id", "question_order", "question",
                                                              "outcome_required", "data_to_consider", "suggested_tool"]),
    }
    tables["promo_events"]["discount_depth_pct"] = tables["promo_events"]["discount_depth_pct"].astype(float)
    # INT columns in the DDL -> int32 parquet, so INSERT ... BY NAME needs no narrowing cast
    for name, cols in {"competitor_pairs": ["target_price_index_low", "target_price_index_high"], "elasticity_estimates": ["n_weeks"],
                       "playbook_section": ["section_order"], "playbook_question": ["question_order"]}.items():
        tables[name][cols] = tables[name][cols].astype("int32")
    for name, df in tables.items():
        df.to_parquet(os.path.join(out_dir, f"{name}.parquet"), index=False)
        print(f"{name}: {len(df)} rows")
    return tables


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "out"))
    build(ap.parse_args().out)
