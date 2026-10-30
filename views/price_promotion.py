import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os
import requests
import html
import re
import time
import datetime
import tempfile
import sys
import traceback

st.set_page_config(layout="wide", page_title="Price Optimization & Promotion Intelligence")

# ---- Business-rule knobs (tune here, no need to touch the prompt) ----
MIN_PROMO_DEPTH = 5.0        # a day counts as a "promo day" if its discount depth >= this %
MIN_DAYS_FOR_UPLIFT = 3      # minimum promo days and normal days needed to estimate uplift
FAST_CUT_FACTOR = 0.5        # fast sellers: new discount = current * this factor
FAST_STOP_BELOW = 5.0        # fast sellers: stop discount entirely if current depth <= this %
SLOW_STEP_UP = 5.0           # slow sellers: raise discount by this many points
SLOW_MIN_DISCOUNT = 10.0     # slow sellers with no discount start here
MAX_DISCOUNT = 40.0          # never recommend a discount deeper than this %
LEAK_CUT_POINTS = 3.0        # medium sellers leaking margin: cut discount by this many points
GROQ_MAX_TOKENS = 2000       # gpt-oss is a reasoning model; reasoning tokens count toward this limit

def resolve_data_dir():
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    local = os.path.join(APP_DIR, 'data')
    return local if os.path.exists(local) else os.path.join(os.path.dirname(APP_DIR), 'data')

if 'lang' not in st.session_state:
    st.session_state.lang = 'ar'

def tr(text_dict):
    return text_dict.get(st.session_state.lang, text_dict.get('en', ''))

def get_secret(name, default=""):
    value = None
    try:
        value = st.secrets.get(name, None)
    except Exception:
        value = None
    if not value:
        value = os.environ.get(name, default)
    return str(value).strip() if value else default

def redact(message, *secrets):
    msg = str(message)
    for s in secrets:
        if s:
            msg = msg.replace(s, "***")
    return re.sub(r"bot\d+:[A-Za-z0-9_-]+", "bot***", msg)

cat_translation = {
    "Men's Basics": "رجالي أساسي", "Women's Basics": "حريمي أساسي", "Kids & Junior": "أطفال",
    "Underwear": "ملابس داخلية", "Activewear": "ملابس رياضية", "Home Textiles": "مفروشات",
    "Accessories": "إكسسوارات", "Boys pajamas": "بيجامات أولاد", "Girls pajamas": "بيجامات بنات",
    "Girls underwear": "ملابس داخلية بنات", "Kids underwear": "ملابس داخلية أطفال", "Men bottoms": "بناطيل رجالي",
    "Men boxers": "بوكسرات رجالي", "Men tops": "توب رجالي", "Men underwear": "ملابس داخلية رجالي",
    "Socks": "جوارب", "Women bottoms": "بناطيل حريمي", "Women bras": "حمالات صدر",
    "Women pajamas": "بيجامات حريمي", "Women tops": "توب حريمي", "Women underwear": "ملابس داخلية حريمي"
}

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
    
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 12px; border: 2px solid #94a3b8 !important; 
        background-color: #ffffff; padding: 15px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    }
    .ai-response-box {
        padding: 40px; background-color: #ffffff; border: 1px solid #cbd5e1;
        border-radius: 8px; font-size: 17px; line-height: 2.2; color: #0f172a;
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1); font-family: 'Arial', sans-serif;
    }
    .chart-subtitle {
        font-size: 12px; color: #64748b; text-align: center; 
        margin-top: -10px; margin-bottom: 15px;
    }
    .kanban-card {
        background-color: #ffffff; padding: 15px; border-radius: 8px; margin-bottom: 15px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); border-right: 5px solid #cbd5e1;
        transition: transform 0.2s ease;
    }
    .k-pending { border-right-color: #f59e0b; }
    .k-executed { border-right-color: #10b981; }
    .k-rejected { border-right-color: #ef4444; }
    .k-title { font-weight: bold; color: #0f172a; font-size: 15px; margin-bottom: 8px; }
    .k-date { font-size: 12px; color: #64748b; }
    </style>
""", unsafe_allow_html=True)

@st.cache_data(show_spinner=False)
def load_pricing_data():
    try:
        data_dir = resolve_data_dir()
        df_items = pd.read_parquet(os.path.join(data_dir, 'sales_order_items.parquet'), 
                                   columns=['order_date', 'product_id', 'quantity', 'gross_line_EGP', 'discount_line_EGP', 'net_line_EGP', 'margin_EGP'])
        df_products = pd.read_parquet(os.path.join(data_dir, 'products_catalog.parquet'), 
                                      columns=['product_id', 'product_name_ar', 'category_en'])
        df_stock = pd.read_parquet(os.path.join(data_dir, 'monthly_stock.parquet'), 
                                   columns=['year_month', 'product_category', 'closing_units'])
        
        df_items['order_date'] = pd.to_datetime(df_items['order_date'], errors='coerce')
        df_items.dropna(subset=['order_date'], inplace=True)
        
        df_merged = df_items.merge(df_products, on='product_id', how='left')
        df_merged['category_ar'] = df_merged['category_en'].map(lambda x: cat_translation.get(x, x))
        
        df_merged['is_promo'] = df_merged['discount_line_EGP'] > 0
        df_merged['year_month'] = df_merged['order_date'].dt.strftime('%Y-%m')
        
        df_stock_agg = df_stock.groupby(['year_month', 'product_category'])['closing_units'].sum().reset_index()
        
        return df_merged, df_stock_agg
    except Exception as e:
        return None, None

df_merged, df_stock = load_pricing_data()

if df_merged is None:
    st.error("Error loading data. Make sure parquet files exist in the data folder.")
    st.stop()

st.sidebar.markdown(f"<h3>{tr({'ar': 'إعدادات النظام', 'en': 'System Settings'})}</h3>", unsafe_allow_html=True)
selected_lang = st.sidebar.radio(tr({'ar': "اللغة", 'en': "Language"}), ['ar', 'en'], index=0 if st.session_state.lang == 'ar' else 1)
if selected_lang != st.session_state.lang:
    st.session_state.lang = selected_lang
    st.rerun()

st.markdown(f"<h2 style='color:#1e3a8a; margin-bottom: 20px;'>{tr({'ar': 'تحسين التسعير وذكاء العروض الترويجية', 'en': 'Price Optimization & Promotion Intelligence'})}</h2>", unsafe_allow_html=True)

min_date, max_date = df_merged['order_date'].min().date(), df_merged['order_date'].max().date()
available_categories = df_merged['category_ar'].dropna().unique().tolist()

with st.container(border=True):
    c1, c2, c3 = st.columns([1, 1, 2])
    start_date = c1.date_input(tr({'ar': "من تاريخ", 'en': "Start Date"}), min_date)
    end_date = c2.date_input(tr({'ar': "إلى تاريخ", 'en': "End Date"}), max_date)
    selected_cats = c3.multiselect(
        tr({'ar': "تحديد الفئات", 'en': "Select Categories"}), 
        available_categories, 
        default=available_categories
    )

mask = (df_merged['order_date'].dt.date >= start_date) & (df_merged['order_date'].dt.date <= end_date)
if selected_cats:
    mask = mask & df_merged['category_ar'].isin(selected_cats)
df_filtered = df_merged[mask].copy()

total_net = df_filtered['net_line_EGP'].sum()
total_gross = df_filtered['gross_line_EGP'].sum()
total_discount = df_filtered['discount_line_EGP'].sum()
total_margin = df_filtered['margin_EGP'].sum()
total_qty = df_filtered['quantity'].sum()

# Promo uplift = avg daily units on promo days vs avg daily units on normal days (volume, so price cuts don't hide the lift)
daily = df_filtered.groupby(df_filtered['order_date'].dt.date).agg(
    units=('quantity', 'sum'), gross=('gross_line_EGP', 'sum'), disc=('discount_line_EGP', 'sum'))
daily['depth'] = (daily['disc'] / daily['gross'] * 100).where(daily['gross'] > 0, 0)
promo_days = daily[daily['depth'] >= MIN_PROMO_DEPTH]
normal_days = daily[daily['depth'] < MIN_PROMO_DEPTH]
if len(promo_days) >= MIN_DAYS_FOR_UPLIFT and len(normal_days) >= MIN_DAYS_FOR_UPLIFT and normal_days['units'].mean() > 0:
    promo_uplift_pct = (promo_days['units'].mean() / normal_days['units'].mean() - 1) * 100
    uplift_txt = f"{abs(promo_uplift_pct):,.1f}%{'+' if promo_uplift_pct >= 0 else '-'}"
else:
    promo_uplift_pct = None
    uplift_txt = "N/A"

gross_margin_pct = (total_margin / total_net * 100) if total_net > 0 else 0
avg_discount_depth = (total_discount / total_gross * 100) if total_gross > 0 else 0

recent_month = df_filtered['year_month'].max() if not df_filtered.empty else None
stock_recent = df_stock[df_stock['year_month'] == recent_month]['closing_units'].sum() if recent_month else 0
sell_through_rate = (total_qty / (total_qty + stock_recent) * 100) if (total_qty + stock_recent) > 0 else 0

tab_dashboard, tab_ai = st.tabs([
    tr({'ar': "لوحة التسعير والعروض", 'en': "Pricing & Promo Dashboard"}),
    tr({'ar': "مستشار التسعير", 'en': "Strategic Pricing Consultant"})
])

with tab_dashboard:
    if df_filtered.empty:
        st.warning(tr({'ar': "لا توجد بيانات للفترة أو الفئات المحددة.", 'en': "No data available for the selected period or categories."}))
    else:
        k1, k2, k3, k4 = st.columns(4)
        k1.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"أثر العروض الترويجية (UPLIFT)", "en":"Promo Uplift"})}</div><div class="kpi-value">{uplift_txt}</div></div>', unsafe_allow_html=True)
        k2.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"إجمالي الهامش الربحي", "en":"Gross Margin"})}</div><div class="kpi-value">{gross_margin_pct:,.1f}%</div></div>', unsafe_allow_html=True)
        k3.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"معدل تصريف المخزون", "en":"Sell-Through Rate"})}</div><div class="kpi-value">{sell_through_rate:,.1f}%</div></div>', unsafe_allow_html=True)
        k4.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"متوسط عمق الخصم", "en":"Avg Discount Depth"})}</div><div class="kpi-value">{avg_discount_depth:,.1f}%</div></div>', unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        r1c1, r1c2 = st.columns(2)

        with r1c1:
            with st.container(border=True):
                st.markdown(f"<h5 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'تحليل مرونة السعر (الطلب مقابل الخصم)', 'en': 'Price Elasticity Analysis'})}</h5>", unsafe_allow_html=True)
                st.markdown(f"<p class='chart-subtitle'>{tr({'ar': 'يوضح حجم الطلب لكل فئة مع تدرج لوني يمثل متوسط نسبة الخصم المقدمة', 'en': 'Shows demand volume per category with a color gradient for discount %'})}</p>", unsafe_allow_html=True)
                
                df_filtered['discount_pct'] = (df_filtered['discount_line_EGP'] / df_filtered['gross_line_EGP'] * 100).fillna(0)
                elasticity_df = df_filtered.groupby('category_ar').agg({'discount_pct': 'mean', 'quantity': 'sum'}).reset_index().sort_values('quantity', ascending=False)
                
                if not elasticity_df.empty:
                    fig_bar1 = px.bar(elasticity_df, x='category_ar', y='quantity', color='discount_pct',
                                      color_continuous_scale='Blues',
                                      labels={'quantity': tr({'ar': 'حجم الطلب', 'en': 'Demand'}), 
                                              'discount_pct': tr({'ar': '% الخصم', 'en': 'Discount %'}), 
                                              'category_ar': tr({'ar': 'الفئة', 'en': 'Category'})})
                    fig_bar1.update_layout(xaxis_title="", yaxis_title=tr({'ar':"حجم الطلب", 'en':"Demand Volume"}), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
                    st.plotly_chart(fig_bar1, use_container_width=True)

        with r1c2:
            with st.container(border=True):
                st.markdown(f"<h5 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'اتجاه المبيعات وأثر الخصومات', 'en': 'Sales & Promo Uplift Trend'})}</h5>", unsafe_allow_html=True)
                st.markdown(f"<p class='chart-subtitle'>{tr({'ar': 'يفصل المبيعات الأساسية عن المبيعات الإضافية الناتجة عن الخصومات', 'en': 'Separates baseline sales from additional sales driven by discounts'})}</p>", unsafe_allow_html=True)
                
                trend_df = df_filtered.groupby([df_filtered['order_date'].dt.to_period('M'), 'is_promo'])['net_line_EGP'].sum().unstack(fill_value=0).reset_index()
                trend_df['order_date'] = trend_df['order_date'].dt.to_timestamp()
                trend_df.columns = ['Date', 'Baseline', 'Promo'] if len(trend_df.columns) == 3 else ['Date', 'Baseline']
                if 'Promo' not in trend_df.columns: trend_df['Promo'] = 0
                trend_df['Total'] = trend_df['Baseline'] + trend_df['Promo']
                
                if not trend_df.empty:
                    fig_trend = go.Figure()
                    fig_trend.add_trace(go.Bar(x=trend_df['Date'], y=trend_df['Baseline'], name=tr({'ar':'مبيعات أساسية','en':'Baseline Sales'}), marker_color='#93c5fd'))
                    fig_trend.add_trace(go.Bar(x=trend_df['Date'], y=trend_df['Promo'], name=tr({'ar':'مبيعات الخصم','en':'Promo Sales'}), marker_color='#3b82f6'))
                    fig_trend.add_trace(go.Scatter(x=trend_df['Date'], y=trend_df['Total'], name=tr({'ar':'الإجمالي','en':'Total Sales'}), mode='lines+markers', line=dict(color='#1e3a8a', width=3)))
                    fig_trend.update_layout(barmode='stack', xaxis_title="", yaxis_title=tr({'ar':"المبيعات (ج.م)", 'en':"Sales (EGP)"}), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5))
                    st.plotly_chart(fig_trend, use_container_width=True)

        st.markdown("<br>", unsafe_allow_html=True)
        r2c1, r2c2 = st.columns([1, 1])

        cat_perf = df_filtered.groupby(['category_en', 'category_ar']).agg({
            'net_line_EGP': 'sum',
            'gross_line_EGP': 'sum',
            'discount_line_EGP': 'sum',
            'quantity': 'sum',
            'margin_EGP': 'sum'
        }).reset_index()
        cat_perf['discount_depth'] = (cat_perf['discount_line_EGP'] / cat_perf['gross_line_EGP'] * 100).fillna(0)
        
        stock_current = df_stock[df_stock['year_month'] == recent_month].groupby('product_category')['closing_units'].sum().reset_index()
        cat_perf = cat_perf.merge(stock_current, left_on='category_en', right_on='product_category', how='left').fillna(0)
        cat_perf['sell_through'] = (cat_perf['quantity'] / (cat_perf['quantity'] + cat_perf['closing_units']) * 100).fillna(0)

        with r2c1:
            with st.container(border=True):
                st.markdown(f"<h5 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'مصفوفة عمق الخصم مقابل تصريف المخزون', 'en': 'Discount Depth vs. Sell-Through Matrix'})}</h5>", unsafe_allow_html=True)
                st.markdown(f"<p class='chart-subtitle'>{tr({'ar': 'يقارن بين نسبة الخصم المقدمة (عمود أزرق) وسرعة بيع المخزون (عمود أحمر) لكل فئة', 'en': 'Compares discount % (Blue) and sell-through % (Red) per category'})}</p>", unsafe_allow_html=True)
                
                top_perf = cat_perf.sort_values('net_line_EGP', ascending=False).head(10)
                
                if not top_perf.empty:
                    fig_bar2 = go.Figure()
                    fig_bar2.add_trace(go.Bar(x=top_perf['category_ar'], y=top_perf['discount_depth'], name=tr({'ar':'% عمق الخصم','en':'Discount %'}), marker_color='#93c5fd'))
                    fig_bar2.add_trace(go.Bar(x=top_perf['category_ar'], y=top_perf['sell_through'], name=tr({'ar':'% معدل التصريف','en':'Sell-Through %'}), marker_color='#ef4444'))
                    
                    fig_bar2.update_layout(
                        barmode='group',
                        yaxis=dict(title="%"),
                        legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5),
                        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
                    )
                    st.plotly_chart(fig_bar2, use_container_width=True)

        with r2c2:
            with st.container(border=True):
                st.markdown(f"<h5 style='color:#1e3a8a;'>{tr({'ar': 'أداء الفئات والهوامش الربحية', 'en': 'Category Performance & Margins'})}</h5>", unsafe_allow_html=True)
                st.markdown(f"<p class='chart-subtitle' style='text-align: right;'>{tr({'ar': 'يبرز كافة الفئات المحددة مع توضيح هامش الربح لتحديد فعالية التسعير', 'en': 'Highlights all selected categories and margins to gauge pricing effectiveness'})}</p>", unsafe_allow_html=True)
                
                if not cat_perf.empty:
                    table_df = cat_perf.copy()
                    table_df['Margin_Pct'] = (table_df['margin_EGP'] / table_df['net_line_EGP'] * 100).fillna(0)
                    
                    col_cat = tr({'ar': 'الفئة', 'en': 'Category'})
                    col_rev = tr({'ar': 'الإيرادات', 'en': 'Revenue'})
                    col_mar = tr({'ar': 'هامش الربح %', 'en': 'Margin %'})
                    col_str = tr({'ar': 'التصريف %', 'en': 'Sell-Through %'})
                    
                    table_df.rename(columns={'category_ar': col_cat, 'net_line_EGP': col_rev, 'Margin_Pct': col_mar, 'sell_through': col_str}, inplace=True)
                    table_df = table_df.sort_values(col_rev, ascending=False)[[col_cat, col_rev, col_mar, col_str]]
                    
                    st.dataframe(table_df.style.format({col_rev: '{:,.0f}', col_mar: '{:.1f}%', col_str: '{:.1f}%'}).map(lambda x: 'color: #10b981; font-weight: bold;', subset=[col_mar]), use_container_width=True, hide_index=True)


# ----------------------------------------------------------------------------------------------
# AI Tab helpers
# ----------------------------------------------------------------------------------------------
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-20b"

def call_groq(api_key, prompt, system_prompt=None):
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    messages = ([{"role": "system", "content": system_prompt}] if system_prompt else []) + [{"role": "user", "content": prompt}]
    payload = {"model": GROQ_MODEL, "messages": messages, "temperature": 0.1,
               "max_completion_tokens": GROQ_MAX_TOKENS, "reasoning_effort": "low"}
    try:
        r = requests.post(GROQ_URL, headers=headers, json=payload, timeout=90)
        if r.status_code == 400 and "reasoning_effort" in r.text:
            payload.pop("reasoning_effort")
            r = requests.post(GROQ_URL, headers=headers, json=payload, timeout=90)
    except requests.exceptions.RequestException as e:
        return None, redact(f"Groq connection error: {e}", api_key)
    if r.status_code != 200:
        return None, redact(f"Groq error {r.status_code}: {r.text[:200]}", api_key)
    try:
        choice = r.json()["choices"][0]
    except (ValueError, KeyError, IndexError):
        return None, "Groq returned an unexpected response."
    content = ((choice.get("message") or {}).get("content") or "").strip()
    if not content:
        return None, f"Groq returned an empty response (finish_reason={choice.get('finish_reason')}). Please try again."
    return content, None

ACTION_LABELS = {
    'REDUCE_OR_STOP_DISCOUNT':     {'ar': 'خفّض الخصم / أوقفه', 'en': 'Reduce / stop the discount'},
    'KEEP_NO_DISCOUNT':            {'ar': 'أبقِ السعر بدون خصم', 'en': 'Keep full price, no discount'},
    'INCREASE_DISCOUNT_CLEARANCE': {'ar': 'زوّد الخصم للتصفية', 'en': 'Increase the discount (clearance)'},
    'REDUCE_DISCOUNT_MARGIN_LEAK': {'ar': 'خفّض الخصم (تسرّب في الهامش)', 'en': 'Reduce the discount (margin leak)'},
    'MAINTAIN':                    {'ar': 'حافظ على الخصم الحالي', 'en': 'Hold the current discount'},
}
SPEED_LABELS = {
    'Fast':   {'ar': 'سريع التصريف', 'en': 'Fast'},
    'Medium': {'ar': 'متوسط', 'en': 'Medium'},
    'Slow':   {'ar': 'بطيء التصريف', 'en': 'Slow'},
}
CUT_ACTIONS = ('REDUCE_OR_STOP_DISCOUNT', 'REDUCE_DISCOUNT_MARGIN_LEAK')

def build_system_prompt(sys_lang):
    return (
        "You are a decisive pricing director at an apparel retailer. "
        f"Write the pricing decisions for sales managers in {sys_lang} ONLY.\n\n"
        "INPUT: a table where every row is ONE decision that was already chosen and calculated by the company's rules. "
        "Your only job is to word each row as a clear, direct decision. Never contradict or change a row.\n\n"
        "OUTPUT FORMAT:\n"
        "- Exactly one line per table row, in the same order, each starting with '- '.\n"
        "- Line pattern: <Category>: <Action> from <Discount_now_pct>% to <Discount_target_pct>%, "
        "because <sell-through> and <margin> (and the current discount if it matters).\n"
        "- If Action says to hold the discount, say the discount stays at its current value.\n"
        "- Write everything in the output language, including the action wording. Never print column names or codes.\n"
        "- No intro, no conclusion, no headings, no emojis, no sub-sections.\n\n"
        "STRICT RULES:\n"
        "- Use only numbers that appear in the table or context. Do not calculate new numbers.\n"
        "- Do not cite revenue as the reason; the reasons are sell-through, margin and discount depth.\n"
        "- Copy each Category name exactly as written in the table; do not rephrase, translate or pluralize it.\n"
        "- Do not add categories that are not in the table."
    )

def build_category_brief(cat_perf, lang, overall_margin, overall_depth, n_decisions=4):
    """Classifies every category, picks the n decisions in code (balanced between cutting and
    deepening discounts), and returns them as a small localized CSV for the LLM to word."""
    d = cat_perf.copy()
    if d.empty:
        return ""
    d['margin_pct'] = (d['margin_EGP'] / d['net_line_EGP'] * 100).where(d['net_line_EGP'] > 0, 0)
    hi, lo = d['sell_through'].quantile(0.67), d['sell_through'].quantile(0.33)

    def speed(v):
        if hi == lo:
            return 'Medium'
        return 'Fast' if v >= hi else 'Slow' if v <= lo else 'Medium'

    def action(r):
        if r['speed'] == 'Fast':
            return 'REDUCE_OR_STOP_DISCOUNT' if r['discount_depth'] > 0 else 'KEEP_NO_DISCOUNT'
        if r['speed'] == 'Slow':
            return 'INCREASE_DISCOUNT_CLEARANCE'
        if r['margin_pct'] < overall_margin and r['discount_depth'] > overall_depth:
            return 'REDUCE_DISCOUNT_MARGIN_LEAK'
        return 'MAINTAIN'

    def new_discount(r):
        depth = r['discount_depth']
        if r['action'] == 'REDUCE_OR_STOP_DISCOUNT':
            return 0.0 if depth <= FAST_STOP_BELOW else depth * FAST_CUT_FACTOR
        if r['action'] == 'INCREASE_DISCOUNT_CLEARANCE':
            return min(SLOW_MIN_DISCOUNT if depth <= 0 else depth + SLOW_STEP_UP, MAX_DISCOUNT)
        if r['action'] == 'REDUCE_DISCOUNT_MARGIN_LEAK':
            return max(depth - LEAK_CUT_POINTS, 0.0)
        return depth

    d['speed'] = d['sell_through'].apply(speed)
    d['action'] = d.apply(action, axis=1)
    d['new_discount'] = d.apply(new_discount, axis=1)
    d['Category'] = d['category_ar'] if lang == 'ar' else d['category_en']
    d = d.sort_values('net_line_EGP', ascending=False)

    # Pick decisions in code: up to half from "cut discount", up to half from "increase discount",
    # then fill with the remaining actionable rows, then with hold/keep rows (highest revenue first).
    half = max(n_decisions // 2, 1)
    cuts = d[d['action'].isin(CUT_ACTIONS)]
    incs = d[d['action'] == 'INCREASE_DISCOUNT_CLEARANCE']
    picked = pd.concat([cuts.head(half), incs.head(half)])
    rest_actionable = d[d['action'].isin(CUT_ACTIONS + ('INCREASE_DISCOUNT_CLEARANCE',)) & ~d.index.isin(picked.index)]
    picked = pd.concat([picked, rest_actionable.head(max(n_decisions - len(picked), 0))])
    holds = d[~d.index.isin(picked.index)]
    picked = pd.concat([picked, holds.head(max(n_decisions - len(picked), 0))])
    picked = picked.sort_values('net_line_EGP', ascending=False).head(n_decisions)

    out = pd.DataFrame({
        'Category': picked['Category'],
        'Action': picked['action'].map(lambda a: ACTION_LABELS[a][lang]),
        'Discount_now_pct': picked['discount_depth'].round(1),
        'Discount_target_pct': picked['new_discount'].round(1),
        'Sell_through_pct': picked['sell_through'].round(1),
        'Sell_through_level': picked['speed'].map(lambda v: SPEED_LABELS[v][lang]),
        'Margin_pct': picked['margin_pct'].round(1),
    })
    return out.to_csv(index=False)

def render_ai_box(text):
    lines = []
    for line in text.split("\n"):
        s = html.escape(line)
        s = re.sub(r"^\s*#{1,6}\s+(.*)$", r"<b>\1</b>", s)
        s = re.sub(r"^(\s*)[*+-]\s+", r"\1• ", s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        lines.append(s)
    safe_html = "<br>".join(lines)
    st.markdown(f"<div class='ai-response-box' dir='auto'>{safe_html}</div>", unsafe_allow_html=True)

TG_CHUNK = 3500
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
        while len(line) > limit:
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
    title = "قرارات تسعيرية استراتيجية (قطونيل)" if lang == 'ar' else "Pricing Decisions (Cotonil)"
    button = "تم الاستلام وجاري التنفيذ" if lang == 'ar' else "Received - in progress"
    chunks = split_for_telegram(telegram_html(memo_text))
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for i, chunk in enumerate(chunks):
        text = (f"<b>{html.escape(title)}</b>\n\n" if i == 0 else "") + chunk
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if i == len(chunks) - 1:
            payload["reply_markup"] = {"inline_keyboard": [[{"text": button, "callback_data": f"Approve_{decision_id}"}]]}
        try:
            r = requests.post(url, json=payload, timeout=30)
            data = r.json() if r.status_code == 200 else {}
            if r.status_code != 200 or not data.get("ok"):
                return False, redact(f"Telegram error {r.status_code}", token)
        except Exception as e:
            return False, redact(f"Telegram connection error: {e}", token)
    return True, None

LOG_COLS = ['ID', 'Date', 'Topic', 'Status']
class DecisionLogError(Exception): pass

def read_decisions(path):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return pd.DataFrame(columns=LOG_COLS)
    df = pd.read_csv(path, dtype=str, encoding='utf-8-sig').fillna('')
    for col in LOG_COLS:
        if col not in df.columns: df[col] = ''
    return df

def write_decisions(df, path):
    import tempfile
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
    os.close(fd)
    df.to_csv(tmp, index=False, encoding='utf-8-sig')
    os.replace(tmp, path)

def append_decision(path, row):
    existing = read_decisions(path)
    new_row = pd.DataFrame([row], columns=LOG_COLS)
    write_decisions(pd.concat([new_row, existing], ignore_index=True), path)

def sync_telegram_statuses(token, path):
    try: df = read_decisions(path)
    except: return 0, "Log read error"
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=30)
        res = r.json()
    except: return 0, "Telegram connection error"
    if not res.get("ok"): return 0, "Telegram API error"
    updated = 0
    for update in res.get("result", []):
        data = (update.get("callback_query") or {}).get("data") or ""
        if "_" not in data: continue
        action, dec_id = data.split("_", 1)
        if not dec_id.startswith("PRIC_"): continue
        new_status = {'Approve': 'Executed', 'Reject': 'Rejected'}.get(action)
        mask = df['ID'].astype(str) == dec_id
        if new_status and mask.any() and (df.loc[mask, 'Status'] != new_status).any():
            df.loc[mask, 'Status'] = new_status
            updated += 1
    if updated: write_decisions(df, path)
    return updated, None

def status_style(val):
    color = '#f59e0b' if val == 'Pending' else '#10b981' if val == 'Executed' else '#ef4444'
    return f'color: {color}; font-weight: bold'

with tab_ai:
    dec_file = os.path.join(resolve_data_dir(), 'pricing_decisions_log.csv')
    groq_key = get_secret("GROQ_API_KEY")
    telegram_token = get_secret("TELEGRAM_TOKEN")
    telegram_chat_id = get_secret("TELEGRAM_CHAT_ID")
    api_key_configured = bool(groq_key)
    telegram_configured = bool(telegram_token and telegram_chat_id)

    flash = st.session_state.pop('pric_flash', None)
    if flash:
        getattr(st, flash[0])(flash[1])

    st.markdown(f"<h4 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'إصدار القرارات التسعيرية', 'en': 'Generate Pricing Decisions'})}</h4>", unsafe_allow_html=True)
    
    if st.button(tr({'ar': "توليد القرارات الآن", 'en': "Generate Decisions Now"}), type="primary", use_container_width=True):
        if not api_key_configured:
            st.warning(tr({'ar': "الرجاء إعداد GROQ_API_KEY", 'en': "Please configure GROQ_API_KEY"}))
        elif df_filtered.empty:
            st.warning(tr({'ar': "لا توجد بيانات كافية.", 'en': "Not enough data."}))
        else:
            with st.spinner(tr({'ar': "يتم تحليل البيانات لاستخراج قرارات صارمة...", 'en': "Analyzing data for strict decisions..."})):
                sys_lang = "Arabic" if st.session_state.lang == 'ar' else "English"
                cat_summary = build_category_brief(cat_perf, st.session_state.lang, gross_margin_pct, avg_discount_depth)

                uplift_line = (f"{promo_uplift_pct:+.1f}% more units per day on promo days vs normal days"
                               if promo_uplift_pct is not None else "not enough promo/normal days to estimate")
                system_prompt = build_system_prompt(sys_lang)
                prompt = (
                    "OVERALL CONTEXT (selected period):\n"
                    f"- Average discount depth: {avg_discount_depth:.1f}%\n"
                    f"- Gross margin: {gross_margin_pct:.1f}%\n"
                    f"- Overall sell-through: {sell_through_rate:.1f}%\n"
                    f"- Promo uplift: {uplift_line}\n\n"
                    "DECISIONS TABLE (CSV) - one pre-decided decision per row, word each one:\n"
                    f"{cat_summary}\n"
                    f"Reply in {sys_lang} only."
                )

                ai_res, ai_err = call_groq(groq_key, prompt, system_prompt)
                if ai_res:
                    st.session_state['pric_ai_response'] = ai_res
                    st.session_state['pric_ai_lang'] = st.session_state.lang
                else:
                    st.error(ai_err)

    if 'pric_ai_response' in st.session_state:
        memo_text = st.session_state['pric_ai_response']
        memo_lang = st.session_state.get('pric_ai_lang', st.session_state.lang)

        st.markdown("<br>", unsafe_allow_html=True)
        render_ai_box(memo_text)
        st.markdown("<br>", unsafe_allow_html=True)
        
        c_btn1, c_btn2 = st.columns([1, 2])
        with c_btn1:
            if st.button(tr({'ar': "إرسال القرارات لاعتمادها (تليجرام)", 'en': "Send Decisions via Telegram"}), use_container_width=True):
                if not telegram_configured:
                    st.warning(tr({'ar': "تليجرام غير مفعل", 'en': "Telegram not configured"}))
                else:
                    decision_id = "PRIC_" + str(int(time.time()))
                    ok, err = send_telegram_directive(telegram_token, telegram_chat_id, memo_text, decision_id, memo_lang)
                    if not ok:
                        st.error(err)
                    else:
                        topic = "قرارات تسعيرية استراتيجية" if memo_lang == 'ar' else "Strategic Pricing Decisions"
                        try:
                            append_decision(dec_file, {'ID': decision_id, 'Date': pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"), 'Topic': topic, 'Status': "Pending"})
                            st.session_state['pric_flash'] = ('success', tr({'ar': "تم إرسال القرارات بنجاح", 'en': "Sent successfully"}))
                        except Exception as e:
                            st.session_state['pric_flash'] = ('warning', f"Sent to Telegram but log failed: {e}")
                        st.rerun()

    st.markdown("<br><hr>", unsafe_allow_html=True)
    c_ai1, c_ai2 = st.columns([2, 1])
    with c_ai1:
        st.markdown(f"#### {tr({'ar': 'سجل القرارات التسعيرية', 'en': 'Pricing Decisions Log'})}")
    with c_ai2:
        if telegram_configured:
            if st.button(tr({'ar': "تحديث حالات التنفيذ", 'en': "Sync Executions"})):
                n_updated, sync_err = sync_telegram_statuses(telegram_token, dec_file)
                if sync_err:
                    st.error(f"Sync error: {sync_err}")
                elif n_updated:
                    st.session_state['pric_flash'] = ('success', tr({'ar': "تمت المزامنة بنجاح", 'en': "Synced successfully"}))
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
            'Topic': tr({'ar': 'موضوع القرار', 'en': 'Topic'}), 
            'Status': tr({'ar': 'حالة التنفيذ', 'en': 'Status'})
        }
        dec_df = dec_df.rename(columns=display_cols)
        styler = dec_df.style
        styler = (styler.map if hasattr(styler, 'map') else styler.applymap)(status_style, subset=[display_cols['Status']])
        st.dataframe(styler, hide_index=True, use_container_width=True)