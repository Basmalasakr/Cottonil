import streamlit as st
import pandas as pd
import plotly.express as px
import os
import time
import requests
import html
import re
import numpy as np

# ==========================================
# 1. إعدادات اللغة (Bilingual Support)
# ==========================================
if 'lang' not in st.session_state:
    st.session_state.lang = 'ar'

def tr(text_dict):
    return text_dict.get(st.session_state.lang, text_dict.get('en', ''))

st.sidebar.markdown(f"<h3>{tr({'ar': 'إعدادات اللغة', 'en': 'Language Settings'})}</h3>", unsafe_allow_html=True)
selected_lang = st.sidebar.radio(
    tr({'ar': "اختر اللغة", 'en': "Select Language"}),
    options=['ar', 'en'],
    index=0 if st.session_state.lang == 'ar' else 1,
    key="branch_lang_selector"
)
if selected_lang != st.session_state.lang:
    st.session_state.lang = selected_lang
    st.rerun()

# ==========================================
# 2. معالجة البيانات وبناء المؤشرات (Business Logic)
# ==========================================
@st.cache_data
def get_branch_metrics():
    df_sales = pd.read_parquet('data/sales_orders.parquet')
    df_branches = pd.read_parquet('data/branches.parquet')
    df_employees = pd.read_parquet('data/employees.parquet')
    df_opex = pd.read_parquet('data/operating_expenses.parquet')
    
    # حساب COGS (التكلفة) إن وُجدت، أو استخدام نسبة تقديرية
    try:
        df_po_items = pd.read_parquet('data/purchase_order_items.parquet')
        df_so_items = pd.read_parquet('data/sales_order_items.parquet')
        avg_cost = df_po_items.groupby('sku_id')['unit_cost_EGP'].mean().reset_index()
        if 'sku_id' in df_so_items.columns:
            so_with_cost = df_so_items.merge(avg_cost, on='sku_id', how='left')
            so_with_cost['line_cogs'] = so_with_cost['quantity'] * so_with_cost['unit_cost_EGP'].fillna(0)
            order_cogs = so_with_cost.groupby('sales_order_id')['line_cogs'].sum().reset_index()
            df_sales = df_sales.merge(order_cogs, on='sales_order_id', how='left')
        else:
            df_sales['line_cogs'] = df_sales['net_before_tax_EGP'] * 0.6 
    except Exception:
        df_sales['line_cogs'] = df_sales['net_before_tax_EGP'] * 0.6

    df_sales['line_cogs'] = df_sales['line_cogs'].fillna(df_sales['net_before_tax_EGP'] * 0.6)

    # حساب المرتجعات إن وُجدت
    try:
        df_returns = pd.read_parquet('data/sales_returns.parquet')
        returns_grp = df_returns.groupby('sales_order_id')['refund_amount_EGP'].sum().reset_index()
        df_sales = df_sales.merge(returns_grp, on='sales_order_id', how='left')
        df_sales['refund_amount_EGP'] = df_sales['refund_amount_EGP'].fillna(0)
    except Exception:
        df_sales['refund_amount_EGP'] = 0

    # تجميع المبيعات لكل فرع
    sales_grp = df_sales.groupby('branch_id').agg(
        revenue=('net_before_tax_EGP', 'sum'),
        cogs=('line_cogs', 'sum'),
        refunds=('refund_amount_EGP', 'sum'),
        orders=('sales_order_id', 'count')
    ).reset_index()

    sales_grp['avg_basket'] = sales_grp['revenue'] / sales_grp['orders']
    sales_grp['return_rate_pct'] = (sales_grp['refunds'] / sales_grp['revenue'].replace(0, 1)) * 100

    emp_grp = df_employees.groupby('branch_id')['employee_id'].count().reset_index(name='headcount')
    opex_grp = df_opex.groupby('branch_or_department_id')['amount_EGP'].sum().reset_index(name='opex')
    opex_grp.rename(columns={'branch_or_department_id': 'branch_id'}, inplace=True)

    # الربط النهائي
    cols_to_keep = ['branch_id', 'branch_name_ar', 'branch_name_en', 'governorate_ar', 'governorate_en', 'retail_location_type']
    cols_exist = [c for c in cols_to_keep if c in df_branches.columns]
    df = df_branches[cols_exist].merge(sales_grp, on='branch_id', how='left')
    df = df.merge(emp_grp, on='branch_id', how='left')
    df = df.merge(opex_grp, on='branch_id', how='left').fillna(0)

    # حساب الربحية الحقيقية
    df['sales_per_emp'] = df['revenue'] / df['headcount'].replace(0, 1)
    df['net_profit'] = df['revenue'] - df['cogs'] - df['opex']
    df['margin_pct'] = (df['net_profit'] / df['revenue'].replace(0, 1)) * 100

    # مؤشر الصحة الخماسي (Percentile Ranking)
    df['p_rev'] = df['revenue'].rank(pct=True) * 100
    df['p_basket'] = df['avg_basket'].rank(pct=True) * 100
    df['p_emp'] = df['sales_per_emp'].rank(pct=True) * 100
    df['p_margin'] = df['margin_pct'].rank(pct=True) * 100
    df['p_returns'] = df['return_rate_pct'].rank(pct=True, ascending=False) * 100 
    
    df['health_score'] = ((df['p_margin'] * 0.25) + (df['p_rev'] * 0.20) + (df['p_basket'] * 0.20) + (df['p_emp'] * 0.20) + (df['p_returns'] * 0.15)).round(1)

    # تحديد نقطة الضعف برمجياً
    def get_weakness(row):
        scores = {
            'margin': row['p_margin'], 'basket': row['p_basket'], 'emp': row['p_emp'], 'returns': row['p_returns'], 'rev': row['p_rev']
        }
        weak_key = min(scores, key=scores.get)
        return weak_key
        
    df['weakness_key'] = df.apply(get_weakness, axis=1)

    return df

# قاموس ترجمة العيوب
WEAKNESS_MAP = {
    'margin': {'ar': 'انخفاض الهامش (مراجعة المصروفات)', 'en': 'Low Margin (Review OPEX)'},
    'basket': {'ar': 'حجم السلة صغير (يحتاج عروض Bundles)', 'en': 'Small Basket (Needs Bundles)'},
    'emp': {'ar': 'ضعف إنتاجية الموظف (يحتاج تدريب وتارجت)', 'en': 'Low Staff Productivity (Needs Training)'},
    'returns': {'ar': 'ارتفاع المرتجعات (مراجعة الجودة)', 'en': 'High Returns (Review Quality)'},
    'rev': {'ar': 'تراجع المبيعات (يحتاج تنشيط محلي)', 'en': 'Low Sales (Needs Local Promo)'}
}

def build_ai_context(df, analysis_type, lang):
    if df.empty: return "No data."
    b_name = 'branch_name_ar' if lang == 'ar' else 'branch_name_en'
    gov_name = 'governorate_ar' if lang == 'ar' else 'governorate_en'
    if b_name not in df.columns: b_name = 'branch_name_ar'
    if gov_name not in df.columns: gov_name = 'governorate_ar'

    if analysis_type == "health":
        weak = df.nsmallest(3, 'health_score')
        lines = []
        for _, r in weak.iterrows():
            w_text = WEAKNESS_MAP.get(r['weakness_key'], {}).get(lang, '')
            lines.append(f"- {r[b_name]} | Score: {r['health_score']}/100 | Defect: {w_text}")
        return "\n".join(lines)
        
    elif analysis_type == "twin":
        lines = []
        loc_col = 'retail_location_type' if 'retail_location_type' in df.columns else gov_name
        grouped = df.groupby([gov_name, loc_col])
        for (gov, loc_type), group in grouped:
            if len(group) >= 2:
                top = group.nlargest(1, 'revenue').iloc[0]
                bottom = group.nsmallest(1, 'revenue').iloc[0]
                w_text = WEAKNESS_MAP.get(bottom['weakness_key'], {}).get(lang, '')
                lines.append(f"Location: {gov} ({loc_type})")
                lines.append(f"  * Top: {top[b_name]} ({top['revenue']/1e6:.1f}M)")
                lines.append(f"  * Lagging: {bottom[b_name]} ({bottom['revenue']/1e6:.1f}M | Defect: {w_text})")
        return "\n".join(lines)

    return ""

# ==========================================
# 3. إعدادات الـ AI (Groq)
# ==========================================
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-20b"

def call_groq(api_key, prompt):
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": GROQ_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1, "max_completion_tokens": 3000}
    try:
        r = requests.post(GROQ_URL, headers=headers, json=payload, timeout=90)
        return (r.json()["choices"][0]["message"].get("content", "").strip(), None) if r.status_code == 200 else (None, f"HTTP Error {r.status_code}")
    except Exception as e:
        return None, str(e)

def render_ai_box(text):
    clean_text = re.sub(r'\n\s*-\s*\n', '\n', text)
    safe = html.escape(clean_text).replace("\n", "<br>")
    safe = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", safe)
    st.markdown(f"<div style='padding: 25px; background: #F4F6FA; border: 2px solid #2BB3F3; border-radius: 12px; line-height: 1.8; color: #1B2F7A;' dir='auto'>{safe}</div>", unsafe_allow_html=True)

# ==========================================
# 4. بناء الواجهة (Bilingual UI)
# ==========================================
st.markdown(f"<h2 style='color:#1B2F7A; font-weight:800; margin-bottom: 0;'>{tr({'ar': 'أداء الفروع والربحية', 'en': 'Branch Performance & Profitability'})}</h2>", unsafe_allow_html=True)

df_metrics = get_branch_metrics()

tab_analytics, tab_ai = st.tabs([
    tr({'ar': "التحليل المالي والمقارنة", 'en': "Financial Analysis"}), 
    tr({'ar': "المساعد الذكي لتطوير الفروع", 'en': "AI Branch Assistant"})
])

with tab_analytics:
    total_rev = df_metrics['revenue'].sum()
    avg_basket = df_metrics['avg_basket'].mean()
    total_net_profit = df_metrics['net_profit'].sum()
    overall_margin = (total_net_profit / total_rev * 100) if total_rev > 0 else 0

    cols = st.columns(4)
    cols[0].markdown(f"<div style='background:#fff; padding:15px; border-radius:10px; border:1px solid #E1E6EE;'><div style='color:#667085; font-size:14px;'>{tr({'ar':'الكفاءة التشغيلية','en':'Operational Efficiency'})}</div><div style='color:#1B2F7A; font-size:24px; font-weight:bold;'>{overall_margin:.1f}%</div></div>", unsafe_allow_html=True)
    cols[1].markdown(f"<div style='background:#fff; padding:15px; border-radius:10px; border:1px solid #E1E6EE;'><div style='color:#667085; font-size:14px;'>{tr({'ar':'متوسط حجم السلة','en':'Avg Basket Size'})}</div><div style='color:#1B2F7A; font-size:24px; font-weight:bold;'>EGP {avg_basket:,.0f}</div></div>", unsafe_allow_html=True)
    cols[2].markdown(f"<div style='background:#fff; padding:15px; border-radius:10px; border:1px solid #E1E6EE;'><div style='color:#667085; font-size:14px;'>{tr({'ar':'إجمالي المبيعات','en':'Total Revenue'})}</div><div style='color:#1B2F7A; font-size:24px; font-weight:bold;'>EGP {total_rev/1e6:.1f}M</div></div>", unsafe_allow_html=True)
    cols[3].markdown(f"<div style='background:#fff; padding:15px; border-radius:10px; border:1px solid #E1E6EE;'><div style='color:#667085; font-size:14px;'>{tr({'ar':'إجمالي الفروع','en':'Total Branches'})}</div><div style='color:#1B2F7A; font-size:24px; font-weight:bold;'>{len(df_metrics)}</div></div>", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ------------------------------------------
    # الرسوم البيانية (Charts)
    # ------------------------------------------
    b_col = 'branch_name_ar' if st.session_state.lang == 'ar' else 'branch_name_en'
    gov_col = 'governorate_ar' if st.session_state.lang == 'ar' else 'governorate_en'
    if b_col not in df_metrics.columns: b_col = 'branch_name_ar'
    if gov_col not in df_metrics.columns: gov_col = 'governorate_ar'

    chart_cols = st.columns([2, 1])
    
    with chart_cols[0]:
        st.markdown(f"<div style='color:#1B2F7A; font-weight:700;'>{tr({'ar': 'مقارنة أداء المحافظات (إيرادات)', 'en': 'Governorate Performance (Revenue)'})}</div>", unsafe_allow_html=True)
        gov_df = df_metrics.groupby(gov_col).agg({'revenue':'sum'}).reset_index()
        fig_gov = px.bar(gov_df, x=gov_col, y='revenue', title="")
        fig_gov.update_traces(marker_color='#2BB3F3')
        fig_gov.update_layout(xaxis_title="", yaxis_title="")
        st.plotly_chart(fig_gov, use_container_width=True)

    with chart_cols[1]:
        st.markdown(f"<div style='color:#1B2F7A; font-weight:700;'>{tr({'ar': 'أفضل الفروع أداءً', 'en': 'Top Performing Branches'})}</div>", unsafe_allow_html=True)
        top_branches = df_metrics.sort_values('revenue', ascending=False).head(5)
        fig_top = px.bar(top_branches.sort_values('revenue', ascending=True), x='revenue', y=b_col, orientation='h')
        fig_top.update_traces(marker_color='#1B2F7A')
        fig_top.update_layout(xaxis_title="", yaxis_title="")
        st.plotly_chart(fig_top, use_container_width=True)

    st.markdown("<br>", unsafe_allow_html=True)
    
    st.markdown(f"<div style='color:#1B2F7A; font-weight:700; margin-top:20px;'>{tr({'ar': 'مكونات مؤشر صحة الفروع (Percentile Ranking)', 'en': 'Branch Health Score Components'})}</div>", unsafe_allow_html=True)
    
    # تجهيز الجدول للعرض حسب اللغة
    display_df = df_metrics.copy()
    display_df['ضعف_مترجم'] = display_df['weakness_key'].apply(lambda k: WEAKNESS_MAP.get(k, {}).get(st.session_state.lang, ''))
    
    cols_order = [b_col, 'revenue', 'avg_basket', 'return_rate_pct', 'margin_pct', 'health_score', 'ضعف_مترجم']
    display_df = display_df[cols_order]
    
    if st.session_state.lang == 'ar':
        display_df.columns = ['الفرع', 'المبيعات', 'متوسط السلة', 'المرتجعات', 'الهامش الحقيقي', 'مؤشر الصحة (0-100)', 'أكبر نقطة ضعف (تحتاج تدخل)']
    else:
        display_df.columns = ['Branch', 'Revenue', 'Avg Basket', 'Return Rate', 'Real Margin', 'Health Score (0-100)', 'Primary Weakness (Action Needed)']
    
    sort_col = 'مؤشر الصحة (0-100)' if st.session_state.lang == 'ar' else 'Health Score (0-100)'
    display_df = display_df.sort_values(sort_col, ascending=True)
    
    st.dataframe(display_df.style.format({
        'المبيعات': '{:,.0f}', 'Revenue': '{:,.0f}',
        'متوسط السلة': '{:,.0f}', 'Avg Basket': '{:,.0f}',
        'المرتجعات': '{:.1f}%', 'Return Rate': '{:.1f}%',
        'الهامش الحقيقي': '{:.1f}%', 'Real Margin': '{:.1f}%',
        'مؤشر الصحة (0-100)': '{:.1f}', 'Health Score (0-100)': '{:.1f}'
    }), use_container_width=True)

with tab_ai:
    api_key_configured, telegram_configured = False, False
    try:
        api_key = st.secrets.get("GROQ_API_KEY", "")
        if api_key: api_key_configured = True
        telegram_token = st.secrets.get("TELEGRAM_TOKEN", "")
        telegram_chat_id = st.secrets.get("TELEGRAM_CHAT_ID", "")
        if telegram_token and telegram_chat_id: telegram_configured = True
    except:
        pass

    dec_file = 'data/branch_decisions_log.csv'

    c_ai1, c_ai2 = st.columns([1, 1])
    
    with c_ai1:
        analysis_options = {
            "health": tr({'ar': "مؤشر صحة الفروع (توصيات بناءً على العيوب المكتشفة)", 'en': "Branch Health Score (Recommendations based on defects)"}),
            "twin": tr({'ar': "مقارنة التوائم (مقارنة نوع الموقع: مول بمول، شارع بشارع)", 'en': "Twin Benchmarking (Same Location Type & Governorate)"})
        }
        selected_option = st.selectbox(tr({'ar': "نوع التحليل الإداري:", 'en': "Analysis Type:"}), list(analysis_options.keys()), format_func=lambda x: analysis_options[x])
        
        btn_label = tr({'ar': "توليد التقرير", 'en': "Generate Report"})
        if st.button(btn_label, type="primary"):
            if not api_key_configured:
                st.error(tr({'ar': "الرجاء إعداد GROQ_API_KEY.", 'en': "Please set GROQ_API_KEY."}))
            else:
                with st.spinner(tr({'ar': "جاري صياغة التقرير...", 'en': "Drafting report..."})):
                    context_data = build_ai_context(df_metrics, selected_option, st.session_state.lang)
                    
                    sys_lang = "Arabic" if st.session_state.lang == 'ar' else "English"
                    
                    prompts = {
                        "health": (
                            f"You are a retail data analyst. Write the report in {sys_lang}.\n"
                            f"Data of weakest branches with their computed defect:\n{context_data}\n\n"
                            "Task: Write a direct executive report. State the branch, its score, and propose the exact solution mentioned in the 'Defect' section of the data. Do NOT invent external solutions like decorations. No intros."
                        ),
                        "twin": (
                            f"You are a retail data analyst. Write the report in {sys_lang}.\n"
                            f"Data compares branches with the same location type:\n{context_data}\n\n"
                            "Task: Extract up to 3 pairs with a noticeable sales gap. State the top branch and lagging branch. Propose a solution for the lagging branch based ONLY on the provided 'Defect' note. Do NOT invent solutions. No intros."
                        )
                    }
                    
                    ai_res, ai_err = call_groq(api_key, prompts[selected_option])
                    if ai_res:
                        st.session_state['branch_ai_response'] = ai_res
                        st.session_state['branch_ai_title'] = analysis_options[selected_option]
                    else:
                        st.error(ai_err)

        if 'branch_ai_response' in st.session_state:
            st.markdown(f"**{tr({'ar': 'تقرير:', 'en': 'Report:'})} {st.session_state['branch_ai_title']}**")
            render_ai_box(st.session_state['branch_ai_response'])
            
            st.markdown("<br>", unsafe_allow_html=True)
            send_btn = tr({'ar': "إرسال التقرير لاعتماد الإدارة (تليجرام)", 'en': "Send to Management for Approval (Telegram)"})
            if st.button(send_btn):
                if telegram_configured:
                    try:
                        decision_id = str(int(time.time()))
                        topic_label = "الموضوع:" if st.session_state.lang == 'ar' else "Topic:"
                        report_label = "التقرير:" if st.session_state.lang == 'ar' else "Report:"
                        
                        message = f"*Cotonil Branch Performance*\n\n*{topic_label}* {st.session_state['branch_ai_title']}\n\n*{report_label}*\n{st.session_state['branch_ai_response']}"
                        
                        url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
                        payload = {
                            "chat_id": telegram_chat_id,
                            "text": message[:4000],
                            "parse_mode": "Markdown",
                            "reply_markup": {
                                "inline_keyboard": [[
                                    {"text": "Approve / اعتماد", "callback_data": f"Approve_{decision_id}"},
                                    {"text": "Reject / رفض", "callback_data": f"Reject_{decision_id}"}
                                ]]
                            }
                        }
                        res = requests.post(url, json=payload, timeout=30)
                        if res.status_code == 200:
                            new_dec = pd.DataFrame([{'ID': decision_id, 'Date': pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"), 'Decision': st.session_state['branch_ai_title'], 'Status': "Pending"}])
                            if os.path.exists(dec_file):
                                df_exist = pd.read_csv(dec_file)
                                df_updated = pd.concat([new_dec, df_exist], ignore_index=True)
                            else:
                                df_updated = new_dec
                            if not os.path.exists('data'): os.makedirs('data')
                            df_updated.to_csv(dec_file, index=False)
                            st.success(tr({'ar': "تم الإرسال وحفظ القرار بحالة 'معلق'.", 'en': "Sent successfully and saved as 'Pending'."}))
                        else:
                            st.error(tr({'ar': "خطأ تليجرام.", 'en': "Telegram error."}))
                    except Exception as e:
                        st.error(str(e))
                else:
                    st.warning(tr({'ar': "إعدادات تليجرام مفقودة.", 'en': "Telegram settings missing."}))

    with c_ai2:
        st.markdown(f"<h4 style='color:#1B2F7A;'>{tr({'ar': 'سجل الاعتمادات', 'en': 'Approvals Log'})}</h4>", unsafe_allow_html=True)
        if telegram_configured:
            sync_btn = tr({'ar': "تحديث الحالات من تليجرام (Sync)", 'en': "Sync Status from Telegram"})
            if st.button(sync_btn):
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
                                st.success(tr({'ar': "تم تحديث الحالات بنجاح.", 'en': "Status synced successfully."}))
                                time.sleep(1)
                                st.rerun()
                except:
                    pass

        if os.path.exists(dec_file):
            dec_df = pd.read_csv(dec_file)
            
            if st.session_state.lang == 'ar':
                dec_df.rename(columns={'Date': 'التاريخ', 'Decision': 'الموضوع', 'Status': 'الحالة'}, inplace=True)
            
            status_col = 'الحالة' if st.session_state.lang == 'ar' else 'Status'
            
            def color_status(val):
                color = '#f59e0b' if val == 'Pending' else '#10b981' if val == 'Approved' else '#ef4444'
                return f'color: {color}; font-weight: bold'
                
            if status_col in dec_df.columns:
                st.dataframe(dec_df.style.map(color_status, subset=[status_col]), hide_index=True, use_container_width=True)
            else:
                st.dataframe(dec_df, hide_index=True, use_container_width=True)