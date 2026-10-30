"""
Cotonil - Demand Forecasting Page (Bilingual)
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ----------------------------------------------------------------------------- i18n Dictionary
LANGUAGES = {
    "ar": {
        "title": "التنبؤ بالطلب",
        "caption": "كم سنبيع من كل قطعة؟ تنبؤ شهري لكل منتج وفرع للأشهر القادمة",
        "err_engine": "شغّل forecasting_engine.py الأول.",
        "f_cat": "الفئة", "f_aud": "الشريحة", "f_branch": "الفرع", "f_prod": "المنتج",
        "no_data": "لا توجد بيانات بهذه الفلاتر.",
        "m_fcst": "إجمالي التنبؤ ({n} أشهر)",
        "vs_ly": "{val} عن نفس الفترة العام الماضي",
        "m_acc": "مؤشر دقة التوقعات",
        "m_naive": "كفاءة الذكاء الاصطناعي",
        "pts": "{val} نقطة",
        "better": "أدق من الطرق التقليدية", "worse": "أضعف من الطرق التقليدية",
        "m_series": "نطاق التغطية (منتج × فرع)",
        "tab1": "التنبؤ", "tab2": "تخطيط المنتجات", "tab3": "تحليلات متقدمة",
        "actual": "الفعلي", "pred": "التنبؤ", "range": "نطاق P10–P90",
        "y_units": "وحدات / شهر",
        "fcst_table": "التنبؤ لكل منتج وفرع",
        "exp_table": "عرض بيانات الجدول التفصيلية",
        "total": "الإجمالي",
        "dl_csv": "تحميل CSV",
        "plan_title": "أولويات التخطيط: أين يرتفع الطلب وأين ينخفض؟",
        "top_growth": "**الأعلى نمواً (للتوريد المبكر)**",
        "top_decline": "**الأكثر انخفاضاً (للتخفيض أو التصفية)**",
        "all_prods": "**كل المنتجات**",
        "c_prod": "المنتج", "c_cat": "الفئة", "c_ly": "نفس الفترة العام الماضي", "c_l3m": "آخر 3 شهور",
        "c_vs_ly": "التغير عن العام الماضي", "c_vs_l3m": "التغير عن آخر 3 شهور", "c_branches": "عدد الفروع",
        "seasonality": "مؤشر الموسمية (1.0 = متوسط الشهر في السنة)",
        "month": "شهر ",
        "promo": "تأثير الخصم", "camp": "تأثير الإنفاق التسويقي",
        "promo_bins": ["بدون خصم", "أقل من 5%", "5-10%", "10-20%", "أكثر من 20%"],
        "camp_bins": ["بدون حملة", "إنفاق منخفض", "إنفاق متوسط", "إنفاق عالٍ"],
        "y_rel": "الطلب مقارنةً بمتوسط السلسلة",
        "corr_note": "التأثيران محسوبان على الشهور التي حدثت فيها مبيعات، وهما ارتباط وليس سببية مؤكدة.",
        "tech_title": "تفاصيل النموذج التقنية (دقة النموذج وأهم العوامل)",
        "feat_imp": "أهم العوامل في النموذج",
        "backtest": "دقة النموذج (Backtesting)",
        "bt_note": "اختبار على آخر {n} أشهر لم يرها النموذج أثناء التدريب. WAPE = إجمالي الخطأ ÷ إجمالي المبيعات (الأقل أفضل).",
        "lvl": "المستوى", "w_mod": "WAPE النموذج", "w_naive": "WAPE نفس الشهر العام الماضي", "w_avg3": "WAPE متوسط 3 شهور", "bias": "انحياز النموذج",
        "cov": "نسبة الفعلي الواقعة داخل نطاق P10–P90 (منتج×فرع×شهر): {c} (المستهدف ≈ 80%)",
        "err_hz": "الخطأ حسب أفق التنبؤ (منتج × شهر)",
        "model": "النموذج", "naive_model": "نفس الشهر العام الماضي", "hz_lbl": "+{i} شهر",
        "act_vs_pred": "الفعلي مقابل المتوقع في فترة الاختبار (الإجمالي)", "pred_nm": "تنبؤ النموذج (شهر قادم)",
        "lvl_map": {"منتج × فرع × شهر": "منتج × فرع × شهر", "منتج × شهر": "منتج × شهر", 
                    "فرع × شهر": "فرع × شهر", "فئة × شهر": "فئة × شهر", "الإجمالي × شهر": "الإجمالي × شهر"},
        "lang_select": "اللغة",
        "lang_opts": ["العربية", "English"],
        "dir": "rtl"
    },
    "en": {
        "title": "Demand Forecasting",
        "caption": "How many units will we sell? Monthly forecast per product and branch for upcoming months",
        "err_engine": "Please run forecasting_engine.py first.",
        "f_cat": "Category", "f_aud": "Audience", "f_branch": "Branch", "f_prod": "Product",
        "no_data": "No data found for the selected filters.",
        "m_fcst": "Total Forecast ({n} Months)",
        "vs_ly": "{val} vs same period last year",
        "m_acc": "Forecast Reliability Index",
        "m_naive": "AI Efficiency Gain",
        "pts": "{val} pts",
        "better": "More accurate than traditional", "worse": "Less accurate than traditional",
        "m_series": "Coverage (Product × Branch)",
        "tab1": "Forecast", "tab2": "Product Planning", "tab3": "Advanced Analytics",
        "actual": "Actual", "pred": "Forecast", "range": "P10–P90 Range",
        "y_units": "Units / Month",
        "fcst_table": "Forecast per Product & Branch",
        "exp_table": "Show Detailed Table Data",
        "total": "Total",
        "dl_csv": "Download CSV",
        "plan_title": "Planning Priorities: Where is demand rising or falling?",
        "top_growth": "**Top Growth (For Early Supply)**",
        "top_decline": "**Top Decline (For Clearance)**",
        "all_prods": "**All Products**",
        "c_prod": "Product", "c_cat": "Category", "c_ly": "Same Period Last Year", "c_l3m": "Last 3 Months",
        "c_vs_ly": "Change vs Last Year", "c_vs_l3m": "Change vs Last 3 Months", "c_branches": "Branches Count",
        "seasonality": "Seasonality Index (1.0 = Average Month of Year)",
        "month": "Month ",
        "promo": "Discount Effect", "camp": "Marketing Spend Effect",
        "promo_bins": ["No Discount", "< 5%", "5-10%", "10-20%", "> 20%"],
        "camp_bins": ["No Campaign", "Low Spend", "Med Spend", "High Spend"],
        "y_rel": "Demand vs Series Average",
        "corr_note": "Effects are calculated on months with sales (Correlation, not causality).",
        "tech_title": "Technical Model Details (Accuracy & Features)",
        "feat_imp": "Feature Importance",
        "backtest": "Model Accuracy (Backtesting)",
        "bt_note": "Tested on the last {n} months unseen by the model. WAPE = Total Error ÷ Total Sales (Lower is better).",
        "lvl": "Level", "w_mod": "Model WAPE", "w_naive": "Naive WAPE (LY)", "w_avg3": "Avg 3M WAPE", "bias": "Model Bias",
        "cov": "Actuals inside P10–P90 range (Prod×Branch×Month): {c} (Target ≈ 80%)",
        "err_hz": "Error by Forecast Horizon (Product × Month)",
        "model": "Model", "naive_model": "Same Month LY", "hz_lbl": "+{i} Month",
        "act_vs_pred": "Actual vs Predicted in Test Period (Total)", "pred_nm": "Model Prediction (1 month ahead)",
        "lvl_map": {"منتج × فرع × شهر": "Prod × Branch × Month", "منتج × شهر": "Prod × Month", 
                    "فرع × شهر": "Branch × Month", "فئة × شهر": "Cat × Month", "الإجمالي × شهر": "Total × Month"},
        "lang_select": "Language",
        "lang_opts": ["العربية", "English"],
        "dir": "ltr"
    }
}

if 'lang' not in st.session_state:
    st.session_state.lang = 'ar'

lang_opts = LANGUAGES[st.session_state.lang]["lang_opts"]
selected_lang_label = st.sidebar.radio(
    LANGUAGES[st.session_state.lang]["lang_select"], 
    lang_opts, 
    index=0 if st.session_state.lang == 'ar' else 1
)

if selected_lang_label == lang_opts[0] and st.session_state.lang != 'ar':
    st.session_state.lang = 'ar'
    st.rerun()
elif selected_lang_label == lang_opts[1] and st.session_state.lang != 'en':
    st.session_state.lang = 'en'
    st.rerun()

T = LANGUAGES[st.session_state.lang]
DIR = T["dir"]

st.markdown(f"""
<style>
    /* Styling text and headers */
    h1, h2, h3, p, span, .st-emotion-cache-10trblm {{ color: #1e3a8a !important; }}
    
    /* Metrics Cards Styling */
    [data-testid="stMetric"] {{
        background-color: #ffffff;
        border: 1px solid #e5e7eb;
        border-radius: 10px;
        padding: 15px 20px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
        text-align: center;
    }}
    
    [data-testid="stMarkdownContainer"] {{ direction: {DIR}; }}
</style>
""", unsafe_allow_html=True)

DATA_DIR = Path("data")                       
OUT_DIR = Path("outputs/forecasting")         
Z90 = 1.2816                                  

@st.cache_data(show_spinner="Loading...")
def load():
    r = lambda n: pd.read_parquet(OUT_DIR / f"{n}.parquet")
    d = {k: r(k) for k in ["forecast", "history", "backtest", "accuracy", "importance",
                           "seasonality", "promo_effect", "camp_effect"]}
    d["meta"] = json.loads((OUT_DIR / "meta.json").read_text(encoding="utf-8"))
    br = pd.read_parquet(DATA_DIR / "branches.parquet", columns=["branch_id", "branch_name_ar"])
    pr = pd.read_parquet(DATA_DIR / "products_catalog.parquet", columns=["product_id", "product_name_ar"])
    d["bn"] = dict(zip(br.branch_id, br.branch_name_ar))
    d["pn"] = dict(zip(pr.product_id, pr.product_name_ar))
    return d

def agg_forecast(f):
    f = f.assign(sig=(f.p90 - f.p10) / (2 * Z90))
    g = f.groupby("month").agg(forecast=("forecast", "sum"), var=("sig", lambda s: (s ** 2).sum()))
    g["p10"] = (g.forecast - Z90 * np.sqrt(g["var"])).clip(lower=0)
    g["p90"] = g.forecast + Z90 * np.sqrt(g["var"])
    return g.reset_index()

def fmt(x):
    return f"{x:,.0f}"

st.title(T["title"])
st.caption(T["caption"])

try:
    D = load()
except Exception as e:
    st.error(f"{T['err_engine']} ({e})")
    st.stop()

F, H, BT, ACC, META = D["forecast"], D["history"], D["backtest"], D["accuracy"], D["meta"]
F["branch"] = F.branch_id.map(D["bn"]).fillna(F.branch_id)
F["product"] = F.product_id.map(D["pn"]).fillna(F.product_id)

c1, c2, c3, c4 = st.columns(4)
cats = c1.multiselect(T["f_cat"], sorted(F.category.unique()))
auds = c2.multiselect(T["f_aud"], sorted(F.audience.unique()))
brs = c3.multiselect(T["f_branch"], sorted(F.branch.unique()))
prs = c4.multiselect(T["f_prod"], sorted(F["product"].unique()))

def flt(df, branch_col="branch", prod_col="product"):
    m = pd.Series(True, index=df.index)
    if cats: m &= df.category.isin(cats)
    if auds: m &= df.audience.isin(auds)
    if brs: m &= df[branch_col].isin(brs)
    if prs: m &= df[prod_col].isin(prs)
    return df[m]

H["branch"] = H.branch_id.map(D["bn"]).fillna(H.branch_id)
H["product"] = H.product_id.map(D["pn"]).fillna(H.product_id)
f, h = flt(F), flt(H)
if f.empty:
    st.warning(T["no_data"])
    st.stop()

fm = agg_forecast(f)
fmonths = list(fm.month)
ly = h[h.month.isin([m - pd.DateOffset(years=1) for m in fmonths])].units.sum()
tot = fm.forecast.sum()
a0 = ACC[(ACC.h == 0) & (ACC.level == "منتج × شهر")].iloc[0]

k1, k2, k3, k4 = st.columns(4)
k1.metric(T["m_fcst"].format(n=len(fmonths)), fmt(tot), T["vs_ly"].format(val=f"{(tot / ly - 1) * 100:+.1f}%") if ly else None)
k2.metric(T["m_acc"], f"{(1 - a0.wape_model) * 100:.0f}%", f"WAPE {a0.wape_model:.1%}", delta_color="off")
k3.metric(T["m_naive"], T["pts"].format(val=f"{(a0.wape_seasonal_naive - a0.wape_model) * 100:+.1f}"),
          T["better"] if a0.wape_model < a0.wape_seasonal_naive else T["worse"], delta_color="off")
k4.metric(T["m_series"], fmt(f.groupby(["branch_id", "product_id"]).ngroups))

st.write("---")

t1, t2, t3 = st.tabs([T["tab1"], T["tab2"], T["tab3"]])

# ----------------------------------------------------------------------------- tab 1
with t1:
    hm = h.groupby("month").units.sum().reset_index().tail(36)
    fig = go.Figure()
    fig.add_scatter(x=hm.month, y=hm.units, name=T["actual"], line=dict(color="#1E3A5F", width=2))
    fig.add_scatter(x=fm.month, y=fm.p90, line=dict(width=0), showlegend=False, hoverinfo="skip")
    fig.add_scatter(x=fm.month, y=fm.p10, fill="tonexty", fillcolor="rgba(37,99,235,0.18)", line=dict(width=0), name=T["range"])
    fig.add_scatter(x=[hm.month.iloc[-1]] + fmonths, y=[hm.units.iloc[-1]] + list(fm.forecast), name=T["pred"], line=dict(color="#2563EB", width=3, dash="dash"))
    fig.update_layout(height=420, margin=dict(l=10, r=10, t=30, b=10), hovermode="x unified", yaxis_title=T["y_units"], legend=dict(orientation="h"))
    st.plotly_chart(fig, use_container_width=True)

    st.subheader(T["fcst_table"])
    with st.expander(T["exp_table"]):
        pv = (f.pivot_table(index=["branch", "product", "category"], columns=f.month.dt.strftime("%Y-%m"), values="forecast", aggfunc="sum").round(1))
        pv[T["total"]] = pv.sum(axis=1)
        pv = pv.sort_values(T["total"], ascending=False).reset_index()
        st.dataframe(pv, use_container_width=True, height=380, hide_index=True)
        st.download_button(T["dl_csv"], pv.to_csv(index=False).encode("utf-8-sig"), "forecast_product_branch.csv")

# ----------------------------------------------------------------------------- tab 2
with t2:
    st.subheader(T["plan_title"])
    cur = f.groupby(["product_id", "product", "category"], as_index=False).forecast.sum()
    prev = (h[h.month.isin([m - pd.DateOffset(years=1) for m in fmonths])].groupby("product_id", as_index=False).units.sum().rename(columns={"units": "last_year"}))
    last3 = (h[h.month > h.month.max() - pd.DateOffset(months=3)].groupby("product_id", as_index=False).units.sum().rename(columns={"units": "last_3m"}))
    p = cur.merge(prev, on="product_id", how="left").merge(last3, on="product_id", how="left").fillna(0)
    p["vs_last_year"] = np.where(p.last_year > 0, p.forecast / p.last_year - 1, np.nan)
    p["vs_last_3m"] = np.where(p.last_3m > 0, p.forecast / p.last_3m - 1, np.nan)
    p["branches"] = p.product_id.map(f.groupby("product_id").branch_id.nunique())
    
    p = p.rename(columns={"product": T["c_prod"], "category": T["c_cat"], "forecast": T["pred"],
                          "last_year": T["c_ly"], "last_3m": T["c_l3m"],
                          "vs_last_year": T["c_vs_ly"], "vs_last_3m": T["c_vs_l3m"], "branches": T["c_branches"]}).drop(columns="product_id")
    
    sty = {T["pred"]: "{:,.0f}", T["c_ly"]: "{:,.0f}", T["c_l3m"]: "{:,.0f}", T["c_vs_ly"]: "{:+.1%}", T["c_vs_l3m"]: "{:+.1%}"}
    
    ca, cb = st.columns(2)
    with ca:
        st.markdown(T["top_growth"])
        st.dataframe(p[p[T["pred"]] > p[T["pred"]].median()].nlargest(10, T["c_vs_l3m"]).style.format(sty), hide_index=True)
    with cb:
        st.markdown(T["top_decline"])
        st.dataframe(p[p[T["pred"]] > p[T["pred"]].median()].nsmallest(10, T["c_vs_l3m"]).style.format(sty), hide_index=True)
    st.markdown(T["all_prods"])
    st.dataframe(p.sort_values(T["pred"], ascending=False).style.format(sty), hide_index=True, height=360)

# ----------------------------------------------------------------------------- tab 3
with t3:
    st.subheader(T["seasonality"])
    sp = D["seasonality"].pivot(index="category", columns="moy", values="idx")
    fig = go.Figure(go.Heatmap(z=sp.values, x=[f"{T['month']}{m}" for m in sp.columns], y=sp.index, colorscale="Blues", text=np.round(sp.values, 2), texttemplate="%{text}"))
    fig.update_layout(height=60 + 60 * len(sp), margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, use_container_width=True)

    a, b = st.columns(2)
    pe = D["promo_effect"].copy()
    ar_promo = ["بدون خصم", "أقل من 5%", "5-10%", "10-20%", "أكثر من 20%"]
    pe["bucket"] = pe["bucket"].replace(dict(zip(ar_promo, T["promo_bins"])))
    
    ce = D["camp_effect"].copy()
    ar_camp = ["بدون حملة", "إنفاق منخفض", "إنفاق متوسط", "إنفاق عالٍ"]
    ce["camp"] = ce["camp"].replace(dict(zip(ar_camp, T["camp_bins"])))

    with a:
        st.subheader(T["promo"])
        fig = go.Figure()
        for c in pe.category.unique():
            x = pe[pe.category == c].set_index("bucket").reindex(T["promo_bins"])
            fig.add_bar(x=T["promo_bins"], y=x.rel, name=c)
        fig.update_layout(barmode="group", height=340, yaxis_title=T["y_rel"], margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)
    with b:
        st.subheader(T["camp"])
        fig = go.Figure()
        for c in ce.category.unique():
            x = ce[ce.category == c].set_index("camp").reindex(T["camp_bins"])
            fig.add_bar(x=T["camp_bins"], y=x.rel, name=c)
        fig.update_layout(barmode="group", height=340, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)
    st.caption(T["corr_note"])

    with st.expander(T["tech_title"]):
        st.subheader(T["feat_imp"])
        imp = D["importance"].head(12).iloc[::-1]
        fig = go.Figure(go.Bar(x=imp.share, y=imp.feature, orientation="h", marker_color="#2563EB"))
        fig.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10), xaxis_tickformat=".0%")
        st.plotly_chart(fig, use_container_width=True)

        st.subheader(T["backtest"])
        st.caption(T["bt_note"].format(n=META['holdout_months']))
        
        t = ACC[ACC.h == 0][["level", "wape_model", "wape_seasonal_naive", "wape_avg3", "bias_model"]].copy()
        t["level"] = t["level"].map(T["lvl_map"]).fillna(t["level"])
        t.columns = [T["lvl"], T["w_mod"], T["w_naive"], T["w_avg3"], T["bias"]]
        st.dataframe(t.style.format({c: "{:.1%}" for c in t.columns[1:]}), hide_index=True, use_container_width=True)

        cov = ACC[(ACC.h == 0) & ACC.coverage_p10_p90.notna()].coverage_p10_p90.iloc[0]
        st.info(T["cov"].format(c=f"{cov:.0%}"))

        hz = ACC[(ACC.h > 0) & (ACC.level == "منتج × شهر")]
        fig = go.Figure()
        fig.add_bar(x=[T["hz_lbl"].format(i=i) for i in hz.h], y=hz.wape_model, name=T["model"], marker_color="#2563EB")
        fig.add_bar(x=[T["hz_lbl"].format(i=i) for i in hz.h], y=hz.wape_seasonal_naive, name=T["naive_model"], marker_color="#9CA3AF")
        fig.update_layout(barmode="group", height=320, title=T["err_hz"], yaxis_tickformat=".0%", margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)

        b1 = BT[BT.h == 1].groupby("month")[["units", "forecast"]].sum().reset_index()
        fig = go.Figure()
        fig.add_scatter(x=b1.month, y=b1.units, name=T["actual"], line=dict(color="#1E3A5F", width=2))
        fig.add_scatter(x=b1.month, y=b1.forecast, name=T["pred_nm"], line=dict(color="#2563EB", dash="dash"))
        fig.update_layout(height=320, title=T["act_vs_pred"], margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)