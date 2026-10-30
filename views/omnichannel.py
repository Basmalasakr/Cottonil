import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os
import sys

# إعداد الصفحة
try:
    st.set_page_config(layout="wide", page_title="Omnichannel & Digital Analytics")
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

# --- i18n Dictionary ---
LANGUAGES = {
    "ar": {
        "page_title": "تحليلات القنوات المتعددة",
        "page_desc": "توحيد أداء المتاجر، التجارة الإلكترونية، التطبيق، ومنصات التواصل في شاشة واحدة.",
        "select_year": "اختر السنة",
        "no_data": "لا توجد بيانات مبيعات للسنة المحددة.",
        "m_online_sales": "المبيعات الرقمية",
        "m_conv_rate": "معدل التحويل",
        "m_users": "عملاء الأونلاين",
        "m_orders": "إجمالي الطلبات",
        "m_aov": "متوسط الطلب",
        "c_trend_sales": "نمو المبيعات الرقمية",
        "c_mix": "مساهمة القنوات",
        "c_top_channels": "أداء القنوات التفصيلي",
        "c_aov_trend": "تطور متوسط قيمة الطلب",
        "c_orders_trend": "حجم الطلبات الشهري",
        "col_channel": "القناة",
        "col_sales": "المبيعات",
        "col_orders": "الطلبات",
        "col_yoy": "النمو السنوي",
        "vs_ly": "عن العام الماضي",
        "settings": "إعدادات النظام",
        "language": "اللغة",
        "err_load": "خطأ في تحميل البيانات:"
    },
    "en": {
        "page_title": "Omnichannel Commerce Analytics",
        "page_desc": "Unify store, e-commerce, app, and social commerce performance in one connected view.",
        "select_year": "Select Year",
        "no_data": "No sales data found for the selected year.",
        "m_online_sales": "Online Sales",
        "m_conv_rate": "Conversion Rate",
        "m_users": "Online Users",
        "m_orders": "Total Orders",
        "m_aov": "Average Order Value",
        "c_trend_sales": "Online Sales Trend",
        "c_mix": "Channel Contribution",
        "c_top_channels": "Top Performing Channels",
        "c_aov_trend": "AOV Trend",
        "c_orders_trend": "Monthly Orders Trend",
        "col_channel": "Channel",
        "col_sales": "Sales",
        "col_orders": "Orders",
        "col_yoy": "YoY Growth",
        "vs_ly": "vs LY",
        "settings": "System Settings",
        "language": "Language",
        "err_load": "Error loading data:"
    }
}

if 'lang' not in st.session_state:
    st.session_state.lang = 'ar'

T = LANGUAGES[st.session_state.lang]

# --- Sidebar Language Setup ---
st.sidebar.markdown(f"<h3 style='color:#1e3a8a;'>{T['settings']}</h3>", unsafe_allow_html=True)
selected_lang = st.sidebar.radio(T['language'], ['عربي', 'English'], index=0 if st.session_state.lang == 'ar' else 1)
new_lang = 'ar' if selected_lang == 'عربي' else 'en'
if new_lang != st.session_state.lang:
    st.session_state.lang = new_lang
    st.rerun()

# تحديث القاموس بعد تغيير اللغة
T = LANGUAGES[st.session_state.lang]

# --- Formatting ---
def format_number(num, is_currency=False, is_percent=False):
    if pd.isna(num): return "0"
    if is_percent: return f"{num:.2f}%"
    prefix = "ج.م " if is_currency and st.session_state.lang == 'ar' else ("EGP " if is_currency else "")
    if num >= 1e9: return f"{prefix}{num / 1e9:.2f}B"
    elif num >= 1e6: return f"{prefix}{num / 1e6:.2f}M"
    elif num >= 1e3: return f"{prefix}{num / 1e3:.1f}K"
    else: return f"{prefix}{num:,.0f}"

def format_yoy(val):
    if pd.isna(val) or val == 0: return ""
    color = "#10b981" if val > 0 else "#ef4444"
    arrow = "▲" if val > 0 else "▼"
    return f"<span style='color:{color}; font-size: 13px; font-weight: bold;'>{arrow} {abs(val):.1f}% {T['vs_ly']}</span>"

# --- CSS Styling (نفس تصميم صفحة التسويق الهادئ تماماً) ---
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
    </style>
""", unsafe_allow_html=True)

# --- Data Loading ---
@st.cache_data(show_spinner=False)
def load_omnichannel_data():
    try:
        data_dir = resolve_data_dir()
        path_orders = os.path.join(data_dir, 'sales_orders.parquet')
        path_marketing = os.path.join(data_dir, 'marketing_campaigns.parquet')
        
        if not os.path.exists(path_orders): return None, None, f"Missing file: {path_orders}"
        if not os.path.exists(path_marketing): return None, None, f"Missing file: {path_marketing}"
        
        df_orders = pd.read_parquet(path_orders)
        df_marketing = pd.read_parquet(path_marketing)
        
        df_orders['order_date'] = pd.to_datetime(df_orders['order_date'], errors='coerce')
        df_orders['Year'] = df_orders['order_date'].dt.year
        df_orders['Month_Num'] = df_orders['order_date'].dt.month
        df_orders['Month'] = df_orders['order_date'].dt.strftime('%b')
        
        offline_channels = ['In-store', 'Retail Stores', 'POS', 'Wholesale']
        df_orders['Channel_Type'] = df_orders['sales_channel'].apply(lambda x: 'Offline' if any(off in str(x) for off in offline_channels) else 'Online')
        
        return df_orders, df_marketing, None
    except Exception as e:
        return None, None, str(e)

df_orders, df_marketing, err = load_omnichannel_data()

if err:
    st.error(f"{T['err_load']} {err}")
    st.stop()

# --- Header & Filters ---
st.markdown(f"<h2 style='color:#1e3a8a; margin-bottom: 5px; font-weight: bold;'>{T['page_title']}</h2>", unsafe_allow_html=True)
st.markdown(f"<p style='margin-bottom:20px; color:#64748b;'>{T['page_desc']}</p>", unsafe_allow_html=True)

available_years = sorted(df_orders['Year'].dropna().unique().tolist(), reverse=True)
c1, c2, c3 = st.columns([1, 1, 3])

if st.session_state.lang == 'ar':
    selected_year = c3.selectbox(T['select_year'], available_years, index=0)
else:
    selected_year = c1.selectbox(T['select_year'], available_years, index=0)

compare_year = selected_year - 1

df_cy = df_orders[df_orders['Year'] == selected_year]
df_ly = df_orders[df_orders['Year'] == compare_year]

if df_cy.empty:
    st.warning(T['no_data'])
    st.stop()

# --- Calculations ---
online_sales_cy = df_cy[df_cy['Channel_Type'] == 'Online']['paid_total_EGP'].sum()
online_sales_ly = df_ly[df_ly['Channel_Type'] == 'Online']['paid_total_EGP'].sum()
online_yoy = ((online_sales_cy - online_sales_ly) / online_sales_ly * 100) if online_sales_ly > 0 else 0

orders_cy = df_cy['sales_order_id'].nunique()
orders_ly = df_ly['sales_order_id'].nunique()
orders_yoy = ((orders_cy - orders_ly) / orders_ly * 100) if orders_ly > 0 else 0

users_cy = df_cy[df_cy['Channel_Type'] == 'Online']['customer_id'].nunique()
users_ly = df_ly[df_ly['Channel_Type'] == 'Online']['customer_id'].nunique()
users_yoy = ((users_cy - users_ly) / users_ly * 100) if users_ly > 0 else 0

aov_cy = (df_cy['paid_total_EGP'].sum() / orders_cy) if orders_cy > 0 else 0
aov_ly = (df_ly['paid_total_EGP'].sum() / orders_ly) if orders_ly > 0 else 0
aov_yoy = ((aov_cy - aov_ly) / aov_ly * 100) if aov_ly > 0 else 0

clicks_cy = df_marketing[pd.to_datetime(df_marketing['start_date']).dt.year == selected_year]['clicks'].sum()
clicks_ly = df_marketing[pd.to_datetime(df_marketing['start_date']).dt.year == compare_year]['clicks'].sum()
conv_cy = (orders_cy / clicks_cy * 100) if clicks_cy > 0 else 0
conv_ly = (orders_ly / clicks_ly * 100) if clicks_ly > 0 else 0
conv_yoy = ((conv_cy - conv_ly) / conv_ly * 100) if conv_ly > 0 else 0

# --- Top KPIs Row ---
k1, k2, k3, k4, k5 = st.columns(5)

cards = [
    (T['m_online_sales'], format_number(online_sales_cy, is_currency=True), online_yoy),
    (T['m_conv_rate'], format_number(conv_cy, is_percent=True), conv_yoy),
    (T['m_users'], format_number(users_cy), users_yoy),
    (T['m_orders'], format_number(orders_cy), orders_yoy),
    (T['m_aov'], format_number(aov_cy, is_currency=True), aov_yoy)
]

if st.session_state.lang == 'ar':
    cards = cards[::-1]

for col, card in zip([k1, k2, k3, k4, k5], cards):
    col.markdown(f"""<div class='kpi-card'>
        <div class='kpi-label'>{card[0]}</div>
        <div class='kpi-value'>{card[1]}</div>
        <div>{format_yoy(card[2])}</div></div>""", unsafe_allow_html=True)

st.write("") 

# --- Charts Row 1 ---
r1c1, r1c2, r1c3 = st.columns([1.5, 1, 1.5])

if st.session_state.lang == 'ar':
    col_trend, col_mix, col_table = r1c3, r1c2, r1c1
else:
    col_trend, col_mix, col_table = r1c1, r1c2, r1c3

with col_trend:
    with st.container(border=True):
        st.markdown(f"<h5 style='color:#1e3a8a; text-align:center;'>{T['c_trend_sales']}</h5><br>", unsafe_allow_html=True)
        trend_df = df_cy[df_cy['Channel_Type'] == 'Online'].groupby('Month_Num').agg(Sales=('paid_total_EGP', 'sum')).reset_index()
        months = {1:'Jan', 2:'Feb', 3:'Mar', 4:'Apr', 5:'May', 6:'Jun', 7:'Jul', 8:'Aug', 9:'Sep', 10:'Oct', 11:'Nov', 12:'Dec'}
        trend_df['Month'] = trend_df['Month_Num'].map(months)
        
        fig1 = px.line(trend_df, x='Month', y='Sales', markers=True)
        fig1.update_traces(line_color='#1e3a8a', line_width=3, marker=dict(size=8, color='#1e3a8a'))
        fig1.update_layout(xaxis_title="", yaxis_title="", margin=dict(l=0, r=0, t=10, b=0), plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
        fig1.update_xaxes(showgrid=False)
        fig1.update_yaxes(showgrid=True, gridcolor='#f1f5f9')
        st.plotly_chart(fig1, use_container_width=True)

with col_mix:
    with st.container(border=True):
        st.markdown(f"<h5 style='color:#1e3a8a; text-align:center;'>{T['c_mix']}</h5><br>", unsafe_allow_html=True)
        mix_df = df_cy.groupby('sales_channel')['paid_total_EGP'].sum().reset_index()
        mix_df = mix_df.sort_values('paid_total_EGP', ascending=False)
        
        fig2 = px.pie(mix_df, names='sales_channel', values='paid_total_EGP', hole=0.6,
                      color_discrete_sequence=['#1e3a8a', '#2563eb', '#60a5fa', '#93c5fd', '#cbd5e1'])
        fig2.update_traces(textinfo='percent', textposition='inside')
        fig2.update_layout(showlegend=False, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig2, use_container_width=True)

with col_table:
    with st.container(border=True):
        st.markdown(f"<h5 style='color:#1e3a8a; text-align:center;'>{T['c_top_channels']}</h5><br>", unsafe_allow_html=True)
        chan_cy = df_cy.groupby('sales_channel').agg(Sales_CY=('paid_total_EGP', 'sum'), Orders_CY=('sales_order_id', 'nunique'))
        chan_ly = df_ly.groupby('sales_channel').agg(Sales_LY=('paid_total_EGP', 'sum'), Orders_LY=('sales_order_id', 'nunique'))
        
        table_df = chan_cy.join(chan_ly, how='left').fillna(0)
        table_df['YoY Growth'] = ((table_df['Sales_CY'] - table_df['Sales_LY']) / table_df['Sales_LY'] * 100).fillna(0)
        
        display_df = pd.DataFrame({
            T['col_channel']: table_df.index,
            T['col_sales']: table_df['Sales_CY'].apply(lambda x: format_number(x, is_currency=True)),
            T['col_orders']: table_df['Orders_CY'].apply(lambda x: format_number(x)),
            T['col_yoy']: table_df['YoY Growth'].apply(lambda x: f"+{x:.1f}%" if x > 0 else f"{x:.1f}%")
        }).sort_values(T['col_sales'], ascending=False).head(5)
        
        st.dataframe(display_df, use_container_width=True, hide_index=True)