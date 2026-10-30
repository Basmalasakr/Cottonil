import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os
import sys

# إعداد الصفحة
try:
    st.set_page_config(layout="wide", page_title="Marketing ROI & Campaign Performance")
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

# --- Language Setup ---
if 'lang' not in st.session_state:
    st.session_state.lang = 'ar'

def tr(text_dict):
    """دالة إرجاع النص بناءً على اللغة المحددة"""
    return text_dict.get(st.session_state.lang, text_dict.get('en', ''))

def format_number(num, as_currency=False):
    if pd.isna(num): return "0"
    prefix = tr({'ar': "ج.م ", 'en': "EGP "}) if as_currency else ""
    if num >= 1e9: return f"{prefix}{num / 1e9:.1f}B"
    elif num >= 1e6: return f"{prefix}{num / 1e6:.1f}M"
    elif num >= 1e3: return f"{prefix}{num / 1e3:.1f}K"
    else: return f"{prefix}{num:,.0f}"

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
    .chart-subtitle { font-size: 12px; color: #64748b; text-align: center; margin-top: -10px; margin-bottom: 15px; }
    </style>
""", unsafe_allow_html=True)

# --- Data Loading ---
@st.cache_data(show_spinner=False)
def load_marketing_data():
    try:
        data_dir = resolve_data_dir()
        path_marketing = os.path.join(data_dir, 'marketing_campaigns.parquet')
        path_orders = os.path.join(data_dir, 'sales_orders.parquet')
        
        if not os.path.exists(path_marketing): return None, f"Missing file: {path_marketing}"
        
        df_m = pd.read_parquet(path_marketing)
        
        # حساب متوسط قيمة الطلب (AOV) كقيمة افتراضية أو من البيانات الفعلية
        aov = 450.0 
        if os.path.exists(path_orders):
            df_o = pd.read_parquet(path_orders)
            if 'paid_total_EGP' in df_o.columns and len(df_o) > 0:
                aov = df_o['paid_total_EGP'].sum() / len(df_o)
        
        df_final = df_m.copy()
        df_final['Date'] = pd.to_datetime(df_final['start_date'], errors='coerce')
        
        df_final = df_final.rename(columns={
            'campaign_id': 'Campaign',
            'channel': 'Channel',
            'spend_EGP': 'Spend',
            'impressions': 'Impressions',
            'clicks': 'Clicks',
            'orders_attributed': 'Conversions'
        })
        
        df_final['Campaign'] = df_final['Campaign'].apply(lambda x: f"Campaign {x}")
        df_final['Revenue'] = df_final['Conversions'] * aov
        
        return df_final, None
    except Exception as e:
        return None, str(e)

df_marketing, load_error = load_marketing_data()

if df_marketing is None:
    st.error(tr({'ar': f"خطأ في تحميل البيانات. التفاصيل: {load_error}", 'en': f"Error loading data: {load_error}"}))
    st.stop()

df_marketing['Date'] = pd.to_datetime(df_marketing['Date'], errors='coerce')

# --- Sidebar ---
st.sidebar.markdown(f"<h3>{tr({'ar': 'إعدادات النظام', 'en': 'System Settings'})}</h3>", unsafe_allow_html=True)
selected_lang = st.sidebar.radio(tr({'ar': "اللغة", 'en': "Language"}), ['عربي', 'English'], index=0 if st.session_state.lang == 'ar' else 1)

# تحديث لغة النظام عند التغيير
new_lang = 'ar' if selected_lang == 'عربي' else 'en'
if new_lang != st.session_state.lang:
    st.session_state.lang = new_lang
    st.rerun()

# --- التعديل هنا: العنوان يظهر عربي فقط عند اختيار العربية ---
st.markdown(f"<h2 style='color:#1e3a8a; margin-bottom: 20px;'>{tr({'ar': 'عائد الاستثمار التسويقي', 'en': 'Marketing ROI & Campaign Performance'})}</h2>", unsafe_allow_html=True)

# --- Filters ---
min_date, max_date = df_marketing['Date'].min().date(), df_marketing['Date'].max().date()
available_channels = df_marketing['Channel'].dropna().unique().tolist()

with st.container(border=True):
    c1, c2, c3 = st.columns([1, 1, 1])
    start_date = c1.date_input(tr({'ar': "من تاريخ", 'en': "Start Date"}), min_date)
    end_date = c2.date_input(tr({'ar': "إلى تاريخ", 'en': "End Date"}), max_date)
    selected_channels = c3.multiselect(tr({'ar': "تصفية بالقناة الإعلانية", 'en': "Filter by Channel"}), available_channels, default=[])

mask = (df_marketing['Date'].dt.date >= start_date) & (df_marketing['Date'].dt.date <= end_date)
df_filtered = df_marketing[mask].copy()
if selected_channels:
    df_filtered = df_filtered[df_filtered['Channel'].isin(selected_channels)]

if df_filtered.empty:
    st.warning(tr({'ar': "لا توجد بيانات للفترة المحددة.", 'en': "No data for selected period."}))
    st.stop()

# --- Aggregations & Metrics ---
tot_spend = df_filtered['Spend'].sum()
tot_rev = df_filtered['Revenue'].sum()
tot_imp = df_filtered['Impressions'].sum()
tot_clicks = df_filtered['Clicks'].sum()
tot_conv = df_filtered['Conversions'].sum()

# حساب المؤشرات
roas = (tot_rev / tot_spend) if tot_spend > 0 else 0
cpo = (tot_spend / tot_conv) if tot_conv > 0 else 0
ctr = (tot_clicks / tot_imp * 100) if tot_imp > 0 else 0
cvr = (tot_conv / tot_clicks * 100) if tot_clicks > 0 else 0

# --- KPI Row ---
k1, k2, k3, k4, k5 = st.columns(5)
k1.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"عائد الإنفاق (ROAS)", "en":"ROAS"})}</div><div class="kpi-value">{roas:.1f}x</div></div>', unsafe_allow_html=True)
k2.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"تكلفة الطلب (CPO)", "en":"Cost Per Order"})}</div><div class="kpi-value">{format_number(cpo, True)}</div></div>', unsafe_allow_html=True)
k3.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"الظهور (Impressions)", "en":"Impressions"})}</div><div class="kpi-value">{format_number(tot_imp)}</div></div>', unsafe_allow_html=True)
k4.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"معدل النقر (CTR)", "en":"CTR"})}</div><div class="kpi-value">{ctr:.2f}%</div></div>', unsafe_allow_html=True)
k5.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"معدل التحويل (CVR)", "en":"CVR"})}</div><div class="kpi-value">{cvr:.2f}%</div></div>', unsafe_allow_html=True)
st.markdown("<br>", unsafe_allow_html=True)

# --- Charts Row 1 ---
r1c1, r1c2 = st.columns([1, 1])

with r1c1:
    with st.container(border=True):
        st.markdown(f"<h5 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'توزيع المبيعات حسب القناة الإعلانية', 'en': 'Sales Distribution by Channel'})}</h5>", unsafe_allow_html=True)
        st.markdown(f"<p class='chart-subtitle'>{tr({'ar': 'توضيح القنوات الأكثر تأثيراً في تحقيق الإيرادات', 'en': 'Channels driving the most revenue'})}</p>", unsafe_allow_html=True)
        
        chan_df = df_filtered.groupby('Channel')['Revenue'].sum().reset_index()
        if not chan_df.empty:
            fig_pie = px.pie(chan_df, names='Channel', values='Revenue', hole=0.6, color_discrete_sequence=px.colors.sequential.Blues_r)
            fig_pie.update_traces(textinfo='percent+label')
            fig_pie.update_layout(showlegend=False, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig_pie, use_container_width=True)

with r1c2:
    with st.container(border=True):
        st.markdown(f"<h5 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'تطور الإنفاق مقابل المبيعات', 'en': 'Spend vs. Revenue Trend'})}</h5>", unsafe_allow_html=True)
        st.markdown(f"<p class='chart-subtitle'>{tr({'ar': 'مقارنة شهرية بين الصرف الإعلاني والعائد المحقق', 'en': 'Monthly comparison of ad spend vs generated revenue'})}</p>", unsafe_allow_html=True)
        
        trend_df = df_filtered.copy()
        trend_df['Month'] = trend_df['Date'].dt.strftime('%Y-%m')
        trend_grouped = trend_df.groupby('Month')[['Spend', 'Revenue']].sum().reset_index().sort_values('Month')
        
        if not trend_grouped.empty:
            fig_trend = go.Figure()
            fig_trend.add_trace(go.Bar(x=trend_grouped['Month'], y=trend_grouped['Revenue'], name=tr({'ar':'العائد', 'en':'Revenue'}), marker_color='#1e3a8a'))
            fig_trend.add_trace(go.Scatter(x=trend_grouped['Month'], y=trend_grouped['Spend'], name=tr({'ar':'الصرف', 'en':'Spend'}), mode='lines+markers', line=dict(color='#ef4444', width=3)))
            fig_trend.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig_trend, use_container_width=True)

# --- Charts Row 2 ---
r2c1, r2c2 = st.columns([1, 1.2])

with r2c1:
    with st.container(border=True):
        st.markdown(f"<h5 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'قمع الأداء التسويقي (Funnel)', 'en': 'Marketing Performance Funnel'})}</h5>", unsafe_allow_html=True)
        
        funnel_stages = [tr({'ar': 'الظهور', 'en': 'Impressions'}), tr({'ar': 'النقرات', 'en': 'Clicks'}), tr({'ar': 'الطلبات', 'en': 'Conversions'})]
        funnel_values = [tot_imp, tot_clicks, tot_conv]
        
        fig_funnel = go.Figure(go.Funnel(
            y=funnel_stages, x=funnel_values,
            textinfo="value+percent initial",
            marker={"color": ["#94a3b8", "#3b82f6", "#1e3a8a"]}
        ))
        fig_funnel.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(t=20))
        st.plotly_chart(fig_funnel, use_container_width=True)

with r2c2:
    with st.container(border=True):
        st.markdown(f"<h5 style='color:#1e3a8a;'>{tr({'ar': 'أداء الحملات وعائد الاستثمار', 'en': 'Campaign Performance & ROI'})}</h5>", unsafe_allow_html=True)
        
        camp_df = df_filtered.groupby(['Campaign', 'Channel']).agg({'Spend': 'sum', 'Revenue': 'sum', 'Conversions': 'sum'}).reset_index()
        camp_df['ROAS'] = (camp_df['Revenue'] / camp_df['Spend']).fillna(0)
        camp_df['CPO'] = (camp_df['Spend'] / camp_df['Conversions']).fillna(0)
        camp_df = camp_df.sort_values('ROAS', ascending=False).head(10)
        
        cols = {
            'Campaign': tr({'ar': 'اسم الحملة', 'en': 'Campaign'}),
            'Channel': tr({'ar': 'القناة', 'en': 'Channel'}),
            'Spend': tr({'ar': 'الصرف', 'en': 'Spend'}),
            'Revenue': tr({'ar': 'العائد', 'en': 'Revenue'}),
            'ROAS': 'ROAS'
        }
        
        display_df = camp_df.rename(columns=cols)
        st.dataframe(display_df[list(cols.values())].style.format({
            cols['Spend']: '{:,.0f}', cols['Revenue']: '{:,.0f}', 'ROAS': '{:.1f}x'
        }).map(lambda x: 'color: #10b981; font-weight:bold;' if isinstance(x, float) and x > 3 else '', subset=['ROAS']), use_container_width=True, hide_index=True)