import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os
import datetime
import sys

# إعداد الصفحة
try:
    st.set_page_config(layout="wide", page_title="Customer Lifetime Value & Churn Prediction")
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
    .kpi-risk { color: #ef4444 !important; }
    .kpi-good { color: #10b981 !important; }
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 12px; border: 2px solid #94a3b8 !important; 
        background-color: #ffffff; padding: 15px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    }
    .chart-subtitle { font-size: 12px; color: #64748b; text-align: center; margin-top: -10px; margin-bottom: 15px; }
    </style>
""", unsafe_allow_html=True)

# --- RFM Mapping Function ---
def segment_customer(row):
    r, f, m = row['R_Score'], row['F_Score'], row['M_Score']
    
    if r >= 4 and f >= 4 and m >= 4: return 'Champions (أبطال)'
    elif r >= 3 and f >= 3: return 'Loyal Customers (موالون)'
    elif r >= 3 and f <= 2: return 'Potential Loyalist (ولاء محتمل)'
    elif r == 4 and f == 1: return 'New Customers (عملاء جدد)'
    elif r == 2: return 'Need Attention (يحتاجون انتباه)'
    elif r == 1 and f >= 3: return 'At Risk (في خطر)'
    elif r == 1 and f <= 2: return 'Churned (متسربون)'
    else: return 'Others (آخرون)'

def get_churn_risk(segment):
    risks = {
        'Champions (أبطال)': 1.0, 'Loyal Customers (موالون)': 3.0, 'Potential Loyalist (ولاء محتمل)': 5.0,
        'New Customers (عملاء جدد)': 8.0, 'Need Attention (يحتاجون انتباه)': 15.0, 
        'At Risk (في خطر)': 45.0, 'Churned (متسربون)': 90.0, 'Others (آخرون)': 10.0
    }
    return risks.get(segment, 10.0)

def get_segment_priority(segment):
    if segment in ['Champions (أبطال)', 'Loyal Customers (موالون)', 'At Risk (في خطر)']: return 'High (عالية)'
    elif segment in ['Potential Loyalist (ولاء محتمل)', 'Need Attention (يحتاجون انتباه)']: return 'Medium (متوسطة)'
    else: return 'Low (منخفضة)'

# --- Data Loading & RFM Processing ---
@st.cache_data(show_spinner=False)
def load_rfm_data():
    try:
        data_dir = resolve_data_dir()
        path_orders = os.path.join(data_dir, 'sales_orders.parquet')
        path_customers = os.path.join(data_dir, 'customers.parquet')
        
        if not os.path.exists(path_orders): return None, f"Missing file: {path_orders}"
        if not os.path.exists(path_customers): return None, f"Missing file: {path_customers}"

        df_orders = pd.read_parquet(path_orders, columns=['sales_order_id', 'order_date', 'customer_id', 'paid_total_EGP'])
        df_customers = pd.read_parquet(path_customers, columns=['customer_id', 'governorate_ar', 'age_band', 'customer_segment'])
        
        df_orders['order_date'] = pd.to_datetime(df_orders['order_date'], errors='coerce')
        df_orders = df_orders.dropna(subset=['order_date'])
        
        if df_orders.empty: return None, "ملف المبيعات فارغ أو لا يحتوي على تواريخ صحيحة."

        snapshot_date = df_orders['order_date'].max() + datetime.timedelta(days=1)
        
        rfm = df_orders.groupby('customer_id').agg({
            'order_date': lambda x: (snapshot_date - x.max()).days,
            'sales_order_id': 'count',
            'paid_total_EGP': 'sum'
        }).reset_index()
        
        rfm.rename(columns={'order_date': 'Recency', 'sales_order_id': 'Frequency', 'paid_total_EGP': 'Monetary'}, inplace=True)
        
        rfm['R_Score'] = pd.qcut(rfm['Recency'].rank(method='first'), 4, labels=[4, 3, 2, 1]).astype(int)
        rfm['F_Score'] = pd.qcut(rfm['Frequency'].rank(method='first'), 4, labels=[1, 2, 3, 4]).astype(int)
        rfm['M_Score'] = pd.qcut(rfm['Monetary'].rank(method='first'), 4, labels=[1, 2, 3, 4]).astype(int)
        
        rfm['Segment'] = rfm.apply(segment_customer, axis=1)
        rfm['Churn_Risk_Pct'] = rfm['Segment'].apply(get_churn_risk)
        rfm['Priority'] = rfm['Segment'].apply(get_segment_priority)
        
        df_rfm_full = rfm.merge(df_customers, on='customer_id', how='left')
        
        return df_rfm_full, None
    except Exception as e:
        return None, str(e)

df_rfm_full, load_error = load_rfm_data()

if df_rfm_full is None:
    st.error(f"خطأ في تحميل البيانات. التفاصيل: {load_error}")
    st.stop()

# --- Sidebar ---
st.sidebar.markdown(f"<h3>{tr({'ar': 'إعدادات النظام', 'en': 'System Settings'})}</h3>", unsafe_allow_html=True)
selected_lang = st.sidebar.radio(tr({'ar': "اللغة", 'en': "Language"}), ['ar', 'en'], index=0 if st.session_state.lang == 'ar' else 1)
if selected_lang != st.session_state.lang:
    st.session_state.lang = selected_lang
    st.rerun()

st.markdown(f"<h2 style='color:#1e3a8a; margin-bottom: 20px;'>{tr({'ar': 'القيمة الدائمة للعملاء وتوقع التسرب (RFM Analysis)', 'en': 'Customer Lifetime Value & Churn Prediction'})}</h2>", unsafe_allow_html=True)

# --- Filters ---
available_govs = df_rfm_full['governorate_ar'].dropna().unique().tolist()
available_ages = df_rfm_full['age_band'].dropna().unique().tolist()

with st.container(border=True):
    c1, c2 = st.columns(2)
    selected_govs = c1.multiselect(tr({'ar': "تصفية بالمحافظة", 'en': "Filter by Governorate"}), available_govs, default=[])
    selected_ages = c2.multiselect(tr({'ar': "تصفية بالفئة العمرية", 'en': "Filter by Age Band"}), available_ages, default=[])

df_filtered = df_rfm_full.copy()
if selected_govs: df_filtered = df_filtered[df_filtered['governorate_ar'].isin(selected_govs)]
if selected_ages: df_filtered = df_filtered[df_filtered['age_band'].isin(selected_ages)]

if df_filtered.empty:
    st.warning(tr({'ar': "لا توجد بيانات مطابقة للخيارات المحددة.", 'en': "No data for selected filters."}))
    st.stop()

# --- Safe KPI Calculations ---
f_total_customers = df_filtered['customer_id'].nunique()
f_avg_clv = df_filtered['Monetary'].mean()
f_avg_churn_risk = df_filtered['Churn_Risk_Pct'].mean()

churned_subset = df_filtered[df_filtered['Segment'] == 'Churned (متسربون)']
f_retention_rate = 100 - (churned_subset['customer_id'].nunique() / f_total_customers * 100) if f_total_customers > 0 else 0

repeat_subset = df_filtered[df_filtered['Frequency'] > 1]
f_repeat_cycle = repeat_subset['Recency'].median() if not repeat_subset.empty else 0
win_back_opps = churned_subset['customer_id'].nunique()

f_avg_clv = 0 if pd.isna(f_avg_clv) else f_avg_clv
f_avg_churn_risk = 0 if pd.isna(f_avg_churn_risk) else f_avg_churn_risk
f_retention_rate = 0 if pd.isna(f_retention_rate) else f_retention_rate
f_repeat_cycle = 0 if pd.isna(f_repeat_cycle) else f_repeat_cycle

# --- Main Dashboard ---
k1, k2, k3, k4, k5 = st.columns(5)
k1.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"متوسط قيمة العميل (CLV)", "en":"Avg CLV"})}</div><div class="kpi-value">{f_avg_clv:,.0f} ج.م</div></div>', unsafe_allow_html=True)
k2.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"خطر التسرب", "en":"Avg Churn Risk"})}</div><div class="kpi-value kpi-risk">{f_avg_churn_risk:,.1f}%</div></div>', unsafe_allow_html=True)
k3.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"معدل الاحتفاظ", "en":"Retention Rate"})}</div><div class="kpi-value kpi-good">{f_retention_rate:,.1f}%</div></div>', unsafe_allow_html=True)
k4.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"دورة الشراء", "en":"Repeat Purchase"})}</div><div class="kpi-value">{f_repeat_cycle:,.0f} يوم</div></div>', unsafe_allow_html=True)
k5.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"فرص الاستعادة", "en":"Win-Back Opps"})}</div><div class="kpi-value">{format_number(win_back_opps)}</div></div>', unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

r1c1, r1c2 = st.columns([1, 1])

with r1c1:
    with st.container(border=True):
        st.markdown(f"<h5 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'توزيع شرائح العملاء (RFM Segments)', 'en': 'RFM Customer Segments'})}</h5>", unsafe_allow_html=True)
        st.markdown(f"<p class='chart-subtitle'>{tr({'ar': 'يوضح حجم كل شريحة بناءً على حداثة وتكرار وقيمة الشراء', 'en': 'Segment size based on Recency, Frequency, and Monetary value'})}</p>", unsafe_allow_html=True)
        
        seg_dist = df_filtered.groupby('Segment')['customer_id'].nunique().reset_index().sort_values('customer_id', ascending=True)
        if not seg_dist.empty:
            fig_bar = px.bar(seg_dist, x='customer_id', y='Segment', orientation='h', color='Segment', color_discrete_sequence=px.colors.qualitative.Pastel)
            fig_bar.update_layout(xaxis_title=tr({'ar':"عدد العملاء", 'en':"Customers Count"}), yaxis_title="", showlegend=False, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig_bar, use_container_width=True)

with r1c2:
    with st.container(border=True):
        st.markdown(f"<h5 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'تحليل الشرائح الديموغرافية (العمر والمحافظة)', 'en': 'Demographic Segments (Age & Location)'})}</h5>", unsafe_allow_html=True)
        st.markdown(f"<p class='chart-subtitle'>{tr({'ar': 'أين يتركز عملاؤنا وما هي فئاتهم العمرية؟', 'en': 'Where are our customers and what is their age band?'})}</p>", unsafe_allow_html=True)
        
        demo_dist = df_filtered.groupby(['governorate_ar', 'age_band'])['customer_id'].nunique().reset_index()
        if not demo_dist.empty:
            top_govs = demo_dist.groupby('governorate_ar')['customer_id'].sum().nlargest(5).index
            demo_dist = demo_dist[demo_dist['governorate_ar'].isin(top_govs)]
            
            fig_demo = px.bar(demo_dist, x='governorate_ar', y='customer_id', color='age_band', barmode='stack', color_discrete_sequence=px.colors.sequential.Blues_r)
            fig_demo.update_layout(xaxis_title="", yaxis_title=tr({'ar':"عدد العملاء", 'en':"Customers Count"}), legend_title=tr({'ar':"الفئة العمرية", 'en':"Age Band"}), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig_demo, use_container_width=True)

st.markdown("<br>", unsafe_allow_html=True)

with st.container(border=True):
    st.markdown(f"<h5 style='color:#1e3a8a;'>{tr({'ar': 'أداء شرائح العملاء وقيمة CLV (Top Segments)', 'en': 'Top Customer Segments by CLV'})}</h5>", unsafe_allow_html=True)
    st.markdown(f"<p class='chart-subtitle' style='text-align: right;'>{tr({'ar': 'يساعد في توجيه ميزانية التسويق للفئات ذات القيمة العالية وحماية الفئات المعرضة للخطر', 'en': 'Helps direct marketing budget to high-value segments and protect at-risk customers'})}</p>", unsafe_allow_html=True)
    
    table_df = df_filtered.groupby('Segment').agg(
        Customers=('customer_id', 'nunique'),
        Avg_CLV=('Monetary', 'mean'),
        Avg_Churn_Risk=('Churn_Risk_Pct', 'mean'),
        Priority=('Priority', 'first')
    ).reset_index()
    
    if not table_df.empty:
        table_df = table_df.sort_values('Avg_CLV', ascending=False)
        
        col_seg = tr({'ar': 'شريحة العملاء', 'en': 'Segment'})
        col_cnt = tr({'ar': 'عدد العملاء', 'en': 'Customers'})
        col_clv = tr({'ar': 'متوسط قيمة العميل (ج.م)', 'en': 'Avg CLV (EGP)'})
        col_risk = tr({'ar': 'معدل خطر التسرب %', 'en': 'Churn Risk %'})
        col_pri = tr({'ar': 'أولوية الاستهداف', 'en': 'Priority'})
        
        table_df.rename(columns={'Segment': col_seg, 'Customers': col_cnt, 'Avg_CLV': col_clv, 'Avg_Churn_Risk': col_risk, 'Priority': col_pri}, inplace=True)
        
        def highlight_priority(val):
            if 'High' in str(val) or 'عالية' in str(val): return 'color: #ef4444; font-weight: bold;'
            elif 'Medium' in str(val) or 'متوسطة' in str(val): return 'color: #f59e0b; font-weight: bold;'
            else: return 'color: #10b981; font-weight: bold;'
            
        st.dataframe(table_df.style.format({
            col_cnt: '{:,.0f}', col_clv: '{:,.0f}', col_risk: '{:.1f}%'
        }).map(highlight_priority, subset=[col_pri]), use_container_width=True, hide_index=True)