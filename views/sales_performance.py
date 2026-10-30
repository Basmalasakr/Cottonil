import streamlit as st
import pandas as pd
import plotly.express as px
import os
import re
import html
import requests
import joblib
import time

st.set_page_config(layout="wide", page_title="Sales Performance")

if 'lang' not in st.session_state:
    st.session_state.lang = 'ar'

def tr(text_dict):
    return text_dict.get(st.session_state.lang, text_dict.get('en', ''))

st.markdown("""
    <style>
    .stApp { background-color: #f8fafc; color: #0f172a; }
    .kpi-card {
        background-color: #ffffff; padding: 20px; border-radius: 12px;
        border: 2px solid #cbd5e1; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        text-align: center; margin-bottom: 15px;
    }
    .kpi-value { font-size: 24px; font-weight: bold; color: #1e3a8a; margin-bottom: 5px; }
    .kpi-label { font-size: 14px; color: #64748b; font-weight: 600; }
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 12px; border: 2px solid #94a3b8 !important; 
        background-color: #ffffff; padding: 15px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    }
    .ai-response-box {
        padding: 25px; background-color: #eef2ff; border: 2px solid #6366f1;
        border-radius: 12px; font-size: 16px; line-height: 1.8; color: #0f172a;
    }
    </style>
""", unsafe_allow_html=True)

# ----------------------------------------------------------------------------------------------
# AI helpers
# ----------------------------------------------------------------------------------------------
AR_MONTHS = {1: "يناير", 2: "فبراير", 3: "مارس", 4: "أبريل", 5: "مايو", 6: "يونيو",
             7: "يوليو", 8: "أغسطس", 9: "سبتمبر", 10: "أكتوبر", 11: "نوفمبر", 12: "ديسمبر"}

# Same seasonal guide that is written in the prompt; used here to detect conflicts with the data
GUIDE_SEASON = {3: "عيد الأم وعيد الفطر", 4: "عيد الأم وعيد الفطر", 5: "عيد الأم وعيد الفطر",
                6: "عيد الأضحى والمصايف", 7: "عيد الأضحى والمصايف", 8: "عيد الأضحى والمصايف",
                9: "العودة للمدارس", 10: "العودة للمدارس",
                11: "الجمعة البيضاء", 12: "الجمعة البيضاء ودخول الشتاء"}

def month_label(ts):
    return f"{AR_MONTHS[ts.month]} {ts.year}"

def recent_basket_text(f_orders):
    """Average basket of the last 12 months vs the 12 before. The all-period average (~1,558) is
    misleading because the basket grew ~7x over the years (436 in 2018 -> ~3,000 in 2026)."""
    if f_orders.empty:
        return ""
    last = f_orders['order_date'].max()
    cut1 = last - pd.Timedelta(days=365)
    cut2 = cut1 - pd.Timedelta(days=365)
    r1 = f_orders[f_orders['order_date'] > cut1]
    r2 = f_orders[(f_orders['order_date'] > cut2) & (f_orders['order_date'] <= cut1)]
    a1 = r1['net_before_tax_EGP'].sum() / max(r1['sales_order_id'].nunique(), 1)
    if (last - f_orders['order_date'].min()).days < 365 or r2.empty:
        return f"متوسط السلة في الفترة المختارة: {a1:,.0f} ج.م"
    a2 = r2['net_before_tax_EGP'].sum() / max(r2['sales_order_id'].nunique(), 1)
    return f"متوسط السلة آخر 12 شهرًا: {a1:,.0f} ج.م (مقابل {a2:,.0f} ج.م في الـ12 شهرًا السابقة)"

def build_sales_facts(ms, first_order_date, last_order_date):
    """Pre-compute trend / anomalies / seasonality with pandas.

    The model used to receive ~100 raw monthly rows and spent its whole token budget
    "thinking" through them (finish_reason=length, empty answer). Now it only receives a short
    list of facts and just has to explain them.
    Returns (facts_text, notes_list).
    """
    notes = []
    if ms is None or ms.empty or pd.isna(last_order_date):
        return "لا توجد بيانات كافية في الفترة المختارة.", notes

    s = ms.set_index('order_date')['net_before_tax_EGP'].astype(float).sort_index()

    # drop partial months at both ends (they look like fake spikes / drops)
    last_start = last_order_date.to_period('M').to_timestamp()
    month_end = (last_start + pd.offsets.MonthEnd(0)).normalize()
    if last_order_date.normalize() < month_end and last_start in s.index:
        s = s.drop(last_start)
        notes.append(f"تم استبعاد {month_label(last_start)} لأنه شهر غير مكتمل")
    first_start = first_order_date.to_period('M').to_timestamp()
    if first_order_date.day > 1 and first_start in s.index:
        s = s.drop(first_start)
        notes.append(f"تم استبعاد {month_label(first_start)} لأنه شهر غير مكتمل في بداية الفترة")

    if len(s) < 4:
        return "عدد الأشهر المكتملة في الفترة المختارة قليل جدًا للتحليل.", notes

    s = s.asfreq('MS')
    n = int(s.notna().sum())
    lines = [f"- الأشهر المكتملة المحللة: {n} شهرًا (من {month_label(s.index[0])} إلى {month_label(s.index[-1])})."]
    lines += [f"- ملاحظة: {x}." for x in notes]

    # 1) trend: last 12 complete months vs the previous 12
    if n >= 24:
        last12, prev12 = s.iloc[-12:].sum(), s.iloc[-24:-12].sum()
        if prev12 > 0:
            lines.append(f"- مبيعات آخر 12 شهرًا مكتملة: {last12 / 1e6:.1f} مليون ج.م مقابل {prev12 / 1e6:.1f} مليون "
                         f"للـ12 شهرًا السابقة ({(last12 / prev12 - 1) * 100:+.0f}%).")

    # 2) anomalies: compare each month with its own normal growth (removes trend and seasonality)
    if n >= 20:
        base = s / s.shift(12) - 1
        label = "مقارنة بنفس الشهر في العام السابق"
        normal = base.rolling(13, center=True, min_periods=5).median()
    else:
        base = s.pct_change()
        label = "مقارنة بالشهر السابق (فترة قصيرة، قد تكون بعض التغيرات موسمية)"
        normal = base.median()
    dev = (base - normal).dropna()
    if len(dev) >= 5:
        mad = max(float((dev - dev.median()).abs().median()) * 1.4826, 0.02)
        z = ((dev - dev.median()) / mad)
        spikes = z[z >= 2].sort_values(ascending=False).head(3)
        dips = z[z <= -2].sort_values().head(3)
        old_cut = s.index[-1] - pd.DateOffset(months=24)
        def fmt(idx):
            return "، ".join(
                f"{month_label(m)} ({s[m] / 1e6:.1f} مليون، {base[m] * 100:+.0f}%"
                f"{'، تاريخي: أقدم من سنتين' if m < old_cut else ''})" for m in idx.index)
        lines.append(f"- طفرات للأعلى ({label}): {fmt(spikes) if len(spikes) else 'لا توجد طفرات واضحة'}.")
        lines.append(f"- هبوطات غير معتادة ({label}): {fmt(dips) if len(dips) else 'لا توجد هبوطات واضحة'}.")

    # 3) seasonality: ratio to the centred 12-month moving average
    if n >= 24:
        ma = s.rolling(12).mean().rolling(2).mean().shift(-6)
        ratio = (s / ma).dropna()
        if len(ratio) >= 12:
            seas = ratio.groupby(ratio.index.month).mean()
            seas = seas / seas.mean()
            hi = seas.sort_values(ascending=False).head(3)
            lo = seas.sort_values().head(3)
            f2 = lambda ser: "، ".join(f"{AR_MONTHS[m]} ({(v - 1) * 100:+.0f}%)" for m, v in ser.items())
            lines.append(f"- أقوى الشهور موسميًا (مقارنة بالشهر المعتاد): {f2(hi)}.")
            lines.append(f"- أضعف الشهور موسميًا: {f2(lo)}.")
            agree = [m for m in hi.index if m in GUIDE_SEASON]
            clash = [m for m in lo.index if m in GUIDE_SEASON]
            if agree:
                lines.append("- يتفق مع دليل المواسم: " + "، ".join(
                    f"{AR_MONTHS[m]} (موسم {GUIDE_SEASON[m]}، أقوى الشهور)" for m in agree) + ".")
            if clash:
                lines.append("- تعارض مع دليل المواسم (يستحق التحقيق): " + "، ".join(
                    f"{AR_MONTHS[m]} (الدليل يعتبره موسم {GUIDE_SEASON[m]} لكنه من أضعف الشهور: {(seas[m] - 1) * 100:+.0f}%)"
                    for m in clash) + ".")

    return "\n".join(lines), notes

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-20b"

def call_groq(api_key, prompt):
    """Returns (text, error).

    openai/gpt-oss-20b is a reasoning model: its hidden thinking is counted inside the token limit.
    With max_tokens=2500 and a big prompt it used all 2500 tokens on thinking, so `content` came
    back empty with finish_reason="length". Fix: low reasoning effort + a generous limit, and a
    couple of fallbacks if the API rejects an option.
    """
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    attempts = [
        {"reasoning_effort": "low", "include_reasoning": False, "max_completion_tokens": 3000},
        {"reasoning_effort": "low", "max_completion_tokens": 8000},
        {"max_completion_tokens": 8000},
    ]
    last_err = None
    for extra in attempts:
        payload = {"model": GROQ_MODEL, "messages": [{"role": "user", "content": prompt}],
                   "temperature": 0.2, **extra}
        try:
            r = requests.post(GROQ_URL, headers=headers, json=payload, timeout=90)
        except requests.RequestException as e:
            last_err = str(e)
            continue
        if r.status_code != 200:
            last_err = f"HTTP {r.status_code}: {r.text[:300]}"
            continue
        choice = r.json()["choices"][0]
        text = (choice["message"].get("content") or "").strip()
        if text:
            return text, None
        last_err = f"empty answer (finish_reason={choice.get('finish_reason')})"
    return None, last_err

def render_ai_box(text):
    """Escape the model output, then turn **bold** and new lines into HTML (markdown does not
    render inside a raw <div>). dir='auto' lets Arabic text align right."""
    safe = html.escape(text)
    safe = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", safe)
    safe = safe.replace("\n", "<br>")
    st.markdown(f"<div class='ai-response-box' dir='auto'>{safe}</div>", unsafe_allow_html=True)

# ----------------------------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------------------------
@st.cache_data
def load_sales_data():
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(current_dir, 'data') if os.path.exists(os.path.join(current_dir, 'data')) else os.path.join(os.path.dirname(current_dir), 'data')
        
        orders_cols = ['sales_order_id', 'order_date', 'branch_id', 'sales_channel', 'gross_EGP', 'discount_EGP', 'net_before_tax_EGP']
        orders = pd.read_parquet(os.path.join(data_dir, 'sales_orders.parquet'), columns=orders_cols)
        orders['order_date'] = pd.to_datetime(orders['order_date'])
        for col in ['gross_EGP', 'discount_EGP', 'net_before_tax_EGP']:
            orders[col] = pd.to_numeric(orders[col], errors='coerce').astype('float32')

        items_cols = ['sales_order_id', 'product_id', 'quantity']
        items_path_pq = os.path.join(data_dir, 'sales_order_items.parquet')
        items_path_csv = os.path.join(data_dir, 'sales_order_items.csv')
        if os.path.exists(items_path_pq):
            items = pd.read_parquet(items_path_pq, columns=items_cols)
        else:
            items = pd.read_csv(items_path_csv, usecols=items_cols)
        items['quantity'] = pd.to_numeric(items['quantity'], errors='coerce').astype('float32')

        products = pd.read_parquet(os.path.join(data_dir, 'products_catalog.parquet'), columns=['product_id', 'product_name_ar'])
        branches = pd.read_parquet(os.path.join(data_dir, 'branches.parquet'), columns=['branch_id', 'branch_name_ar'])

        return orders, items, products, branches
    except Exception as e:
        return None, None, None, str(e)

orders_df, items_df, products_df, branches_df = load_sales_data()

if orders_df is None:
    st.error(tr({'ar': "تعذر تحميل البيانات", 'en': "Failed to load data"}))
    st.stop()

st.sidebar.markdown(f"<h3>{tr({'ar': 'إعدادات النظام', 'en': 'System Settings'})}</h3>", unsafe_allow_html=True)
selected_lang = st.sidebar.radio(
    tr({'ar': "اختر اللغة", 'en': "Select Language"}),
    options=['ar', 'en'],
    index=0 if st.session_state.lang == 'ar' else 1
)
if selected_lang != st.session_state.lang:
    st.session_state.lang = selected_lang
    st.rerun()

st.markdown(f"<h2 style='color:#1e3a8a; margin-bottom: 20px;'>{tr({'ar': 'أداء المبيعات', 'en': 'Sales Performance'})}</h2>", unsafe_allow_html=True)

min_date = orders_df['order_date'].min().date()
max_date = orders_df['order_date'].max().date()

with st.container(border=True):
    f1, f2, f3 = st.columns([1, 1, 2])
    with f1: start_date = st.date_input(tr({'ar': "من تاريخ", 'en': "Start Date"}), min_date)
    with f2: end_date = st.date_input(tr({'ar': "إلى تاريخ", 'en': "End Date"}), max_date)
    with f3:
        channels = orders_df['sales_channel'].dropna().unique().tolist()
        selected_channels = st.multiselect(tr({'ar': "قنوات البيع", 'en': "Sales Channels"}), channels, default=channels)

mask = (orders_df['order_date'].dt.date >= start_date) & (orders_df['order_date'].dt.date <= end_date) & (orders_df['sales_channel'].isin(selected_channels))
f_orders = orders_df[mask]
f_items = items_df[items_df['sales_order_id'].isin(f_orders['sales_order_id'])]

gross_sales = f_orders['gross_EGP'].sum()
total_discounts = f_orders['discount_EGP'].sum()
net_sales = f_orders['net_before_tax_EGP'].sum()
total_items = f_items['quantity'].sum()
total_orders_count = f_orders['sales_order_id'].nunique()
aov = (net_sales / total_orders_count) if total_orders_count > 0 else 0

tab_dashboard, tab_ai = st.tabs([
    tr({'ar': "لوحة أداء المبيعات", 'en': "Sales Dashboard"}),
    tr({'ar': "محلل المبيعات الاستراتيجي", 'en': "Strategic Sales Analyst"})
])

with tab_dashboard:
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"إجمالي المبيعات", "en":"Gross Sales"})}</div><div class="kpi-value">{gross_sales / 1e6:.2f}M EGP</div></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"إجمالي الخصومات", "en":"Total Discounts"})}</div><div class="kpi-value">{total_discounts / 1e6:.2f}M EGP</div></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"صافي المبيعات", "en":"Net Sales"})}</div><div class="kpi-value">{net_sales / 1e6:.2f}M EGP</div></div>', unsafe_allow_html=True)
    c4.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"القطع المباعة", "en":"Items Sold"})}</div><div class="kpi-value">{total_items / 1e6:.2f}M</div></div>', unsafe_allow_html=True)
    c5.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"متوسط السلة", "en":"Average Basket"})}</div><div class="kpi-value">EGP {aov:.0f}</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    
    r1c1, r1c2 = st.columns(2)
    with r1c1:
        with st.container(border=True):
            st.markdown(f"<h4 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'الاتجاه الشهري للمبيعات', 'en': 'Monthly Sales Trend'})}</h4>", unsafe_allow_html=True)
            monthly_sales = f_orders.groupby(f_orders['order_date'].dt.to_period('M'))['net_before_tax_EGP'].sum().reset_index()
            monthly_sales['order_date'] = monthly_sales['order_date'].dt.to_timestamp()
            fig_trend = px.line(monthly_sales, x='order_date', y='net_before_tax_EGP', markers=True, color_discrete_sequence=['#3b82f6'])
            fig_trend.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', xaxis_title="", yaxis_title="")
            st.plotly_chart(fig_trend, use_container_width=True)

    with r1c2:
        with st.container(border=True):
            st.markdown(f"<h4 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'المبيعات حسب القناة', 'en': 'Sales by Channel'})}</h4>", unsafe_allow_html=True)
            channel_sales = f_orders.groupby('sales_channel')['net_before_tax_EGP'].sum().reset_index()
            fig_channel = px.pie(channel_sales, values='net_before_tax_EGP', names='sales_channel', hole=0.5, color_discrete_sequence=px.colors.qualitative.Pastel)
            fig_channel.update_layout(paper_bgcolor='rgba(0,0,0,0)', margin=dict(t=10, b=10))
            st.plotly_chart(fig_channel, use_container_width=True)

    r2c1, r2c2 = st.columns(2)
    with r2c1:
        with st.container(border=True):
            st.markdown(f"<h4 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'أفضل 5 منتجات مبيعاً', 'en': 'Top 5 Products'})}</h4>", unsafe_allow_html=True)
            top_items = f_items.groupby('product_id')['quantity'].sum().nlargest(5).reset_index()
            top_items = top_items.merge(products_df, on='product_id', how='left').fillna(tr({'ar': 'غير معروف', 'en': 'Unknown'}))
            fig_prod = px.bar(top_items, x='quantity', y='product_name_ar', orientation='h', text_auto='.2s', color_discrete_sequence=['#10b981'])
            fig_prod.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', yaxis={'categoryorder':'total ascending'}, xaxis_title="", yaxis_title="")
            st.plotly_chart(fig_prod, use_container_width=True)

    with r2c2:
        with st.container(border=True):
            st.markdown(f"<h4 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'أفضل 5 فروع تحقيقاً للمبيعات', 'en': 'Top 5 Branches'})}</h4>", unsafe_allow_html=True)
            top_branches = f_orders.groupby('branch_id')['net_before_tax_EGP'].sum().nlargest(5).reset_index()
            top_branches = top_branches.merge(branches_df, on='branch_id', how='left').fillna(tr({'ar': 'غير معروف', 'en': 'Unknown'}))
            fig_branch = px.bar(top_branches, x='net_before_tax_EGP', y='branch_name_ar', orientation='h', text_auto='.2s', color_discrete_sequence=['#f59e0b'])
            fig_branch.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', yaxis={'categoryorder':'total ascending'}, xaxis_title="", yaxis_title="")
            st.plotly_chart(fig_branch, use_container_width=True)

with tab_ai:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(current_dir, 'data') if os.path.exists(os.path.join(current_dir, 'data')) else os.path.join(os.path.dirname(current_dir), 'data')
    dec_file = os.path.join(data_dir, 'decisions_log.csv')
    
    api_key_configured = False
    telegram_configured = False
    
    try:
        api_key = st.secrets["GROQ_API_KEY"]
        if api_key: api_key_configured = True
        telegram_token = st.secrets["TELEGRAM_TOKEN"]
        telegram_chat_id = st.secrets["TELEGRAM_CHAT_ID"]
        telegram_configured = True
    except:
        pass

    ml_context = ""
    try:
        forecast_model = joblib.load(os.path.join(data_dir, 'forecast_model.pkl'))
        ml_context += "Forecasting Model is active."
    except:
        pass

    user_query = st.text_input(tr({'ar': "سؤالك للمحلل (أو اتركه فارغاً للتحليل التلقائي الشامل):", 'en': "Your question (or leave blank for automated analysis):"}))
    auto_send_urgent = st.checkbox(tr({'ar': "إرسال تلقائي للإدارة عبر تليجرام في حال وجود تنبيهات هامة أو شذوذ", 'en': "Auto-send to management on important alerts or anomalies"}))
    
    if st.button(tr({'ar': "تحليل وإصدار التقرير", 'en': "Analyze & Generate Report"}), use_container_width=True, type="primary", key="run_sales_ai"):
        if not api_key_configured:
            st.warning(tr({'ar': "الرجاء إعداد GROQ_API_KEY", 'en': "Please configure GROQ_API_KEY"}))
        elif f_orders.empty or monthly_sales.empty:
            st.warning(tr({'ar': "لا توجد مبيعات في الفترة المختارة.", 'en': "No sales in the selected period."}))
        else:
            with st.spinner(tr({'ar': "يجري التحليل...", 'en': "Analyzing..."})):
                
                query_text = user_query if user_query else "قم بتقديم تحليل شامل عن الشذوذ في المبيعات وتوقعات الموسمية واقترح خطة عمل."
                facts_text, _notes = build_sales_facts(monthly_sales, f_orders['order_date'].min(), f_orders['order_date'].max())
                ml_line = (f"سياق التوقعات: {ml_context} (لم تُمرَّر مخرجات رقمية من الموديل لهذا التقرير، فلا تذكر أي أرقام توقعات)\n"
                           if ml_context else "")
                
                prompt = (
                    "أنت مستشار مبيعات تنفيذي لشركة تجزئة كبرى (قطنيات وملابس) تعمل في السوق المصري.\n"
                    f"الفترة: من {start_date} إلى {end_date}\n"
                    f"صافي المبيعات: {net_sales / 1e6:.1f} مليون ج.م | الخصومات: {total_discounts / 1e6:.1f} مليون ج.م\n"
                    f"{recent_basket_text(f_orders)}\n\n"
                    "الحقائق التالية تم حسابها مسبقاً من البيانات (لا تعد حسابها ولا تخترع أرقاماً جديدة، فقط فسّرها):\n"
                    f"{facts_text}\n"
                    f"{ml_line}\n"
                    f"الطلب: {query_text}\n\n"
                    "قواعد صارمة جداً للتقرير:\n"
                    "1. الأشهر غير المكتملة تم استبعادها من الأرقام أعلاه، لا تذكرها كشذوذ أو هبوط.\n"
                    "2. استخدم الأرقام الموجودة أعلاه فقط ولا تضع أهدافاً رقمية من عندك. إذا لم تتوفر معلومة قل ذلك صراحة.\n"
                    "3. دليل المواسم في السوق المصري (استخدمه كتفسير محتمل فقط، وبشرط أن يتسق مع الأرقام أعلاه).\n"
                    "   إذا تعارض الدليل مع الأرقام (شهر موسمه قوي عادةً لكن مبيعاته ضعيفة) فاذكر التعارض صراحة كنقطة تستحق التحقيق ولا تبرّره:\n"
                    "   - نوفمبر وديسمبر: عروض الجمعة البيضاء (Black Friday) ودخول موسم الشتاء.\n"
                    "   - سبتمبر وأكتوبر: موسم العودة للمدارس.\n"
                    "   - مارس، أبريل، مايو: عيد الأم، دخول الصيف، وعيد الفطر.\n"
                    "   - يونيو ويوليو وأغسطس: عيد الأضحى وموسم المصايف والإجازات.\n"
                    "4. اكتب التقرير باللغة العربية بأسلوب تنفيذي (أقل من 150 كلمة) وبدون أي مصطلحات رياضية.\n"
                    "   إذا وُجد سطر 'تعارض مع دليل المواسم' فاذكر كل الشهور الواردة فيه. الطفرات المكتوب بجانبها (تاريخي) للعلم فقط ولا تبنِ عليها أي إجراء.\n"
                    "5. استخدم 3 عناوين رئيسية فقط كالتالي:\n"
                    "**تحليل الشذوذ:** (اذكر الشهور التي بها طفرات للأعلى أو للأسفل حسب الحقائق أعلاه)\n"
                    "**تحليل الموسمية:** (اربط فترات الذروة والهبوط بدليل المواسم عندما يتسق مع الأرقام، وإلا اذكر التعارض صراحة)\n"
                    "**خطة العمل:** (3 خطوات مرقمة، كل خطوة مرتبطة بنتيجة محددة من الحقائق أعلاه، وتغطي الشهور الضعيفة والقوية المذكورة فيها. "
                    "لا تقترح أي إجراء تعتمد فيه على معلومة غير موجودة، مثل أوقات الانتظار أو نقص المخزون)"
                )
                
                ai_response, ai_error = call_groq(api_key, prompt)

                if not ai_response:
                    st.warning(tr({'ar': "الموديل لم يُرجع إجابة هذه المرة. حاولي مرة أخرى.", 'en': "The model did not return an answer. Please try again."}))
                    if ai_error:
                        st.caption(ai_error)
                else:
                    st.session_state['last_sales_ai_response'] = ai_response
                    st.session_state['last_sales_query'] = query_text
                    st.session_state['last_sales_facts'] = facts_text

                    try:
                        if auto_send_urgent and telegram_configured:
                            decision_id = str(int(time.time()))
                            message = f"*تنبيه تلقائي - تحليل المبيعات*\n\n*الطلب:* {query_text}\n\n*التحليل:*\n{ai_response}"
                            safe_msg = message[:4000]
                            t_url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
                            t_payload = {
                                "chat_id": telegram_chat_id,
                                "text": safe_msg,
                                "parse_mode": "Markdown",
                                "reply_markup": {"inline_keyboard": [[{"text": "اعتماد", "callback_data": f"Approve_{decision_id}"}, {"text": "رفض", "callback_data": f"Reject_{decision_id}"}]]}
                            }
                            res_t = requests.post(t_url, json=t_payload, timeout=30)
                            if res_t.status_code == 200:
                                new_dec = pd.DataFrame([{'ID': decision_id, 'Date': pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"), 'Decision': query_text[:50], 'Status': "Pending"}])
                                if os.path.exists(dec_file):
                                    df = pd.read_csv(dec_file)
                                    df = pd.concat([new_dec, df], ignore_index=True)
                                else:
                                    df = new_dec
                                df.to_csv(dec_file, index=False)
                                st.info(tr({'ar': "تم الإرسال تلقائياً إلى تليجرام لوجود تنبيهات.", 'en': "Auto-sent to Telegram."}))
                    except Exception as e:
                        st.error(f"Error: {str(e)}")

    # The report lives in session_state, so it stays on screen after any other button is clicked
    if 'last_sales_ai_response' in st.session_state:
        st.markdown("<br>", unsafe_allow_html=True)
        render_ai_box(st.session_state['last_sales_ai_response'])
        if st.session_state.get('last_sales_facts'):
            with st.expander(tr({'ar': "الأرقام التي بُني عليها التقرير", 'en': "Figures the report is based on"})):
                st.markdown(st.session_state['last_sales_facts'])

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button(tr({'ar': "إرسال التقرير إلى الإدارة (تليجرام) وحفظ القرار", 'en': "Send to Telegram & Save"})):
            if telegram_configured:
                try:
                    decision_id = str(int(time.time()))
                    message = f"*تقرير أداء المبيعات*\n\n*الطلب:* {st.session_state['last_sales_query']}\n\n*التحليل:*\n{st.session_state['last_sales_ai_response']}"
                    safe_message = message[:4000]

                    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
                    payload = {
                        "chat_id": telegram_chat_id,
                        "text": safe_message,
                        "parse_mode": "Markdown",
                        "reply_markup": {
                            "inline_keyboard": [[
                                {"text": "اعتماد", "callback_data": f"Approve_{decision_id}"},
                                {"text": "رفض", "callback_data": f"Reject_{decision_id}"}
                            ]]
                        }
                    }
                    response = requests.post(url, json=payload, timeout=30)
                    
                    if response.status_code == 200:
                        new_decision = pd.DataFrame([{
                            'ID': decision_id,
                            'Date': pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
                            'Decision': st.session_state['last_sales_query'][:50],
                            'Status': "Pending"
                        }])
                        if os.path.exists(dec_file):
                            existing_df = pd.read_csv(dec_file)
                            updated_df = pd.concat([new_decision, existing_df], ignore_index=True)
                        else:
                            updated_df = new_decision
                        updated_df.to_csv(dec_file, index=False)
                        
                        st.success(tr({'ar': "تم الإرسال إلى تليجرام وحفظ القرار في السجل بنجاح", 'en': "Sent to Telegram and saved to log successfully"}))
                        time.sleep(1.5)
                        st.rerun()
                    else:
                        st.error(f"Telegram Error: {response.text}")
                except Exception as e:
                    st.error(f"Error: {str(e)}")
            else:
                st.warning(tr({'ar': "إعدادات تليجرام غير موجودة في secrets.toml", 'en': "Telegram settings are missing from secrets.toml"}))

    c_ai1, c_ai2 = st.columns(2)
    with c_ai1:
        st.markdown(f"#### {tr({'ar': 'سجل القرارات والتقارير', 'en': 'Decisions Log'})}")
        if telegram_configured:
            if st.button(tr({'ar': "تحديث ردود تليجرام", 'en': "Sync Telegram Responses"})):
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
                                st.success(tr({'ar': "تمت مزامنة القرارات بنجاح", 'en': "Decisions synced successfully"}))
                                time.sleep(1)
                                st.rerun()
                except:
                    pass

        if os.path.exists(dec_file):
            dec_df = pd.read_csv(dec_file)
            display_cols = {
                'ID': 'ID',
                'Date': tr({'ar': 'التاريخ', 'en': 'Date'}),
                'Decision': tr({'ar': 'القرار', 'en': 'Decision'}),
                'Status': tr({'ar': 'الحالة', 'en': 'Status'})
            }
            if 'Status' in dec_df.columns:
                dec_df.rename(columns=display_cols, inplace=True)
                def color_status(val):
                    color = 'orange' if val == 'Pending' else 'green' if val == 'Approved' else 'red'
                    return f'color: {color}; font-weight: bold'
                status_col_name = display_cols['Status']
                st.dataframe(dec_df.style.map(color_status, subset=[status_col_name]), hide_index=True, use_container_width=True)
            else:
                st.dataframe(dec_df, hide_index=True, use_container_width=True)