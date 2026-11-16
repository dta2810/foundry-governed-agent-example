"""Local checks: shapes, keys, the planted data stories and SQL rendering. Run: pytest -q"""
import os
import sys

import pandas as pd
import pyarrow.parquet as pq
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "data"))
import generate as G  # noqa: E402
from entities import MARKETS, PRODUCTS  # noqa: E402


@pytest.fixture(scope="module")
def out(tmp_path_factory):
    d = tmp_path_factory.mktemp("pricing")
    G.build(str(d))
    return d


@pytest.fixture(scope="module")
def t(out):
    return {f[:-8]: pd.read_parquet(out / f) for f in os.listdir(out) if f.endswith(".parquet")}


def windows(df, col="week_start"):
    wk = sorted(df[col].unique())
    return set(wk[-13:]), set(wk[-26:-13])


def test_shapes_and_keys(t, out):
    n = len(MARKETS) * 3 * len(G.SKUS) * G.WEEKS
    assert len(t["price_observations"]) == n == len(t["sku_pnl"]) == len(t["competitor_prices"])
    assert t["price_observations"].week_start.nunique() == 52
    assert max(t["price_observations"].week_start) == G.END_WEEK
    assert set(t["price_observations"].market_id) == {m[0] for m in MARKETS}
    assert set(t["price_observations"].sku) <= {p[0] for p in PRODUCTS}
    assert not t["price_observations"].sku.str.startswith("HB-").any()  # no alcohol in this domain
    assert set(t["price_observations"].distributor_id) == {f"{m[0]}-D{i}" for m in MARKETS for i in (1, 2, 3)}
    assert not t["price_observations"].duplicated(["week_start", "market_id", "channel", "sku"]).any()
    assert not t["competitor_prices"].duplicated(["week_start", "market_id", "channel", "competitor_sku"]).any()
    assert not t["competitor_pairs"].duplicated(["market_id", "sku"]).any()
    assert set(t["competitor_pairs"].competitor_sku) == set(t["competitor_prices"].competitor_sku)
    assert len(t["elasticity_estimates"]) == len(G.SKUS) * 3
    assert (t["elasticity_estimates"].own_elasticity < 0).all() and (t["elasticity_estimates"].cross_elasticity_vs_pair > 0).all()
    assert len(t["playbook_question"]) == 12 and t["playbook_question"].section_id.nunique() == 4
    assert set(t["playbook_question"].section_id) <= set(t["playbook_section"].section_id)
    assert set(t["dim_product"].sku) == {p[0] for p in PRODUCTS} and t["dim_product"].category.notna().all()
    assert set(t["dim_market"].market_id) == {m[0] for m in MARKETS}


def test_nullable_promo_price_is_null_in_parquet(out):
    col = pq.read_table(out / "price_observations.parquet").column("promo_price")
    assert 0 < col.null_count < len(col)


def test_pnl_consistent(t):
    p = t["sku_pnl"]
    assert ((p.nsv - p.cogs - p.gp).abs() < 0.02).all()
    assert (p.units >= 0).all()


def price_index(t, market, sku):
    o = t["price_observations"].merge(t["competitor_pairs"], on=["market_id", "sku"]).merge(
        t["competitor_prices"], on=["week_start", "market_id", "channel", "competitor_sku"], suffixes=("", "_c"))
    o = o[(o.market_id == market) & (o.sku == sku)]
    last, prior = windows(o)
    idx = {k: 100 * (d.shelf_price * d.units).sum() / (d.shelf_price_c * d.units).sum()
           for k, d in (("last", o[o.week_start.isin(last)]), ("prior", o[o.week_start.isin(prior)]))}
    vol = o[o.week_start.isin(last)].units.sum() / o[o.week_start.isin(prior)].units.sum() - 1
    return idx, vol, o.target_price_index_low.iloc[0], o.target_price_index_high.iloc[0]


def test_story_index_drift_drops_volume(t):
    idx, vol, low, high = price_index(t, "TX", "FZ-COLA-355C")
    assert low <= idx["prior"] <= high and idx["last"] > high
    assert vol < -0.15


def test_story_price_headroom(t):
    idx, vol, low, _ = price_index(t, "CA", "AP-STILL-500P")
    assert idx["last"] < low and vol > -0.05


def test_story_deep_promo_destroys_gp(t):
    pe = t["promo_events"]
    ga = pe[(pe.market_id == "GA") & (pe.sku == "FZ-ZERO-355C")].set_index("discount_depth_pct")
    assert ga.loc[0.35, "incremental_units"] > ga.loc[0.15, "incremental_units"]
    assert ga.loc[0.35, "gp_uplift"] < 0 < ga.loc[0.15, "gp_uplift"]
    by_depth = pe.groupby("discount_depth_pct").gp_uplift.mean()
    assert by_depth.loc[0.10] > 0 > by_depth.loc[0.25]


def test_story_pack_below_guardrail(t):
    p = t["sku_pnl"]
    last, prior = windows(p)
    g = p[p.week_start.isin(last)].groupby(["market_id", "pack_type"])[["nsv", "gp"]].sum()
    gm = g.gp / g.nsv
    ref = t["margin_guardrail_thresholds"]
    min_glass = ref[(ref.market_id == "ALL") & (ref.pack_type == "Glass")].min_gm_pct.iloc[0]
    assert gm.loc[("NY", "Glass")] < min_glass
    others = gm.drop(("NY", "Glass"))
    mins = others.index.map(lambda k: ref[(ref.pack_type == k[1]) & (ref.market_id.isin([k[0], "ALL"]))]
                            .assign(o=lambda r: r.market_id.eq("ALL")).sort_values("o").min_gm_pct.iloc[0])
    assert (others.values >= mins.values).all()


def test_sql_renders_and_python_udf_compiles():
    sys.path.insert(0, os.path.join(HERE, "..", "setup"))
    import config as C
    import run_setup as R
    from sqlrun import statements
    p = C.sql_params() | {"catalog": "c", "env": "t", "trace_table": "a.b.c", "workspace_id": "1", "m365_folder": "f",
                          "agent_client_id": "x", "agent_sp_app_id": "y", "user_email": "u@x", "folder_path": "f",
                          "drive_id": "b!drive", "policy_doc_id": "d", "guardrails_xlsx_id": "g", "draft_clause": "",
                          "sp_app_id": "y"}
    for f in R.SQL.values():
        for stmt in statements(os.path.join(R.HERE, "sql", f), p):
            assert "${" not in stmt, (f, stmt[:80])
            if "LANGUAGE PYTHON" in stmt:
                body = stmt.split("AS $$", 1)[1].rsplit("$$", 1)[0]
                compile("def _f(p_price_change_pct, p_own_elasticity, p_cross_elasticity, p_competitor_price_change_pct):\n"
                        + "\n".join("    " + line for line in body.strip().splitlines()), "udf", "exec")
    fns = [s for s in statements(os.path.join(R.HERE, "sql", "30_functions.sql"), p) if s.startswith("CREATE OR REPLACE FUNCTION")]
    assert len(fns) == 9
    assert all("SQL SECURITY DEFINER" in s for s in fns if "LANGUAGE PYTHON" not in s)


def test_agent_templates_render(monkeypatch):
    sys.path.insert(0, os.path.join(HERE, "..", "infra", "foundry"))
    import _common
    for k, v in {"CATALOG": "c", "SCHEMA": "s", "M365_DRIVE_ID": "b!drive", "M365_POLICY_DOC_ID": "d", "M365_GUARDRAILS_ID": "g"}.items():
        monkeypatch.setattr(_common.C, k, v)
    cfg = {"sql_connection": "sc", "m365_connection": "mc", "sql_toolbox": "st", "m365_toolbox": "mt"}
    for name in ("agent.yaml", "agent.naive.yaml"):
        a = _common.render_agent(os.path.join(HERE, "..", "infra", "foundry", name), cfg)
        text = str(a)
        assert "${" not in text and "c.s" in text and a["tools"][0]["connection"] == "sc"
        assert all(n.startswith(("st___", "mt___")) for t in a["tools"] for n in t["require_approval"]["never"]["tool_names"])
