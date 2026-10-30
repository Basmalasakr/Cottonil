import streamlit as st
import pandas as pd
import plotly.express as px
import os
import re
import html
import requests
import time
import datetime

st.set_page_config(layout="wide", page_title="Workforce Productivity & Operations")

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
        transition: transform 0.2s;
    }
    .kpi-card:hover { transform: scale(1.02); border-color: #3b82f6; }
    .kpi-value { font-size: 25px; font-weight: bold; color: #1e3a8a; margin-bottom: 5px; }
    .kpi-alert { font-size: 25px; font-weight: bold; color: #ef4444; margin-bottom: 5px; }
    .kpi-na { font-size: 25px; font-weight: bold; color: #94a3b8; margin-bottom: 5px; }
    .kpi-label { font-size: 14px; color: #64748b; font-weight: 600; }
    .delta-good { font-size: 13px; color: #10b981; font-weight: bold; margin-top: 5px;}
    .delta-bad { font-size: 13px; color: #ef4444; font-weight: bold; margin-top: 5px;}
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
# Data Loading 
# ----------------------------------------------------------------------------------------------
@st.cache_data
def load_workforce_data():
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(current_dir, 'data') if os.path.exists(os.path.join(current_dir, 'data')) else os.path.join(os.path.dirname(current_dir), 'data')
        
        df_employees = pd.read_parquet(os.path.join(data_dir, 'employees.parquet'))
        df_payroll = pd.read_parquet(os.path.join(data_dir, 'payroll.parquet'))
        df_orders = pd.read_parquet(os.path.join(data_dir, 'sales_orders.parquet'))
        df_branches = pd.read_parquet(os.path.join(data_dir, 'branches.parquet'))
        df_deliveries = pd.read_parquet(os.path.join(data_dir, 'delivery_shipments.parquet'))
        df_returns = pd.read_parquet(os.path.join(data_dir, 'sales_returns.parquet'))
        
        df_orders['order_date'] = pd.to_datetime(df_orders['order_date'], errors='coerce')
        df_payroll['pay_month'] = pd.to_datetime(df_payroll['pay_month'], format='%Y-%m', errors='coerce')
        
        df_deliveries['ship_date'] = pd.to_datetime(df_deliveries['ship_date'], errors='coerce')
        df_deliveries['delivery_date'] = pd.to_datetime(df_deliveries['delivery_date'], errors='coerce')
        df_deliveries['processing_days'] = (df_deliveries['delivery_date'] - df_deliveries['ship_date']).dt.days
        df_deliveries['processing_days'] = df_deliveries['processing_days'].clip(lower=0)
        df_deliveries = df_deliveries.merge(df_orders[['sales_order_id', 'branch_id']], on='sales_order_id', how='left')
        
        df_returns['return_date'] = pd.to_datetime(df_returns['return_date'], errors='coerce')
        df_returns = df_returns.merge(df_orders[['sales_order_id', 'branch_id']], on='sales_order_id', how='left')
        
        return df_employees, df_payroll, df_orders, df_branches, df_deliveries, df_returns
    except Exception as e:
        return None, None, None, None, None, str(e)

df_employees, df_payroll, df_orders, df_branches, df_deliveries, df_returns = load_workforce_data()

if df_employees is None:
    st.error("Failed to load data.")
    st.stop()

# ----------------------------------------------------------------------------------------------
# Sidebar & Filters
# ----------------------------------------------------------------------------------------------
st.sidebar.markdown(f"<h3>{tr({'ar': 'إعدادات النظام', 'en': 'System Settings'})}</h3>", unsafe_allow_html=True)
selected_lang = st.sidebar.radio(
    tr({'ar': "اختر اللغة", 'en': "Select Language"}),
    options=['ar', 'en'],
    index=0 if st.session_state.lang == 'ar' else 1
)
if selected_lang != st.session_state.lang:
    st.session_state.lang = selected_lang
    st.rerun()

st.markdown(f"<h2 style='color:#1e3a8a; margin-bottom: 20px;'>{tr({'ar': 'إنتاجية القوى العاملة والتشغيل', 'en': 'Workforce Productivity & Operations'})}</h2>", unsafe_allow_html=True)

min_date = df_payroll['pay_month'].min().date() if not df_payroll.empty else datetime.date(2020, 1, 1)
max_date = df_payroll['pay_month'].max().date() if not df_payroll.empty else datetime.date.today()

valid_types = df_branches['retail_location_type'].dropna().unique().tolist()
if not valid_types:
    valid_types = ['Retail branch', 'Point of sale / reseller']

with st.container(border=True):
    c_start, c_end, c_type = st.columns(3)
    with c_start:
        start_date = st.date_input(tr({'ar': "من تاريخ", 'en': "Start Date"}), min_date)
    with c_end:
        end_date = st.date_input(tr({'ar': "إلى تاريخ", 'en': "End Date"}), max_date)
    with c_type:
        selected_types = st.multiselect(
            tr({'ar': "نوع المنفذ (تجزئة / موزع)", 'en': "Location Type"}),
            valid_types, default=valid_types
        )

# تحديد ما إذا كان الفلتر يشمل الموزعين فقط لإخفاء زمن الشحن
is_reseller_only = len(selected_types) == 1 and 'reseller' in selected_types[0].lower()

if selected_types:
    filtered_branches = df_branches[df_branches['retail_location_type'].isin(selected_types)]
else:
    filtered_branches = df_branches.copy()
    
valid_branch_ids = filtered_branches['branch_id'].tolist()

mask_payroll = (df_payroll['pay_month'].dt.date >= start_date) & (df_payroll['pay_month'].dt.date <= end_date)
f_payroll = df_payroll[mask_payroll].copy()

mask_orders = (df_orders['order_date'].dt.date >= start_date) & (df_orders['order_date'].dt.date <= end_date) & (df_orders['branch_id'].isin(valid_branch_ids))
f_orders = df_orders[mask_orders].copy()

mask_deliveries = (df_deliveries['ship_date'].dt.date >= start_date) & (df_deliveries['ship_date'].dt.date <= end_date) & (df_deliveries['branch_id'].isin(valid_branch_ids))
f_deliveries = df_deliveries[mask_deliveries].copy()

mask_returns = (df_returns['return_date'].dt.date >= start_date) & (df_returns['return_date'].dt.date <= end_date) & (df_returns['branch_id'].isin(valid_branch_ids))
f_returns = df_returns[mask_returns].copy()

# ==========================================
# Core Calculations
# ==========================================
branch_sales = f_orders.groupby('branch_id')['net_before_tax_EGP'].sum().reset_index()

employee_payroll = f_payroll.groupby('employee_id')['net_paid_EGP'].sum().reset_index()
employee_branch = df_employees[['employee_id', 'branch_id']].drop_duplicates()
employee_payroll = employee_payroll.merge(employee_branch, on='employee_id', how='left')

employee_payroll = employee_payroll[employee_payroll['branch_id'].isin(valid_branch_ids)]

branch_payroll = employee_payroll.groupby('branch_id').agg(
    total_payroll=('net_paid_EGP', 'sum'),
    employee_count=('employee_id', 'nunique')
).reset_index()

branch_delivery = f_deliveries.groupby('branch_id')['processing_days'].mean().reset_index()
branch_returns = f_returns.groupby('branch_id')['return_id'].count().reset_index()
branch_returns.rename(columns={'return_id': 'returns_count'}, inplace=True)

branch_metrics = filtered_branches[['branch_id', 'branch_name_ar']].copy()
branch_metrics = branch_metrics.merge(branch_sales, on='branch_id', how='left')
branch_metrics = branch_metrics.merge(branch_payroll, on='branch_id', how='left')
branch_metrics = branch_metrics.merge(branch_delivery, on='branch_id', how='left')
branch_metrics = branch_metrics.merge(branch_returns, on='branch_id', how='left').fillna(0)

branch_metrics['labor_cost_ratio'] = (branch_metrics['total_payroll'] / branch_metrics['net_before_tax_EGP'].replace(0, 1)) * 100
branch_metrics['labor_productivity'] = branch_metrics['net_before_tax_EGP'] / branch_metrics['employee_count'].replace(0, 1)

total_sales_all = branch_metrics['net_before_tax_EGP'].sum()
total_payroll_all = branch_metrics['total_payroll'].sum()
total_employees_all = branch_metrics['employee_count'].sum()

actual_labor_cost_ratio = (total_payroll_all / total_sales_all * 100) if total_sales_all > 0 else 0
overall_productivity = (total_sales_all / total_employees_all) if total_employees_all > 0 else 0
overall_delivery_speed = branch_metrics['processing_days'].mean() if not branch_metrics['processing_days'].isna().all() else 0
overall_returns = branch_metrics['returns_count'].sum()

# ----------------------------------------------------------------------------------------------
# Dashboard UI
# ----------------------------------------------------------------------------------------------
tab_dashboard, tab_ai = st.tabs([
    tr({'ar': "لوحة عمليات المتاجر", 'en': "Store Operations Dashboard"}),
    tr({'ar': "المحلل الإداري الذكي", 'en': "AI Workforce Analyst"})
])

with tab_dashboard:
    
    # --- Top KPIs ---
    c1, c2, c3, c4 = st.columns(4)
    
    c1.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"إنتاجية الموظف (المبيعات)", "en":"Labor Productivity"})}</div><div class="kpi-value">EGP {overall_productivity:,.0f}</div><div class="delta-good">Average Sales / Employee</div></div>', unsafe_allow_html=True)
    
    cost_color = "delta-bad" if actual_labor_cost_ratio > 12 else "delta-good"
    c2.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"نسبة تكلفة العمالة", "en":"Labor Cost Ratio"})}</div><div class="kpi-value">{actual_labor_cost_ratio:.1f}%</div><div class="{cost_color}">Cost % of Sales</div></div>', unsafe_allow_html=True)
    
    # التعامل الديناميكي مع الموزعين في الكارت
    if is_reseller_only:
        c3.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"زمن تجهيز وشحن الطلبات", "en":"Avg Processing Time"})}</div><div class="kpi-na">N/A</div><div class="delta-good" style="color:#94a3b8;">لا ينطبق للموزعين</div></div>', unsafe_allow_html=True)
    else:
        c3.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"زمن تجهيز وشحن الطلبات", "en":"Avg Processing Time"})}</div><div class="kpi-value">{overall_delivery_speed:.1f} Days</div><div class="delta-good">Fulfillment Speed KPI</div></div>', unsafe_allow_html=True)
    
    c4.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"أخطاء التشغيل (المرتجعات)", "en":"Operational Returns"})}</div><div class="kpi-alert">{overall_returns:,.0f}</div><div class="delta-bad">Returned Items</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    
    # --- Charts ---
    r1c1, r1c2 = st.columns(2)
    with r1c1:
        with st.container(border=True):
            st.markdown(f"<h4 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'إنتاجية الموظفين حسب الفرع', 'en': 'Labor Productivity by Branch'})}</h4>", unsafe_allow_html=True)
            if not branch_metrics.empty:
                prod_chart = branch_metrics[branch_metrics['employee_count'] > 0].sort_values('labor_productivity', ascending=False).head(10)
                fig_prod = px.bar(prod_chart, x='branch_name_ar', y='labor_productivity', text_auto='.2s', color_discrete_sequence=['#3b82f6'])
                fig_prod.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', xaxis_title="", yaxis_title="المبيعات لكل موظف")
                st.plotly_chart(fig_prod, use_container_width=True)

    with r1c2:
        with st.container(border=True):
            st.markdown(f"<h4 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'تحليل تكلفة العمالة حسب الفرع', 'en': 'Labor Cost Ratio Analysis'})}</h4>", unsafe_allow_html=True)
            if not branch_metrics.empty:
                cost_chart = branch_metrics[branch_metrics['net_before_tax_EGP'] > 0].sort_values('labor_cost_ratio', ascending=False).head(10)
                fig_cost = px.bar(cost_chart, x='branch_name_ar', y='labor_cost_ratio', text_auto='.1f', color_discrete_sequence=['#ef4444'])
                fig_cost.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', xaxis_title="", yaxis_title="% من المبيعات")
                st.plotly_chart(fig_cost, use_container_width=True)

    # --- Data Table ---
    st.markdown("<br>", unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown(f"<h4 style='color:#1e3a8a;'>{tr({'ar': 'الأداء التشغيلي للمتاجر', 'en': 'Store Operational Performance'})}</h4>", unsafe_allow_html=True)
        display_df = branch_metrics[['branch_name_ar', 'labor_productivity', 'labor_cost_ratio', 'processing_days', 'returns_count']].copy()
        display_df = display_df[display_df['labor_productivity'] > 0].sort_values('labor_productivity', ascending=False)
        
        # إخفاء عمود المعالجة إذا كان الموزع فقط هو المختار
        if is_reseller_only:
            display_df.drop(columns=['processing_days'], inplace=True)
            cols_format = {
                tr({'ar': 'إنتاجية الموظف (ج.م)', 'en': 'Labor Productivity'}): "{:,.0f}",
                tr({'ar': 'نسبة تكلفة العمالة %', 'en': 'Labor Cost %'}): "{:.1f}%"
            }
        else:
            cols_format = {
                tr({'ar': 'إنتاجية الموظف (ج.م)', 'en': 'Labor Productivity'}): "{:,.0f}",
                tr({'ar': 'نسبة تكلفة العمالة %', 'en': 'Labor Cost %'}): "{:.1f}%",
                tr({'ar': 'زمن التجهيز للشحن (أيام)', 'en': 'Processing Time (Days)'}): "{:.1f}"
            }

        rename_dict = {
            'branch_name_ar': tr({'ar': 'اسم الفرع', 'en': 'Branch'}),
            'labor_productivity': tr({'ar': 'إنتاجية الموظف (ج.م)', 'en': 'Labor Productivity'}),
            'labor_cost_ratio': tr({'ar': 'نسبة تكلفة العمالة %', 'en': 'Labor Cost %'}),
            'processing_days': tr({'ar': 'زمن التجهيز للشحن (أيام)', 'en': 'Processing Time (Days)'}),
            'returns_count': tr({'ar': 'أخطاء التشغيل (مرتجعات)', 'en': 'Returns Count'})
        }
        
        display_df.rename(columns=rename_dict, inplace=True)
        st.dataframe(display_df.style.format(cols_format), use_container_width=True, hide_index=True)


# ----------------------------------------------------------------------------------------------
# AI Tab (Fully Conversational & Operational)
# ----------------------------------------------------------------------------------------------
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-20b"

def call_groq(api_key, prompt):
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": GROQ_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2, "max_completion_tokens": 3000}
    try:
        r = requests.post(GROQ_URL, headers=headers, json=payload, timeout=90)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"].get("content", "").strip(), None
    except Exception as e:
        return None, str(e)
    return None, "Error connecting to AI."

def build_workforce_facts_for_ai(b_metrics):
    if b_metrics.empty or total_sales_all == 0:
        return "لا توجد بيانات كافية للفترة المحددة."

    b_sorted_cost = b_metrics.sort_values('labor_cost_ratio', ascending=False)
    high_cost_branches = b_sorted_cost.head(3)[['branch_name_ar', 'labor_cost_ratio']].to_dict('records')
    
    b_sorted_prod = b_metrics.sort_values('labor_productivity', ascending=False)
    best_prod = b_sorted_prod.head(3)[['branch_name_ar', 'labor_productivity']].to_dict('records')
    
    facts = (
        f"متوسط تكلفة العمالة للشركة ككل يمثل {actual_labor_cost_ratio:.1f}% من إجمالي المبيعات.\n"
        f"أعلى 3 فروع في تكلفة العمالة (وهي الأسوأ لأنها تتخطى متوسط الشركة بشكل كبير وتستهلك الأرباح): {high_cost_branches}\n"
        f"أفضل 3 فروع في إنتاجية الموظف (حيث يحقق الموظف الواحد أعلى مبيعات): {best_prod}\n"
        f"متوسط زمن تجهيز وتغليف الطلبات العام للشركة: {overall_delivery_speed:.1f} يوم.\n"
        f"إجمالي أخطاء التشغيل (مرتجعات بسبب أخطاء بشرية أو غيرها): {overall_returns} قطعة."
    )
    return facts

with tab_ai:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(current_dir, 'data') if os.path.exists(os.path.join(current_dir, 'data')) else os.path.join(os.path.dirname(current_dir), 'data')
    dec_file = os.path.join(data_dir, 'workforce_decisions_log.csv') 
    
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

    st.markdown(f"#### {tr({'ar': 'اسأل المحلل الذكي عن أداء التشغيل والقوى العاملة:', 'en': 'Ask the AI Analyst about Workforce & Ops:'})}")
    user_query = st.text_input(
        tr({'ar': "مثال: أي الفروع تعاني من تكلفة عمالة مرتفعة؟ أو: ما هي توصياتك لتحسين سرعة التجهيز؟", 'en': "e.g., Which branches have high labor costs?"}), 
        key="wf_query_input"
    )
    
    if st.button(tr({'ar': "تحليل وإجابة", 'en': "Analyze & Answer"}), type="primary", use_container_width=True):
        if not api_key_configured:
            st.warning(tr({'ar': "الرجاء إعداد GROQ_API_KEY", 'en': "Please configure GROQ_API_KEY"}))
        else:
            with st.spinner(tr({'ar': "المحلل يقرأ البيانات...", 'en': "Analyzing Data..."})):
                facts_text = build_workforce_facts_for_ai(branch_metrics)
                sys_lang = "Arabic" if st.session_state.lang == 'ar' else "English"
                
                final_question = user_query if user_query.strip() else "قدم تحليلاً لأعلى الفروع في تكلفة العمالة واقترح خطة عمل لتحسين التشغيل."
                
                prompt = (
                    f"أنت مدير الموارد البشرية والعمليات (HR & Ops Director). اكتب باللغة {sys_lang}.\n"
                    f"هذه هي الأرقام الحقيقية للشركة حالياً:\n{facts_text}\n\n"
                    f"سؤال الإدارة لك: {final_question}\n\n"
                    "المطلوب:\n"
                    "أجب على السؤال بوضوح واحترافية وبشكل مباشر باستخدام الأرقام المعطاة لك فقط. "
                    "قم دائماً بمقارنة أرقام الفروع بالمتوسط العام للشركة لتوضيح حجم الفجوة. "
                    "لا تؤلف فروعاً أو أرقاماً غير موجودة بالنص. استخدم النقاط (Bullet points) لتسهيل القراءة. لا تستخدم أي رموز تعبيرية (Emojis)."
                )
                
                ai_res, ai_err = call_groq(api_key, prompt)
                if ai_res:
                    st.session_state['wf_ai_response'] = ai_res
                    st.session_state['wf_user_query'] = final_question
                else:
                    st.error(ai_err)

    if 'wf_ai_response' in st.session_state:
        st.markdown("<br>", unsafe_allow_html=True)
        safe_html = html.escape(st.session_state['wf_ai_response']).replace("\n", "<br>")
        safe_html = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", safe_html)
        st.markdown(f"<div class='ai-response-box' dir='auto'>{safe_html}</div>", unsafe_allow_html=True)
        
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button(tr({'ar': "إرسال القرار للإدارة (تليجرام)", 'en': "Send Decision to Management"})):
            if telegram_configured:
                try:
                    decision_id = str(int(time.time()))
                    message = f"*قرار قوى عاملة وتشغيل*\n\n*الطلب:* {st.session_state['wf_user_query']}\n\n*التوصية:*\n{st.session_state['wf_ai_response']}"
                    
                    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
                    t_payload = {
                        "chat_id": telegram_chat_id,
                        "text": message[:4000],
                        "parse_mode": "Markdown",
                        "reply_markup": {
                            "inline_keyboard": [[
                                {"text": "اعتماد التوصية", "callback_data": f"Approve_{decision_id}"},
                                {"text": "رفض", "callback_data": f"Reject_{decision_id}"}
                            ]]
                        }
                    }
                    requests.post(url, json=t_payload, timeout=30)
                    
                    new_dec = pd.DataFrame([{'ID': decision_id, 'Date': pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"), 'Decision': st.session_state['wf_user_query'][:50], 'Status': "Pending"}])
                    if os.path.exists(dec_file):
                        df = pd.read_csv(dec_file)
                        df = pd.concat([new_dec, df], ignore_index=True)
                    else:
                        df = new_dec
                    df.to_csv(dec_file, index=False)
                    st.success(tr({'ar': "تم الإرسال بنجاح", 'en': "Sent successfully"}))
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
            else:
                 st.warning(tr({'ar': "تليجرام غير مفعل في secrets", 'en': "Telegram not configured"}))

        st.markdown("<br><hr>", unsafe_allow_html=True)
        
        # --- Decisions Log Section ---
        c_ai1, c_ai2 = st.columns([2, 1])
        with c_ai1:
            st.markdown(f"#### {tr({'ar': 'سجل قرارات القوى العاملة والتشغيل', 'en': 'Workforce Decisions Log'})}")
        with c_ai2:
            if telegram_configured:
                if st.button(tr({'ar': "تحديث حالات الاعتماد من تليجرام", 'en': "Sync Approvals"})):
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
                                    st.success(tr({'ar': "تمت المزامنة بنجاح", 'en': "Synced successfully"}))
                                    time.sleep(1)
                                    st.rerun()
                    except Exception as e:
                        st.error(f"Sync error: {e}")

        if os.path.exists(dec_file):
            dec_df = pd.read_csv(dec_file)
            display_cols = {
                'ID': 'ID', 
                'Date': tr({'ar': 'التاريخ', 'en': 'Date'}), 
                'Decision': tr({'ar': 'الموضوع / الاستفسار', 'en': 'Topic'}), 
                'Status': tr({'ar': 'حالة الاعتماد', 'en': 'Status'})
            }
            if 'Status' in dec_df.columns:
                dec_df.rename(columns=display_cols, inplace=True)
                def color_status(val):
                    color = '#f59e0b' if val == 'Pending' else '#10b981' if val == 'Approved' else '#ef4444'
                    return f'color: {color}; font-weight: bold'
                st.dataframe(dec_df.style.map(color_status, subset=[display_cols['Status']]), hide_index=True, use_container_width=True)
            else:
                st.dataframe(dec_df, hide_index=True, use_container_width=True)