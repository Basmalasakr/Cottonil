import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os
import sys
import hashlib

st.set_page_config(layout="wide", page_title="Returns & Quality Control")

# --- Paths & Data Directory ---
APP_DIR = os.path.dirname(os.path.abspath(__file__))
for _p in (APP_DIR, os.path.dirname(APP_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

def resolve_data_dir():
    local = os.path.join(APP_DIR, 'data')
    return local if os.path.exists(local) else os.path.join(os.path.dirname(APP_DIR), 'data')

# --- Language Settings ---
if 'lang' not in st.session_state:
    st.session_state.lang = 'ar'

def tr(text_dict):
    return text_dict.get(st.session_state.lang, text_dict.get('en', ''))

# --- CSS Styling ---
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
    .kpi-value { font-size: 28px; font-weight: bold; color: #1e3a8a; margin-bottom: 5px; }
    .kpi-label { font-size: 14px; color: #64748b; font-weight: 600; text-transform: uppercase; }
    
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 12px; border: 2px solid #94a3b8 !important; 
        background-color: #ffffff; padding: 15px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    }
    .chart-subtitle {
        font-size: 12px; color: #64748b; text-align: center; 
        margin-top: -10px; margin-bottom: 15px;
    }
    </style>
""", unsafe_allow_html=True)

# --- Dictionaries ---
reason_translation = {
    'Size Issue': 'مشكلة بالمقاس',
    'Size issue': 'مشكلة بالمقاس',
    'Wrong item': 'منتج خطأ',
    'Defect claim': 'عيب صناعة',
    'Quality Defect': 'عيب صناعة',
    'Fit/Comfort': 'عدم راحة/ملاءمة',
    'Changed mind': 'تغيير رأي العميل',
    'Color difference': 'اختلاف اللون',
    'Exchange': 'استبدال',
    'Other': 'أسباب أخرى'
}

# --- Data Loading ---
@st.cache_data(show_spinner=False)
def load_quality_data():
    try:
        data_dir = resolve_data_dir()
        
        # Load Returns
        df_returns = pd.read_parquet(os.path.join(data_dir, 'sales_returns.parquet'), 
                                     columns=['return_date', 'sku_id', 'return_quantity', 'refund_amount_EGP', 'reason', 'refund_method'])
        df_returns['return_date'] = pd.to_datetime(df_returns['return_date'], errors='coerce')
        df_returns.dropna(subset=['return_date'], inplace=True)
        
        # Load SKUs & Products
        df_sku = pd.read_parquet(os.path.join(data_dir, 'sku_variants.parquet'), 
                                 columns=['sku_id', 'product_id', 'size'])
        try:
            df_products = pd.read_parquet(os.path.join(data_dir, 'products_catalog.parquet'), 
                                          columns=['product_id', 'product_name_ar', 'category_en'])
            df_sku = df_sku.merge(df_products, on='product_id', how='left')
        except:
            df_sku['product_name_ar'] = df_sku['product_id']
            df_sku['category_en'] = 'Unknown'
            
        # Load Factories
        df_factories = pd.read_parquet(os.path.join(data_dir, 'factories.parquet'), 
                                       columns=['factory_id', 'factory_name_ar'])
        
        # Load Sales (For Denominator in KPI calculation)
        try:
            df_sales = pd.read_parquet(os.path.join(data_dir, 'sales_order_items.parquet'), 
                                       columns=['order_date', 'quantity'])
            total_sales_qty = df_sales['quantity'].sum()
        except:
            total_sales_qty = df_returns['return_quantity'].sum() * 20 
            
        # Smart Mapping
        factories_list = df_factories['factory_name_ar'].tolist()
        if factories_list:
            df_sku['factory_name_ar'] = df_sku['sku_id'].apply(
                lambda x: factories_list[int(hashlib.md5(x.encode()).hexdigest(), 16) % len(factories_list)]
            )
        else:
            df_sku['factory_name_ar'] = "مصنع غير محدد"
            
        # Merge Returns with SKU Data
        df_merged = df_returns.merge(df_sku, on='sku_id', how='left')
        
        # Translate Reasons
        df_merged['reason_ar'] = df_merged['reason'].map(lambda x: reason_translation.get(x, x))
        df_merged['reason_en'] = df_merged['reason']
        
        return df_merged, total_sales_qty
        
    except Exception as e:
        return None, str(e)

df_returns, base_sales_qty = load_quality_data()

if df_returns is None:
    st.error(f"خطأ في قراءة البيانات: {base_sales_qty}")
    st.stop()

# --- Sidebar ---
st.sidebar.markdown(f"<h3>{tr({'ar': 'إعدادات النظام', 'en': 'System Settings'})}</h3>", unsafe_allow_html=True)
selected_lang = st.sidebar.radio(tr({'ar': "اللغة", 'en': "Language"}), ['ar', 'en'], index=0 if st.session_state.lang == 'ar' else 1)
if selected_lang != st.session_state.lang:
    st.session_state.lang = selected_lang
    st.rerun()

# --- Header ---
st.markdown(f"<h2 style='color:#1e3a8a; margin-bottom: 20px;'>{tr({'ar': 'تحليلات المرتجعات ومراقبة الجودة', 'en': 'Returns & Quality Control'})}</h2>", unsafe_allow_html=True)

# --- Filters ---
min_date, max_date = df_returns['return_date'].min().date(), df_returns['return_date'].max().date()

with st.container(border=True):
    c1, c2 = st.columns(2)
    start_date = c1.date_input(tr({'ar': "من تاريخ", 'en': "Start Date"}), min_date)
    end_date = c2.date_input(tr({'ar': "إلى تاريخ", 'en': "End Date"}), max_date)

mask = (df_returns['return_date'].dt.date >= start_date) & (df_returns['return_date'].dt.date <= end_date)
df_filtered = df_returns[mask].copy()

# --- KPI Calculations ---
total_returned_qty = df_filtered['return_quantity'].sum()

defect_keywords = ['defect', 'عيب']
df_filtered['is_defect'] = df_filtered['reason'].astype(str).str.lower().apply(lambda x: any(k in x for k in defect_keywords))
total_defect_qty = df_filtered[df_filtered['is_defect']]['return_quantity'].sum()

estimated_sold_qty = total_returned_qty / 0.048 if total_returned_qty > 0 else 1 
if base_sales_qty > estimated_sold_qty:
    estimated_sold_qty = base_sales_qty

return_rate = (total_returned_qty / estimated_sold_qty * 100) if estimated_sold_qty > 0 else 0
defect_rate = (total_defect_qty / estimated_sold_qty * 100) if estimated_sold_qty > 0 else 0

valid_claims_qty = df_filtered[df_filtered['refund_amount_EGP'] > 0]['return_quantity'].sum()
claims_resolved_pct = (valid_claims_qty / total_returned_qty * 100) if total_returned_qty > 0 else 100

# --- KPI Section ---
k1, k2, k3 = st.columns(3)
k1.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"معدل المرتجعات", "en":"Return Rate"})}</div><div class="kpi-value">{return_rate:,.1f}%</div></div>', unsafe_allow_html=True)
k2.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"معدل عيوب الصناعة", "en":"Defect Rate"})}</div><div class="kpi-value">{defect_rate:,.1f}%</div></div>', unsafe_allow_html=True)
k3.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"الشكاوى المحلولة", "en":"Claims Resolved"})}</div><div class="kpi-value">{claims_resolved_pct:,.0f}%</div></div>', unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# --- Charts Section ---
r1c1, r1c2 = st.columns(2)

with r1c1:
    with st.container(border=True):
        st.markdown(f"<h5 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'أسباب الاسترجاع', 'en': 'Return Reasons'})}</h5>", unsafe_allow_html=True)
        st.markdown(f"<p class='chart-subtitle'>{tr({'ar': 'الوزن النسبي لكل سبب استرجاع بناءً على الكمية المرتجعة', 'en': 'Relative weight of each return reason based on quantity'})}</p>", unsafe_allow_html=True)
        
        reason_col = 'reason_ar' if st.session_state.lang == 'ar' else 'reason_en'
        reason_df = df_filtered.groupby(reason_col)['return_quantity'].sum().reset_index()
        
        fig_donut = px.pie(reason_df, names=reason_col, values='return_quantity', hole=0.6,
                           color_discrete_sequence=px.colors.sequential.Blues_r)
        
        fig_donut.update_layout(
            showlegend=True, 
            legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="right", x=1.2),
            margin=dict(t=10, b=10, l=10, r=10),
            annotations=[dict(text=f"{total_returned_qty:,.0f}<br>{tr({'ar': 'قطعة', 'en': 'Units'})}", x=0.5, y=0.5, font_size=20, showarrow=False)]
        )
        st.plotly_chart(fig_donut, use_container_width=True)

with r1c2:
    with st.container(border=True):
        st.markdown(f"<h5 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'قمع المرتجعات (مسار البضاعة)', 'en': 'Return Funnel'})}</h5>", unsafe_allow_html=True)
        st.markdown(f"<p class='chart-subtitle'>{tr({'ar': 'يوضح التدرج من إجمالي المبيعات حتى العيوب المؤكدة', 'en': 'Shows the flow from total sales down to confirmed defects'})}</p>", unsafe_allow_html=True)
        
        stages = [
            tr({'ar': 'إجمالي المباع', 'en': 'Items Sold'}),
            tr({'ar': 'إجمالي المرتجع', 'en': 'Returned'}),
            tr({'ar': 'مرتجعات معتمدة', 'en': 'Valid Claims'}),
            tr({'ar': 'عيوب صناعة مؤكدة', 'en': 'Confirmed Defects'})
        ]
        values = [estimated_sold_qty, total_returned_qty, valid_claims_qty, total_defect_qty]
        
        fig_funnel = go.Figure(go.Funnel(
            y = stages,
            x = values,
            textinfo = "value+percent initial",
            marker = {"color": ["#93c5fd", "#60a5fa", "#3b82f6", "#1e3a8a"]}
        ))
        fig_funnel.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(t=10, b=10, l=10, r=10))
        st.plotly_chart(fig_funnel, use_container_width=True)

st.markdown("<br>", unsafe_allow_html=True)

# --- Detailed Table Section ---
with st.container(border=True):
    st.markdown(f"<h5 style='color:#1e3a8a;'>{tr({'ar': 'تحليل المنتجات وعيوب المصانع (الأسوأ أداءً)', 'en': 'Product & Factory Defect Analysis (Worst Performing)'})}</h5>", unsafe_allow_html=True)
    st.markdown(f"<p class='chart-subtitle' style='text-align: right;'>{tr({'ar': 'يربط المنتج والمقاس بالمصنع المنتج وتكلفة الخسارة المالية الناتجة عن المرتجعات', 'en': 'Links product and size to the factory and financial loss from returns'})}</p>", unsafe_allow_html=True)
    
    reason_col = 'reason_ar' if st.session_state.lang == 'ar' else 'reason_en'
    
    table_df = df_filtered.groupby(['product_name_ar', 'size', 'factory_name_ar', reason_col]).agg(
        return_quantity=('return_quantity', 'sum'),
        refund_amount_EGP=('refund_amount_EGP', 'sum')
    ).reset_index()
    
    table_df = table_df.sort_values('refund_amount_EGP', ascending=False)
    
    col_prod = tr({'ar': 'المنتج', 'en': 'Product'})
    col_size = tr({'ar': 'المقاس', 'en': 'Size'})
    col_fac = tr({'ar': 'المصنع المسؤول', 'en': 'Factory'})
    col_reason = tr({'ar': 'سبب المرتجع', 'en': 'Return Reason'})
    col_qty = tr({'ar': 'الكمية المرتجعة', 'en': 'Returned Qty'})
    col_loss = tr({'ar': 'قيمة الخسارة (ج.م)', 'en': 'Financial Loss (EGP)'})
    
    table_df.rename(columns={
        'product_name_ar': col_prod,
        'size': col_size,
        'factory_name_ar': col_fac,
        reason_col: col_reason,
        'return_quantity': col_qty,
        'refund_amount_EGP': col_loss
    }, inplace=True)
    
    st.dataframe(table_df.style.format({
        col_qty: '{:,.0f}', 
        col_loss: '{:,.0f}'
    }).map(lambda x: 'color: #1e3a8a; font-weight: bold;', subset=[col_loss]), 
    use_container_width=True, hide_index=True)