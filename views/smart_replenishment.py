import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import os
import re
import sys
import html
import time
import json
import hashlib
import tempfile
import datetime
import traceback
import requests

st.set_page_config(layout="wide", page_title="Smart Inventory Distribution")

# ----------------------------------------------------------------------------------------------
# Paths + optional PDF module (kept optional so the rest of the app never dies because of it)
# ----------------------------------------------------------------------------------------------
APP_DIR = os.path.dirname(os.path.abspath(__file__))
for _p in (APP_DIR, os.path.dirname(APP_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    import directive_pdf
    PDF_IMPORT_ERROR = None
except Exception as _e:  # noqa: BLE001 - shown to the user when a PDF is requested
    directive_pdf = None
    PDF_IMPORT_ERROR = f"{type(_e).__name__}: {_e}"


def resolve_data_dir():
    local = os.path.join(APP_DIR, 'data')
    return local if os.path.exists(local) else os.path.join(os.path.dirname(APP_DIR), 'data')


if 'lang' not in st.session_state:
    st.session_state.lang = 'ar'


def tr(text_dict):
    return text_dict.get(st.session_state.lang, text_dict.get('en', ''))


def get_secret(name, default=""):
    """Read one secret independently of the others (st.secrets first, then environment)."""
    value = None
    try:
        value = st.secrets.get(name, None)
    except Exception:  # no secrets file / key missing
        value = None
    if not value:
        value = os.environ.get(name, default)
    return str(value).strip() if value else default


def redact(message, *secrets):
    """Never show tokens / keys in error messages (requests errors contain the full URL)."""
    msg = str(message)
    for s in secrets:
        if s:
            msg = msg.replace(s, "***")
    return re.sub(r"bot\d+:[A-Za-z0-9_-]+", "bot***", msg)


st.markdown("""
    <style>
    .stApp { background-color: #f8fafc; color: #0f172a; }
    .kpi-card {
        background-color: #ffffff; padding: 20px; border-radius: 12px;
        border: 2px solid #cbd5e1; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        text-align: center; margin-bottom: 15px;
        transition: transform 0.2s;
    }
    .kpi-card:hover { transform: scale(1.02); border-color: #3b82f6; }
    .kpi-value { font-size: 25px; font-weight: bold; color: #1e3a8a; margin-bottom: 5px; }
    .kpi-label { font-size: 14px; color: #64748b; font-weight: 600; }
    
    .ai-response-box {
        padding: 40px; 
        background-color: #ffffff; 
        border: 1px solid #cbd5e1;
        border-radius: 8px; 
        font-size: 17px; 
        line-height: 2.2; 
        color: #0f172a;
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
        font-family: 'Arial', sans-serif;
    }
    
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 12px; border: 2px solid #94a3b8 !important; 
        background-color: #ffffff; padding: 15px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    }
    </style>
""", unsafe_allow_html=True)


# ----------------------------------------------------------------------------------------------
# Data Loading (Memory Optimized)
# ----------------------------------------------------------------------------------------------
class DataLoadError(Exception):
    """Readable data problem (missing file / missing columns)."""


def _read_parquet(data_dir, filename, columns):
    path = os.path.join(data_dir, filename)
    if not os.path.exists(path):
        raise DataLoadError(f"الملف غير موجود / File not found: {path}")
    try:
        import pyarrow.parquet as pq
        available = set(pq.read_schema(path).names)
        missing = [c for c in columns if c not in available]
        if missing:
            raise DataLoadError(f"{filename}: أعمدة ناقصة / missing columns: {missing}")
    except ImportError:
        pass  # pandas will raise its own clear error below if no parquet engine exists
    return pd.read_parquet(path, columns=columns)


def _to_naive_datetime(series):
    out = pd.to_datetime(series, errors='coerce')
    try:
        if getattr(out.dt, 'tz', None) is not None:
            out = out.dt.tz_localize(None)
    except (AttributeError, TypeError):
        pass
    return out


@st.cache_data(show_spinner=False)
def load_distribution_data():
    data_dir = resolve_data_dir()

    df_transfers = _read_parquet(data_dir, 'inventory_transfers.parquet',
                                 ['transfer_id', 'transfer_date', 'destination_branch_id', 'transport_cost_EGP'])
    df_transfer_items = _read_parquet(data_dir, 'inventory_transfer_items.parquet',
                                      ['transfer_id', 'sku_id', 'quantity_units'])
    df_sku = _read_parquet(data_dir, 'sku_variants.parquet', ['sku_id', 'product_id', 'size'])
    df_products = _read_parquet(data_dir, 'products_catalog.parquet', ['product_id', 'product_name_ar'])
    df_so_items = _read_parquet(data_dir, 'sales_order_items.parquet', ['order_date', 'branch_id', 'sku_id', 'quantity'])
    df_branches = _read_parquet(data_dir, 'branches.parquet', ['branch_id', 'branch_name_ar'])

    # Lookup tables must have unique keys, otherwise the joins silently multiply sales/transfer rows.
    dup = {
        'sku': int(df_sku['sku_id'].duplicated().sum()),
        'product': int(df_products['product_id'].duplicated().sum()),
        'branch': int(df_branches['branch_id'].duplicated().sum()),
        'transfer': int(df_transfers['transfer_id'].duplicated().sum()),
    }
    df_sku = df_sku.drop_duplicates('sku_id')
    df_products = df_products.drop_duplicates('product_id')
    df_branches = df_branches.drop_duplicates('branch_id')
    df_transfers = df_transfers.drop_duplicates('transfer_id')

    df_sku_full = df_sku.merge(df_products, on='product_id', how='inner')
    df_sku_full.drop(columns=['product_id'], inplace=True)

    sales_full = df_so_items.merge(df_sku_full, on='sku_id', how='inner')
    sales_full = sales_full.merge(df_branches, on='branch_id', how='inner')
    sales_full['order_date'] = _to_naive_datetime(sales_full['order_date'])
    sales_full.drop(columns=['branch_id', 'sku_id'], inplace=True)

    transfers_full = df_transfer_items.merge(df_transfers, on='transfer_id', how='inner')
    transfers_full = transfers_full.merge(df_branches, left_on='destination_branch_id', right_on='branch_id', how='inner')
    transfers_full = transfers_full.merge(df_sku_full, on='sku_id', how='inner')
    transfers_full['transfer_date'] = _to_naive_datetime(transfers_full['transfer_date'])

    # FIX (real calculation error): transport_cost_EGP is stored once per TRANSFER (header table), but after the
    # join with the transfer LINES it is repeated on every line, so summing it counted each transfer's cost once
    # per line. The cost is now split across the lines of the same transfer in proportion to their units, so
    # totals (and any product filter) add up to the real cost.
    qty = pd.to_numeric(transfers_full['quantity_units'], errors='coerce').fillna(0)
    cost = pd.to_numeric(transfers_full['transport_cost_EGP'], errors='coerce')
    tot_units = qty.groupby(transfers_full['transfer_id']).transform('sum')
    n_lines = qty.groupby(transfers_full['transfer_id']).transform('size')
    share = (qty / tot_units.where(tot_units > 0)).fillna(1.0 / n_lines)
    transfers_full['quantity_units'] = qty
    transfers_full['transport_cost_EGP'] = cost * share
    transfers_full.drop(columns=['destination_branch_id', 'branch_id', 'sku_id', 'transfer_id'], inplace=True)

    quality = {
        'sales_rows_in': int(len(df_so_items)), 'sales_rows_used': int(len(sales_full)),
        'transfer_lines_in': int(len(df_transfer_items)), 'transfer_lines_used': int(len(transfers_full)),
        'bad_sales_dates': int(sales_full['order_date'].isna().sum()),
        'bad_transfer_dates': int(transfers_full['transfer_date'].isna().sum()),
        'duplicate_keys': dup,
    }
    return sales_full, transfers_full, quality


try:
    sales_full, transfers_full, load_quality = load_distribution_data()
except DataLoadError as _err:
    st.error(f"حدث خطأ أثناء قراءة البيانات / Data error:\n\n{_err}")
    st.stop()
except Exception:  # noqa: BLE001
    st.error("حدث خطأ فني أثناء قراءة البيانات. التفاصيل:")
    st.code(traceback.format_exc())
    st.stop()

# ----------------------------------------------------------------------------------------------
# Sidebar & Filters
# ----------------------------------------------------------------------------------------------
st.sidebar.markdown(f"<h3>{tr({'ar': 'إعدادات النظام', 'en': 'System Settings'})}</h3>", unsafe_allow_html=True)
selected_lang = st.sidebar.radio(
    tr({'ar': "اختر اللغة", 'en': "Select Language"}),
    options=['ar', 'en'],
    index=0 if st.session_state.lang == 'ar' else 1
)
if selected_lang != st.session_state.lang:
    st.session_state.lang = selected_lang
    st.rerun()

st.markdown(f"<h2 style='color:#1e3a8a; margin-bottom: 20px;'>{tr({'ar': 'اللوجستيات والتوزيع الجغرافي', 'en': 'Logistics & Geographic Distribution'})}</h2>", unsafe_allow_html=True)

_valid_dates = sales_full['order_date'].dropna()
min_date = _valid_dates.min().date() if not _valid_dates.empty else datetime.date(2020, 1, 1)
max_date = _valid_dates.max().date() if not _valid_dates.empty else datetime.date.today()
available_products = sales_full['product_name_ar'].dropna().unique().tolist()

with st.container(border=True):
    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        start_date = st.date_input(tr({'ar': "من تاريخ", 'en': "Start Date"}), min_date)
    with c2:
        end_date = st.date_input(tr({'ar': "إلى تاريخ", 'en': "End Date"}), max_date)
    with c3:
        selected_products = st.multiselect(
            tr({'ar': "تحديد المنتجات (للتوزيع والتكلفة)", 'en': "Select Products"}),
            available_products, 
            default=available_products[:3] if len(available_products) > 3 else available_products
        )

if start_date > end_date:
    st.error(tr({'ar': "تاريخ البداية يجب أن يكون قبل تاريخ النهاية.", 'en': "Start date must be on or before end date."}))
    st.stop()

_dropped_s = load_quality['sales_rows_in'] - load_quality['sales_rows_used']
_dropped_t = load_quality['transfer_lines_in'] - load_quality['transfer_lines_used']
if _dropped_s > 0 or _dropped_t > 0 or any(load_quality['duplicate_keys'].values()):
    with st.expander(tr({'ar': "ملاحظات جودة البيانات", 'en': "Data quality notes"})):
        if _dropped_s > 0:
            st.write(tr({'ar': f"تم استبعاد {_dropped_s:,} سطر مبيعات لعدم وجود SKU أو فرع مطابق.", 'en': f"{_dropped_s:,} sales rows were excluded (no matching SKU or branch)."}))
        if _dropped_t > 0:
            st.write(tr({'ar': f"تم استبعاد {_dropped_t:,} سطر تحويل لعدم وجود تحويل أو فرع أو SKU مطابق.", 'en': f"{_dropped_t:,} transfer lines were excluded (no matching transfer, branch or SKU)."}))
        if any(load_quality['duplicate_keys'].values()):
            st.write(tr({'ar': f"مفاتيح مكررة في جداول المرجع (تم الاحتفاظ بأول سجل): {load_quality['duplicate_keys']}", 'en': f"Duplicate keys in lookup tables (first record kept): {load_quality['duplicate_keys']}"}))

_start_ts = pd.Timestamp(start_date)
_end_ts = pd.Timestamp(end_date) + pd.Timedelta(days=1)   # end date is inclusive
mask_sales = (sales_full['order_date'] >= _start_ts) & (sales_full['order_date'] < _end_ts)
f_sales = sales_full[mask_sales].copy()
if selected_products:
    f_sales = f_sales[f_sales['product_name_ar'].isin(selected_products)]

mask_transfers = (transfers_full['transfer_date'] >= _start_ts) & (transfers_full['transfer_date'] < _end_ts)
f_transfers = transfers_full[mask_transfers].copy()
if selected_products:
    f_transfers = f_transfers[f_transfers['product_name_ar'].isin(selected_products)]


# ==========================================
# Core Calculations 
# ==========================================
def compute_distribution_metrics(f_sales, f_transfers):
    total_transport_cost = float(f_transfers['transport_cost_EGP'].sum())
    total_units_transferred = float(f_transfers['quantity_units'].sum())
    avg_cost_per_unit = total_transport_cost / total_units_transferred if total_units_transferred > 0 else 0.0

    size_dist = f_sales.groupby(['branch_name_ar', 'product_name_ar', 'size'])['quantity'].sum().reset_index()
    top_sizes_per_branch = size_dist.sort_values(
        ['branch_name_ar', 'product_name_ar', 'quantity'], ascending=[True, True, False]
    ).drop_duplicates(['branch_name_ar', 'product_name_ar'])

    if f_transfers.empty:
        route_cost = pd.DataFrame(columns=['branch_name_ar', 'transport_cost_EGP', 'quantity_units', 'cost_per_unit'])
    else:
        route_cost = f_transfers.groupby('branch_name_ar').agg(
            transport_cost_EGP=('transport_cost_EGP', 'sum'),
            quantity_units=('quantity_units', 'sum'),
        ).reset_index()
        # cost per unit only makes sense when units were actually moved (no division by zero / fake values)
        route_cost['cost_per_unit'] = route_cost['transport_cost_EGP'] / route_cost['quantity_units'].where(route_cost['quantity_units'] > 0)

    valid_routes = route_cost.dropna(subset=['cost_per_unit'])
    worst_route = valid_routes.sort_values('cost_per_unit', ascending=False).iloc[0] if not valid_routes.empty else None

    return {
        'total_transport_cost': total_transport_cost,
        'total_units_transferred': total_units_transferred,
        'avg_cost_per_unit': avg_cost_per_unit,
        'size_dist': size_dist,
        'top_sizes_per_branch': top_sizes_per_branch,
        'route_cost': route_cost,
        'worst_route': worst_route,
    }


metrics = compute_distribution_metrics(f_sales, f_transfers)
total_transport_cost = metrics['total_transport_cost']
total_units_transferred = metrics['total_units_transferred']
avg_cost_per_unit = metrics['avg_cost_per_unit']
size_dist = metrics['size_dist']
top_sizes_per_branch = metrics['top_sizes_per_branch']
route_cost = metrics['route_cost']
worst_route = metrics['worst_route']

# ----------------------------------------------------------------------------------------------
# Dashboard UI
# ----------------------------------------------------------------------------------------------
tab_dashboard, tab_ai = st.tabs([
    tr({'ar': "تحليلات التوزيع والنقل", 'en': "Distribution & Logistics"}),
    tr({'ar': "مركز التكليفات اللوجستية", 'en': "Logistics Directives Center"})
])

with tab_dashboard:
    c1, c2, c3 = st.columns(3)
    c1.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"إجمالي تكلفة النقل", "en":"Total Transport Cost"})}</div><div class="kpi-value">EGP {total_transport_cost:,.0f}</div></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"إجمالي القطع المحولة", "en":"Units Transferred"})}</div><div class="kpi-value">{total_units_transferred:,.0f}</div></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"متوسط تكلفة نقل القطعة", "en":"Avg Cost / Unit"})}</div><div class="kpi-value">EGP {avg_cost_per_unit:,.2f}</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    
    r1c1, r1c2 = st.columns(2)
    with r1c1:
        with st.container(border=True):
            st.markdown(f"<h4 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'توزيع سحب المقاسات جغرافياً (للمنتجات المحددة)', 'en': 'Size Demand for Selected Products'})}</h4>", unsafe_allow_html=True)
            if not size_dist.empty:
                top_branches_vol = size_dist.groupby('branch_name_ar')['quantity'].sum().nlargest(15).index
                chart_data = size_dist[size_dist['branch_name_ar'].isin(top_branches_vol)]
                fig_sizes = px.bar(chart_data, x='branch_name_ar', y='quantity', color='size', barmode='stack')
                fig_sizes.update_layout(xaxis_title="", yaxis_title=tr({'ar': "كمية المبيعات", 'en': "Sales Quantity"}), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', legend_title=tr({'ar': "المقاس", 'en': "Size"}))
                st.plotly_chart(fig_sizes, use_container_width=True)

    with r1c2:
        with st.container(border=True):
            st.markdown(f"<h4 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'تكلفة نقل القطعة الواحدة حسب وجهة الفرع', 'en': 'Transport Cost Per Unit by Destination'})}</h4>", unsafe_allow_html=True)
            if not route_cost.empty:
                cost_chart = route_cost[route_cost['quantity_units'] > 0].sort_values('cost_per_unit', ascending=False).head(10)
                fig_cost = px.bar(cost_chart, x='branch_name_ar', y='cost_per_unit', text_auto='.2f', color_discrete_sequence=['#f59e0b'])
                fig_cost.update_layout(xaxis_title="", yaxis_title=tr({'ar': "تكلفة نقل القطعة (ج.م)", 'en': "Transport cost per unit (EGP)"}), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
                st.plotly_chart(fig_cost, use_container_width=True)

    st.markdown("<br>", unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown(f"<h4 style='color:#1e3a8a;'>{tr({'ar': 'جدول التوجيه الدقيق للمقاسات حسب المنتج والفرع', 'en': 'Exact Size Distribution by Product & Branch'})}</h4>", unsafe_allow_html=True)
        
        display_df = top_sizes_per_branch.merge(route_cost[['branch_name_ar', 'cost_per_unit']], on='branch_name_ar', how='left')
        display_df = display_df.sort_values(['product_name_ar', 'quantity'], ascending=[True, False])
        
        display_df.rename(columns={
            'branch_name_ar': tr({'ar': 'الفرع الوجهة', 'en': 'Destination Branch'}),
            'product_name_ar': tr({'ar': 'اسم المنتج', 'en': 'Product Name'}),
            'size': tr({'ar': 'المقاس الواجب توجيهه', 'en': 'Required Size'}),
            'quantity': tr({'ar': 'حجم الطلب (مبيعات)', 'en': 'Sales Volume'}),
            'cost_per_unit': tr({'ar': 'تكلفة نقل القطعة للفرع (ج.م)', 'en': 'Route Cost / Unit'})
        }, inplace=True)
        
        st.dataframe(display_df.style.format({
            tr({'ar': 'حجم الطلب (مبيعات)', 'en': 'Sales Volume'}): "{:,.0f}",
            tr({'ar': 'تكلفة نقل القطعة للفرع (ج.م)', 'en': 'Route Cost / Unit'}): "{:.2f}"
        }, na_rep="-"), use_container_width=True, hide_index=True)


# ----------------------------------------------------------------------------------------------
# AI Tab helpers (Groq, facts, Telegram, decisions log, PDF)
# ----------------------------------------------------------------------------------------------
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-20b"


def call_groq(api_key, prompt):
    """Returns (text, None) on success or (None, readable_error). Never returns an empty 'success'."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": GROQ_MODEL, "messages": [{"role": "user", "content": prompt}],
               "temperature": 0.1, "max_completion_tokens": 3000, "reasoning_effort": "low"}
    try:
        r = requests.post(GROQ_URL, headers=headers, json=payload, timeout=90)
        if r.status_code == 400 and "reasoning_effort" in r.text:
            payload.pop("reasoning_effort")   # model/account without that parameter
            r = requests.post(GROQ_URL, headers=headers, json=payload, timeout=90)
    except requests.exceptions.Timeout:
        return None, tr({'ar': "انتهت مهلة الاتصال بـ Groq (90 ثانية). حاول مرة أخرى.", 'en': "Groq request timed out (90s). Please try again."})
    except requests.exceptions.RequestException as e:
        return None, redact(f"Groq connection error: {e}", api_key)

    if r.status_code != 200:
        detail = ""
        try:
            detail = (r.json().get("error") or {}).get("message", "")
        except ValueError:
            detail = r.text[:200]
        hint = {
            401: tr({'ar': "مفتاح GROQ_API_KEY غير صالح.", 'en': "Invalid GROQ_API_KEY."}),
            403: tr({'ar': "ليس لديك صلاحية استخدام هذا النموذج.", 'en': "No permission to use this model."}),
            429: tr({'ar': "تم تجاوز حد الطلبات، انتظر قليلاً ثم أعد المحاولة.", 'en': "Rate limit reached, wait a moment and retry."}),
        }.get(r.status_code, "")
        return None, redact(f"Groq HTTP {r.status_code}. {hint} {detail}".strip(), api_key)

    try:
        choice = r.json()["choices"][0]
        content = (choice["message"].get("content") or "").strip()
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        return None, tr({'ar': "استجابة غير متوقعة من Groq.", 'en': "Unexpected response from Groq."})
    if not content:
        return None, tr({'ar': "أعاد النموذج ردًا فارغًا. أعد المحاولة.", 'en': "The model returned an empty reply. Please retry."})
    return content, None


def build_distribution_facts(m, lang):
    """Plain-text facts for the model. Returns None when there is not enough data (no AI call is made then)."""
    route_cost_m, top_sizes_m, worst_m = m['route_cost'], m['top_sizes_per_branch'], m['worst_route']
    if route_cost_m.empty or top_sizes_m.empty:
        return None

    # "most important branches" = highest sales volume (the original took the alphabetically first 7)
    sample = top_sizes_m.sort_values('quantity', ascending=False).head(7)
    if lang == 'ar':
        lines = [f"متوسط تكلفة نقل القطعة الواحدة للشركة هو {m['avg_cost_per_unit']:.2f} ج.م."]
        if worst_m is not None:
            lines.append(f"أغلى خط سير نقل هو فرع: {worst_m['branch_name_ar']} بتكلفة {worst_m['cost_per_unit']:.2f} ج.م للقطعة.")
        lines.append("البيانات الدقيقة لتوجيه المقاسات للمنتجات في أهم الفروع (الأعلى طلباً):")
        for _, row in sample.iterrows():
            lines.append(f"- فرع: {row['branch_name_ar']} | المنتج: {row['product_name_ar']} | المقاس: {row['size']} | حجم الطلب: {row['quantity']:,.0f}")
    else:
        lines = [f"The company's average transport cost per unit is EGP {m['avg_cost_per_unit']:.2f}."]
        if worst_m is not None:
            lines.append(f"The most expensive transport route is the branch: {worst_m['branch_name_ar']} at EGP {worst_m['cost_per_unit']:.2f} per unit.")
        lines.append("Exact size-routing data for products in the most important branches (highest demand):")
        for _, row in sample.iterrows():
            lines.append(f"- Branch: {row['branch_name_ar']} | Product: {row['product_name_ar']} | Size: {row['size']} | Sales volume: {row['quantity']:,.0f}")
    return "\n".join(lines)


def build_prompt(facts_text, lang):
    if lang == 'ar':
        return (
            "أنت مدير قطاع اللوجستيات وإدارة المخزون. اكتب باللغة العربية مذكرة رسمية (Business Memo) لمديري المخازن.\n"
            f"بناءً على البيانات التالية حصرياً:\n{facts_text}\n"
            "المطلوب:\n"
            "1. يمنع منعاً باتاً استخدام الجداول (Tables) أو صيغة الماركدوان للجداول، استخدم بدلاً منها القوائم النقطية (Bullet points) لسهولة قراءتها.\n"
            "2. يمنع استخدام أي رموز تعبيرية (Emojis).\n"
            "3. اذكر بوضوح في قائمة نقطية أسماء الفروع، وأمام كل فرع اسم المنتج والمقاس المطلوب توجيهه له.\n"
            "4. قدم توصيات تشغيلية سريعة لخفض تكلفة النقل للفرع الأغلى المذكور في البيانات.\n"
            "5. لا تقم بتأليف بيانات غير موجودة.\n"
            "6. اكتب أسماء الفروع والمنتجات كما وردت في البيانات تماماً."
        )
    return (
        "You are the head of logistics and inventory management. Write a formal business memo in English for warehouse managers.\n"
        f"Based exclusively on the following data:\n{facts_text}\n"
        "Requirements:\n"
        "1. Tables and Markdown table syntax are strictly forbidden; use bullet points instead for readability.\n"
        "2. Do not use any emojis.\n"
        "3. List clearly, in bullet points, the branch names, and next to each branch the product name and the size to be routed to it.\n"
        "4. Give quick operational recommendations to reduce transport cost for the most expensive branch mentioned in the data.\n"
        "5. Do not invent data that is not provided.\n"
        "6. Keep branch and product names exactly as given in the data (they are in Arabic)."
    )


def render_memo_box(text):
    """Escape first (the text comes from an LLM), then apply simple formatting."""
    lines = []
    for line in text.split("\n"):
        s = html.escape(line)
        s = re.sub(r"^\s*#{1,6}\s+(.*)$", r"<b>\1</b>", s)
        s = re.sub(r"^(\s*)[*+-]\s+", r"\1• ", s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        lines.append(s)
    safe_html = "<br>".join(lines)
    st.markdown(f"<div class='ai-response-box' dir='auto'>{safe_html}</div>", unsafe_allow_html=True)


# ---- Telegram -----------------------------------------------------------------------------------
TG_CHUNK = 3500   # Telegram limit is 4096 characters per message; leave room for tags


def telegram_html(text):
    out = []
    for line in text.split("\n"):
        s = html.escape(line, quote=False)
        s = re.sub(r"^\s*#{1,6}\s+(.*)$", r"<b>\1</b>", s)
        s = re.sub(r"^(\s*)[*+-]\s+", r"\1• ", s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        s = s.replace("**", "")
        out.append(s)
    return "\n".join(out)


def split_for_telegram(body, limit=TG_CHUNK):
    chunks, cur = [], ""
    for line in body.split("\n"):
        while len(line) > limit:                       # one extremely long line
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(cur) + len(line) + 1 > limit and cur:
            chunks.append(cur)
            cur = line
        else:
            cur = line if not cur else cur + "\n" + line
    if cur:
        chunks.append(cur)
    return chunks or [""]


def send_telegram_directive(token, chat_id, memo_text, decision_id, lang):
    """Returns (True, None) only if Telegram confirmed every message; otherwise (False, readable_error)."""
    title = "أمر تكليف لوجستي (قطونيل)" if lang == 'ar' else "Logistics Directive (Cotonil)"
    button = "تم استلام التوجيه وجاري التنفيذ" if lang == 'ar' else "Directive received - in progress"
    chunks = split_for_telegram(telegram_html(memo_text))
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for i, chunk in enumerate(chunks):
        text = (f"<b>{html.escape(title)}</b>\n\n" if i == 0 else "") + chunk
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if i == len(chunks) - 1:   # the approval button goes on the last part
            payload["reply_markup"] = {"inline_keyboard": [[{"text": button, "callback_data": f"Approve_{decision_id}"}]]}
        try:
            r = requests.post(url, json=payload, timeout=30)
            try:
                data = r.json()
            except ValueError:
                data = {}
            if r.status_code != 200 or not data.get("ok"):
                desc = data.get("description") or r.text[:200]
                prefix = "" if i == 0 else tr({'ar': f"(أُرسل {i} من {len(chunks)} جزء فقط) ", 'en': f"(only {i} of {len(chunks)} parts were sent) "})
                return False, redact(f"{prefix}Telegram error {r.status_code}: {desc}", token)
        except requests.exceptions.RequestException as e:
            return False, redact(f"Telegram connection error: {e}", token)
    return True, None


# ---- Decisions log ------------------------------------------------------------------------------
LOG_COLS = ['ID', 'Date', 'Topic', 'Status']


class DecisionLogError(Exception):
    pass


def read_decisions(path):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return pd.DataFrame(columns=LOG_COLS)
    try:
        df = pd.read_csv(path, dtype=str, encoding='utf-8-sig').fillna('')
    except Exception as e:  # noqa: BLE001
        raise DecisionLogError(tr({
            'ar': f"تعذر قراءة سجل الأوامر ({path}). لم يتم تعديل الملف. السبب: {type(e).__name__}: {e}",
            'en': f"Could not read the directives log ({path}). The file was NOT modified. Reason: {type(e).__name__}: {e}",
        })) from e
    for col in LOG_COLS:
        if col not in df.columns:
            df[col] = ''
    return df


def write_decisions(df, path):
    """Atomic write: a crash in the middle can never leave a half-written log."""
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
    os.close(fd)
    try:
        df.to_csv(tmp, index=False, encoding='utf-8-sig')
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def append_decision(path, row):
    existing = read_decisions(path)
    new_row = pd.DataFrame([row], columns=LOG_COLS)
    write_decisions(pd.concat([new_row, existing], ignore_index=True), path)


def sync_telegram_statuses(token, path):
    """Reads callback clicks and updates ONLY this page's decisions (IDs starting with DIST_).
    Returns (updated_rows, error). Updates are deliberately NOT acknowledged to Telegram: other pages that
    share the same bot would otherwise lose their approvals. Re-processing is harmless (idempotent)."""
    try:
        df = read_decisions(path)
    except DecisionLogError as e:
        return 0, str(e)
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=30)
        res = r.json()
    except requests.exceptions.RequestException as e:
        return 0, redact(f"Telegram connection error: {e}", token)
    except ValueError:
        return 0, tr({'ar': "استجابة غير مفهومة من تليجرام.", 'en': "Unreadable response from Telegram."})
    if not res.get("ok"):
        return 0, redact(f"Telegram error: {res.get('description', r.status_code)}", token)

    updated = 0
    for update in res.get("result", []):
        data = (update.get("callback_query") or {}).get("data") or ""
        if "_" not in data:
            continue
        action, dec_id = data.split("_", 1)
        if not dec_id.startswith("DIST_"):
            continue                         # belongs to another page's log
        new_status = {'Approve': 'Executed', 'Reject': 'Rejected'}.get(action)
        mask = df['ID'].astype(str) == dec_id
        if new_status and mask.any() and (df.loc[mask, 'Status'] != new_status).any():
            df.loc[mask, 'Status'] = new_status
            updated += 1
    if updated:
        try:
            write_decisions(df, path)
        except OSError as e:
            return 0, f"{type(e).__name__}: {e}"
    return updated, None


# ---- PDF ----------------------------------------------------------------------------------------
def generate_arabic_pdf(text_content, lang=None):
    """Kept under its original name. Returns (pdf_bytes, None) or (None, readable_error).
    The real work (fonts, RTL, layout) lives in directive_pdf.py."""
    lang = lang or st.session_state.get('lang', 'ar')
    if directive_pdf is None:
        return None, tr({
            'ar': f"ملف directive_pdf.py غير موجود بجانب التطبيق أو به خطأ: {PDF_IMPORT_ERROR}",
            'en': f"directive_pdf.py is missing next to the app or failed to import: {PDF_IMPORT_ERROR}",
        })
    return directive_pdf.generate_directive_pdf(text_content, lang=lang)


def status_style(val):
    color = '#f59e0b' if val == 'Pending' else '#10b981' if val == 'Executed' else '#ef4444'
    return f'color: {color}; font-weight: bold'


# ----------------------------------------------------------------------------------------------
# AI Tab (PDF Generation & Strict Directives)
# ----------------------------------------------------------------------------------------------
with tab_ai:
    dec_file = os.path.join(resolve_data_dir(), 'distribution_decisions_log.csv')

    groq_key = get_secret("GROQ_API_KEY")
    telegram_token = get_secret("TELEGRAM_TOKEN")
    telegram_chat_id = get_secret("TELEGRAM_CHAT_ID")
    api_key_configured = bool(groq_key)
    telegram_configured = bool(telegram_token and telegram_chat_id)

    flash = st.session_state.pop('dist_flash', None)
    if flash:
        getattr(st, flash[0])(flash[1])

    st.markdown(f"<h4 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'توليد خطة التوزيع المثلى (أوامر الشحن)', 'en': 'Generate Optimal Distribution Plan'})}</h4>", unsafe_allow_html=True)
    
    if st.button(tr({'ar': "توليد أمر التكليف الآن", 'en': "Generate Directive Now"}), type="primary", use_container_width=True):
        facts_text = build_distribution_facts(metrics, st.session_state.lang)
        if not api_key_configured:
            st.warning(tr({'ar': "الرجاء إعداد GROQ_API_KEY", 'en': "Please configure GROQ_API_KEY"}))
        elif facts_text is None:
            st.warning(tr({'ar': "لا توجد بيانات توزيع كافية للفترة أو المنتجات المحددة، غيّر الفلاتر ثم أعد المحاولة.", 'en': "Not enough distribution data for the selected period or products. Adjust the filters and retry."}))
        else:
            with st.spinner(tr({'ar': "يتم صياغة المذكرة الإدارية وأوامر الشحن...", 'en': "Drafting directive..."})):
                ai_res, ai_err = call_groq(groq_key, build_prompt(facts_text, st.session_state.lang))
            if ai_res:
                st.session_state['dist_ai_response'] = ai_res
                st.session_state['dist_ai_lang'] = st.session_state.lang
            else:
                st.error(ai_err)

    if 'dist_ai_response' in st.session_state:
        memo_text = st.session_state['dist_ai_response']
        memo_lang = st.session_state.get('dist_ai_lang', st.session_state.lang)

        st.markdown("<br>", unsafe_allow_html=True)
        render_memo_box(memo_text)
        st.markdown("<br>", unsafe_allow_html=True)
        
        c_btn1, c_btn2 = st.columns(2)
        with c_btn1:
            if st.button(tr({'ar': "إرسال أمر التكليف لاعتماده (تليجرام)", 'en': "Send Directive via Telegram"}), use_container_width=True):
                if not telegram_configured:
                    st.warning(tr({'ar': "تليجرام غير مفعل في secrets", 'en': "Telegram not configured"}))
                else:
                    decision_id = "DIST_" + str(int(time.time()))
                    ok, err = send_telegram_directive(telegram_token, telegram_chat_id, memo_text, decision_id, memo_lang)
                    if not ok:
                        st.error(err)    # nothing is logged when Telegram did not confirm the message
                    else:
                        topic = "أمر توزيع مقاسات وتخفيض شحن" if memo_lang == 'ar' else "Size allocation & shipping cost reduction directive"
                        try:
                            append_decision(dec_file, {'ID': decision_id, 'Date': pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"), 'Topic': topic, 'Status': "Pending"})
                            st.session_state['dist_flash'] = ('success', tr({'ar': "تم إرسال أمر التكليف بنجاح", 'en': "Sent successfully"}))
                        except Exception as e:  # noqa: BLE001
                            st.session_state['dist_flash'] = ('warning', tr({
                                'ar': f"تم الإرسال إلى تليجرام لكن تعذر تسجيله في السجل: {e}",
                                'en': f"Sent to Telegram but could not be written to the log: {e}"}))
                        st.rerun()
                     
        with c_btn2:
            pdf_key = (memo_lang, hashlib.md5(memo_text.encode('utf-8')).hexdigest())
            if st.session_state.get('dist_pdf_key') != pdf_key:      # build once, not on every rerun
                pdf_bytes, pdf_error = generate_arabic_pdf(memo_text, memo_lang)
                st.session_state['dist_pdf_key'] = pdf_key if pdf_bytes else None
                st.session_state['dist_pdf_bytes'] = pdf_bytes
                st.session_state['dist_pdf_error'] = pdf_error
            pdf_bytes = st.session_state.get('dist_pdf_bytes')
            if pdf_bytes:
                st.download_button(
                    label=tr({'ar': "📄 تحميل أمر التكليف (PDF)", 'en': "📄 Download Directive (PDF)"}),
                    data=pdf_bytes,
                    file_name=f"Logistics_Directive_{memo_lang.upper()}_{datetime.date.today()}.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
            else:
                st.error(tr({'ar': "تعذر إنشاء ملف PDF:", 'en': "Could not build the PDF:"}) + f"\n\n{st.session_state.get('dist_pdf_error')}")
                if directive_pdf is not None:
                    with st.expander(tr({'ar': "تشخيص PDF", 'en': "PDF diagnostics"})):
                        st.code(directive_pdf.diagnose(memo_lang))

    # --- Decisions Log Section (always visible, not only after generating a memo) ---
    st.markdown("<br><hr>", unsafe_allow_html=True)
    c_ai1, c_ai2 = st.columns([2, 1])
    with c_ai1:
        st.markdown(f"#### {tr({'ar': 'سجل أوامر التكليف', 'en': 'Directives Log'})}")
    with c_ai2:
        if telegram_configured:
            if st.button(tr({'ar': "تحديث حالات التنفيذ", 'en': "Sync Executions"})):
                n_updated, sync_err = sync_telegram_statuses(telegram_token, dec_file)
                if sync_err:
                    st.error(f"Sync error: {sync_err}")
                elif n_updated:
                    st.session_state['dist_flash'] = ('success', tr({'ar': "تمت مزامنة التنفيذ بنجاح", 'en': "Synced successfully"}))
                    st.rerun()
                else:
                    st.info(tr({'ar': "لا توجد تحديثات جديدة.", 'en': "No new updates."}))

    try:
        dec_df = read_decisions(dec_file)
    except DecisionLogError as e:
        dec_df = None
        st.error(str(e))
    if dec_df is not None and not dec_df.empty:
        display_cols = {
            'ID': 'ID', 
            'Date': tr({'ar': 'التاريخ', 'en': 'Date'}), 
            'Topic': tr({'ar': 'أمر التكليف', 'en': 'Topic'}), 
            'Status': tr({'ar': 'حالة التنفيذ', 'en': 'Status'})
        }
        dec_df = dec_df.rename(columns=display_cols)
        styler = dec_df.style
        styler = (styler.map if hasattr(styler, 'map') else styler.applymap)(status_style, subset=[display_cols['Status']])
        st.dataframe(styler, hide_index=True, use_container_width=True)