"""
Cotonil - Demand Forecasting Engine (HVIA Task 3)
=================================================
Forecast units for every product x branch, monthly, 3 months ahead.

    python forecasting_engine.py --data data --out outputs/forecasting

Reads  : sales_order_items, sales_orders, products_catalog, branches,
         marketing_campaigns   (parquet, or csv for sales_order_items)
Writes : forecast.parquet, backtest.parquet, accuracy.parquet, history.parquet,
         seasonality.parquet, promo_effect.parquet, camp_effect.parquet,
         importance.parquet, meta.json

Method
------
* Unit of analysis: product x branch x month (zeros filled after the series can exist).
* Direct multi-horizon LightGBM (h = 1..3): one model, "h" is a feature, so no
  error accumulation from recursive forecasting.
* Features known at the forecast origin: lags, rolling means, activity, age.
* Features of the target month: calendar (month, Ramadan, Eids), discount rate,
  campaign spend (same governorate+audience, national audience, governorate), price.
  For future months these are PLAN INPUTS: discount = last-6-months average of the
  series, campaign spend = same month last year.
* Three models: Tweedie (point forecast), quantile 0.1 and 0.9 (range).
* Backtest: train on everything up to HOLDOUT months before the end, test on the
  last HOLDOUT months, compare with seasonal-naive and 3-month-average baselines.
"""
import argparse
import json
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm as lgb

warnings.filterwarnings("ignore")

HORIZON = 3          # months ahead
HOLDOUT = 6          # months kept for the accuracy test
TRAIN_MONTHS = 36    # how many target months the model trains on
BAD_STATUS = "cancel|fail|void|reject"
KEYS = ["branch_id", "product_id"]

RAMADAN_START = ["2018-05-16", "2019-05-06", "2020-04-24", "2021-04-13", "2022-04-02",
                 "2023-03-23", "2024-03-11", "2025-03-01", "2026-02-18", "2027-02-08"]
EID_ADHA = ["2018-08-21", "2019-08-11", "2020-07-31", "2021-07-20", "2022-07-09",
            "2023-06-28", "2024-06-16", "2025-06-06", "2026-05-27", "2027-05-16"]

CATS = ["branch_id", "product_id", "category", "audience", "gov", "loc_type"]
ORIGIN_COLS = ["l0", "l1", "l2", "l5", "l11", "r3", "r6", "r12", "nz12", "disc_r6", "age"]
TARGET_COLS = ["disc_rate", "s12", "s24", "c_ga", "c_a", "c_g", "price"]
CAL_COLS = ["moy", "dim", "ram", "eid_f", "eid_a", "ram_next"]
FEATURES = ORIGIN_COLS + ["h"] + TARGET_COLS + CAL_COLS + CATS


# --------------------------------------------------------------------------- utils
def to_month(mi):
    mi = pd.Series(mi)
    return pd.to_datetime(pd.DataFrame({"year": mi // 12, "month": mi % 12 + 1, "day": 1}))


def overlap(s, e, ms, me):
    return max(0, (min(e, me) - max(s, ms)).days + 1)


def read(data, name, **kw):
    p = data / f"{name}.parquet"
    if p.exists():
        return pd.read_parquet(p, **kw)
    return pd.read_csv(data / f"{name}.csv", usecols=kw.get("columns"))


# --------------------------------------------------------------------------- data
def load_sales(data):
    cols = ["sales_order_id", "order_date", "branch_id", "product_id",
            "quantity", "gross_line_EGP", "discount_line_EGP"]
    items = read(data, "sales_order_items", columns=cols)
    orders = read(data, "sales_orders", columns=["sales_order_id", "status"])
    print("order status counts:\n", orders.status.value_counts().to_string())
    bad = orders.loc[orders.status.astype(str).str.lower().str.contains(BAD_STATUS), "sales_order_id"]
    items = items[~items.sales_order_id.isin(set(bad))]
    d = pd.to_datetime(items.order_date)
    mx = d.max()
    mi_max = mx.year * 12 + mx.month - 1
    last_full = mi_max if mx.is_month_end else mi_max - 1   # drop the partial last month
    items["mi"] = d.dt.year * 12 + d.dt.month - 1
    items = items[items.mi <= last_full]
    print(f"data ends {mx.date()} -> last full month = {to_month([last_full])[0]:%Y-%m}")
    agg = items.groupby(KEYS + ["mi"], as_index=False).agg(
        units=("quantity", "sum"), gross=("gross_line_EGP", "sum"), disc=("discount_line_EGP", "sum"))
    return agg, last_full


def campaign_tables(camp, last_full):
    rows = []
    for r in camp.itertuples(index=False):
        s, e = pd.Timestamp(r.start_date), pd.Timestamp(r.end_date)
        days = (e - s).days + 1
        for p in pd.period_range(s, e, freq="M"):
            ov = overlap(s, e, p.start_time, p.end_time.normalize())
            rows.append((p.year * 12 + p.month - 1, r.governorate_ar, r.target_audience,
                         r.spend_EGP * ov / days))
    c = pd.DataFrame(rows, columns=["mi", "gov", "audience", "spend"])
    c = c[c.mi <= last_full]
    fut = []
    for t in range(last_full + 1, last_full + HORIZON + 1):      # plan: same month last year
        x = c[c.mi == t - 12].copy()
        x["mi"] = t
        fut.append(x)
    c = pd.concat([c] + fut)
    c_ga = c.groupby(["mi", "gov", "audience"], as_index=False).spend.sum().rename(columns={"spend": "c_ga"})
    c_a = c.groupby(["mi", "audience"], as_index=False).spend.sum().rename(columns={"spend": "c_a"})
    c_g = c.groupby(["mi", "gov"], as_index=False).spend.sum().rename(columns={"spend": "c_g"})
    return c_ga, c_a, c_g


def calendar(lo, hi):
    def counts(ms):
        me = ms + pd.offsets.MonthEnd(0)
        ram = ef = ea = 0
        for d in RAMADAN_START:
            s = pd.Timestamp(d)
            e = s + pd.Timedelta(days=29)
            ram += overlap(s, e, ms, me)
            ef += overlap(e + pd.Timedelta(days=1), e + pd.Timedelta(days=3), ms, me)
        for d in EID_ADHA:
            s = pd.Timestamp(d)
            ea += overlap(s, s + pd.Timedelta(days=3), ms, me)
        return ram, ef, ea, me.day

    out = []
    for mi in range(lo, hi + 2):
        ms = pd.Timestamp(year=mi // 12, month=mi % 12 + 1, day=1)
        ram, ef, ea, dim = counts(ms)
        out.append(dict(mi=mi, moy=ms.month, dim=dim, ram=ram, eid_f=ef, eid_a=ea))
    cal = pd.DataFrame(out)
    cal["ram_next"] = cal.ram.shift(-1)
    return cal.iloc[:-1]


def build_panel(data):
    agg, last_full = load_sales(data)
    prod = read(data, "products_catalog", columns=["product_id", "category_en", "audience", "listed_price_EGP"]
                ).rename(columns={"category_en": "category", "listed_price_EGP": "price"})
    br = read(data, "branches", columns=["branch_id", "governorate_ar", "retail_location_type"]
              ).rename(columns={"governorate_ar": "gov", "retail_location_type": "loc_type"})
    camp = read(data, "marketing_campaigns",
                columns=["start_date", "end_date", "governorate_ar", "target_audience", "spend_EGP"])

    # grid: a series exists from max(first sale of the branch, first sale of the product)
    first_b = agg.groupby("branch_id").mi.min()
    first_p = agg.groupby("product_id").mi.min()
    ser = agg[KEYS].drop_duplicates().reset_index(drop=True)
    ser["start"] = np.maximum(ser.branch_id.map(first_b), ser.product_id.map(first_p))
    months = pd.DataFrame({"mi": np.arange(agg.mi.min(), last_full + HORIZON + 1)})
    panel = ser.merge(months, how="cross")
    panel = panel[panel.mi >= panel.start].drop(columns="start")
    panel = panel.merge(agg, on=KEYS + ["mi"], how="left")
    fut = panel.mi > last_full
    panel.loc[~fut, ["units", "gross", "disc"]] = panel.loc[~fut, ["units", "gross", "disc"]].fillna(0)
    panel["disc_rate"] = np.where(panel.gross > 0, panel.disc / panel.gross, 0.0)
    panel = panel.sort_values(KEYS + ["mi"]).reset_index(drop=True)
    fut = panel.mi > last_full

    # plan discount for future months = average of the last 6 real months
    plan = (panel[panel.mi.between(last_full - 5, last_full)]
            .groupby(KEYS, as_index=False).disc_rate.mean().rename(columns={"disc_rate": "plan_disc"}))
    pd_ = panel.loc[fut, KEYS].merge(plan, on=KEYS, how="left").plan_disc.fillna(0).values
    panel.loc[fut, "disc_rate"] = pd_

    panel = panel.merge(prod, on="product_id", how="left").merge(br, on="branch_id", how="left")
    c_ga, c_a, c_g = campaign_tables(camp, last_full)
    panel = (panel.merge(c_ga, on=["mi", "gov", "audience"], how="left")
                  .merge(c_a, on=["mi", "audience"], how="left")
                  .merge(c_g, on=["mi", "gov"], how="left"))
    for c in ["c_ga", "c_a", "c_g"]:
        panel[c] = np.log1p(panel[c].fillna(0))
    panel = panel.sort_values(KEYS + ["mi"]).reset_index(drop=True)

    # origin-side features
    g = panel.groupby(KEYS, sort=False).units
    panel["l0"] = panel.units
    for k in (1, 2, 5, 11):
        panel[f"l{k}"] = g.shift(k)
    for w in (3, 6, 12):
        panel[f"r{w}"] = g.rolling(w, min_periods=1).mean().reset_index(level=[0, 1], drop=True)
    panel["_nz"] = (panel.units > 0).astype(float)
    panel["nz12"] = (panel.groupby(KEYS, sort=False)._nz.rolling(12, min_periods=1).sum()
                     .reset_index(level=[0, 1], drop=True))
    panel["disc_r6"] = (panel.groupby(KEYS, sort=False).disc_rate.rolling(6, min_periods=1).mean()
                        .reset_index(level=[0, 1], drop=True))
    panel["age"] = panel.mi - panel.groupby(KEYS, sort=False).mi.transform("min")
    # target-side seasonal memory
    panel["s12"] = g.shift(12)
    panel["s24"] = g.shift(24)
    cal = calendar(int(panel.mi.min()), int(panel.mi.max()))
    levels = {c: sorted(panel[c].dropna().unique()) for c in CATS}
    return panel, cal, last_full, levels


def make_rows(panel, cal, h, levels):
    o = panel[KEYS + ["mi"] + ORIGIN_COLS].copy()
    o["t"] = o.mi + h
    t = panel[KEYS + ["mi", "units"] + TARGET_COLS + ["category", "audience", "gov", "loc_type"]
              ].rename(columns={"mi": "t"})
    d = o.merge(t, on=KEYS + ["t"], how="inner")
    d["h"] = h
    d = d.merge(cal.rename(columns={"mi": "t"}), on="t", how="left")
    for c in CATS:
        d[c] = pd.Categorical(d[c], categories=levels[c])
    return d


# --------------------------------------------------------------------------- model
def fit(train):
    X, y = train[FEATURES], train.units
    p = dict(n_estimators=400, learning_rate=0.05, num_leaves=63, min_child_samples=40,
             subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1, n_jobs=-1)
    mean = lgb.LGBMRegressor(objective="tweedie", tweedie_variance_power=1.3, **p).fit(X, y)
    lo = lgb.LGBMRegressor(objective="quantile", alpha=0.1, **p).fit(X, y)
    hi = lgb.LGBMRegressor(objective="quantile", alpha=0.9, **p).fit(X, y)
    return mean, lo, hi


def predict(models, d):
    X = d[FEATURES]
    f = np.clip(models[0].predict(X), 0, None)
    lo = np.clip(np.minimum(models[1].predict(X), f), 0, None)
    hi = np.maximum(models[2].predict(X), f)
    return f, lo, hi


def wape(a, f):
    return float(np.abs(a - f).sum() / max(a.sum(), 1e-9))


def bias(a, f):
    return float((f.sum() - a.sum()) / max(a.sum(), 1e-9))


def accuracy_table(bt):
    levels = {"منتج × فرع × شهر": KEYS, "منتج × شهر": ["product_id"], "فرع × شهر": ["branch_id"],
              "فئة × شهر": ["category"], "الإجمالي × شهر": []}
    out = []
    for h in [0] + list(range(1, HORIZON + 1)):          # 0 = all horizons
        sub = bt if h == 0 else bt[bt.h == h]
        for name, k in levels.items():
            a = sub.groupby(k + ["t"], observed=True)[["units", "forecast", "s12", "r3"]].sum()
            out.append(dict(level=name, h=h, n=len(a), actual=float(a.units.sum()),
                            wape_model=wape(a.units, a.forecast), wape_seasonal_naive=wape(a.units, a.s12),
                            wape_avg3=wape(a.units, a.r3), bias_model=bias(a.units, a.forecast)))
        out[-len(levels)]["coverage_p10_p90"] = float(((sub.units >= sub.p10) & (sub.units <= sub.p90)).mean())
    return pd.DataFrame(out)


def seasonality_and_promo(panel, last_full):
    hist = panel[panel.mi <= last_full].copy()
    cm = hist.groupby(["category", "mi"], observed=True, as_index=False).units.sum()
    cm["year"], cm["moy"] = cm.mi // 12, cm.mi % 12 + 1
    cm = cm[cm.groupby(["category", "year"]).moy.transform("nunique") == 12]   # full years only
    cm["idx"] = cm.units / cm.groupby(["category", "year"]).units.transform("mean")
    seas = cm.groupby(["category", "moy"], as_index=False).idx.mean()

    hist["rel"] = hist.units / hist.groupby(KEYS).units.transform("mean").replace(0, np.nan)
    sell = hist[hist.units > 0]                       # discount is undefined when nothing was sold
    sell["bucket"] = pd.cut(sell.disc_rate, [-0.001, 0.0001, 0.05, 0.10, 0.20, 1.0],
                            labels=["بدون خصم", "أقل من 5%", "5-10%", "10-20%", "أكثر من 20%"])
    promo = sell.groupby(["category", "bucket"], observed=True, as_index=False).rel.mean()
    sell["camp"] = "بدون حملة"
    pos = sell.c_ga > 0
    sell.loc[pos, "camp"] = pd.qcut(sell.loc[pos, "c_ga"].rank(method="first"), 3, labels=["إنفاق منخفض", "إنفاق متوسط", "إنفاق عالٍ"]
                                    ).astype(str)
    camp = sell.groupby(["category", "camp"], as_index=False).rel.mean()
    return seas, promo, camp


# --------------------------------------------------------------------------- main
def main(data, out):
    data, out = Path(data), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    panel, cal, last_full, levels = build_panel(data)
    print("panel rows:", f"{len(panel):,}", "| series:", panel.groupby(KEYS).ngroups)

    rows = pd.concat([make_rows(panel, cal, h, levels) for h in range(1, HORIZON + 1)])
    known = rows[rows.t <= last_full]

    # ---- backtest
    test = known[known.t > last_full - HOLDOUT].copy()
    train = known[(known.t <= last_full - HOLDOUT) & (known.t > last_full - HOLDOUT - TRAIN_MONTHS)]
    print(f"backtest: train {len(train):,} rows, test {len(test):,} rows")
    models = fit(train)
    test["forecast"], test["p10"], test["p90"] = predict(models, test)
    acc = accuracy_table(test)
    print(acc[acc.h == 0][["level", "wape_model", "wape_seasonal_naive", "wape_avg3", "bias_model"]]
          .round(3).to_string(index=False))

    # ---- final model + future forecast
    train = known[known.t > last_full - TRAIN_MONTHS]
    models = fit(train)
    fut = rows[(rows.mi == last_full) & (rows.t > last_full)].copy()
    fut = fut[fut.r12 > 0]                              # series with no sale in 12 months -> 0
    fut["forecast"], fut["p10"], fut["p90"] = predict(models, fut)

    try:
        imp = pd.DataFrame({"feature": FEATURES,
                            "gain": models[0].booster_.feature_importance(importance_type="gain")})
        imp["share"] = imp.gain / imp.gain.sum()
        imp = imp.sort_values("share", ascending=False)
    except Exception:
        imp = pd.DataFrame({"feature": FEATURES, "gain": 0.0, "share": 0.0})

    seas, promo, camp = seasonality_and_promo(panel, last_full)

    # ---- save
    def tidy(d, cols):
        d = d.copy()
        d["month"] = to_month(d.t.astype(int)).values
        for c in ["branch_id", "product_id", "category", "audience"]:
            d[c] = d[c].astype(str)
        return d[cols]

    fcols = ["branch_id", "product_id", "category", "audience", "month", "h", "forecast", "p10", "p90"]
    f = tidy(fut, fcols + ["disc_rate", "c_ga"]).rename(columns={"disc_rate": "plan_discount_rate",
                                                                "c_ga": "plan_campaign_log_spend"})
    f[["forecast", "p10", "p90"]] = f[["forecast", "p10", "p90"]].round(3)
    f.to_parquet(out / "forecast.parquet", index=False)
    tidy(test, fcols[:4] + ["month", "h", "units", "forecast", "p10", "p90", "s12", "r3"]
         ).to_parquet(out / "backtest.parquet", index=False)
    acc.to_parquet(out / "accuracy.parquet", index=False)
    imp.to_parquet(out / "importance.parquet", index=False)
    seas.to_parquet(out / "seasonality.parquet", index=False)
    promo.assign(bucket=promo.bucket.astype(str)).to_parquet(out / "promo_effect.parquet", index=False)
    camp.to_parquet(out / "camp_effect.parquet", index=False)
    hist = panel[panel.mi <= last_full][KEYS + ["mi", "units", "disc_rate", "category", "audience"]].copy()
    hist["month"] = to_month(hist.mi).values
    hist[["category", "audience"]] = hist[["category", "audience"]].astype(str)
    hist.drop(columns="mi").to_parquet(out / "history.parquet", index=False)
    meta = dict(generated=datetime.now().isoformat(timespec="seconds"),
                last_full_month=f"{to_month([last_full])[0]:%Y-%m}",
                forecast_months=[f"{m:%Y-%m}" for m in sorted(f.month.unique())],
                horizon=HORIZON, holdout_months=HOLDOUT, train_months=TRAIN_MONTHS,
                series_forecasted=int(f.groupby(KEYS).ngroups),
                assumptions="discount = last-6-month average per series; campaign spend = same month last year")
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print("done ->", out.resolve())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="outputs/forecasting")
    a = ap.parse_args()
    main(a.data, a.out)
