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

# إعداد الصفحة
try:
    st.set_page_config(layout="wide", page_title="Customer Segmentation & Loyalty")
except:
    pass

# --- Paths & Data Directory ---
APP_DIR = os.path.dirname(os.path.abspath(__file__))
for _p in (APP_DIR, os.path.dirname(APP_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

def resolve_data_dir():
    local = os.path.join(APP_DIR, 'data')
    parent = os.path.join(os.path.dirname(APP_DIR), 'data')
    if os.path.exists(local): return local
    if os.path.exists(parent): return parent
    return '/content'

if 'lang' not in st.session_state:
    st.session_state.lang = 'ar'

def tr(text_dict):
    return text_dict.get(st.session_state.lang, text_dict.get('en', ''))

def get_secret(name, default=""):
    value = None
    try: value = st.secrets.get(name, None)
    except: value = None
    if not value: value = os.environ.get(name, default)
    return str(value).strip() if value else default

def redact(message, *secrets):
    msg = str(message)
    for s in secrets:
        if s: msg = msg.replace(s, "***")
    return re.sub(r"bot\d+:[A-Za-z0-9_-]+", "bot***", msg)

def format_number(num):
    if pd.isna(num): return "0"
    if num >= 1e9: return f"{num / 1e9:.1f}B"
    elif num >= 1e6: return f"{num / 1e6:.1f}M"
    elif num >= 1e3: return f"{num / 1e3:.1f}K"
    else: return f"{num:,.0f}"

# --- CSS Styling ---
st.markdown("""
    <style>
    .stApp { background-color: #f8fafc; color: #0f172a; }
    .kpi-card {
        background-color: #ffffff; padding: 20px; border-radius: 12px;
        border: 2px solid #cbd5e1; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        text-align: center; margin-bottom: 15px; transition: transform 0.2s;
    }
    .kpi-card:hover { transform: scale(1.02); border-color: #3b82f6; }
    .kpi-value { font-size: 26px; font-weight: bold; color: #1e3a8a; margin-bottom: 5px; }
    .kpi-label { font-size: 13px; color: #64748b; font-weight: 600; text-transform: uppercase; }
    
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 12px; border: 2px solid #94a3b8 !important; 
        background-color: #ffffff; padding: 15px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    }
    .ai-response-box {
        padding: 40px; background-color: #ffffff; border: 1px solid #cbd5e1;
        border-radius: 8px; font-size: 17px; line-height: 2.2; color: #0f172a;
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1); font-family: 'Arial', sans-serif;
    }
    .chart-subtitle { font-size: 12px; color: #64748b; text-align: center; margin-top: -10px; margin-bottom: 15px; }
    </style>
""", unsafe_allow_html=True)

# --- Category Mapping ---
cat_mapping = {
    "Men's Basics": "أساسيات رجالي", "Men bottoms": "أساسيات رجالي", "Men boxers": "أساسيات رجالي", "Men tops": "أساسيات رجالي", "Men underwear": "أساسيات رجالي",
    "Women's Basics": "يومي حريمي", "Women bottoms": "يومي حريمي", "Women bras": "يومي حريمي", "Women tops": "يومي حريمي", "Women pajamas": "يومي حريمي",
    "Kids & Junior": "أطفال ومراهقين", "Boys pajamas": "أطفال ومراهقين", "Girls pajamas": "أطفال ومراهقين", "Girls underwear": "أطفال ومراهقين", "Kids underwear": "أطفال ومراهقين",
    "Activewear": "رياضي وعملي", "Socks": "رياضي وعملي", "Accessories": "رياضي وعملي",
    "Home Textiles": "مفروشات ومنزل"
}

# أسماء محتملة لعمود قيمة الطلب (أضف اسم عمودك هنا لو مختلف)
AMOUNT_COL_CANDIDATES = [
    'total_amount', 'net_amount', 'order_total', 'grand_total',
    'order_value', 'net_total', 'total', 'amount', 'total_price'
]

def detect_amount_column(path):
    """يرجع اسم عمود قيمة الطلب لو موجود في ملف الطلبات، وإلا None."""
    try:
        import pyarrow.parquet as pq
        names = pq.read_schema(path).names
        for c in AMOUNT_COL_CANDIDATES:
            if c in names:
                return c
    except Exception:
        pass
    return None

# --- Data Loading & Cohort Processing ---
@st.cache_data(show_spinner=False)
def load_loyalty_data():
    try:
        data_dir = resolve_data_dir()
        path_orders = os.path.join(data_dir, 'sales_orders.parquet')
        path_customers = os.path.join(data_dir, 'customers.parquet')
        path_items = os.path.join(data_dir, 'sales_order_items.parquet')
        path_products = os.path.join(data_dir, 'products_catalog.parquet')
        
        if not os.path.exists(path_orders): return None, None, str(f"Missing file: {path_orders}")
        
        amount_col = detect_amount_column(path_orders)
        order_cols = ['sales_order_id', 'order_date', 'customer_id'] + ([amount_col] if amount_col else [])
        
        df_orders = pd.read_parquet(path_orders, columns=order_cols)
        df_customers = pd.read_parquet(path_customers, columns=['customer_id', 'governorate_ar', 'age_band', 'joined_date'])
        
        if amount_col:
            df_orders = df_orders.rename(columns={amount_col: 'order_amount'})
            df_orders['order_amount'] = pd.to_numeric(df_orders['order_amount'], errors='coerce')
        
        df_orders['order_date'] = pd.to_datetime(df_orders['order_date'], errors='coerce')
        df_customers['joined_date'] = pd.to_datetime(df_customers['joined_date'], errors='coerce')
        df_orders = df_orders.dropna(subset=['order_date'])
        
        # Merge basic
        df_full = df_orders.merge(df_customers, on='customer_id', how='inner')
        
        # Fix Joined Date (use first purchase if missing)
        first_orders = df_full.groupby('customer_id')['order_date'].min().reset_index()
        first_orders.rename(columns={'order_date': 'first_purchase'}, inplace=True)
        df_full = df_full.merge(first_orders, on='customer_id', how='left')
        df_full['joined_date'] = df_full['joined_date'].fillna(df_full['first_purchase'])
        
        # --- COHORT ALGORITHM ---
        # الفوج = شهر أول شراء فعلي للعميل (زي ما الوصف في الرسم بيقول)
        df_full['order_month'] = df_full['order_date'].dt.to_period('M')
        df_full['cohort_month'] = df_full['first_purchase'].dt.to_period('M')
        max_period = df_full['order_month'].max()
        
        cohort_size = df_full.groupby('cohort_month')['customer_id'].nunique().rename('cohort_size')
        active = df_full.groupby(['cohort_month', 'order_month'])['customer_id'].nunique().rename('n_customers').reset_index()
        active['cohort_index'] = (active['order_month'].dt.year - active['cohort_month'].dt.year) * 12 + \
                                 (active['order_month'].dt.month - active['cohort_month'].dt.month)
        
        # شبكة كاملة: كل فوج × كل شهر متاح فعلاً في البيانات (الشهور الفاضية = 0 عميل نشط)
        grid_rows = []
        for cm in cohort_size.index:
            for k in range((max_period - cm).n + 1):
                grid_rows.append((cm, k))
        grid = pd.DataFrame(grid_rows, columns=['cohort_month', 'cohort_index'])
        grid = grid.merge(active[['cohort_month', 'cohort_index', 'n_customers']], on=['cohort_month', 'cohort_index'], how='left')
        grid['n_customers'] = grid['n_customers'].fillna(0)
        grid = grid.merge(cohort_size.reset_index(), on='cohort_month', how='left')
        grid['joined_quarter'] = grid['cohort_month'].dt.asfreq('Q').dt.strftime('%YQ%q')
        
        # معدل الاحتفاظ لكل ربع = مجموع النشطين / مجموع حجم الأفواج (مرجّح بعدد العملاء، ومش ممكن يعدي 100%)
        final_cohort = grid.groupby(['joined_quarter', 'cohort_index']).agg(
            n=('n_customers', 'sum'), size=('cohort_size', 'sum')).reset_index()
        final_cohort['retention_rate'] = final_cohort['n'] / final_cohort['size'] * 100
        final_cohort = final_cohort[['joined_quarter', 'cohort_index', 'retention_rate']]
                                  
        # Load Items for Segments
        try:
            df_items = pd.read_parquet(path_items, columns=['sales_order_id', 'product_id'])
            df_products = pd.read_parquet(path_products, columns=['product_id', 'category_en'])
            df_items = df_items.merge(df_products, on='product_id', how='left')
            df_items['Main_Segment'] = df_items['category_en'].map(lambda x: cat_mapping.get(x, 'أخرى'))
            
            order_segments = df_items.groupby(['sales_order_id', 'Main_Segment']).size().reset_index(name='count')
            order_segments = order_segments.sort_values('count', ascending=False).drop_duplicates('sales_order_id')
            
            df_full = df_full.merge(order_segments[['sales_order_id', 'Main_Segment']], on='sales_order_id', how='left')
        except:
            df_full['Main_Segment'] = "غير محدد"

        return df_full, final_cohort, None
    except Exception as e:
        return None, None, str(e)

df_full, cohort_data, load_error = load_loyalty_data()

if df_full is None:
    st.error(f"خطأ في تحميل البيانات. التفاصيل: {load_error}")
    st.stop()

# --- Sidebar ---
st.sidebar.markdown(f"<h3>{tr({'ar': 'إعدادات النظام', 'en': 'System Settings'})}</h3>", unsafe_allow_html=True)
selected_lang = st.sidebar.radio(tr({'ar': "اللغة", 'en': "Language"}), ['ar', 'en'], index=0 if st.session_state.lang == 'ar' else 1)
if selected_lang != st.session_state.lang:
    st.session_state.lang = selected_lang
    st.rerun()

st.markdown(f"<h2 style='color:#1e3a8a; margin-bottom: 20px;'>{tr({'ar': 'شرائح العملاء والولاء', 'en': 'Customer Segmentation & Loyalty'})}</h2>", unsafe_allow_html=True)

# --- Date Filter ---
min_date, max_date = df_full['order_date'].min().date(), df_full['order_date'].max().date()
with st.container(border=True):
    c1, c2 = st.columns(2)
    start_date = c1.date_input(tr({'ar': "من تاريخ", 'en': "Start Date"}), min_date)
    end_date = c2.date_input(tr({'ar': "إلى تاريخ", 'en': "End Date"}), max_date)

mask = (df_full['order_date'].dt.date >= start_date) & (df_full['order_date'].dt.date <= end_date)
df_filtered = df_full[mask].copy()

if df_filtered.empty:
    st.warning(tr({'ar': "لا توجد بيانات للفترة المحددة.", 'en': "No data for selected period."}))
    st.stop()

# --- KPI Calculations ---
total_unique_customers = df_filtered['customer_id'].nunique()
total_orders = df_filtered['sales_order_id'].nunique()

customer_order_counts = df_filtered.groupby('customer_id')['sales_order_id'].nunique()
repeat_customers = (customer_order_counts > 1).sum()
repeat_rate = (repeat_customers / total_unique_customers * 100) if total_unique_customers > 0 else 0

avg_freq = total_orders / total_unique_customers if total_unique_customers > 0 else 0

urban_govs = ['القاهرة', 'الجيزة', 'الإسكندرية', 'Cairo', 'Giza', 'Alexandria']
urban_customers = df_filtered[df_filtered['governorate_ar'].isin(urban_govs)]['customer_id'].nunique()
urban_rate = (urban_customers / total_unique_customers * 100) if total_unique_customers > 0 else 0

age_counts = df_filtered.groupby('age_band')['customer_id'].nunique()
core_age_band = age_counts.idxmax() if not age_counts.empty else "N/A"
core_age_pct = (age_counts.max() / total_unique_customers * 100) if total_unique_customers > 0 else 0

# متوسط قيمة الطلب (لو عمود القيمة موجود في ملف الطلبات)
aov = None
if 'order_amount' in df_filtered.columns:
    _aov = df_filtered.drop_duplicates('sales_order_id')['order_amount'].mean()
    if pd.notna(_aov) and _aov > 0:
        aov = float(_aov)

# احتفاظ الشهر الأول لأحدث فوج متاح
m1_retention = None
_m1 = cohort_data[cohort_data['cohort_index'] == 1] if cohort_data is not None else pd.DataFrame()
if not _m1.empty:
    m1_retention = float(_m1.sort_values('joined_quarter').iloc[-1]['retention_rate'])

# شرائح المنتجات (محسوبة بره التابات عشان تتاح للـ AI حتى لو التاب الأول ما اتنفذش)
if 'Main_Segment' in df_filtered.columns:
    seg_df = df_filtered[df_filtered['Main_Segment'] != 'غير محدد'].groupby('Main_Segment')['customer_id'].nunique().reset_index()
    if not seg_df.empty:
        seg_df['share'] = seg_df['customer_id'] / seg_df['customer_id'].sum() * 100
        seg_df = seg_df.sort_values('share', ascending=True)
    else:
        seg_df = pd.DataFrame(columns=['Main_Segment', 'customer_id', 'share'])
else:
    seg_df = pd.DataFrame(columns=['Main_Segment', 'customer_id', 'share'])

top_segment = seg_df.iloc[-1]['Main_Segment'] if not seg_df.empty else "غير محدد"

tab_dashboard, tab_ai = st.tabs([
    tr({'ar': "لوحة الولاء والشرائح", 'en': "Loyalty Dashboard"}),
    tr({'ar': "قرارات الولاء الاستراتيجية", 'en': "Strategic Loyalty Decisions"})
])

with tab_dashboard:
    st.markdown(f"<h5 style='color:#1e3a8a;'>{tr({'ar': 'لمحة عن ملف العملاء', 'en': 'Customer Profile Snapshot'})}</h5>", unsafe_allow_html=True)
    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"معدل تكرار الشراء", "en":"Avg Purchase Frequency"})}</div><div class="kpi-value">{avg_freq:,.1f}x</div></div>', unsafe_allow_html=True)
    k2.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"العملاء المتكررين", "en":"Repeat Customers"})}</div><div class="kpi-value">{repeat_rate:,.0f}%</div></div>', unsafe_allow_html=True)
    k3.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"المتسوقين بالمدن الكبرى", "en":"Urban Shoppers"})}</div><div class="kpi-value">{urban_rate:,.0f}%</div></div>', unsafe_allow_html=True)
    k4.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"الفئة العمرية الأساسية", "en":"Core Age Base"})} ({core_age_band})</div><div class="kpi-value">{core_age_pct:,.0f}%</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    
    r1c1, r1c2 = st.columns([1.2, 1])

    with r1c1:
        with st.container(border=True):
            st.markdown(f"<h5 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'معدل احتفاظ الأفواج', 'en': 'Cohort Retention'})}</h5>", unsafe_allow_html=True)
            st.markdown(f"<p class='chart-subtitle'>{tr({'ar': 'يتتبع نسبة عودة العملاء للشراء بناءً على ربع سنة انضمامهم (أول شراء)', 'en': 'Tracks customer return rate based on their joining quarter'})}</p>", unsafe_allow_html=True)
            
            if not cohort_data.empty:
                c_data = cohort_data[(cohort_data['cohort_index'] >= 1) & (cohort_data['cohort_index'] <= 12)].copy()
                recent_quarters = sorted(c_data['joined_quarter'].unique())[-4:]
                c_data = c_data[c_data['joined_quarter'].isin(recent_quarters)]
                
                y_max = max(5, float(c_data['retention_rate'].max()) * 1.2) if not c_data.empty else 15
                fig_line = px.line(c_data, x='cohort_index', y='retention_rate', color='joined_quarter', markers=True, color_discrete_sequence=px.colors.sequential.Blues_r)
                fig_line.update_traces(hovertemplate='%{y:.1f}%')
                fig_line.update_layout(
                    xaxis_title=tr({'ar':"الأشهر منذ أول شراء", 'en':"Months since first purchase"}),
                    yaxis_title=tr({'ar':"% معدل الاحتفاظ", 'en':"Retention Rate %"}),
                    legend_title="",
                    yaxis_range=[0, y_max],
                    yaxis_ticksuffix="%",
                    hovermode="x unified",
                    paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
                )
                fig_line.update_xaxes(tickmode='array', tickvals=list(range(1, 13)), ticktext=[str(i) for i in range(1, 13)])
                st.plotly_chart(fig_line, use_container_width=True)
            else:
                st.info("لا توجد بيانات كافية.")

    with r1c2:
        with st.container(border=True):
            st.markdown(f"<h5 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'شرائح المنتجات الرئيسية', 'en': 'Product Segments'})}</h5>", unsafe_allow_html=True)
            st.markdown(f"<p class='chart-subtitle'>{tr({'ar': 'نسبة العملاء لكل قسم من أقسام المنتجات', 'en': 'Share of customers per main product segment'})}</p>", unsafe_allow_html=True)
            
            if not seg_df.empty:
                fig_bar = px.bar(seg_df, x='share', y='Main_Segment', orientation='h', text=seg_df['share'].apply(lambda x: f"{x:.0f}%"), color_discrete_sequence=['#3b82f6'])
                fig_bar.update_traces(textposition='outside')
                fig_bar.update_layout(xaxis_title=tr({'ar':"% نسبة العملاء", 'en':"% Share of Customers"}), yaxis_title="", showlegend=False, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', xaxis_range=[0, max(seg_df['share'])+15])
                st.plotly_chart(fig_bar, use_container_width=True)
            else:
                st.info("Product segment data not available.")

# --- AI Strategic Decisions Tab ---
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-20b"

def call_groq(api_key, prompt):
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_completion_tokens": 2000,  # gpt-oss بيستهلك جزء من التوكنز في التفكير
    }
    try:
        r = requests.post(GROQ_URL, headers=headers, json=payload, timeout=90)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"].get("content", "").strip(), None
        return None, redact(f"Groq error {r.status_code}: {r.text[:200]}", api_key)
    except requests.exceptions.RequestException as e:
        return None, redact(f"Groq connection error: {e}", api_key)

def build_loyalty_prompt():
    """يبني البرومبت من الأرقام الفعلية للفترة المحددة."""
    lines = [
        f"- عدد العملاء: {total_unique_customers:,} | عدد الطلبات: {total_orders:,}",
    ]
    if aov is not None:
        lines.append(f"- متوسط قيمة الطلب: {aov:,.0f} ج.م")
    lines.append(f"- نسبة العملاء المتكررين: {repeat_rate:.0f}% (متوسط تكرار الشراء {avg_freq:.1f} مرة للعميل)")
    lines.append(f"- القسم الأكثر شراءً: {top_segment}")
    lines.append(f"- المتسوقون في المدن الكبرى (القاهرة/الجيزة/الإسكندرية): {urban_rate:.0f}% من العملاء")
    lines.append(f"- الفئة العمرية الأساسية: {core_age_band} وتمثل {core_age_pct:.0f}% من العملاء")
    if m1_retention is not None:
        lines.append(f"- معدل الاحتفاظ بعد الشهر الأول للفوج الأحدث: {m1_retention:.0f}%")
    data_block = "\n".join(lines)

    if aov is not None:
        basket_rule = "2. أمر يستهدف رفع قيمة السلة، وتُحسب حدوده من متوسط قيمة الطلب (حد أعلى من المتوسط بنحو 20-30%)."
        numbers_rule = "- لا تخترع أرقاماً عن العملاء غير الموجودة أعلاه؛ الأرقام المسموح بها فقط هي أرقام العروض نفسها وأهداف الـ KPI."
    else:
        basket_rule = "2. أمر يستهدف رفع قيمة السلة بالاعتماد على عدد القطع (مثل: اشترِ 3 قطع واحصل على خصم)، دون تحديد حد بالجنيه لأن متوسط قيمة الطلب غير متاح."
        numbers_rule = "- لا تخترع أرقاماً عن العملاء ولا حدوداً بالجنيه مرتبطة بقيمة الطلب؛ الأرقام المسموح بها فقط هي نسب الخصم وعدد القطع وأهداف الـ KPI."

    return (
        "أنت مدير تسويق تنفيذي (CMO) في شركة قطونيل (مصر) متخصصة في الملابس الداخلية والأساسيات. "
        "مهمتك إصدار 3 أوامر تشغيلية لزيادة ولاء العملاء، مبنية فقط على الأرقام التالية.\n\n"
        "البيانات الفعلية للفترة المحددة:\n"
        f"{data_block}\n\n"
        "المطلوب: 3 أوامر مختلفة تماماً في الآلية، كل واحد يعالج هدفاً مختلفاً:\n"
        "1. أمر يستهدف تحويل العملاء ذوي الشراء الواحد إلى متكررين (اعتمد على نسبة المتكررين ومعدل الاحتفاظ).\n"
        f"{basket_rule}\n"
        "3. أمر يستهدف الشريحة الأقوى (الفئة العمرية أو المدن الكبرى أو القسم الأعلى) بعرض خاص بها.\n\n"
        "قواعد صارمة:\n"
        "- اللغة العربية فقط، بدون أي مقدمة أو خاتمة أو رموز تعبيرية.\n"
        "- أرجع الرد كـ JSON فقط (مصفوفة من 3 عناصر) بدون أي نص خارجه وبدون علامات ```، وكل عنصر بالمفاتيح التالية بالضبط: "
        "\"title\" (عنوان قصير من 2-4 كلمات)، \"target\" (الشريحة المستهدفة)، \"action\" (الآلية بالأرقام في جملة واحدة قصيرة)، "
        "\"duration\" (مدة التنفيذ)، \"kpi\" (مؤشر النجاح المتوقع بهدف رقمي). كل قيمة نص عربي قصير بدون رموز تعبيرية.\n"
        "- ممنوع تكرار نفس الآلية في قرارين (مثلاً لا تستخدم النقاط أو التوصيل المجاني أكثر من مرة واحدة في الثلاثة).\n"
        "- نوّع الآليات بين: كوبون، باقات/عروض الكميات، هدية عند حد معين، مكافأة إحالة، عرض حصري لقسم معين، رسالة استرجاع للعملاء الخاملين.\n"
        f"{numbers_rule}\n"
        "- الأوامر لازم تكون قابلة للتنفيذ خلال 30 يوم."
    )

def parse_directives(text):
    """يحاول يقرأ JSON من رد الموديل. يرجع قائمة عناصر أو None."""
    import json
    try:
        t = re.sub(r"```(?:json)?", "", text).strip()
        i, j = t.find("["), t.rfind("]")
        if i == -1 or j == -1: return None
        items = json.loads(t[i:j + 1])
        keys = ("title", "target", "action", "duration", "kpi")
        out = [{k: str(it.get(k, "")).strip() for k in keys} for it in items if isinstance(it, dict)]
        return out[:3] if out else None
    except Exception:
        return None

def directives_to_text(items, lang='ar'):
    """نص منسق للإرسال على تليجرام."""
    labels = {'target': 'الشريحة', 'action': 'الآلية', 'duration': 'المدة', 'kpi': 'مؤشر النجاح'} if lang == 'ar' \
        else {'target': 'Target', 'action': 'Mechanism', 'duration': 'Duration', 'kpi': 'KPI'}
    blocks = []
    for n, it in enumerate(items, 1):
        lines = [f"{n}. {it['title']}"]
        for k in ('target', 'action', 'duration', 'kpi'):
            if it.get(k): lines.append(f"- {labels[k]}: {it[k]}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)

def render_directive_cards(items):
    labels = {'target': tr({'ar': 'الشريحة', 'en': 'Target'}), 'action': tr({'ar': 'الآلية', 'en': 'Mechanism'}),
              'duration': tr({'ar': 'المدة', 'en': 'Duration'}), 'kpi': tr({'ar': 'مؤشر النجاح', 'en': 'KPI'})}
    for n, it in enumerate(items, 1):
        rows = "".join(
            f"<div style='margin-top:8px;'><span style='color:#64748b; font-weight:600;'>{html.escape(labels[k])}:</span> "
            f"<span style='color:#0f172a;'>{html.escape(it.get(k, ''))}</span></div>"
            for k in ('target', 'action', 'duration', 'kpi') if it.get(k)
        )
        card = (
            "<div dir='auto' style='background:#ffffff; border:1px solid #cbd5e1; border-right:6px solid #3b82f6; "
            "border-radius:10px; padding:18px 22px; margin-bottom:14px; box-shadow:0 4px 6px -1px rgba(0,0,0,0.08); font-size:16px; line-height:1.9;'>"
            f"<div style='font-size:18px; font-weight:bold; color:#1e3a8a;'>{n}. {html.escape(it['title'])}</div>{rows}</div>"
        )
        st.markdown(card, unsafe_allow_html=True)

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

def send_telegram_directive(token, chat_id, memo_text, decision_id, lang):
    title = "قرارات برامج الولاء (Loyalty CRM)" if lang == 'ar' else "Loyalty CRM Decisions"
    button = "تم الاستلام وجاري الإطلاق" if lang == 'ar' else "Received - Launching"
    
    chunks, cur = [], ""
    for line in memo_text.split("\n"):
        s = html.escape(line, quote=False)
        s = re.sub(r"^\s*#{1,6}\s+(.*)$", r"<b>\1</b>", s)
        s = re.sub(r"^(\s*)[*+-]\s+", r"\1• ", s)
        s = s.replace("**", "")
        if len(cur) + len(s) > 3500:
            chunks.append(cur)
            cur = s + "\n"
        else:
            cur += s + "\n"
    if cur: chunks.append(cur)
        
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for i, chunk in enumerate(chunks):
        text = (f"<b>{html.escape(title)}</b>\n\n" if i == 0 else "") + chunk
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if i == len(chunks) - 1:
            payload["reply_markup"] = {"inline_keyboard": [[{"text": button, "callback_data": f"Approve_{decision_id}"}]]}
        try:
            r = requests.post(url, json=payload, timeout=30)
            if r.status_code != 200 or not r.json().get("ok"):
                return False, redact(f"Telegram error {r.status_code}", token)
        except Exception as e:
            return False, redact(f"Telegram connection error: {e}", token)
    return True, None

LOG_COLS = ['ID', 'Date', 'Topic', 'Status']

def read_decisions(path):
    if not os.path.exists(path): return pd.DataFrame(columns=LOG_COLS)
    df = pd.read_csv(path, dtype=str, encoding='utf-8-sig').fillna('')
    for col in LOG_COLS:
        if col not in df.columns: df[col] = ''
    return df

def write_decisions(df, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
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
    try: res = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=30).json()
    except: return 0, "Telegram connection error"
    if not res.get("ok"): return 0, "Telegram API error"
    
    updated = 0
    for update in res.get("result", []):
        data = (update.get("callback_query") or {}).get("data") or ""
        if "_" not in data: continue
        action, dec_id = data.split("_", 1)
        if not dec_id.startswith("LOY_"): continue
        new_status = 'Executed' if action == 'Approve' else 'Rejected'
        mask = df['ID'].astype(str) == dec_id
        if mask.any() and (df.loc[mask, 'Status'] != new_status).any():
            df.loc[mask, 'Status'] = new_status
            updated += 1
    if updated: write_decisions(df, path)
    return updated, None

def status_style(val):
    color = '#f59e0b' if val == 'Pending' else '#10b981' if val == 'Executed' else '#ef4444'
    return f'color: {color}; font-weight: bold'

with tab_ai:
    dec_file = os.path.join(resolve_data_dir(), 'loyalty_decisions_log.csv')
    groq_key = get_secret("GROQ_API_KEY")
    telegram_token = get_secret("TELEGRAM_TOKEN")
    telegram_chat_id = get_secret("TELEGRAM_CHAT_ID")
    api_key_configured = bool(groq_key)
    telegram_configured = bool(telegram_token and telegram_chat_id)

    flash = st.session_state.pop('loy_flash', None)
    if flash: getattr(st, flash[0])(flash[1])

    st.markdown(f"<h4 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'إصدار قرارات برامج الولاء التسويقية', 'en': 'Generate Loyalty Program Directives'})}</h4>", unsafe_allow_html=True)
    
    if st.button(tr({'ar': "توليد قرارات الولاء الآن", 'en': "Generate Loyalty Decisions Now"}), type="primary", use_container_width=True):
        if not api_key_configured:
            st.warning(tr({'ar': "الرجاء إعداد GROQ_API_KEY", 'en': "Please configure GROQ_API_KEY"}))
        elif cohort_data is None or cohort_data.empty:
            st.warning(tr({'ar': "لا توجد بيانات كافية لاستخراج القرارات.", 'en': "Not enough data."}))
        else:
            with st.spinner(tr({'ar': "يتم تحليل البيانات لاستخراج أوامر استراتيجية للولاء...", 'en': "Analyzing data for loyalty directives..."})):
                prompt = build_loyalty_prompt()
                ai_res, ai_err = call_groq(groq_key, prompt)
                if ai_res:
                    items = parse_directives(ai_res)
                    st.session_state['loy_ai_items'] = items
                    st.session_state['loy_ai_response'] = directives_to_text(items, st.session_state.lang) if items else ai_res
                    st.session_state['loy_ai_lang'] = st.session_state.lang
                else:
                    st.error(ai_err)

    if 'loy_ai_response' in st.session_state:
        memo_text = st.session_state['loy_ai_response']
        memo_lang = st.session_state.get('loy_ai_lang', st.session_state.lang)

        st.markdown("<br>", unsafe_allow_html=True)
        ai_items = st.session_state.get('loy_ai_items')
        if ai_items:
            render_directive_cards(ai_items)
        else:
            render_ai_box(memo_text)
        st.markdown("<br>", unsafe_allow_html=True)
        
        c_btn1, c_btn2 = st.columns([1, 2])
        with c_btn1:
            if st.button(tr({'ar': "إرسال الأوامر لفريق التسويق (تليجرام)", 'en': "Send Directives via Telegram"}), use_container_width=True):
                if not telegram_configured:
                    st.warning(tr({'ar': "تليجرام غير مفعل", 'en': "Telegram not configured"}))
                else:
                    decision_id = "LOY_" + str(int(time.time()))
                    ok, err = send_telegram_directive(telegram_token, telegram_chat_id, memo_text, decision_id, memo_lang)
                    if not ok: 
                        st.error(err)
                    else:
                        topic = "قرارات برامج الولاء التسويقية" if memo_lang == 'ar' else "Loyalty Program Decisions"
                        try:
                            append_decision(dec_file, {'ID': decision_id, 'Date': pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"), 'Topic': topic, 'Status': "Pending"})
                            st.session_state['loy_flash'] = ('success', tr({'ar': "تم إرسال القرارات بنجاح", 'en': "Sent successfully"}))
                        except Exception as e:
                            st.session_state['loy_flash'] = ('warning', f"Sent to Telegram but log failed: {e}")
                        st.rerun()

    st.markdown("<br><hr>", unsafe_allow_html=True)
    c_ai1, c_ai2 = st.columns([2, 1])
    with c_ai1: 
        st.markdown(f"#### {tr({'ar': 'سجل قرارات برامج الولاء', 'en': 'Loyalty Decisions Log'})}")
    with c_ai2:
        if telegram_configured:
            if st.button(tr({'ar': "تحديث حالات التنفيذ", 'en': "Sync Executions"})):
                n_updated, sync_err = sync_telegram_statuses(telegram_token, dec_file)
                if sync_err: 
                    st.error(f"Sync error: {sync_err}")
                elif n_updated:
                    st.session_state['loy_flash'] = ('success', tr({'ar': "تمت المزامنة بنجاح", 'en': "Synced successfully"}))
                    st.rerun()
                else: 
                    st.info(tr({'ar': "لا توجد تحديثات جديدة.", 'en': "No new updates."}))

    try: 
        dec_df = read_decisions(dec_file)
    except Exception as e: 
        dec_df = None
        st.error(str(e))
    
    if dec_df is not None and not dec_df.empty:
        display_cols = {'ID': 'ID', 'Date': tr({'ar': 'التاريخ', 'en': 'Date'}), 'Topic': tr({'ar': 'موضوع القرار', 'en': 'Topic'}), 'Status': tr({'ar': 'حالة التنفيذ', 'en': 'Status'})}
        dec_df = dec_df.rename(columns=display_cols)
        styler = dec_df.style
        styler = (styler.map if hasattr(styler, 'map') else styler.applymap)(status_style, subset=[display_cols['Status']])
        st.dataframe(styler, hide_index=True, use_container_width=True)