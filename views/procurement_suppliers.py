import streamlit as st
import pandas as pd
import plotly.express as px
import os
import re
import html
import requests
import time

st.set_page_config(layout="wide", page_title="Procurement & Suppliers")

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
# AI helpers & Business Logic
# ----------------------------------------------------------------------------------------------
def build_procurement_facts(f_df):
    notes = []
    if f_df.empty:
        return "لا توجد بيانات كافية في الفترة المختارة.", notes, {}

    # 1. Supplier Lead Time Performance
    supplier_stats = f_df.groupby('supplier_name_ar').agg(
        order_count=('po_id', 'nunique'),
        avg_lead=('lead_time_days', 'mean')
    ).dropna().reset_index()

    supplier_stats = supplier_stats[supplier_stats['order_count'] >= 5].sort_values('avg_lead')
    
    if len(supplier_stats) >= 2:
        best = supplier_stats.iloc[0]
        worst = supplier_stats.iloc[-1]
        gap = worst['avg_lead'] - best['avg_lead']
        supplier_fact = f"أفضل مورد: '{best['supplier_name_ar']}' ({best['avg_lead']:.1f} يوم). أبطأ مورد: '{worst['supplier_name_ar']}' ({worst['avg_lead']:.1f} يوم). الفارق بينهما {gap:.1f} يوم فقط."
    else:
        gap = 0
        supplier_fact = "بيانات الموردين غير كافية للمقارنة (أقل من موردين يمتلكان 5 طلبات)."

    # 2. Cash Flow Analysis
    total_spend = f_df['line_cost_EGP'].sum()
    if total_spend > 0:
        net30_spend = f_df[f_df['payment_terms_days'] <= 30]['line_cost_EGP'].sum()
        net30_pct = (net30_spend / total_spend) * 100
    else:
        net30_pct = 0

    cash_fact = f"المدفوعات العاجلة (مستحقة خلال 30 يوم أو أقل): {net30_pct:.1f}% من إجمالي المشتريات."

    facts_text = f"- {supplier_fact}\n- {cash_fact}"
    payload = {"gap": gap, "net30_pct": net30_pct}
    
    return facts_text, notes, payload

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-20b"

def call_groq(api_key, prompt):
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
    safe = html.escape(text)
    safe = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", safe)
    safe = safe.replace("\n", "<br>")
    st.markdown(f"<div class='ai-response-box' dir='auto'>{safe}</div>", unsafe_allow_html=True)

# ----------------------------------------------------------------------------------------------
# Data Loading
# ----------------------------------------------------------------------------------------------
@st.cache_data
def load_procurement_data():
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(current_dir, 'data') if os.path.exists(os.path.join(current_dir, 'data')) else os.path.join(os.path.dirname(current_dir), 'data')
        
        orders = pd.read_parquet(os.path.join(data_dir, 'purchase_orders.parquet'))
        items = pd.read_parquet(os.path.join(data_dir, 'purchase_order_items.parquet'))
        suppliers = pd.read_parquet(os.path.join(data_dir, 'suppliers.parquet'))
        
        orders['po_date'] = pd.to_datetime(orders['po_date'])
        items['delivery_date'] = pd.to_datetime(items['delivery_date'])
        
        df = items.merge(orders, on='po_id', how='left')
        
        if 'payment_terms_days' in df.columns and 'payment_terms_days' in suppliers.columns:
            suppliers = suppliers.drop(columns=['payment_terms_days'])
            
        df = df.merge(suppliers, on='supplier_id', how='left')
        
        df['lead_time_days'] = (df['delivery_date'] - df['po_date']).dt.days
        df['lead_time_days'] = df['lead_time_days'].clip(lower=0) 
        
        return df
    except Exception as e:
        return str(e)

df_merged = load_procurement_data()

if isinstance(df_merged, str):
    st.error(f"{tr({'ar': 'تعذر تحميل البيانات:', 'en': 'Failed to load data:'})} {df_merged}")
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

st.markdown(f"<h2 style='color:#1e3a8a; margin-bottom: 20px;'>{tr({'ar': 'أداء المشتريات والموردين', 'en': 'Procurement & Suppliers'})}</h2>", unsafe_allow_html=True)

min_date = df_merged['po_date'].min().date()
max_date = df_merged['po_date'].max().date()

with st.container(border=True):
    f1, f2, f3 = st.columns([1, 1, 2])
    with f1: start_date = st.date_input(tr({'ar': "من تاريخ", 'en': "Start Date"}), min_date)
    with f2: end_date = st.date_input(tr({'ar': "إلى تاريخ", 'en': "End Date"}), max_date)
    with f3:
        materials = df_merged['material_type'].dropna().unique().tolist()
        selected_materials = st.multiselect(tr({'ar': "نوع المادة الخام", 'en': "Material Type"}), materials, default=materials)

mask = (df_merged['po_date'].dt.date >= start_date) & (df_merged['po_date'].dt.date <= end_date) & (df_merged['material_type'].isin(selected_materials))
f_df = df_merged[mask].copy() 

total_spend = f_df['line_cost_EGP'].sum()
active_suppliers = f_df['supplier_id'].nunique()
avg_lead_time = f_df['lead_time_days'].mean()
net30_spend = f_df[f_df['payment_terms_days'] <= 30]['line_cost_EGP'].sum()
net30_pct = (net30_spend / total_spend * 100) if total_spend > 0 else 0

tab_dashboard, tab_ai = st.tabs([
    tr({'ar': "لوحة المشتريات", 'en': "Procurement Dashboard"}),
    tr({'ar': "المحلل الاستراتيجي للموردين", 'en': "Strategic Supplier Analyst"})
])

with tab_dashboard:
    c1, c2, c3, c4 = st.columns(4)
    # تعديل إجمالي المشتريات للقسمة على مليار وعرض B EGP
    c1.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"إجمالي المشتريات", "en":"Total Spend"})}</div><div class="kpi-value">{total_spend / 1e9:.2f}B EGP</div></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"عدد الموردين النشطين", "en":"Active Suppliers"})}</div><div class="kpi-value">{active_suppliers}</div></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"متوسط وقت التوريد", "en":"Avg Lead Time"})}</div><div class="kpi-value">{avg_lead_time:.1f} Days</div></div>', unsafe_allow_html=True)
    # تعديل المدفوعات العاجلة لعرض النسبة المئوية فقط
    c4.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"المدفوعات العاجلة (خلال شهر)", "en":"Urgent Payments (≤ 30 days)"})}</div><div class="kpi-value">{net30_pct:.1f}%</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    
    r1c1, r1c2 = st.columns(2)
    with r1c1:
        with st.container(border=True):
            st.markdown(f"<h4 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'متوسط تكلفة المواد الخام', 'en': 'Average Material Cost'})}</h4>", unsafe_allow_html=True)
            st.caption(tr({'ar': 'مقارنة لمتوسط سعر الوحدة لكل خامة خلال الفترة المحددة', 'en': 'Comparison of average unit price per material during the selected period.'}))
            if not f_df.empty:
                avg_cost = f_df.groupby('material_type')['unit_cost_EGP'].mean().sort_values().reset_index()
                fig_cost = px.bar(avg_cost, x='unit_cost_EGP', y='material_type', orientation='h', text_auto='.2f', color_discrete_sequence=['#3b82f6'])
                fig_cost.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', xaxis_title="متوسط السعر (ج.م)", yaxis_title="")
                st.plotly_chart(fig_cost, use_container_width=True)

    with r1c2:
        with st.container(border=True):
            st.markdown(f"<h4 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'تحليل شروط الدفع', 'en': 'Payment Terms Analysis'})}</h4>", unsafe_allow_html=True)
            st.caption(tr({'ar': 'فترات السماح لدفع أموال الموردين', 'en': 'Supplier payment grace periods.'}))
            if not f_df.empty:
                pay_terms = f_df.groupby('payment_terms_days')['line_cost_EGP'].sum().reset_index()
                pay_terms['payment_terms_days'] = pay_terms['payment_terms_days'].apply(lambda x: 'كاش (0 أيام)' if x == 0 else f'آجل ({x} يوم)')
                fig_terms = px.pie(pay_terms, values='line_cost_EGP', names='payment_terms_days', hole=0.4, color_discrete_sequence=px.colors.qualitative.Set2)
                fig_terms.update_layout(paper_bgcolor='rgba(0,0,0,0)', margin=dict(t=10, b=10))
                st.plotly_chart(fig_terms, use_container_width=True)

    with st.container(border=True):
        st.markdown(f"<h4 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'أسرع الموردين استجابة (أفضل 10)', 'en': 'Top 10 Fastest Suppliers'})}</h4>", unsafe_allow_html=True)
        if not f_df.empty:
            sup_perf = f_df.groupby('supplier_name_ar').agg(
                avg_lead_time=('lead_time_days', 'mean'),
                order_count=('po_id', 'nunique')
            ).reset_index()
            sup_perf = sup_perf[sup_perf['order_count'] >= 5].sort_values(by='avg_lead_time')
            
            top_10 = sup_perf.head(10)
            
            fig_sup = px.bar(
                top_10, 
                x='avg_lead_time', 
                y='supplier_name_ar', 
                orientation='h', 
                text_auto='.1f',
                color_discrete_sequence=['#10b981'] 
            )
            fig_sup.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', yaxis={'categoryorder':'total descending'}, xaxis_title="متوسط وقت التوريد (بالأيام)", yaxis_title="")
            st.plotly_chart(fig_sup, use_container_width=True)

with tab_ai:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(current_dir, 'data') if os.path.exists(os.path.join(current_dir, 'data')) else os.path.join(os.path.dirname(current_dir), 'data')
    dec_file = os.path.join(data_dir, 'procurement_decisions_log.csv') 
    
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

    user_query = st.text_input(tr({'ar': "سؤالك للمحلل (أو اتركه فارغاً للتحليل التلقائي الشامل):", 'en': "Your question (or leave blank for automated analysis):"}))
    auto_send_urgent = st.checkbox(tr({'ar': "إرسال تلقائي للإدارة في حال وجود تنبيهات سيولة هامة", 'en': "Auto-send to management on severe cash flow alerts"}))
    
    if st.button(tr({'ar': "تحليل وإصدار التقرير", 'en': "Analyze & Generate Report"}), use_container_width=True, type="primary", key="run_procurement_ai"):
        if not api_key_configured:
            st.warning(tr({'ar': "الرجاء إعداد GROQ_API_KEY", 'en': "Please configure GROQ_API_KEY"}))
        elif f_df.empty:
            st.warning(tr({'ar': "لا توجد بيانات في الفترة المختارة.", 'en': "No data in the selected period."}))
        else:
            with st.spinner(tr({'ar': "يجري التحليل...", 'en': "Analyzing..."})):
                
                query_text = user_query if user_query else "قم بتقديم تحليل شامل لأداء الموردين والسيولة النقدية واقترح خطة عمل."
                facts_text, _notes, payload = build_procurement_facts(f_df)
                
                prompt = (
                    "أنت مدير مالي ولوجستي (CFO & Supply Chain Analyst) لشركة تصنيع كبرى.\n"
                    f"الفترة: من {start_date} إلى {end_date}\n"
                    f"إجمالي المشتريات: {total_spend / 1e9:.2f} مليار ج.م\n\n"
                    "الحقائق التالية تم حسابها برمجياً بدقة (استخدمها كما هي ولا تخترع أرقاماً جديدة):\n"
                    f"{facts_text}\n\n"
                    f"الطلب: {query_text}\n\n"
                    "قواعد التقرير الصارمة:\n"
                    "1. استخدم الأرقام المعطاة فقط. ممنوع اختراع أي مشكلة غير موجودة في الأرقام.\n"
                    "2. إذا كانت 'الفجوة' في وقت التوريد أقل من 3 أيام، اكتب صراحة أن أداء الموردين ممتاز ومتقارب جداً ولا يوجد تأخيرات جوهرية تستدعي القلق.\n"
                    "3. إذا كانت 'المدفوعات العاجلة' أكبر من 30%، أصدر تحذير سيولة واقترح التفاوض لدفع آجل (Net 60/90). إذا كانت أقل، اذكر أن السيولة آمنة.\n"
                    "4. اكتب بأسلوب تنفيذي (Bullet points) باللغة العربية. استخدم العناوين التالية فقط:\n"
                    "**تحليل أداء الموردين:**\n"
                    "**تحليل السيولة النقدية:**\n"
                    "**خطة العمل:**"
                )
                
                ai_response, ai_error = call_groq(api_key, prompt)

                if not ai_response:
                    st.warning(tr({'ar': "الموديل لم يُرجع إجابة. حاولي مرة أخرى.", 'en': "The model did not return an answer. Please try again."}))
                    if ai_error:
                        st.caption(ai_error)
                else:
                    st.session_state['last_proc_ai_response'] = ai_response
                    st.session_state['last_proc_query'] = query_text
                    st.session_state['last_proc_facts'] = facts_text

                    try:
                        if auto_send_urgent and telegram_configured and (payload.get('net30_pct', 0) > 40):
                            decision_id = str(int(time.time()))
                            message = f"*🚨 تنبيه المشتريات التلقائي*\n\n*الطلب:* {query_text}\n\n*التحليل:*\n{ai_response}"
                            safe_msg = message[:4000]
                            t_url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
                            t_payload = {
                                "chat_id": telegram_chat_id,
                                "text": safe_msg,
                                "parse_mode": "Markdown",
                                "reply_markup": {"inline_keyboard": [[{"text": "اعتماد الأكشن", "callback_data": f"Approve_{decision_id}"}, {"text": "تأجيل", "callback_data": f"Reject_{decision_id}"}]]}
                            }
                            res_t = requests.post(t_url, json=t_payload, timeout=30)
                            if res_t.status_code == 200:
                                new_dec = pd.DataFrame([{'ID': decision_id, 'Date': pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"), 'Decision': query_text[:50] + " (Auto Alert)", 'Status': "Pending"}])
                                if os.path.exists(dec_file):
                                    df = pd.read_csv(dec_file)
                                    df = pd.concat([new_dec, df], ignore_index=True)
                                else:
                                    df = new_dec
                                df.to_csv(dec_file, index=False)
                                st.info(tr({'ar': "تم الإرسال تلقائياً إلى الإدارة نظراً لتجاوز الحدود الحرجة في المدفوعات العاجلة.", 'en': "Auto-sent to Management due to critical thresholds."}))
                    except Exception as e:
                        st.error(f"Error: {str(e)}")

    if 'last_proc_ai_response' in st.session_state:
        st.markdown("<br>", unsafe_allow_html=True)
        render_ai_box(st.session_state['last_proc_ai_response'])
        if st.session_state.get('last_proc_facts'):
            with st.expander(tr({'ar': "الأرقام التي بُني عليها التقرير", 'en': "Backend calculations"})):
                st.markdown(st.session_state['last_proc_facts'])

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button(tr({'ar': "إرسال التقرير إلى الإدارة وحفظ القرار", 'en': "Send to Management & Save"})):
            if telegram_configured:
                try:
                    decision_id = str(int(time.time()))
                    message = f"*تقرير المشتريات والموردين*\n\n*الطلب:* {st.session_state['last_proc_query']}\n\n*التحليل:*\n{st.session_state['last_proc_ai_response']}"
                    safe_message = message[:4000]

                    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
                    payload = {
                        "chat_id": telegram_chat_id,
                        "text": safe_message,
                        "parse_mode": "Markdown",
                        "reply_markup": {
                            "inline_keyboard": [[
                                {"text": "اعتماد خطة المشتريات", "callback_data": f"Approve_{decision_id}"},
                                {"text": "رفض/تأجيل", "callback_data": f"Reject_{decision_id}"}
                            ]]
                        }
                    }
                    response = requests.post(url, json=payload, timeout=30)
                    
                    if response.status_code == 200:
                        new_decision = pd.DataFrame([{
                            'ID': decision_id,
                            'Date': pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
                            'Decision': st.session_state['last_proc_query'][:50],
                            'Status': "Pending"
                        }])
                        if os.path.exists(dec_file):
                            existing_df = pd.read_csv(dec_file)
                            updated_df = pd.concat([new_decision, existing_df], ignore_index=True)
                        else:
                            updated_df = new_decision
                        updated_df.to_csv(dec_file, index=False)
                        
                        st.success(tr({'ar': "تم الإرسال إلى الإدارة وحفظ القرار في السجل بنجاح", 'en': "Sent to Management and saved to log successfully"}))
                        time.sleep(1.5)
                        st.rerun()
                    else:
                        st.error(f"Telegram Error: {response.text}")
                except Exception as e:
                    st.error(f"Error: {str(e)}")
            else:
                st.warning(tr({'ar': "إعدادات تليجرام غير موجودة في secrets.toml", 'en': "Telegram settings missing"}))

    c_ai1, c_ai2 = st.columns(2)
    with c_ai1:
        st.markdown(f"#### {tr({'ar': 'سجل قرارات المشتريات والموردين', 'en': 'Procurement Decisions Log'})}")
        if telegram_configured:
            if st.button(tr({'ar': "تحديث ردود الإدارة", 'en': "Sync Management Responses"})):
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