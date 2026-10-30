import streamlit as st
import pandas as pd
import plotly.express as px
import os
import datetime
import traceback

st.set_page_config(layout="wide", page_title="Wholesale & Distributor Performance")

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
    .kpi-value { font-size: 26px; font-weight: bold; color: #1e3a8a; margin-bottom: 5px; }
    .kpi-label { font-size: 13px; color: #64748b; font-weight: 600; text-transform: uppercase; }
    
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 12px; border: 2px solid #94a3b8 !important; 
        background-color: #ffffff; padding: 15px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    }
    </style>
""", unsafe_allow_html=True)

@st.cache_data
def load_wholesale_data():
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(current_dir, 'data') if os.path.exists(os.path.join(current_dir, 'data')) else os.path.join(os.path.dirname(current_dir), 'data')
        
        df_orders = pd.read_parquet(os.path.join(data_dir, 'sales_orders.parquet'), 
                                    columns=['sales_order_id', 'order_date', 'customer_id', 'sales_channel', 'items_count', 'gross_EGP', 'discount_EGP', 'net_before_tax_EGP', 'status'])
        
        df_partners = pd.read_parquet(os.path.join(data_dir, 'import_partners.parquet'), 
                                      columns=['import_partner_id', 'partner_name', 'country', 'goods_category', 'shipping_terms'])
        
        df_orders['order_date'] = pd.to_datetime(df_orders['order_date'], errors='coerce')
        df_orders.dropna(subset=['order_date'], inplace=True)
        
        return df_orders, df_partners
    except Exception as e:
        return None, traceback.format_exc()

df_orders, df_partners = load_wholesale_data()

if df_orders is None:
    st.error(f"حدث خطأ أثناء تحميل البيانات:\n\n{df_partners}")
    st.stop()

st.sidebar.markdown(f"<h3>{tr({'ar': 'إعدادات النظام', 'en': 'System Settings'})}</h3>", unsafe_allow_html=True)
selected_lang = st.sidebar.radio(tr({'ar': "اللغة", 'en': "Language"}), ['ar', 'en'], index=0 if st.session_state.lang == 'ar' else 1)
if selected_lang != st.session_state.lang:
    st.session_state.lang = selected_lang
    st.rerun()

st.markdown(f"<h2 style='color:#1e3a8a; margin-bottom: 20px;'>{tr({'ar': 'مبيعات الجملة وأداء الموزعين', 'en': 'Wholesale & Distributor Performance'})}</h2>", unsafe_allow_html=True)

min_date, max_date = df_orders['order_date'].min().date(), df_orders['order_date'].max().date()

with st.container(border=True):
    c1, c2 = st.columns(2)
    start_date = c1.date_input(tr({'ar': "من تاريخ", 'en': "Start Date"}), min_date)
    end_date = c2.date_input(tr({'ar': "إلى تاريخ", 'en': "End Date"}), max_date)

mask = (df_orders['order_date'].dt.date >= start_date) & (df_orders['order_date'].dt.date <= end_date)
df_filtered = df_orders[mask]

# قصر التحليل على الجملة فقط
df_filtered = df_filtered[df_filtered['sales_channel'].str.lower().str.contains('wholesale', na=False)]

total_wholesale_sales = df_filtered['net_before_tax_EGP'].sum()
total_discounts = df_filtered['discount_EGP'].sum()
total_orders_count = df_filtered['sales_order_id'].nunique()
avg_deal_value = total_wholesale_sales / total_orders_count if total_orders_count > 0 else 0
avg_discount_pct = (total_discounts / df_filtered['gross_EGP'].sum() * 100) if df_filtered['gross_EGP'].sum() > 0 else 0

trend_df = df_filtered.groupby(df_filtered['order_date'].dt.to_period('M')).agg(
    Sales=('net_before_tax_EGP', 'sum')
).reset_index()
trend_df['order_date'] = trend_df['order_date'].dt.to_timestamp()

# عرض المؤشرات (KPIs)
k1, k2, k3, k4 = st.columns(4)
k1.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"إجمالي مبيعات الجملة", "en":"Total Wholesale Sales"})}</div><div class="kpi-value">EGP {total_wholesale_sales:,.0f}</div></div>', unsafe_allow_html=True)
k2.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"عدد صفقات الجملة", "en":"Total Wholesale Deals"})}</div><div class="kpi-value">{total_orders_count:,}</div></div>', unsafe_allow_html=True)
k3.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"متوسط قيمة الصفقة", "en":"Avg Deal Value"})}</div><div class="kpi-value">EGP {avg_deal_value:,.0f}</div></div>', unsafe_allow_html=True)
k4.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"متوسط نسبة الخصم", "en":"Avg Discount %"})}</div><div class="kpi-value">{avg_discount_pct:.1f}%</div></div>', unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# عرض الجداول
r1c1, r1c2 = st.columns(2)

with r1c1:
    st.markdown(f"<h5 style='color:#1e3a8a;'>{tr({'ar': 'شبكة شركاء الاستيراد والتوزيع', 'en': 'Import & Distribution Partners'})}</h5>", unsafe_allow_html=True)
    st.dataframe(df_partners[['partner_name', 'country', 'goods_category', 'shipping_terms']].rename(columns={
        'partner_name': 'Partner', 'country': 'Country', 'goods_category': 'Category', 'shipping_terms': 'Terms'
    }), use_container_width=True, hide_index=True)

with r1c2:
    st.markdown(f"<h5 style='color:#1e3a8a;'>{tr({'ar': 'توزيع الشركاء حسب الدول', 'en': 'Partners by Country'})}</h5>", unsafe_allow_html=True)
    country_counts = df_partners['country'].value_counts().reset_index()
    country_counts.columns = ['Country', 'Count']
    fig_country = px.bar(country_counts, x='Country', y='Count', color_discrete_sequence=['#f59e0b'])
    fig_country.update_layout(xaxis_title="", yaxis_title="Partners Count", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    st.plotly_chart(fig_country, use_container_width=True)

st.markdown("<br>", unsafe_allow_html=True)

# عرض الرسم البياني للاتجاه
with st.container(border=True):
    st.markdown(f"<h5 style='color:#1e3a8a;'>{tr({'ar': 'اتجاه مبيعات الجملة خلال الفترة', 'en': 'Wholesale Sales Trend'})}</h5>", unsafe_allow_html=True)
    fig_trend = px.line(trend_df, x='order_date', y='Sales', markers=True)
    fig_trend.update_layout(xaxis_title="", yaxis_title="Sales (EGP)", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    fig_trend.update_traces(line_color='#3b82f6')
    st.plotly_chart(fig_trend, use_container_width=True)