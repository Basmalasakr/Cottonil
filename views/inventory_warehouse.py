import streamlit as st
import pandas as pd
import plotly.express as px
import os

st.set_page_config(layout="wide", page_title="المخزون والمخازن")

if 'lang' not in st.session_state:
    st.session_state.lang = 'ar'

def tr(text_dict):
    return text_dict.get(st.session_state.lang, text_dict.get('en', ''))

st.markdown("""
    <style>
    .stApp { background-color: #f8fafc; color: #0f172a; }
    .kpi-card {
        background-color: #ffffff; padding: 20px; border-radius: 12px;
        border: 2px solid #cbd5e1; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
        text-align: center; margin-bottom: 15px;
    }
    .kpi-value { font-size: 26px; font-weight: bold; color: #1e3a8a; margin-bottom: 5px; }
    .kpi-warning { color: #dc2626 !important; }
    .kpi-alert { color: #d97706 !important; }
    .kpi-label { font-size: 14px; color: #64748b; font-weight: 600; }
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 12px; border: 2px solid #94a3b8 !important; 
        background-color: #ffffff; padding: 15px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    }
    h1, h2, h3, h4, h5, h6 { color: #0f172a; }
    </style>
""", unsafe_allow_html=True)

@st.cache_data
def load_inventory_data():
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(current_dir, 'data') if os.path.exists(os.path.join(current_dir, 'data')) else os.path.join(os.path.dirname(current_dir), 'data')
        
        stock_cols = ['year_month', 'stock_location_id', 'product_category', 'closing_units', 'closing_stock_value_EGP', 'stockout_risk_score']
        stock = pd.read_parquet(os.path.join(data_dir, 'monthly_stock.parquet'), columns=stock_cols)
        
        wh_cols = ['warehouse_id', 'warehouse_label', 'capacity_units']
        warehouses = pd.read_parquet(os.path.join(data_dir, 'warehouses.parquet'), columns=wh_cols)
        
        catalog = pd.read_parquet(os.path.join(data_dir, 'products_catalog.parquet'))
        
        transfers_cols = ['transfer_id', 'transfer_date', 'transfer_status', 'source_warehouse_id']
        transfers = pd.read_parquet(os.path.join(data_dir, 'inventory_transfers.parquet'), columns=transfers_cols)
        
        sales_items = None
        sales_cols = ['order_date', 'product_id', 'quantity']
        sales_pq_path = os.path.join(data_dir, 'sales_order_items.parquet')
        
        if os.path.exists(sales_pq_path):
            sales_items = pd.read_parquet(sales_pq_path, columns=sales_cols)
            
        if sales_items is not None:
            sales_items['order_date'] = pd.to_datetime(sales_items['order_date'])
            sales_items['quantity'] = pd.to_numeric(sales_items['quantity'], errors='coerce').astype('float32')
            max_date = sales_items['order_date'].max()
            sales_items = sales_items[sales_items['order_date'] >= max_date - pd.Timedelta(days=90)]
            
        stock['closing_units'] = pd.to_numeric(stock['closing_units'], errors='coerce').astype('float32')
        stock['closing_stock_value_EGP'] = pd.to_numeric(stock['closing_stock_value_EGP'], errors='coerce').astype('float32')
        stock['stockout_risk_score'] = pd.to_numeric(stock['stockout_risk_score'], errors='coerce').astype('float32')
        warehouses['capacity_units'] = pd.to_numeric(warehouses['capacity_units'], errors='coerce').astype('float32')
        transfers['transfer_date'] = pd.to_datetime(transfers['transfer_date'])
            
        return stock, warehouses, catalog, sales_items, transfers
    except Exception as e:
        return None, None, None, None, str(e)

stock_df, warehouses_df, catalog_df, sales_items_df, transfers_df = load_inventory_data()

if stock_df is None:
    st.error(tr({'ar': "تعذر تحميل البيانات. تأكد من وجود الملفات.", 'en': "Failed to load data. Ensure files exist."}))
    st.stop()

st.sidebar.markdown(f"<h3 style='color:#1e3a8a;'>{tr({'ar': 'إعدادات النظام', 'en': 'System Settings'})}</h3>", unsafe_allow_html=True)
selected_lang = st.sidebar.radio(
    tr({'ar': "اختر اللغة", 'en': "Select Language"}),
    options=['ar', 'en'],
    index=0 if st.session_state.lang == 'ar' else 1
)
if selected_lang != st.session_state.lang:
    st.session_state.lang = selected_lang
    st.rerun()

st.markdown(f"<h2 style='color:#1e3a8a; margin-bottom: 20px;'>{tr({'ar': 'المخزون والمخازن', 'en': 'Inventory & Warehouses'})}</h2>", unsafe_allow_html=True)

with st.container(border=True):
    st.markdown(f"<strong style='color:#1e3a8a; font-size:18px;'>{tr({'ar': 'أدوات التصفية والتحكم', 'en': 'Filters & Controls'})}</strong>", unsafe_allow_html=True)
    filter_col1, filter_col2, filter_col3 = st.columns([1, 1.5, 1.5])
    
    with filter_col1:
        available_months = sorted(stock_df['year_month'].dropna().unique(), reverse=True)
        selected_month = st.selectbox(tr({'ar': "شهر التقرير:", 'en': "Report Month:"}), available_months)
        
    with filter_col2:
        available_wh = sorted(warehouses_df['warehouse_label'].dropna().unique())
        selected_warehouses = st.multiselect(tr({'ar': "المخازن:", 'en': "Warehouses:"}), available_wh, default=available_wh)
        
    with filter_col3:
        available_cats = sorted(stock_df['product_category'].dropna().unique())
        selected_categories = st.multiselect(tr({'ar': "الفئات:", 'en': "Categories:"}), available_cats, default=available_cats)

current_stock = stock_df[stock_df['year_month'] == selected_month].copy()
f_wh_stock = current_stock.merge(warehouses_df, left_on='stock_location_id', right_on='warehouse_id', how='inner')

if selected_warehouses:
    f_wh_stock = f_wh_stock[f_wh_stock['warehouse_label'].isin(selected_warehouses)]
else:
    f_wh_stock = f_wh_stock.iloc[0:0]

if selected_categories:
    f_wh_stock = f_wh_stock[f_wh_stock['product_category'].isin(selected_categories)]
else:
    f_wh_stock = f_wh_stock.iloc[0:0]

total_units = f_wh_stock['closing_units'].sum()
total_stock_val = f_wh_stock['closing_stock_value_EGP'].sum()

if selected_warehouses:
    selected_capacity = warehouses_df[warehouses_df['warehouse_label'].isin(selected_warehouses)]['capacity_units'].sum()
else:
    selected_capacity = 0
    
utilization = (total_units / selected_capacity * 100) if selected_capacity > 0 else 0

low_stock_threshold = 0.28
overstock_threshold = 0.1
high_qty_threshold = f_wh_stock['closing_units'].quantile(0.85) if not f_wh_stock.empty else 0

low_stock_count = f_wh_stock[f_wh_stock['stockout_risk_score'] >= low_stock_threshold].shape[0]
overstock_count = f_wh_stock[(f_wh_stock['stockout_risk_score'] <= overstock_threshold) & (f_wh_stock['closing_units'] >= high_qty_threshold)].shape[0]

c1, c2, c3, c4 = st.columns(4)
c1.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar": "إجمالي الوحدات بالمخازن", "en": "Total Units"})}</div><div class="kpi-value">{total_units:,.0f}</div></div>', unsafe_allow_html=True)
c2.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar": "نسبة الإشغال (للمخازن المحددة)", "en": "Capacity Utilization"})}</div><div class="kpi-value">{utilization:.1f}%</div></div>', unsafe_allow_html=True)
c3.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar": "تحذير: نقص المخزون", "en": "Low Stock Alerts"})}</div><div class="kpi-value kpi-warning">{low_stock_count} {tr({"ar": "تنبيه", "en": "Alerts"})}</div></div>', unsafe_allow_html=True)
c4.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar": "تنبيه: تكدس المخزون", "en": "Overstock Alerts"})}</div><div class="kpi-value kpi-alert">{overstock_count} {tr({"ar": "تنبيه", "en": "Alerts"})}</div></div>', unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

r1c1, r1c2, r1c3 = st.columns([1.5, 1, 1.5])

with r1c1:
    with st.container(border=True):
        st.markdown(f"<h4 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'توزيع المخزون حسب الفئة', 'en': 'Inventory by Category'})}</h4>", unsafe_allow_html=True)
        if not f_wh_stock.empty:
            cat_dist = f_wh_stock.groupby('product_category')['closing_units'].sum().reset_index()
            cat_dist['percentage'] = (cat_dist['closing_units'] / total_units) * 100 if total_units > 0 else 0
            fig_cat = px.bar(cat_dist.sort_values('percentage', ascending=True), x='percentage', y='product_category', orientation='h', text_auto='.1f', color_discrete_sequence=['#3b82f6'])
            fig_cat.update_layout(margin=dict(l=0, r=0, t=10, b=0), xaxis_title="%", yaxis_title="", height=300)
            st.plotly_chart(fig_cat, use_container_width=True)
        else:
            st.info(tr({'ar': "لا توجد بيانات", 'en': "No data"}))

with r1c2:
    with st.container(border=True):
        st.markdown(f"<h4 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'تقادم المخزون', 'en': 'Stock Aging'})}</h4>", unsafe_allow_html=True)
        if isinstance(transfers_df, pd.DataFrame) and not transfers_df.empty and not f_wh_stock.empty:
            ref_date = pd.to_datetime(selected_month + '-28') 
            completed_transfers = transfers_df[transfers_df['transfer_status'].str.contains('Completed|Received', na=False, case=False)]
            
            selected_wh_ids = warehouses_df[warehouses_df['warehouse_label'].isin(selected_warehouses)]['warehouse_id'].tolist()
            past_transfers = completed_transfers[(completed_transfers['transfer_date'] <= ref_date) & (completed_transfers['source_warehouse_id'].isin(selected_wh_ids))].copy()
            
            past_transfers['days_old'] = (ref_date - past_transfers['transfer_date']).dt.days
            
            bins = [-1, 30, 60, 90, 9999]
            labels_aging = ['0-30 يوم', '31-60 يوم', '61-90 يوم', '+90 يوم'] if st.session_state.lang == 'ar' else ['0-30 Days', '31-60 Days', '61-90 Days', '90+ Days']
            past_transfers['الفترة'] = pd.cut(past_transfers['days_old'], bins=bins, labels=labels_aging)
            
            aging_counts = past_transfers['الفترة'].value_counts().reset_index()
            aging_counts.columns = ['الفترة', 'العدد']
            
            if aging_counts['العدد'].sum() > 0:
                fig_aging = px.pie(aging_counts, values='العدد', names='الفترة', hole=0.6, color_discrete_sequence=['#0ea5e9', '#38bdf8', '#7dd3fc', '#bae6fd'])
                fig_aging.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=300, showlegend=True, legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5))
                st.plotly_chart(fig_aging, use_container_width=True)
            else:
                st.info(tr({'ar': "لا توجد بيانات استلام كافية", 'en': "Not enough receiving data"}))
        else:
            st.info(tr({'ar': "لا توجد بيانات استلام كافية", 'en': "Not enough receiving data"}))

with r1c3:
    with st.container(border=True):
        st.markdown(f"<h4 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'أحدث التنبيهات', 'en': 'Recent Alerts'})}</h4>", unsafe_allow_html=True)
        alerts_list = []
        if not f_wh_stock.empty:
            low_stock_data = f_wh_stock[f_wh_stock['stockout_risk_score'] >= low_stock_threshold].sort_values('stockout_risk_score', ascending=False).head(3)
            for _, row in low_stock_data.iterrows():
                alerts_list.append({
                    tr({'ar': "الحالة", 'en': "Status"}): " Low Stock",
                    tr({'ar': "الفئة والمخزن", 'en': "Category & Location"}): f"{row['product_category']} ({row['warehouse_label']})",
                    tr({'ar': "المتبقي", 'en': "Qty Left"}): f"{row['closing_units']:,.0f}"
                })
                
            overstock_data = f_wh_stock[(f_wh_stock['stockout_risk_score'] <= overstock_threshold) & (f_wh_stock['closing_units'] >= high_qty_threshold)].sort_values('closing_units', ascending=False).head(2)
            for _, row in overstock_data.iterrows():
                alerts_list.append({
                    tr({'ar': "الحالة", 'en': "Status"}): " Overstock",
                    tr({'ar': "الفئة والمخزن", 'en': "Category & Location"}): f"{row['product_category']} ({row['warehouse_label']})",
                    tr({'ar': "المتبقي", 'en': "Qty Left"}): f"{row['closing_units']:,.0f}"
                })
                
        alerts_df = pd.DataFrame(alerts_list)
        if not alerts_df.empty:
            st.dataframe(alerts_df, hide_index=True, use_container_width=True, height=270)
        else:
            st.info(tr({'ar': "لا توجد تنبيهات حالية", 'en': "No recent alerts"}))

r2c1, r2c2 = st.columns(2)
with r2c1:
    with st.container(border=True):
        st.markdown(f"<h4 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'توزيع المخزون على مستوى الفئة والمخزن', 'en': 'Warehouse Capacity by Category'})}</h4>", unsafe_allow_html=True)
        if not f_wh_stock.empty:
            fig_bar = px.bar(f_wh_stock, x='warehouse_label', y='closing_units', color='product_category', barmode='stack', color_discrete_sequence=px.colors.qualitative.Pastel)
            fig_bar.update_layout(margin=dict(l=0, r=0, t=10, b=0), xaxis_title="", yaxis_title="", xaxis_tickangle=-45)
            st.plotly_chart(fig_bar, use_container_width=True)
        else:
            st.info(tr({'ar': "لا توجد بيانات", 'en': "No data"}))

with r2c2:
    with st.container(border=True):
        st.markdown(f"<h4 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'مؤشر مخاطر نفاد المخزون حسب الفئة', 'en': 'Stockout Risk Score by Category'})}</h4>", unsafe_allow_html=True)
        if not f_wh_stock.empty:
            risk_df = f_wh_stock.groupby('product_category')['stockout_risk_score'].mean().reset_index()
            fig_risk = px.bar(risk_df, x='product_category', y='stockout_risk_score', text_auto='.2f', color='stockout_risk_score', color_continuous_scale='Reds')
            fig_risk.update_layout(margin=dict(l=0, r=0, t=10, b=0), xaxis_title="", yaxis_title="", xaxis_tickangle=-45)
            st.plotly_chart(fig_risk, use_container_width=True)
        else:
            st.info(tr({'ar': "لا توجد بيانات", 'en': "No data"}))

if sales_items_df is not None and not sales_items_df.empty and not f_wh_stock.empty:
    with st.container(border=True):
        st.markdown(f"<h4 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'تغطية المخزون (بالشهور)', 'en': 'Inventory Coverage (Months)'})}</h4>", unsafe_allow_html=True)
        recent_sales = sales_items_df.merge(catalog_df, on='product_id', how='left')
        
        if selected_categories:
            recent_sales = recent_sales[recent_sales['category_en'].isin(selected_categories)]
            
        sales_cat = recent_sales.groupby('category_en')['quantity'].sum().reset_index()
        sales_cat.columns = ['product_category', 'sold_90_days']
        sales_cat['monthly_avg_sales'] = (sales_cat['sold_90_days'] / 3).replace(0, 1) 
        
        stock_cat = f_wh_stock.groupby('product_category')['closing_units'].sum().reset_index()
        cov_df = stock_cat.merge(sales_cat, on='product_category', how='inner')
        cov_df['coverage_months'] = cov_df['closing_units'] / cov_df['monthly_avg_sales']
        
        if not cov_df.empty:
            fig_cov = px.bar(cov_df.sort_values('coverage_months'), x='coverage_months', y='product_category', orientation='h', text_auto='.1f', color_discrete_sequence=['#10b981'])
            fig_cov.update_layout(margin=dict(l=0, r=0, t=10, b=0), xaxis_title=tr({'ar': 'أشهر التغطية', 'en': 'Months'}), yaxis_title="")
            st.plotly_chart(fig_cov, use_container_width=True)
        else:
            st.info(tr({'ar': "لا توجد بيانات مبيعات متطابقة", 'en': "No matching sales data"}))

st.markdown("<br>", unsafe_allow_html=True)
with st.container(border=True):
    st.markdown(f"<h4 style='color:#1e3a8a;'>{tr({'ar': 'تفاصيل المخزون والمنتجات', 'en': 'Inventory & Products Details'})}</h4>", unsafe_allow_html=True)
    tab_stock, tab_catalog = st.tabs([tr({'ar': "أرصدة الفئات بالمخازن", 'en': "Category Stock by Warehouse"}), tr({'ar': "دليل المنتجات الشامل", 'en': "Products Catalog"})])
    
    with tab_stock:
        if not f_wh_stock.empty:
            display_stock = f_wh_stock[['warehouse_label', 'product_category', 'closing_units', 'closing_stock_value_EGP', 'stockout_risk_score']].copy()
            if st.session_state.lang == 'ar':
                display_stock.columns = ['المخزن', 'الفئة', 'الوحدات المتبقية', 'قيمة المخزون', 'مؤشر الخطر']
            st.dataframe(display_stock, use_container_width=True, hide_index=True)
        else:
            st.info(tr({'ar': "لا توجد بيانات", 'en': "No data"}))
            
    with tab_catalog:
        display_catalog = catalog_df.copy()
        if selected_categories:
            display_catalog = display_catalog[display_catalog['category_en'].isin(selected_categories)]
        if st.session_state.lang == 'ar':
            display_catalog.columns = ['كود المنتج', 'اسم المنتج', 'الفئة', 'الجمهور', 'السعر', 'الرابط'] if len(display_catalog.columns) == 6 else display_catalog.columns
        st.dataframe(display_catalog, use_container_width=True, hide_index=True)