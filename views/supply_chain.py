import streamlit as st
import pandas as pd
import plotly.express as px
import os
import time
import requests
import html
import re
import json
import math

# ==========================================
# 1. إعدادات اللغة (Bilingual Support)
# ==========================================
if 'lang' not in st.session_state:
    st.session_state.lang = 'ar'

def tr(text_dict):
    return text_dict.get(st.session_state.lang, text_dict.get('en', ''))

st.sidebar.markdown(f"<h3>{tr({'ar': 'إعدادات اللغة', 'en': 'Language Settings'})}</h3>", unsafe_allow_html=True)
selected_lang = st.sidebar.radio(
    tr({'ar': "اختر اللغة", 'en': "Select Language"}),
    options=['ar', 'en'],
    index=0 if st.session_state.lang == 'ar' else 1,
    key="sc_lang_selector"
)
if selected_lang != st.session_state.lang:
    st.session_state.lang = selected_lang
    st.rerun()

# ==========================================
# 2. معالجة البيانات (Data Processing)
# ==========================================
@st.cache_data
def get_supply_chain_data():
    try:
        df_import = pd.read_parquet('data/import_shipments.parquet')
        df_partners = pd.read_parquet('data/import_partners.parquet')
        df_delivery = pd.read_parquet('data/delivery_shipments.parquet')
    except Exception:
        # Fallback if files are missing or corrupted
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    # 1. معالجة الاستيراد (Inbound)
    if not df_import.empty and not df_partners.empty:
        df_import = df_import.merge(df_partners, on='import_partner_id', how='left')
        df_import['total_landed_cost_USD'] = df_import['customs_value_USD'].fillna(0) + df_import['freight_USD'].fillna(0) + df_import['duty_and_tax_USD'].fillna(0)
    
    # 2. معالجة التوزيع المحلي (Outbound)
    if not df_delivery.empty:
        # حساب زمن التوصيل بالأيام
        df_delivery['ship_date'] = pd.to_datetime(df_delivery['ship_date'])
        df_delivery['delivery_date'] = pd.to_datetime(df_delivery['delivery_date'])
        df_delivery['lead_time_days'] = (df_delivery['delivery_date'] - df_delivery['ship_date']).dt.days
        
        # تصنيف حالة التوصيل
        df_delivery['is_delayed'] = df_delivery['fulfillment_status'].apply(lambda x: 1 if str(x).strip().lower() == 'delayed' else 0)

    return df_import, df_partners, df_delivery

df_import, df_partners, df_delivery = get_supply_chain_data()

# ==========================================
# 3. إعدادات الـ AI (Groq) + منطق القرار
# ==========================================
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-20b"

# ==== AI ANALYSIS START ====

# --- عتبات القرار (عدّليها حسب سياسة العميل) ---
MIN_N_CARRIER = 100          # أقل عدد شحنات لتقييم شركة شحن
MIN_N_REGION_CARRIER = 30    # أقل عدد شحنات لشركة داخل محافظة معينة
MIN_N_GOV = 100              # أقل عدد شحنات لتقييم محافظة
MIN_N_PARTNER = 10           # أقل عدد شحنات لتقييم مورد/شريك استيراد
MIN_GAP_PP = 1.0             # أقل فرق (نقطة مئوية) يستحق تدخل في التأخير
MIN_COST_GAP_PCT = 10.0      # أقل زيادة % في تكلفة الشحن تستحق تدخل
MIN_COVERAGE = 0.8           # البديل لازم يغطي 80% على الأقل من محافظات الشركة الأسوأ
ALPHA = 0.05                 # مستوى الدلالة الإحصائية

# حالات الشحنات اللي لا تدخل في حساب التأخير (لسه مخلصتش أو اتلغت)
# راجعي القيم الفعلية: df_delivery['fulfillment_status'].value_counts()
EXCLUDE_STATUSES = {'in transit', 'in_transit', 'cancelled', 'canceled', 'returned', 'pending'}


def _f(x, d=2):
    return round(float(x), d)


def _i(x):
    return int(x)


def two_prop_pvalue(x1, n1, x2, n2):
    """اختبار فرق نسبتين (two-sided)."""
    if n1 == 0 or n2 == 0:
        return 1.0
    p = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0
    z = (x1 / n1 - x2 / n2) / se
    return math.erfc(abs(z) / math.sqrt(2))


def one_prop_pvalue(x, n, p0):
    """هل النسبة الفعلية أعلى من المتوقع p0؟ (one-sided)."""
    if n == 0 or p0 <= 0 or p0 >= 1:
        return 1.0
    se = math.sqrt(p0 * (1 - p0) / n)
    z = (x / n - p0) / se
    return 0.5 * math.erfc(z / math.sqrt(2))


def eval_deliveries():
    """الشحنات المكتملة فقط (بدون اللي في الطريق/الملغاة) وبدون قيم ناقصة."""
    d = df_delivery.dropna(subset=['carrier', 'ship_to_governorate']).copy()
    status = d['fulfillment_status'].astype(str).str.strip().str.lower()
    return d[~status.isin(EXCLUDE_STATUSES)]


def _period(df):
    s = pd.to_datetime(df['ship_date'], errors='coerce')
    if s.notna().any():
        return f"{s.min():%Y-%m-%d} → {s.max():%Y-%m-%d}"
    return "n/a"


def action_texts(kind, verdict):
    a = {
        'NO_ACTION': ('no change', 'لا تغيير'),
        'INSUFFICIENT_DATA': ('wait for more data', 'انتظار مزيد من البيانات'),
        'WARN_AND_MONITOR': ('issue a formal warning and monitor for 4 weeks', 'إنذار رسمي ومتابعة لمدة 4 أسابيع'),
        'SHIFT_VOLUME': ('shift part of the volume to the alternative', 'تحويل جزء من الحجم إلى البديل'),
    }
    if kind == 'import_costs':
        a['WARN_AND_MONITOR'] = ('renegotiate freight rates and monitor', 'إعادة التفاوض على أسعار الشحن ومتابعتها')
        a['SHIFT_VOLUME'] = ('shift part of the volume to the lower-cost partner after verifying capacity and quality',
                             'تحويل جزء من الحجم للشريك الأقل تكلفة بعد التحقق من الطاقة الاستيعابية والجودة')
    return a[verdict]


def _finish(res, kind):
    en, ar = action_texts(kind, res['verdict'])
    res['action_en'], res['action_ar'] = en, ar
    return res


# ---------- 1) أداء شركات الشحن (معدّل بمزيج المحافظات) ----------
def analyze_carriers(df):
    base = {"kind": "carrier_perf"}
    if df.empty:
        return _finish({**base, "verdict": "INSUFFICIENT_DATA", "min_n": MIN_N_CARRIER, "required_names": []}, "carrier_perf")
    base["period"] = _period(df)

    # التأخير المتوقع لكل شركة = متوسط تأخير الشبكة في المحافظات اللي بتشتغل فيها (عدالة المقارنة)
    gov_rate = df.groupby('ship_to_governorate')['is_delayed'].mean()
    d = df.assign(gov_expected=df['ship_to_governorate'].map(gov_rate))
    g = d.groupby('carrier').agg(
        total_orders=('shipment_id', 'count'),
        delayed_orders=('is_delayed', 'sum'),
        expected_rate=('gov_expected', 'mean'),
    ).reset_index()
    g = g[g['total_orders'] >= MIN_N_CARRIER].copy()
    if len(g) < 2:
        return _finish({**base, "verdict": "INSUFFICIENT_DATA", "min_n": MIN_N_CARRIER, "required_names": []}, "carrier_perf")

    g['delay_rate_pct'] = g['delayed_orders'] / g['total_orders'] * 100
    g['expected_pct'] = g['expected_rate'] * 100
    g['excess_pp'] = g['delay_rate_pct'] - g['expected_pct']
    g = g.sort_values('excess_pp')

    w = g.iloc[-1]
    p = one_prop_pvalue(w['delayed_orders'], w['total_orders'], w['expected_rate'])

    if p >= ALPHA or w['excess_pp'] < MIN_GAP_PP:
        verdict = "NO_ACTION"
    elif w['excess_pp'] < 3 * MIN_GAP_PP:
        verdict = "WARN_AND_MONITOR"
    else:
        verdict = "SHIFT_VOLUME"

    best = None
    if verdict != "NO_ACTION":
        w_counts = df[df['carrier'] == w['carrier']].groupby('ship_to_governorate').size()
        for _, c in g.iloc[:-1].iterrows():  # مرتبين تصاعدياً: أول بديل صالح هو الأفضل
            c_counts = df[df['carrier'] == c['carrier']].groupby('ship_to_governorate').size()
            mask = [c_counts.get(gv, 0) >= MIN_N_REGION_CARRIER for gv in w_counts.index]
            cov = w_counts[mask].sum() / w_counts.sum()
            if cov >= MIN_COVERAGE:
                best, best_cov = c, cov
                break
        if best is None:
            verdict = "WARN_AND_MONITOR"  # مفيش بديل يغطي نفس المحافظات

    res = {
        **base, "verdict": verdict,
        "worst_carrier": str(w['carrier']),
        "worst_orders": _i(w['total_orders']),
        "worst_delay_pct": _f(w['delay_rate_pct'], 1),
        "worst_expected_pct": _f(w['expected_pct'], 1),
        "worst_excess_pp": _f(w['excess_pp'], 1),
        "p_value": round(float(p), 4),
        "required_names": [str(w['carrier'])],
    }
    if best is not None:
        res.update({
            "best_carrier": str(best['carrier']),
            "best_orders": _i(best['total_orders']),
            "best_delay_pct": _f(best['delay_rate_pct'], 1),
            "best_excess_pp": _f(best['excess_pp'], 1),
            "coverage_of_worst_regions_pct": _f(best_cov * 100, 0),
            "delays_avoidable_if_all_volume_moved": _i(max(0, round((w['excess_pp'] - best['excess_pp']) / 100 * w['total_orders']))),
        })
        res["required_names"].append(str(best['carrier']))
    elif verdict == "WARN_AND_MONITOR":
        res["no_covering_alternative"] = True
    return _finish(res, "carrier_perf")


# ---------- 2) اختناقات المحافظات ----------
def analyze_governorates(df):
    base = {"kind": "gov_bottleneck"}
    if df.empty:
        return _finish({**base, "verdict": "INSUFFICIENT_DATA", "min_n": MIN_N_GOV, "required_names": []}, "gov_bottleneck")
    base["period"] = _period(df)

    net_rate = float(df['is_delayed'].mean())
    gv = df.groupby('ship_to_governorate').agg(
        total_orders=('shipment_id', 'count'),
        delayed_orders=('is_delayed', 'sum'),
    ).reset_index()
    gv = gv[gv['total_orders'] >= MIN_N_GOV].copy()
    if gv.empty:
        return _finish({**base, "verdict": "INSUFFICIENT_DATA", "min_n": MIN_N_GOV, "required_names": []}, "gov_bottleneck")

    gv['delay_rate_pct'] = gv['delayed_orders'] / gv['total_orders'] * 100
    gv['excess_pp'] = gv['delay_rate_pct'] - net_rate * 100
    w = gv.sort_values('excess_pp').iloc[-1]
    p = one_prop_pvalue(w['delayed_orders'], w['total_orders'], net_rate)

    res = {
        **base,
        "worst_governorate": str(w['ship_to_governorate']),
        "gov_orders": _i(w['total_orders']),
        "gov_delay_pct": _f(w['delay_rate_pct'], 1),
        "network_delay_pct": _f(net_rate * 100, 1),
        "gov_excess_pp": _f(w['excess_pp'], 1),
        "p_value": round(float(p), 4),
        "required_names": [str(w['ship_to_governorate'])],
    }

    if p >= ALPHA or w['excess_pp'] < MIN_GAP_PP:
        res["verdict"] = "NO_ACTION"
        return _finish(res, "gov_bottleneck")

    # هل المشكلة في شركة بعينها داخل المحافظة ولا في المحافظة كلها؟
    sub = df[df['ship_to_governorate'] == w['ship_to_governorate']]
    cs = sub.groupby('carrier').agg(
        total_orders=('shipment_id', 'count'),
        delayed_orders=('is_delayed', 'sum'),
    ).reset_index()
    cs = cs[cs['total_orders'] >= MIN_N_REGION_CARRIER].copy()
    if len(cs) < 2:
        res.update({"verdict": "WARN_AND_MONITOR", "cause": "insufficient_carrier_data"})
        return _finish(res, "gov_bottleneck")

    cs['rate'] = cs['delayed_orders'] / cs['total_orders'] * 100
    cs = cs.sort_values('rate')
    wc, bc = cs.iloc[-1], cs.iloc[0]
    cgap = wc['rate'] - bc['rate']
    p2 = two_prop_pvalue(wc['delayed_orders'], wc['total_orders'], bc['delayed_orders'], bc['total_orders'])

    if cgap >= MIN_GAP_PP and p2 < ALPHA:
        res.update({
            "cause": "carrier",
            "verdict": "SHIFT_VOLUME" if cgap >= 3 * MIN_GAP_PP else "WARN_AND_MONITOR",
            "failing_carrier": str(wc['carrier']),
            "failing_carrier_delay_pct": _f(wc['rate'], 1),
            "failing_carrier_orders": _i(wc['total_orders']),
            "best_carrier_in_region": str(bc['carrier']),
            "best_carrier_delay_pct": _f(bc['rate'], 1),
            "carrier_gap_pp": _f(cgap, 1),
            "carrier_p_value": round(float(p2), 4),
        })
        res["required_names"] += [str(wc['carrier']), str(bc['carrier'])]
    else:
        # كل الشركات متأخرة بنفس القدر: المشكلة في المحافظة نفسها مش في شركة
        res.update({"cause": "region_wide", "verdict": "WARN_AND_MONITOR"})
    return _finish(res, "gov_bottleneck")


# ---------- 3) تكاليف الاستيراد (معدّلة بنوع الحاوية والدولة) ----------
def analyze_imports(df):
    base = {"kind": "import_costs",
            "caveat": "Freight only; supplier quality, lead time and capacity were not evaluated."}
    needed = ['partner_name', 'freight_USD', 'container_type', 'country', 'import_shipment_id']
    if df.empty or any(c not in df.columns for c in needed):
        return _finish({**base, "verdict": "INSUFFICIENT_DATA", "min_n": MIN_N_PARTNER, "required_names": []}, "import_costs")

    d = df.dropna(subset=needed[:4]).copy()
    d = d[d['freight_USD'] > 0]
    # المتوقع = متوسط الشحن لنفس نوع الحاوية ونفس الدولة (عدالة المقارنة)
    d['expected'] = d.groupby(['container_type', 'country'])['freight_USD'].transform('mean')
    d['ratio'] = d['freight_USD'] / d['expected']
    g = d.groupby('partner_name').agg(
        shipments=('import_shipment_id', 'count'),
        avg_freight=('freight_USD', 'mean'),
        sum_freight=('freight_USD', 'sum'),
        sum_expected=('expected', 'sum'),
        ratio_mean=('ratio', 'mean'),
        ratio_std=('ratio', 'std'),
    ).reset_index()
    g = g[g['shipments'] >= MIN_N_PARTNER].copy()
    if len(g) < 2:
        return _finish({**base, "verdict": "INSUFFICIENT_DATA", "min_n": MIN_N_PARTNER, "required_names": []}, "import_costs")

    g['index_pct'] = (g['ratio_mean'] - 1) * 100
    g = g.sort_values('index_pct')
    w, b = g.iloc[-1], g.iloc[0]

    se = (w['ratio_std'] / math.sqrt(w['shipments'])) if pd.notna(w['ratio_std']) else 0.0
    if se > 0:
        z = (w['ratio_mean'] - 1) / se
        p = 0.5 * math.erfc(z / math.sqrt(2))
    else:
        p = 0.0 if w['ratio_mean'] > 1 else 1.0

    if w['index_pct'] < MIN_COST_GAP_PCT or p >= ALPHA:
        verdict = "NO_ACTION"
    elif w['index_pct'] < 2 * MIN_COST_GAP_PCT:
        verdict = "WARN_AND_MONITOR"
    else:
        verdict = "SHIFT_VOLUME"

    res = {
        **base, "verdict": verdict,
        "most_expensive_partner": str(w['partner_name']),
        "shipments": _i(w['shipments']),
        "avg_freight_usd": _f(w['avg_freight'], 0),
        "above_like_for_like_avg_pct": _f(w['index_pct'], 1),
        "p_value": round(float(p), 4),
        "required_names": [str(w['partner_name'])],
    }
    if verdict != "NO_ACTION":
        saving = max(0.0, w['sum_freight'] - w['sum_expected'] * b['ratio_mean'])
        res.update({
            "cheapest_partner": str(b['partner_name']),
            "cheapest_avg_freight_usd": _f(b['avg_freight'], 0),
            "cheapest_vs_like_for_like_pct": _f(b['index_pct'], 1),
            "estimated_saving_usd_if_at_cheapest_level": _f(saving, 0),
        })
        res["required_names"].append(str(b['partner_name']))
    return _finish(res, "import_costs")


def run_sc_analysis(kind):
    if kind == "carrier_perf":
        return analyze_carriers(eval_deliveries())
    if kind == "gov_bottleneck":
        return analyze_governorates(eval_deliveries())
    if kind == "import_costs":
        return analyze_imports(df_import)
    return {"kind": kind, "verdict": "INSUFFICIENT_DATA", "required_names": [], "action_en": "", "action_ar": ""}


# ---------- صياغة التقرير: قالب جاهز (بدون هلوسة) ----------
def template_report(kind, r, lang):
    ar = lang == 'ar'
    v = r['verdict']
    act = r['action_ar'] if ar else r['action_en']

    if v == 'INSUFFICIENT_DATA':
        return ("• لا توجد بيانات كافية لتوصية موثوقة (حجم العينة أقل من الحد الأدنى).\n• يُفضّل الانتظار حتى تتراكم شحنات أكثر."
                if ar else
                "• Not enough data for a reliable recommendation (sample size below the minimum).\n• Wait until more shipments accumulate.")

    if kind == 'carrier_perf':
        w = r['worst_carrier']
        if v == 'NO_ACTION':
            return (f"• لا يوجد إجراء مبرر: انحراف {w} عن المتوقع {r['worst_excess_pp']:+.1f} نقطة ({r['worst_delay_pct']}% فعلي مقابل {r['worst_expected_pct']}% متوقع، {r['worst_orders']:,} شحنة) — {_no_action_reason(r, True)}.\n"
                    "• الشركات متقاربة بعد تعديل مزيج المحافظات؛ متابعة دورية فقط."
                    if ar else
                    f"• No action justified: {w} deviates {r['worst_excess_pp']:+.1f} pp from expected ({r['worst_delay_pct']}% actual vs {r['worst_expected_pct']}% expected, {r['worst_orders']:,} shipments), — {_no_action_reason(r, False)}.\n"
                    "• Carriers are comparable after adjusting for governorate mix; routine monitoring only.")
        l1 = (f"• {w}: تأخير {r['worst_delay_pct']}% مقابل {r['worst_expected_pct']}% متوقع لمزيج محافظاتها (+{r['worst_excess_pp']} نقطة، {r['worst_orders']:,} شحنة) — الإجراء: {act}."
              if ar else
              f"• {w}: {r['worst_delay_pct']}% delayed vs {r['worst_expected_pct']}% expected for its governorate mix (+{r['worst_excess_pp']} pp, {r['worst_orders']:,} shipments) — action: {act}.")
        if 'best_carrier' in r:
            l2 = (f"• البديل المقترح: {r['best_carrier']} ({r['best_delay_pct']}% فعلي، {r['best_excess_pp']:+.1f} نقطة عن المتوقع، يغطي {r['coverage_of_worst_regions_pct']:.0f}% من محافظات {w})؛ الأثر المقدّر لو نُقل كامل الحجم: حوالي {r['delays_avoidable_if_all_volume_moved']:,} شحنة متأخرة أقل خلال {r['period']}."
                  if ar else
                  f"• Suggested alternative: {r['best_carrier']} ({r['best_delay_pct']}% actual, {r['best_excess_pp']:+.1f} pp vs expected, covers {r['coverage_of_worst_regions_pct']:.0f}% of {w}'s governorates); estimated impact if all volume moved: about {r['delays_avoidable_if_all_volume_moved']:,} fewer delayed shipments over {r['period']}.")
        else:
            l2 = ("• لا توجد شركة بديلة تغطي نفس المحافظات بحجم كافٍ؛ يُكتفى بالإنذار والمتابعة."
                  if ar else
                  "• No alternative carrier covers the same governorates with sufficient volume; warning and monitoring only.")
        return f"{l1}\n{l2}"

    if kind == 'gov_bottleneck':
        g = r['worst_governorate']
        if v == 'NO_ACTION':
            return (f"• لا يوجد اختناق مؤكد: أعلى محافظة ({g}) تتأخر {r['gov_delay_pct']}% مقابل {r['network_delay_pct']}% للشبكة ({r['gov_excess_pp']:+.1f} نقطة) — {_no_action_reason(r, True)}.\n"
                    "• التوزيع متوازن بين المحافظات؛ لا حاجة لتغيير شركات الشحن."
                    if ar else
                    f"• No confirmed bottleneck: the highest governorate ({g}) is at {r['gov_delay_pct']}% vs {r['network_delay_pct']}% network-wide ({r['gov_excess_pp']:+.1f} pp), — {_no_action_reason(r, False)}.\n"
                    "• Delivery is balanced across governorates; no carrier change needed.")
        l1 = (f"• اختناق في {g}: تأخير {r['gov_delay_pct']}% مقابل {r['network_delay_pct']}% للشبكة ({r['gov_orders']:,} شحنة)."
              if ar else
              f"• Bottleneck in {g}: {r['gov_delay_pct']}% delayed vs {r['network_delay_pct']}% network-wide ({r['gov_orders']:,} shipments).")
        cause = r.get('cause')
        if cause == 'carrier':
            l2 = (f"• السبب يتركز في {r['failing_carrier']} ({r['failing_carrier_delay_pct']}%) مقابل {r['best_carrier_in_region']} ({r['best_carrier_delay_pct']}%) في نفس المحافظة — الإجراء: {act}."
                  if ar else
                  f"• The cause is concentrated in {r['failing_carrier']} ({r['failing_carrier_delay_pct']}%) vs {r['best_carrier_in_region']} ({r['best_carrier_delay_pct']}%) in the same governorate — action: {act}.")
        elif cause == 'region_wide':
            l2 = ("• التأخير موزّع على كل الشركات في المحافظة (لا فرق معنوي بينها)، فالمشكلة غالباً في الطريق أو آخر ميل أو المستودع الإقليمي — المطلوب مراجعة تشغيلية للمحافظة بدل تغيير الشركة."
                  if ar else
                  "• Delays are spread across all carriers in the governorate (no significant difference), so the issue is likely road, last-mile or regional warehouse — review operations there instead of switching carrier.")
        else:
            l2 = ("• عدد الشحنات لكل شركة داخل المحافظة غير كافٍ لتحديد المتسبب؛ تابعي حتى تتراكم بيانات أكثر."
                  if ar else
                  "• Not enough shipments per carrier in this governorate to identify the cause; keep monitoring.")
        return f"{l1}\n{l2}"

    if kind == 'import_costs':
        w = r['most_expensive_partner']
        if v == 'NO_ACTION':
            return (f"• لا يوجد إجراء مبرر: أعلى تكلفة شحن نسبية لدى {w} بزيادة {r['above_like_for_like_avg_pct']:+.1f}% عن المتوسط لنفس نوع الحاوية والدولة (حد التدخل {MIN_COST_GAP_PCT:.0f}%) — {_no_action_reason(r, True)}.\n"
                    "• الشركاء متقاربون في تكلفة الشحن بعد التعديل."
                    if ar else
                    f"• No action justified: {w} has the highest relative freight at {r['above_like_for_like_avg_pct']:+.1f}% vs the like-for-like average (same container type and country) (intervention threshold {MIN_COST_GAP_PCT:.0f}%) — {_no_action_reason(r, False)}.\n"
                    "• Partners are comparable on freight cost after adjustment.")
        l1 = (f"• {w}: متوسط الشحن {r['avg_freight_usd']:,.0f}$ بزيادة {r['above_like_for_like_avg_pct']}% عن المتوسط لنفس نوع الحاوية والدولة ({r['shipments']} شحنة) — الإجراء: {act}."
              if ar else
              f"• {w}: average freight ${r['avg_freight_usd']:,.0f}, {r['above_like_for_like_avg_pct']}% above the like-for-like average (same container type and country, {r['shipments']} shipments) — action: {act}.")
        l2 = (f"• الأقل تكلفة نسبياً: {r['cheapest_partner']} ({r['cheapest_vs_like_for_like_pct']:+.1f}%)؛ الوفر المقدّر لو وصلنا لمستواه: حوالي {r['estimated_saving_usd_if_at_cheapest_level']:,.0f}$ على الفترة. ملاحظة: الجودة ومدة التوريد والطاقة الاستيعابية غير مقيَّمة."
              if ar else
              f"• Lowest relative cost: {r['cheapest_partner']} ({r['cheapest_vs_like_for_like_pct']:+.1f}%); estimated saving at its level: about ${r['estimated_saving_usd_if_at_cheapest_level']:,.0f} over the period. Note: quality, lead time and capacity are not evaluated.")
        return f"{l1}\n{l2}"

    return ""


def call_groq(api_key, prompt):
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": GROQ_MODEL, "messages": [{"role": "user", "content": prompt}],
               "temperature": 0.1, "max_completion_tokens": 3000, "reasoning_effort": "low"}
    try:
        r = requests.post(GROQ_URL, headers=headers, json=payload, timeout=90)
        if r.status_code == 400 and "reasoning_effort" in r.text:
            payload.pop("reasoning_effort")  # لو الموديل مش بيدعم الباراميتر
            r = requests.post(GROQ_URL, headers=headers, json=payload, timeout=90)
        if r.status_code != 200:
            return None, f"HTTP Error {r.status_code}: {r.text[:200]}"
        content = (r.json()["choices"][0]["message"].get("content") or "").strip()
        return (content, None) if content else (None, "Empty response from model")
    except Exception as e:
        return None, str(e)


def build_prompt(r, lang):
    sys_lang = "Arabic" if lang == 'ar' else "English"
    facts = {k: v for k, v in r.items() if k not in ('required_names',)}
    rules = (
        f"Write the output ONLY in {sys_lang}.\n"
        "You are given a PRECOMPUTED analysis (JSON) with a FIXED verdict and a fixed action. "
        "You only explain it. You MUST NOT change, soften or strengthen the verdict or the action.\n"
        "STRICT RULES:\n"
        "1. Output EXACTLY two short bullet points, each starting with '• '. No markdown, no asterisks, no headings.\n"
        "2. Names appear as placeholders like [N1], [N2]. Copy each placeholder EXACTLY as written (including the square brackets). Never translate, drop, rename or invent one.\n"
        "3. Use ONLY numbers that appear in the JSON. Never invent or round differently. Do not print p-values or statistical jargon; say in plain words whether the difference is statistically significant.\n"
        "4. If verdict is NO_ACTION or INSUFFICIENT_DATA: say clearly that no change is justified and why "
        "(gap below threshold / not statistically significant / sample too small). Never recommend suspending anyone.\n"
        "5. Bullet 1: the decision (use the action wording) with the key numbers behind it. "
        "Bullet 2: the evidence for the alternative and the estimated impact, or the cause if provided, or why no change is justified. "
        "If a 'caveat' field exists, mention it briefly in bullet 2.\n"
        "6. No corporate fluff (no 'schedule meetings', 'update contracts', etc.)."
    )
    return f"{rules}\n\nANALYSIS (JSON):\n{json.dumps(facts, ensure_ascii=False)}"


def _mask_names(r):
    """يستبدل الأسماء بعلامات [N1], [N2].. عشان الموديل ما يترجمها أو يغيّرها، ونرجّعها بعد التوليد."""
    names = list(dict.fromkeys(r.get('required_names', [])))
    mapping = {f"N{i + 1}": n for i, n in enumerate(names)}
    inverse = {n: k for k, n in mapping.items()}
    facts = {k: (f"[{inverse[v]}]" if isinstance(v, str) and v in inverse else v)
             for k, v in r.items() if k != 'required_names'}
    return facts, mapping


def _no_action_reason(r, ar):
    """يوضح سبب 'لا إجراء': فرق صغير حقيقي ولا فرق ممكن يكون صدفة."""
    if r.get('p_value', 1) < ALPHA:
        return ("الفرق حقيقي إحصائياً لكنه أصغر من حد التدخل" if ar
                else "the difference is real but smaller than the intervention threshold")
    return ("الفرق غير معنوي إحصائياً (قد يكون صدفة)" if ar
            else "the difference is not statistically significant (it may be chance)")


def generate_report_text(kind, r, lang, api_key):
    """يرجّع (النص، الوضع، ملاحظة). لو الـ AI فشل أو غيّر الأسماء، نرجع للقالب الجاهز."""
    fallback = template_report(kind, r, lang)
    if r['verdict'] == 'INSUFFICIENT_DATA':
        return fallback, 'template', None
    if not api_key:
        return fallback, 'template', 'no_key'

    facts, mapping = _mask_names(r)
    text, err = call_groq(api_key, build_prompt(facts, lang))
    if err:
        return fallback, 'template', err

    text = text.replace('*', '').strip()
    missing = [k for k in mapping if f"[{k}]" not in text]
    stray = sorted(set(re.findall(r"\[(N\d+)\]", text)) - set(mapping))
    if missing or stray:
        return fallback, 'template', f"placeholders missing={missing} stray={stray} | raw: {text[:150]}"
    for k, name in mapping.items():
        text = text.replace(f"[{k}]", name)
    return text, 'ai', None


def render_ai_box(text):
    clean_text = re.sub(r'\n\s*\n', '\n', text)
    safe = html.escape(clean_text)
    safe = re.sub(r'(?m)^[ \t]*[*-][ \t]+', '• ', safe)
    safe = safe.replace("\n", "<br>")
    safe = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", safe)
    st.markdown(f"<div style='padding: 25px; background: #F4F6FA; border: 2px solid #2BB3F3; border-radius: 12px; line-height: 1.8; color: #1B2F7A;' dir='auto'>{safe}</div>", unsafe_allow_html=True)

VERDICT_LABELS = {
    'NO_ACTION': {'ar': 'القرار المحسوب بالكود: لا إجراء', 'en': 'Computed verdict: no action'},
    'WARN_AND_MONITOR': {'ar': 'القرار المحسوب بالكود: إنذار ومتابعة', 'en': 'Computed verdict: warn & monitor'},
    'SHIFT_VOLUME': {'ar': 'القرار المحسوب بالكود: تحويل جزء من الحجم', 'en': 'Computed verdict: shift volume'},
    'INSUFFICIENT_DATA': {'ar': 'القرار المحسوب بالكود: بيانات غير كافية', 'en': 'Computed verdict: insufficient data'},
}

# ==== AI ANALYSIS END ====

# ==========================================
# 4. بناء الواجهة (Bilingual UI)
# ==========================================
st.markdown(f"<h2 style='color:#1B2F7A; font-weight:800; margin-bottom: 0;'>{tr({'ar': 'سلسلة الإمداد واللوجستيات', 'en': 'Supply Chain & Logistics'})}</h2>", unsafe_allow_html=True)

if df_import.empty or df_delivery.empty:
    st.warning(tr({'ar': 'بيانات سلسلة الإمداد غير متوفرة أو جاري تحميلها.', 'en': 'Supply Chain data is missing or loading.'}))
else:
    tab_analytics, tab_ai = st.tabs([
        tr({'ar': "الرؤية والتشغيل", 'en': "Operations Visibility"}), 
        tr({'ar': "مساعد اللوجستيات الذكي", 'en': "AI Logistics Assistant"})
    ])

    with tab_analytics:
        # --- Top KPIs ---
        total_import_cost = df_import['total_landed_cost_USD'].sum()
        total_deliveries = len(df_delivery)
        delayed_deliveries = df_delivery['is_delayed'].sum()
        on_time_rate = ((total_deliveries - delayed_deliveries) / total_deliveries * 100) if total_deliveries > 0 else 0
        avg_lead_time = df_delivery['lead_time_days'].mean()

        cols = st.columns(4)
        cols[0].markdown(f"<div style='background:#fff; padding:15px; border-radius:10px; border:1px solid #E1E6EE;'><div style='color:#667085; font-size:14px;'>{tr({'ar':'نسبة التوصيل في الموعد','en':'On-Time Delivery Rate'})}</div><div style='color:#1B2F7A; font-size:24px; font-weight:bold;'>{on_time_rate:.1f}%</div></div>", unsafe_allow_html=True)
        cols[1].markdown(f"<div style='background:#fff; padding:15px; border-radius:10px; border:1px solid #E1E6EE;'><div style='color:#667085; font-size:14px;'>{tr({'ar':'متوسط زمن الشحن الداخلي','en':'Avg Delivery Lead Time'})}</div><div style='color:#1B2F7A; font-size:24px; font-weight:bold;'>{avg_lead_time:.1f} Days</div></div>", unsafe_allow_html=True)
        cols[2].markdown(f"<div style='background:#fff; padding:15px; border-radius:10px; border:1px solid #E1E6EE;'><div style='color:#667085; font-size:14px;'>{tr({'ar':'إجمالي الشحنات الموزعة','en':'Total Delivered Shipments'})}</div><div style='color:#1B2F7A; font-size:24px; font-weight:bold;'>{total_deliveries:,}</div></div>", unsafe_allow_html=True)
        cols[3].markdown(f"<div style='background:#fff; padding:15px; border-radius:10px; border:1px solid #E1E6EE;'><div style='color:#667085; font-size:14px;'>{tr({'ar':'إجمالي تكلفة الاستيراد','en':'Total Landed Import Cost'})}</div><div style='color:#1B2F7A; font-size:24px; font-weight:bold;'>${total_import_cost/1e6:.2f}M</div></div>", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # --- Charts ---
        chart_cols = st.columns(2)
        
        with chart_cols[0]:
            st.markdown(f"<div style='color:#1B2F7A; font-weight:700;'>{tr({'ar': 'أداء شركات الشحن الداخلي (التأخيرات)', 'en': 'Carrier Performance (Delays)'})}</div>", unsafe_allow_html=True)
            carrier_df = df_delivery.groupby('carrier').agg({'is_delayed':'sum'}).reset_index()
            fig_carrier = px.bar(carrier_df, x='carrier', y='is_delayed', title="", color_discrete_sequence=['#ef4444'])
            fig_carrier.update_layout(xaxis_title="", yaxis_title="")
            st.plotly_chart(fig_carrier, use_container_width=True)

        with chart_cols[1]:
            st.markdown(f"<div style='color:#1B2F7A; font-weight:700;'>{tr({'ar': 'تكاليف الاستيراد حسب الدولة', 'en': 'Import Landed Cost by Country'})}</div>", unsafe_allow_html=True)
            country_df = df_import.groupby('country').agg({'total_landed_cost_USD':'sum'}).reset_index()
            fig_country = px.pie(country_df, names='country', values='total_landed_cost_USD', hole=0.4, color_discrete_sequence=px.colors.sequential.Blues_r)
            st.plotly_chart(fig_country, use_container_width=True)

        # --- Data Table ---
        st.markdown(f"<div style='color:#1B2F7A; font-weight:700; margin-top:20px;'>{tr({'ar': 'سجل الواردات والشحنات الدولية', 'en': 'Inbound Shipments Log'})}</div>", unsafe_allow_html=True)
        display_import_df = df_import[['import_shipment_id', 'partner_name', 'country', 'port_name', 'container_type', 'total_landed_cost_USD']].copy()
        
        if st.session_state.lang == 'ar':
            display_import_df.columns = ['رقم الشحنة', 'المورد', 'دولة المنشأ', 'ميناء الوصول', 'نوع الحاوية', 'إجمالي التكلفة ($)']
        else:
            display_import_df.columns = ['Shipment ID', 'Supplier', 'Origin Country', 'Destination Port', 'Container Type', 'Total Landed Cost ($)']
            
        st.dataframe(display_import_df.style.format({display_import_df.columns[5]: '${:,.0f}'}), use_container_width=True)

    with tab_ai:
        api_key_configured, telegram_configured = False, False
        try:
            api_key = st.secrets.get("GROQ_API_KEY", "")
            if api_key: api_key_configured = True
            telegram_token = st.secrets.get("TELEGRAM_TOKEN", "")
            telegram_chat_id = st.secrets.get("TELEGRAM_CHAT_ID", "")
            if telegram_token and telegram_chat_id: telegram_configured = True
        except:
            pass

        dec_file = 'data/supply_chain_decisions_log.csv'

        c_ai1, c_ai2 = st.columns([1, 1])
        
        with c_ai1:
            analysis_options = {
                "carrier_perf": tr({'ar': "تقييم أداء شركات الشحن (واقتراح البديل)", 'en': "Carrier Performance (Identify Worst & Best)"}),
                "gov_bottleneck": tr({'ar': "اختناقات التوزيع بالمحافظات", 'en': "Governorate Distribution Bottlenecks"}),
                "import_costs": tr({'ar': "تحليل تكاليف الاستيراد والموردين", 'en': "Import Sourcing Cost Analysis"})
            }
            selected_option = st.selectbox(tr({'ar': "نوع التحليل اللوجستي:", 'en': "Logistics Analysis Type:"}), list(analysis_options.keys()), format_func=lambda x: analysis_options[x])
            
            btn_label = tr({'ar': "توليد التقرير", 'en': "Generate Report"})
            if st.button(btn_label, type="primary"):
                with st.spinner(tr({'ar': "جاري تحليل البيانات وصياغة التقرير...", 'en': "Analyzing data and drafting report..."})):
                    # 1) الكود يحسب القرار (عتبات + اختبار إحصائي + أثر)
                    result = run_sc_analysis(selected_option)
                    # 2) الـ AI يصيغ القرار الجاهز فقط، ولو فشل نرجع للقالب
                    ai_text, ai_mode, ai_note = generate_report_text(
                        selected_option, result, st.session_state.lang,
                        api_key if api_key_configured else None
                    )
                    st.session_state['sc_ai_response'] = ai_text
                    st.session_state['sc_ai_title'] = analysis_options[selected_option]
                    st.session_state['sc_ai_facts'] = result
                    st.session_state['sc_ai_mode'] = ai_mode
                    st.session_state['sc_ai_note'] = ai_note

            if 'sc_ai_response' in st.session_state:
                st.markdown(f"**{tr({'ar': 'تقرير:', 'en': 'Report:'})} {st.session_state['sc_ai_title']}**")
                render_ai_box(st.session_state['sc_ai_response'])

                facts = st.session_state.get('sc_ai_facts', {})
                mode_label = tr({'ar': 'صياغة بالذكاء الاصطناعي', 'en': 'AI-worded'}) if st.session_state.get('sc_ai_mode') == 'ai' else tr({'ar': 'صياغة بقالب جاهز', 'en': 'Template-worded'})
                st.caption(f"{tr(VERDICT_LABELS.get(facts.get('verdict'), {}))}  |  {mode_label}")
                if st.session_state.get('sc_ai_note') and st.session_state['sc_ai_note'] != 'no_key':
                    st.caption(tr({'ar': 'تم استخدام القالب الجاهز بسبب: ', 'en': 'Template used because: '}) + str(st.session_state['sc_ai_note']))
                with st.expander(tr({'ar': 'الأرقام التي بُني عليها التقرير', 'en': 'Numbers behind this report'})):
                    st.json({k: v for k, v in facts.items() if k not in ('required_names',)})
                
                st.markdown("<br>", unsafe_allow_html=True)
                send_btn = tr({'ar': "إرسال التقرير لاعتماد الإدارة (تليجرام)", 'en': "Send to Management for Approval (Telegram)"})
                if st.button(send_btn):
                    if telegram_configured:
                        try:
                            decision_id = str(int(time.time()))
                            topic_label = "الموضوع:" if st.session_state.lang == 'ar' else "Topic:"
                            report_label = "التقرير:" if st.session_state.lang == 'ar' else "Report:"
                            
                            message = f"*Cotonil Supply Chain*\n\n*{topic_label}* {st.session_state['sc_ai_title']}\n\n*{report_label}*\n{st.session_state['sc_ai_response']}"
                            
                            url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
                            payload = {
                                "chat_id": telegram_chat_id,
                                "text": message[:4000],
                                "parse_mode": "Markdown",
                                "reply_markup": {
                                    "inline_keyboard": [[
                                        {"text": "Approve / اعتماد", "callback_data": f"Approve_{decision_id}"},
                                        {"text": "Reject / رفض", "callback_data": f"Reject_{decision_id}"}
                                    ]]
                                }
                            }
                            res = requests.post(url, json=payload, timeout=30)
                            if res.status_code == 200:
                                new_dec = pd.DataFrame([{'ID': decision_id, 'Date': pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"), 'Decision': st.session_state['sc_ai_title'], 'Status': "Pending"}])
                                if os.path.exists(dec_file):
                                    df_exist = pd.read_csv(dec_file)
                                    df_updated = pd.concat([new_dec, df_exist], ignore_index=True)
                                else:
                                    df_updated = new_dec
                                if not os.path.exists('data'): os.makedirs('data')
                                df_updated.to_csv(dec_file, index=False)
                                st.success(tr({'ar': "تم الإرسال وحفظ القرار بحالة 'معلق'.", 'en': "Sent successfully and saved as 'Pending'."}))
                            else:
                                st.error(tr({'ar': "خطأ تليجرام.", 'en': "Telegram error."}))
                        except Exception as e:
                            st.error(str(e))
                    else:
                        st.warning(tr({'ar': "إعدادات تليجرام مفقودة.", 'en': "Telegram settings missing."}))

        with c_ai2:
            st.markdown(f"<h4 style='color:#1B2F7A;'>{tr({'ar': 'سجل اعتمادات اللوجستيات', 'en': 'Logistics Approvals Log'})}</h4>", unsafe_allow_html=True)
            if telegram_configured:
                sync_btn = tr({'ar': "تحديث الحالات من تليجرام (Sync)", 'en': "Sync Status from Telegram"})
                if st.button(sync_btn):
                    try:
                        url = f"https://api.telegram.org/bot{telegram_token}/getUpdates"
                        res = requests.get(url, timeout=30).json()
                        if res.get("ok") and res.get("result"):
                            updates = res["result"]
                            highest_update_id = 0
                            updates_found = False
                            if os.path.exists(dec_file):
                                df = pd.read_csv(dec_file)
                                for update in updates:
                                    highest_update_id = update["update_id"]
                                    if "callback_query" in update:
                                        cb_data = update["callback_query"]["data"]
                                        if "_" in cb_data:
                                            action, dec_id = cb_data.split("_")
                                            if 'ID' in df.columns:
                                                df.loc[df['ID'].astype(str) == str(dec_id), 'Status'] = 'Approved' if action == 'Approve' else 'Rejected'
                                                updates_found = True
                                if updates_found:
                                    df.to_csv(dec_file, index=False)
                                    requests.get(f"{url}?offset={highest_update_id + 1}", timeout=30)
                                    st.success(tr({'ar': "تم تحديث الحالات بنجاح.", 'en': "Status synced successfully."}))
                                    time.sleep(1)
                                    st.rerun()
                    except:
                        pass

            if os.path.exists(dec_file):
                dec_df = pd.read_csv(dec_file)
                
                if st.session_state.lang == 'ar':
                    dec_df.rename(columns={'Date': 'التاريخ', 'Decision': 'الموضوع', 'Status': 'الحالة'}, inplace=True)
                
                status_col = 'الحالة' if st.session_state.lang == 'ar' else 'Status'
                
                def color_status(val):
                    color = '#f59e0b' if val == 'Pending' else '#10b981' if val == 'Approved' else '#ef4444'
                    return f'color: {color}; font-weight: bold'
                    
                if status_col in dec_df.columns:
                    st.dataframe(dec_df.style.map(color_status, subset=[status_col]), hide_index=True, use_container_width=True)
                else:
                    st.dataframe(dec_df, hide_index=True, use_container_width=True)