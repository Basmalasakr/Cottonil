import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os
import requests
import html
import re
import traceback

st.set_page_config(layout="wide", page_title="Sustainability & ESG Analytics")

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
    .kpi-risk { color: #ef4444 !important; }
    
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 12px; border: 2px solid #94a3b8 !important; 
        background-color: #ffffff; padding: 15px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    }
    .ai-response-box {
        padding: 30px; background-color: #f0fdf4; border: 1px solid #10b981;
        border-left: 5px solid #10b981; border-radius: 8px; font-size: 16px; 
        line-height: 2; color: #064e3b; margin-top: 15px;
    }
    .chart-subtitle {
        font-size: 12px; color: #64748b; text-align: center; 
        margin-top: -10px; margin-bottom: 15px;
    }
    </style>
""", unsafe_allow_html=True)

@st.cache_data
def load_esg_data():
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(current_dir, 'data') if os.path.exists(os.path.join(current_dir, 'data')) else os.path.join(os.path.dirname(current_dir), 'data')
        
        df_expenses = pd.read_parquet(os.path.join(data_dir, 'operating_expenses.parquet'), 
                                      columns=['expense_id', 'expense_date', 'branch_or_department_id', 'expense_category', 'amount_EGP'])
        
        df_shipments = pd.read_parquet(os.path.join(data_dir, 'import_shipments.parquet'), 
                                       columns=['import_shipment_id', 'shipment_date', 'port_name', 'container_type', 'freight_USD', 'destination_warehouse_id'])
        
        df_warehouses = pd.read_parquet(os.path.join(data_dir, 'warehouses.parquet'), 
                                        columns=['warehouse_id', 'warehouse_label', 'governorate_ar', 'capacity_units'])
        
        df_expenses['expense_date'] = pd.to_datetime(df_expenses['expense_date'], errors='coerce')
        df_expenses.dropna(subset=['expense_date'], inplace=True)
        
        df_shipments['shipment_date'] = pd.to_datetime(df_shipments['shipment_date'], errors='coerce')
        df_shipments.dropna(subset=['shipment_date'], inplace=True)
        
        return df_expenses, df_shipments, df_warehouses
    except Exception as e:
        return None, None, traceback.format_exc()

df_expenses, df_shipments, df_warehouses = load_esg_data()

if df_expenses is None:
    st.error("Error loading data.")
    st.stop()

st.sidebar.markdown(f"<h3>{tr({'ar': 'إعدادات النظام', 'en': 'System Settings'})}</h3>", unsafe_allow_html=True)
selected_lang = st.sidebar.radio(tr({'ar': "اللغة", 'en': "Language"}), ['ar', 'en'], index=0 if st.session_state.lang == 'ar' else 1)
if selected_lang != st.session_state.lang:
    st.session_state.lang = selected_lang
    st.rerun()

st.markdown(f"<h2 style='color:#1e3a8a; margin-bottom: 20px;'>{tr({'ar': 'تحليلات الاستدامة والحوكمة البيئية (ESG)', 'en': 'Sustainability & ESG Analytics'})}</h2>", unsafe_allow_html=True)

min_date = min(df_expenses['expense_date'].min().date(), df_shipments['shipment_date'].min().date())
max_date = max(df_expenses['expense_date'].max().date(), df_shipments['shipment_date'].max().date())

with st.container(border=True):
    c1, c2 = st.columns(2)
    start_date = c1.date_input(tr({'ar': "من تاريخ", 'en': "Start Date"}), min_date)
    end_date = c2.date_input(tr({'ar': "إلى تاريخ", 'en': "End Date"}), max_date)

mask_exp = (df_expenses['expense_date'].dt.date >= start_date) & (df_expenses['expense_date'].dt.date <= end_date)
df_exp_filtered = df_expenses[mask_exp].copy()

mask_ship = (df_shipments['shipment_date'].dt.date >= start_date) & (df_shipments['shipment_date'].dt.date <= end_date)
df_ship_filtered = df_shipments[mask_ship].copy()

electricity_kw = ['كهرباء', 'طاقة', 'electricity']
fuel_kw = ['وقود', 'بنزين', 'سولار', 'fuel']
water_kw = ['مياه', 'صرف', 'water']

df_exp_filtered['is_elec'] = df_exp_filtered['expense_category'].apply(lambda x: any(k in str(x).lower() for k in electricity_kw))
df_exp_filtered['is_fuel'] = df_exp_filtered['expense_category'].apply(lambda x: any(k in str(x).lower() for k in fuel_kw))
df_exp_filtered['is_water'] = df_exp_filtered['expense_category'].apply(lambda x: any(k in str(x).lower() for k in water_kw))

elec_cost = df_exp_filtered[df_exp_filtered['is_elec']]['amount_EGP'].sum()
fuel_cost = df_exp_filtered[df_exp_filtered['is_fuel']]['amount_EGP'].sum()
water_cost = df_exp_filtered[df_exp_filtered['is_water']]['amount_EGP'].sum()

if elec_cost == 0: elec_cost = df_exp_filtered['amount_EGP'].sum() * 0.12
if fuel_cost == 0: fuel_cost = df_exp_filtered['amount_EGP'].sum() * 0.03
if water_cost == 0: water_cost = df_exp_filtered['amount_EGP'].sum() * 0.05

total_electricity_mwh = elec_cost / 1500
total_water_m3 = water_cost / 10
scope1_emissions = (fuel_cost / 1000) * 0.25 
scope2_emissions = total_electricity_mwh * 0.45 
scope3_emissions = df_ship_filtered['freight_USD'].sum() * 0.035 

total_carbon_footprint = scope1_emissions + scope2_emissions + scope3_emissions
carbon_tax_risk = total_carbon_footprint * 45 

target_carbon = total_carbon_footprint * 0.85 

tab_dashboard, tab_ai = st.tabs([
    tr({'ar': "لوحة بيانات الاستدامة", 'en': "Sustainability Dashboard"}),
    tr({'ar': "مستشار الاستدامة", 'en': "Sustainability Consultant"})
])

with tab_dashboard:
    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"إجمالي البصمة الكربونية", "en":"Total Carbon Footprint"})}</div><div class="kpi-value">{total_carbon_footprint:,.1f} <span style="font-size: 14px;">tCO2e</span></div></div>', unsafe_allow_html=True)
    k2.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"مخاطر ضريبة الكربون (مُقدرة)", "en":"Estimated Carbon Tax Risk"})}</div><div class="kpi-value kpi-risk">${carbon_tax_risk:,.0f}</div></div>', unsafe_allow_html=True)
    k3.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"استهلاك المياه", "en":"Water Consumption"})}</div><div class="kpi-value">{total_water_m3:,.0f} <span style="font-size: 14px;">m³</span></div></div>', unsafe_allow_html=True)
    k4.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"استهلاك الكهرباء", "en":"Electricity Consumption"})}</div><div class="kpi-value">{total_electricity_mwh:,.1f} <span style="font-size: 14px;">MWh</span></div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    r1c1, r1c2, r1c3 = st.columns([1, 1, 1])

    with r1c1:
        with st.container(border=True):
            st.markdown(f"<h5 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'الانبعاثات حسب ميناء الاستيراد', 'en': 'Emissions by Import Port'})}</h5>", unsafe_allow_html=True)
            st.markdown(f"<p class='chart-subtitle'>{tr({'ar': 'يوضح البصمة الكربونية الناتجة عن عمليات الشحن لكل ميناء', 'en': 'Shows carbon footprint generated by shipping operations per port'})}</p>", unsafe_allow_html=True)
            port_emissions = df_ship_filtered.groupby('port_name')['freight_USD'].sum().reset_index()
            port_emissions['tCO2e'] = port_emissions['freight_USD'] * 0.035
            port_emissions = port_emissions.sort_values('tCO2e', ascending=False).head(5)
            fig_port = px.bar(port_emissions, x='port_name', y='tCO2e', color_discrete_sequence=['#3b82f6'])
            fig_port.update_layout(xaxis_title="", yaxis_title=tr({'ar': "طن كربون", 'en': "tCO2e"}), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', height=280, margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig_port, use_container_width=True)

    with r1c2:
        with st.container(border=True):
            st.markdown(f"<h5 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'الأداء مقابل الهدف (انبعاثات الكربون)', 'en': 'Target vs Actual (Carbon)'})}</h5>", unsafe_allow_html=True)
            st.markdown(f"<p class='chart-subtitle'>{tr({'ar': 'يقارن الانبعاثات الحالية بالهدف السنوي لتحقيق الحياد الكربوني', 'en': 'Compares current emissions against the annual target'})}</p>", unsafe_allow_html=True)
            fig_gauge_c = go.Figure(go.Indicator(
                mode = "gauge+number+delta",
                value = total_carbon_footprint,
                domain = {'x': [0, 1], 'y': [0, 1]},
                title = {'text': tr({'ar': "طن كربون", 'en': "tCO2e"}), 'font': {'size': 14}},
                delta = {'reference': target_carbon, 'increasing': {'color': "#ef4444"}, 'decreasing': {'color': "#10b981"}},
                gauge = {
                    'axis': {'range': [None, total_carbon_footprint * 1.5]},
                    'bar': {'color': "#1e3a8a"},
                    'steps' : [
                        {'range': [0, target_carbon], 'color': "#d1fae5"},
                        {'range': [target_carbon, total_carbon_footprint * 1.5], 'color': "#fee2e2"}
                    ],
                    'threshold' : {'line': {'color': "black", 'width': 4}, 'thickness': 0.75, 'value': target_carbon}
                }
            ))
            fig_gauge_c.update_layout(height=280, margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig_gauge_c, use_container_width=True)

    with r1c3:
        with st.container(border=True):
            st.markdown(f"<h5 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'نطاقات الانبعاثات (Scope 1, 2, 3)', 'en': 'Emissions by Scope'})}</h5>", unsafe_allow_html=True)
            st.markdown(f"<p class='chart-subtitle'>{tr({'ar': 'يفصل مصادر الانبعاثات (مباشرة، طاقة مشتراة، سلسلة توريد)', 'en': 'Breaks down emission sources (Direct, Purchased Energy, Supply Chain)'})}</p>", unsafe_allow_html=True)
            scopes_df = pd.DataFrame({
                'Scope': [tr({'ar': 'النطاق 1 (مباشر)', 'en': 'Scope 1 (Direct)'}), 
                          tr({'ar': 'النطاق 2 (كهرباء)', 'en': 'Scope 2 (Electricity)'}), 
                          tr({'ar': 'النطاق 3 (سلسلة التوريد)', 'en': 'Scope 3 (Supply Chain)'})],
                'tCO2e': [scope1_emissions, scope2_emissions, scope3_emissions]
            })
            fig_donut = px.pie(scopes_df, names='Scope', values='tCO2e', hole=0.6, color_discrete_sequence=['#93c5fd', '#3b82f6', '#1e3a8a'])
            fig_donut.update_layout(showlegend=True, legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5), margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig_donut, use_container_width=True)

    st.markdown("<br>", unsafe_allow_html=True)

    r2c1, r2c2 = st.columns([1, 1])

    with r2c1:
        with st.container(border=True):
            st.markdown(f"<h5 style='color:#1e3a8a;'>{tr({'ar': 'بطاقة أداء الفروع (كفاءة الطاقة)', 'en': 'Branch Scorecard (Energy Efficiency)'})}</h5>", unsafe_allow_html=True)
            st.markdown(f"<p class='chart-subtitle' style='text-align: right;'>{tr({'ar': 'يقيّم كفاءة استهلاك الطاقة لأبرز الفروع بناءً على مساحتها التشغيلية', 'en': 'Evaluates energy consumption efficiency for top branches based on capacity'})}</p>", unsafe_allow_html=True)
            df_wh_exp = df_exp_filtered.groupby('branch_or_department_id')['amount_EGP'].sum().reset_index()
            scorecard = df_warehouses.merge(df_wh_exp, left_on='warehouse_id', right_on='branch_or_department_id', how='left').fillna(0)
            scorecard['Energy_kWh_per_unit'] = (scorecard['amount_EGP'] * 0.12 / 1.5) / scorecard['capacity_units'].replace(0, 1)
            scorecard['ESG_Score'] = 100 - (scorecard['Energy_kWh_per_unit'] * 10).clip(upper=40)
            scorecard = scorecard.sort_values('ESG_Score', ascending=False)[['warehouse_label', 'governorate_ar', 'ESG_Score', 'Energy_kWh_per_unit']].head(8)
            
            esg_col = tr({'ar': 'تقييم ESG', 'en': 'ESG Score'})
            eng_col = tr({'ar': 'استهلاك الطاقة/وحدة', 'en': 'Energy/Unit'})
            
            scorecard.rename(columns={
                'warehouse_label': tr({'ar': 'المرفق', 'en': 'Facility'}), 
                'governorate_ar': tr({'ar': 'المنطقة', 'en': 'Region'}),
                'ESG_Score': esg_col,
                'Energy_kWh_per_unit': eng_col
            }, inplace=True)
            
            st.dataframe(scorecard.style.format({esg_col: '{:.1f}', eng_col: '{:.2f}'}).map(lambda x: 'color: #1e3a8a; font-weight: bold;', subset=[esg_col]), use_container_width=True, hide_index=True)

    with r2c2:
        with st.container(border=True):
            st.markdown(f"<h5 style='color:#1e3a8a;'>{tr({'ar': 'اتجاه الانبعاثات واستهلاك الطاقة', 'en': 'Emissions & Energy Trend'})}</h5>", unsafe_allow_html=True)
            st.markdown(f"<p class='chart-subtitle' style='text-align: right;'>{tr({'ar': 'يتتبع التغير الشهري في الانبعاثات لتقييم فعالية سياسات الاستدامة بمرور الوقت', 'en': 'Tracks monthly changes in emissions to evaluate sustainability policies'})}</p>", unsafe_allow_html=True)
            trend_df = df_exp_filtered.groupby(df_exp_filtered['expense_date'].dt.to_period('M'))['amount_EGP'].sum().reset_index()
            trend_df['expense_date'] = trend_df['expense_date'].dt.to_timestamp()
            trend_df['tCO2e_Estimated'] = (trend_df['amount_EGP'] * 0.15 / 1500) * 0.45
            fig_trend = px.area(trend_df, x='expense_date', y='tCO2e_Estimated', markers=True, color_discrete_sequence=['#3b82f6'])
            fig_trend.update_layout(xaxis_title="", yaxis_title=tr({'ar': "طن كربون", 'en': "tCO2e"}), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig_trend, use_container_width=True)


GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-20b"

def call_groq(api_key, prompt):
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": GROQ_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1, "max_completion_tokens": 1000}
    try:
        r = requests.post(GROQ_URL, headers=headers, json=payload, timeout=30)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"].get("content", "").strip(), None
    except Exception as e:
        return None, str(e)
    return None, "Error connecting to AI."

with tab_ai:
    st.markdown(f"<h4 style='color:#1e3a8a;'>{tr({'ar': 'مستشار الاستدامة', 'en': 'Sustainability Consultant'})}</h4>", unsafe_allow_html=True)
    c_ai1, c_ai2 = st.columns([1, 2])

    with c_ai1:
        api_key_configured = False
        try:
            api_key = st.secrets["GROQ_API_KEY"]
            if api_key: api_key_configured = True
        except:
            pass

        if st.button(tr({'ar': "استخراج فرص التحسين", 'en': "Extract ESG Opportunities"}), type="primary", use_container_width=True):
            if not api_key_configured:
                st.warning(tr({'ar': "الرجاء إعداد مفتاح النظام (API Key)", 'en': "Please configure API Key"}))
            else:
                with st.spinner(tr({'ar': "جاري تحليل البيانات واستخراج التوصيات...", 'en': "Analyzing data..."})):
                    fac_col = tr({'ar': 'المرفق', 'en': 'Facility'})
                    worst_facility = scorecard.iloc[-1][fac_col] if not scorecard.empty else "N/A"
                    worst_port = port_emissions.iloc[0]['port_name'] if not port_emissions.empty else "N/A"
                    
                    sys_lang = "Arabic" if st.session_state.lang == 'ar' else "English"
                    prompt = (
                        f"أنت خبير استشاري في مجال الاستدامة البيئية. بناءً على البيانات التالية للشركة:\n"
                        f"- إجمالي مخاطر ضريبة الكربون المحتملة: {carbon_tax_risk:,.0f} دولار.\n"
                        f"- الميناء الأعلى مساهمة في الانبعاثات الكربونية: {worst_port}.\n"
                        f"- المرفق الأقل كفاءة في استهلاك الطاقة: {worst_facility}.\n\n"
                        f"قم بكتابة باللغة {sys_lang} 3 نقاط فقط، مباشرة وعملية، كخطة عمل تنفيذية للإدارة العليا لخفض هذه التكاليف والانبعاثات. لا تقم بكتابة أي مقدمات أو استنتاجات، فقط النقاط الثلاث."
                    )
                    
                    ai_res, ai_err = call_groq(api_key, prompt)
                    if ai_res:
                        st.session_state['esg_ai_insights'] = ai_res
                    else:
                        st.error(ai_err)

    with c_ai2:
        if 'esg_ai_insights' in st.session_state:
            safe_html = html.escape(st.session_state['esg_ai_insights']).replace("\n", "<br>")
            safe_html = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", safe_html)
            safe_html = safe_html.replace("* ", "• ").replace("- ", "• ")
            st.markdown(f"<div class='ai-response-box' dir='auto'>{safe_html}</div>", unsafe_allow_html=True)