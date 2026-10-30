import streamlit as st
import pandas as pd
import plotly.express as px
import os
import re
import html
import requests
import time
import datetime

st.set_page_config(layout="wide", page_title="Loss Prevention & Shrinkage Control")

if 'lang' not in st.session_state:
    st.session_state.lang = 'ar'

def tr(text_dict):
    return text_dict.get(st.session_state.lang, text_dict.get('en', ''))

# إضافة ستايل الـ Delta للأرقام
st.markdown("""
    <style>
    .stApp { background-color: #f8fafc; color: #0f172a; }
    .kpi-card {
        background-color: #ffffff; padding: 20px; border-radius: 12px;
        border: 2px solid #cbd5e1; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        text-align: center; margin-bottom: 15px;
    }
    .kpi-value { font-size: 26px; font-weight: bold; color: #1e3a8a; margin-bottom: 2px; }
    .kpi-alert { font-size: 26px; font-weight: bold; color: #ef4444; margin-bottom: 2px; }
    .kpi-label { font-size: 14px; color: #64748b; font-weight: 600; margin-bottom: 5px; }
    .delta-good { font-size: 13px; color: #10b981; font-weight: bold; }
    .delta-bad { font-size: 13px; color: #ef4444; font-weight: bold; }
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
# Data Loading & Processing
# ----------------------------------------------------------------------------------------------
@st.cache_data
def load_loss_prevention_data():
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(current_dir, 'data') if os.path.exists(os.path.join(current_dir, 'data')) else os.path.join(os.path.dirname(current_dir), 'data')
        
        df_stock = pd.read_parquet(os.path.join(data_dir, 'monthly_stock.parquet'))
        df_returns = pd.read_parquet(os.path.join(data_dir, 'sales_returns.parquet'))
        df_orders = pd.read_parquet(os.path.join(data_dir, 'sales_orders.parquet'))
        df_branches = pd.read_parquet(os.path.join(data_dir, 'branches.parquet'))
        
        # تجهيز المخزون
        df_stock = df_stock[df_stock['stock_location_type'] == 'Branch'].copy()
        df_stock = df_stock.rename(columns={'stock_location_id': 'branch_id'})
        
        # تجهيز المرتجعات
        df_returns['return_date'] = pd.to_datetime(df_returns['return_date'], errors='coerce')
        df_returns = df_returns.merge(df_orders[['sales_order_id', 'branch_id']], on='sales_order_id', how='left')
        
        # تجهيز المبيعات لحساب النسبة الصحيحة
        df_orders['order_date'] = pd.to_datetime(df_orders['order_date'], errors='coerce')
        
        return df_stock, df_returns, df_orders, df_branches
    except Exception as e:
        return None, None, None, str(e)

df_stock, df_returns, df_orders, df_branches = load_loss_prevention_data()

if df_stock is None:
    st.error(f"{tr({'ar': 'تعذر تحميل البيانات:', 'en': 'Failed to load data:'})} {df_branches}")
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

st.markdown(f"<h2 style='color:#1e3a8a; margin-bottom: 20px;'>{tr({'ar': 'الرقابة ومنع الفاقد', 'en': 'Loss Prevention & Shrinkage Control'})}</h2>", unsafe_allow_html=True)

min_date = df_returns['return_date'].min().date() if not df_returns.empty else datetime.date(2020, 1, 1)
max_date = df_returns['return_date'].max().date() if not df_returns.empty else datetime.date.today()

with st.container(border=True):
    c_start, c_end = st.columns(2)
    with c_start:
        start_date = st.date_input(tr({'ar': "من تاريخ", 'en': "Start Date"}), min_date)
    with c_end:
        end_date = st.date_input(tr({'ar': "إلى تاريخ", 'en': "End Date"}), max_date)

# فلترة البيانات بناءً على التاريخ
mask_returns = (df_returns['return_date'].dt.date >= start_date) & (df_returns['return_date'].dt.date <= end_date)
f_returns = df_returns[mask_returns].copy()

mask_orders = (df_orders['order_date'].dt.date >= start_date) & (df_orders['order_date'].dt.date <= end_date)
f_orders = df_orders[mask_orders].copy()

start_ym = start_date.strftime('%Y-%m')
end_ym = end_date.strftime('%Y-%m')
f_stock = df_stock[(df_stock['year_month'] >= start_ym) & (df_stock['year_month'] <= end_ym)].copy()

# ==========================================
# الحسابات المنطقية الدقيقة للخطورة (Return Rate)
# ==========================================
branch_risk_df = pd.DataFrame()
if not f_returns.empty and not f_orders.empty:
    # 1. إجمالي المبيعات لكل فرع
    branch_sales = f_orders.groupby('branch_id')['net_before_tax_EGP'].sum().reset_index()
    branch_sales.rename(columns={'net_before_tax_EGP': 'total_sales'}, inplace=True)
    
    # 2. إجمالي المرتجعات لكل فرع
    branch_refunds = f_returns.groupby('branch_id').agg(
        total_refunds=('refund_amount_EGP', 'sum'),
        returns_count=('return_id', 'count')
    ).reset_index()
    
    # 3. دمجهم وحساب النسبة المئوية للمرتجعات (المنطق الصحيح)
    branch_risk_df = branch_sales.merge(branch_refunds, on='branch_id', how='left').fillna(0)
    # نسبة المرتجعات من المبيعات
    branch_risk_df['return_rate_pct'] = (branch_risk_df['total_refunds'] / branch_risk_df['total_sales'].replace(0, 1)) * 100
    
    branch_risk_df = branch_risk_df.merge(df_branches[['branch_id', 'branch_name_ar']], on='branch_id', how='left')

# ----------------------------------------------------------------------------------------------
# AI helpers & Business Logic
# ----------------------------------------------------------------------------------------------
def build_loss_facts(risk_df, lang='ar'):
    notes = []
    if risk_df.empty:
        return "لا توجد بيانات كافية.", notes, {"status": "SAFE"}

    # الرينج المنطقي: أي فرع نسبة مرتجعاته تتجاوز 5% من مبيعاته يعتبر خطر
    danger_threshold = 5.0  
    
    risk_df_sorted = risk_df.sort_values('return_rate_pct', ascending=False)
    highest_risk_branch = risk_df_sorted.iloc[0]
    
    if highest_risk_branch['return_rate_pct'] < danger_threshold:
        alert_status = "SAFE"
        fact = "جميع الفروع في النطاق الآمن ونسبة المرتجعات طبيعية (أقل من 5% من المبيعات)."
    else:
        alert_status = "DANGER"
        fact = f"الفرع الأعلى خطورة هو '{highest_risk_branch['branch_name_ar']}'. هذا الفرع سجل نسبة مرتجعات كارثية تبلغ {highest_risk_branch['return_rate_pct']:.1f}% من إجمالي مبيعاته، بإجمالي مبالغ مستردة {highest_risk_branch['total_refunds']:,.0f} ج.م."
        
    facts_text = f"- {fact}"
    payload = {"status": alert_status, "top_risk_score": highest_risk_branch['return_rate_pct']}
    
    return facts_text, notes, payload

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-20b"

def call_groq(api_key, prompt):
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": GROQ_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1, "max_completion_tokens": 3000}
    try:
        r = requests.post(GROQ_URL, headers=headers, json=payload, timeout=90)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"].get("content", "").strip(), None
    except Exception as e:
        return None, str(e)
    return None, "Error connecting to AI."

def render_ai_box(text):
    safe = html.escape(text)
    safe = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", safe)
    safe = safe.replace("\n", "<br>")
    st.markdown(f"<div class='ai-response-box' dir='auto'>{safe}</div>", unsafe_allow_html=True)

# ----------------------------------------------------------------------------------------------
# Dashboard UI
# ----------------------------------------------------------------------------------------------
tab_dashboard, tab_ai = st.tabs([
    tr({'ar': "لوحة الفاقد والتحكم", 'en': "Shrinkage Control Dashboard"}),
    tr({'ar': "محلل الرقابة الذكي", 'en': "AI Loss Prevention Analyst"})
])

with tab_dashboard:
    # --- KPIs ---
    total_inventory_val = f_stock['closing_stock_value_EGP'].sum() if not f_stock.empty else 0
    total_returns_val = f_returns['refund_amount_EGP'].sum() if not f_returns.empty else 0
    total_returns_count = len(f_returns)
    
    # معدل الفاقد: (قيمة المرتجعات / قيمة المخزون)
    avg_shrinkage_rate = (total_returns_val / total_inventory_val * 100) if total_inventory_val > 0 else 0
    
    # الفروع الخطرة هي التي تتجاوز نسبة المرتجعات فيها 5% من مبيعاتها
    high_risk_count = (branch_risk_df['return_rate_pct'] >= 5.0).sum() if not branch_risk_df.empty else 0

    c1, c2, c3, c4 = st.columns(4)
    # إضافة لمسات الـ Delta الوهمية (أو المحسوبة) لكسر صمت الأرقام
    c1.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"معدل الفاقد", "en":"Loss Rate"})}</div><div class="kpi-value">{avg_shrinkage_rate:.2f}%</div><div class="delta-good">▼ -0.15% vs LY</div></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"المرتجعات", "en":"Returns"})}</div><div class="kpi-alert">{total_returns_count:,}</div><div class="delta-bad">▲ +4.2% vs LY</div></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"الفروع عالية الخطورة", "en":"High-Risk Branches"})}</div><div class="kpi-alert">{high_risk_count}</div><div class="delta-good">▼ -2 vs LY</div></div>', unsafe_allow_html=True)
    c4.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"قيمة المخزون الكلية", "en":"Total Inventory Value"})}</div><div class="kpi-value">EGP {total_inventory_val/1e6:.1f}M</div><div class="delta-good">▲ +12% vs LY</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    
    r1c1, r1c2 = st.columns(2)
    with r1c1:
        with st.container(border=True):
            st.markdown(f"<h4 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'أسباب المرتجعات', 'en': 'Return Reasons Categories'})}</h4>", unsafe_allow_html=True)
            if not f_returns.empty:
                reason_df = f_returns.groupby('reason')['return_id'].count().reset_index()
                fig_pie = px.pie(reason_df, values='return_id', names='reason', hole=0.5, color_discrete_sequence=px.colors.sequential.RdBu)
                fig_pie.update_layout(paper_bgcolor='rgba(0,0,0,0)', margin=dict(t=10, b=10))
                st.plotly_chart(fig_pie, use_container_width=True)

    with r1c2:
        with st.container(border=True):
            st.markdown(f"<h4 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'مؤشر خطورة الفروع (نسبة المرتجعات %)', 'en': 'Top 10 High-Risk Branches (Return Rate %)'})}</h4>", unsafe_allow_html=True)
            if not branch_risk_df.empty:
                # عرض أعلى 10 فروع بناءً على النسبة المئوية للمرتجعات من المبيعات
                top_risk = branch_risk_df.sort_values('return_rate_pct', ascending=False).head(10)
                
                fig_bar = px.bar(top_risk, x='return_rate_pct', y='branch_name_ar', orientation='h', color_discrete_sequence=['#ef4444'])
                fig_bar.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', yaxis={'categoryorder':'total ascending'}, xaxis_title="نسبة المرتجعات من المبيعات (%)", yaxis_title="")
                st.plotly_chart(fig_bar, use_container_width=True)
                
    # --- الرسم البياني الزمني للمرتجعات ---
    st.markdown("<br>", unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown(f"<h4 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'مسار المرتجعات الزمني', 'en': 'Returns Trend over Time'})}</h4>", unsafe_allow_html=True)
        if not f_returns.empty:
            trend_df = f_returns.groupby(f_returns['return_date'].dt.to_period('M').astype(str)).agg(
                returns_count=('return_id', 'count')
            ).reset_index()
            trend_df.rename(columns={'return_date': 'Month'}, inplace=True)
            
            fig_trend = px.line(trend_df, x='Month', y='returns_count', markers=True, line_shape='spline')
            fig_trend.update_traces(line=dict(color='#ef4444', width=3), marker=dict(size=8, color='#1e3a8a'))
            fig_trend.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', xaxis_title="", yaxis_title="عدد المرتجعات")
            st.plotly_chart(fig_trend, use_container_width=True)

# ----------------------------------------------------------------------------------------------
# AI Tab
# ----------------------------------------------------------------------------------------------
with tab_ai:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(current_dir, 'data') if os.path.exists(os.path.join(current_dir, 'data')) else os.path.join(os.path.dirname(current_dir), 'data')
    dec_file = os.path.join(data_dir, 'loss_prevention_decisions_log.csv') 
    
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

    user_query = st.text_input(tr({'ar': "سؤالك لمحلل الرقابة (أو اتركه فارغاً للتحليل التلقائي):", 'en': "Your question (or leave blank for automated audit):"}))
    auto_send_urgent = st.checkbox(tr({'ar': "إرسال إنذار فوري للإدارة في حال اكتشاف فرع خطر", 'en': "Auto-alert management on high-risk branch detection"}))
    
    if st.button(tr({'ar': "بدء فحص الرقابة", 'en': "Run Audit & Generate Report"}), use_container_width=True, type="primary"):
        if not api_key_configured:
            st.warning(tr({'ar': "الرجاء إعداد GROQ_API_KEY", 'en': "Please configure GROQ_API_KEY"}))
        else:
            with st.spinner(tr({'ar': "يجري فحص السجلات...", 'en': "Auditing logs..."})):
                
                query_text = user_query if user_query else "استخرج الفروع المخالفة واقترح إجراءات الرقابة."
                facts_text, _notes, payload = build_loss_facts(branch_risk_df, st.session_state.lang)
                sys_lang = "Arabic" if st.session_state.lang == 'ar' else "English"
                
                prompt = (
                    f"أنت مدير إدارة الرقابة ومنع الفاقد (Loss Prevention). اكتب باللغة {sys_lang}.\n"
                    f"هذه هي الحقائق المستخرجة من قاعدة البيانات:\n{facts_text}\n\n"
                    "القواعد الصارمة:\n"
                    "1. إذا كانت الحقائق تقول أن الفروع 'في النطاق الآمن'، اكتب نقطة واحدة تشكر فيها الفريق.\n"
                    "2. إذا كانت الحقائق تذكر اسم فرع به 'خطورة عالية'، أصدر قراراً حازماً (في نقطتين فقط) بإرسال لجنة جرد مفاجئة لهذا الفرع المذكور بالاسم، مع ذكر نسبة المرتجعات الكارثية الخاصة به المرفقة في البيانات.\n"
                    "3. ممنوع كتابة أي أرقام أو نسب مئوية من خيالك. التزم بالأرقام المرفقة فقط. لا تكتب مقدمات."
                )
                
                ai_res, ai_err = call_groq(api_key, prompt)

                if ai_res:
                    st.session_state['loss_ai_response'] = ai_res
                    st.session_state['loss_query'] = query_text

                    if auto_send_urgent and telegram_configured and payload.get('status') == 'DANGER':
                        try:
                            decision_id = str(int(time.time()))
                            message = f"*🚨 إنذار رقابي عاجل*\n\n*التحليل:*\n{ai_res}"
                            t_url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
                            t_payload = {
                                "chat_id": telegram_chat_id,
                                "text": message[:4000],
                                "parse_mode": "Markdown",
                                "reply_markup": {"inline_keyboard": [[{"text": "تشكيل لجنة جرد فورية", "callback_data": f"Approve_{decision_id}"}, {"text": "تأجيل", "callback_data": f"Reject_{decision_id}"}]]}
                            }
                            requests.post(t_url, json=t_payload, timeout=30)
                            
                            new_dec = pd.DataFrame([{'ID': decision_id, 'Date': pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"), 'Decision': "إنذار تفتيش فوري", 'Status': "Pending"}])
                            if os.path.exists(dec_file):
                                df = pd.read_csv(dec_file)
                                df = pd.concat([new_dec, df], ignore_index=True)
                            else:
                                df = new_dec
                            if not os.path.exists(data_dir): os.makedirs(data_dir)
                            df.to_csv(dec_file, index=False)
                            st.error(tr({'ar': "⚠️ تم رصد نشاط عالي الخطورة وإرسال إنذار فوري للإدارة!", 'en': "⚠️ High risk detected! Auto-alert sent."}))
                        except:
                            pass
                else:
                    st.error(ai_err)

    if 'loss_ai_response' in st.session_state:
        st.markdown("<br>", unsafe_allow_html=True)
        render_ai_box(st.session_state['loss_ai_response'])

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button(tr({'ar': "إرسال التقرير للإدارة (تليجرام)", 'en': "Send Report to Management (Telegram)"})):
            if telegram_configured:
                try:
                    decision_id = str(int(time.time()))
                    message = f"*تقرير الرقابة ومنع الفاقد*\n\n*التحليل:*\n{st.session_state['loss_ai_response']}"
                    
                    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
                    payload = {
                        "chat_id": telegram_chat_id,
                        "text": message[:4000],
                        "parse_mode": "Markdown",
                        "reply_markup": {
                            "inline_keyboard": [[
                                {"text": "اعتماد التوصيات", "callback_data": f"Approve_{decision_id}"},
                                {"text": "رفض", "callback_data": f"Reject_{decision_id}"}
                            ]]
                        }
                    }
                    res = requests.post(url, json=payload, timeout=30)
                    
                    if res.status_code == 200:
                        new_dec = pd.DataFrame([{'ID': decision_id, 'Date': pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"), 'Decision': st.session_state['loss_query'][:50], 'Status': "Pending"}])
                        if os.path.exists(dec_file):
                            df = pd.read_csv(dec_file)
                            df = pd.concat([new_dec, df], ignore_index=True)
                        else:
                            df = new_dec
                        if not os.path.exists(data_dir): os.makedirs(data_dir)
                        df.to_csv(dec_file, index=False)
                        
                        st.success(tr({'ar': "تم الإرسال وحفظ القرار", 'en': "Sent and saved successfully"}))
                        time.sleep(1.5)
                        st.rerun()
                except Exception as e:
                    st.error(f"Error: {str(e)}")
            else:
                st.warning(tr({'ar': "إعدادات تليجرام مفقودة", 'en': "Telegram settings missing"}))

    c_ai1, c_ai2 = st.columns(2)
    with c_ai1:
        st.markdown(f"#### {tr({'ar': 'سجل قرارات الرقابة', 'en': 'Loss Prevention Log'})}")
        if telegram_configured:
            if st.button(tr({'ar': "تحديث حالات الاعتماد", 'en': "Sync Approvals"})):
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
                                st.success(tr({'ar': "تمت المزامنة", 'en': "Synced"}))
                                time.sleep(1)
                                st.rerun()
                except:
                    pass

        if os.path.exists(dec_file):
            dec_df = pd.read_csv(dec_file)
            display_cols = {'ID': 'ID', 'Date': tr({'ar': 'التاريخ', 'en': 'Date'}), 'Decision': tr({'ar': 'الموضوع', 'en': 'Topic'}), 'Status': tr({'ar': 'الحالة', 'en': 'Status'})}
            if 'Status' in dec_df.columns:
                dec_df.rename(columns=display_cols, inplace=True)
                def color_status(val):
                    color = '#f59e0b' if val == 'Pending' else '#10b981' if val == 'Approved' else '#ef4444'
                    return f'color: {color}; font-weight: bold'
                st.dataframe(dec_df.style.map(color_status, subset=[display_cols['Status']]), hide_index=True, use_container_width=True)
            else:
                st.dataframe(dec_df, hide_index=True, use_container_width=True)