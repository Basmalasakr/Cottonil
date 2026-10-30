import streamlit as st
import pandas as pd
import plotly.express as px
import os
import re
import html
import requests
import joblib
import time

st.set_page_config(layout="wide", page_title="Executive Command Center")

if 'lang' not in st.session_state:
    st.session_state.lang = 'ar'

def tr(text_dict):
    return text_dict.get(st.session_state.lang, text_dict.get('en', ''))

st.markdown("""
    <style>
    .stApp { background-color: #f8fafc; color: #1e3a8a; }
    .kpi-card {
        background-color: #ffffff; padding: 20px; border-radius: 12px;
        border: 1px solid #cbd5e1; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        text-align: center; margin-bottom: 15px;
    }
    .kpi-value { font-size: 26px; font-weight: bold; color: #1e3a8a; margin-bottom: 5px; }
    .kpi-label { font-size: 14px; color: #64748b; font-weight: 600; }
    div[data-testid="stSidebar"] { background-color: #ffffff; border-right: 1px solid #e2e8f0; }
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 12px; border: 2px solid #94a3b8 !important; 
        background-color: #ffffff; padding: 15px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    }
    .ai-response-box {
        padding: 25px; background-color: #eef2ff; border: 2px solid #6366f1;
        border-radius: 12px; font-size: 16px; line-height: 1.8; color: #1e3a8a;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); margin-bottom: 20px;
    }
    h1, h2, h3, h4, h5, h6, p, span, div { color: #1e3a8a; }
    </style>
""", unsafe_allow_html=True)

AR_MONTHS = {1: "يناير", 2: "فبراير", 3: "مارس", 4: "أبريل", 5: "مايو", 6: "يونيو",
             7: "يوليو", 8: "أغسطس", 9: "سبتمبر", 10: "أكتوبر", 11: "نوفمبر", 12: "ديسمبر"}

def month_label(ts):
    return f"{AR_MONTHS[ts.month]} {ts.year}"

def build_executive_facts(f_orders):
    if f_orders.empty:
        return "لا توجد بيانات كافية."

    daily = f_orders.groupby(f_orders['order_date'].dt.date)['net_before_tax_EGP'].sum()
    if len(daily) >= 2:
        last_day_val = daily.iloc[-1]
        prev_day_val = daily.iloc[-2]
        growth = (last_day_val / prev_day_val - 1) * 100 if prev_day_val > 0 else 0
        daily_text = f"مبيعات اليوم الأخير: {last_day_val/1e6:.3f} مليون مقارنة بـ {prev_day_val/1e6:.3f} مليون لليوم السابق (تغير {growth:+.1f}%)."
    else:
        daily_text = "بيانات الأيام غير كافية للمقارنة اليومية."

    top_channel = f_orders.groupby('sales_channel')['net_before_tax_EGP'].sum().idxmax()
    facts = f"{daily_text}\nأعلى قناة مبيعات إجمالا: {top_channel}"
    return facts

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
        payload = {"model": GROQ_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2, **extra}
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

@st.cache_data
def load_real_data():
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(current_dir, 'data') if os.path.exists(os.path.join(current_dir, 'data')) else os.path.join(os.path.dirname(current_dir), 'data')
            
        orders_cols = ['sales_order_id', 'order_date', 'sales_channel', 'net_before_tax_EGP', 'gross_EGP', 'discount_EGP']
        orders = pd.read_parquet(os.path.join(data_dir, 'sales_orders.parquet'), columns=orders_cols)
        
        items_cols = ['sales_order_id', 'order_date', 'product_id', 'quantity', 'margin_EGP', 'net_line_EGP']
        if os.path.exists(os.path.join(data_dir, 'sales_order_items.parquet')):
            items = pd.read_parquet(os.path.join(data_dir, 'sales_order_items.parquet'), columns=items_cols)
        elif os.path.exists(os.path.join(data_dir, 'sales_order_items.csv')):
            items = pd.read_csv(os.path.join(data_dir, 'sales_order_items.csv'), usecols=items_cols)
        else:
            raise FileNotFoundError("Could not find sales_order_items")
            
        returns_cols = ['sales_order_id', 'refund_amount_EGP']
        returns = pd.read_parquet(os.path.join(data_dir, 'sales_returns.parquet'), columns=returns_cols)
        
        products_cols = ['product_id', 'category_en']
        products = pd.read_parquet(os.path.join(data_dir, 'products_catalog.parquet'), columns=products_cols)

        orders['net_before_tax_EGP'] = pd.to_numeric(orders['net_before_tax_EGP'], errors='coerce').astype('float32')
        orders['gross_EGP'] = pd.to_numeric(orders['gross_EGP'], errors='coerce').astype('float32')
        orders['discount_EGP'] = pd.to_numeric(orders['discount_EGP'], errors='coerce').astype('float32')
        
        items['quantity'] = pd.to_numeric(items['quantity'], errors='coerce').astype('float32')
        items['margin_EGP'] = pd.to_numeric(items['margin_EGP'], errors='coerce').astype('float32')
        items['net_line_EGP'] = pd.to_numeric(items['net_line_EGP'], errors='coerce').astype('float32')
        
        returns['refund_amount_EGP'] = pd.to_numeric(returns['refund_amount_EGP'], errors='coerce').astype('float32')

        orders['order_date'] = pd.to_datetime(orders['order_date'])
        items['order_date'] = pd.to_datetime(items['order_date'])
        
        return orders, items, returns, products
    except Exception as e:
        return None, None, None, str(e)

orders_df, items_df, returns_df, products_df = load_real_data()

if orders_df is None:
    st.error(f"{tr({'ar': 'تعذر العثور على الملفات. تفاصيل الخطأ:', 'en': 'Could not find files. Error details:'})} {products_df}")
    st.stop()

st.sidebar.markdown(f"<h3 style='color:#1e3a8a;'>{tr({'ar': 'قائمة الملاحة', 'en': 'Navigation'})}</h3>", unsafe_allow_html=True)

selected_lang = st.sidebar.radio(
    tr({'ar': "اختر اللغة", 'en': "Select Language"}),
    options=['ar', 'en'],
    index=0 if st.session_state.lang == 'ar' else 1
)
if selected_lang != st.session_state.lang:
    st.session_state.lang = selected_lang
    st.rerun()

st.markdown(f"<h2 style='color:#1e3a8a; margin-bottom: 20px;'>{tr({'ar': 'لوحة الإدارة التنفيذية', 'en': 'Executive Command Center'})}</h2>", unsafe_allow_html=True)

min_date = orders_df['order_date'].min().date()
max_date = orders_df['order_date'].max().date()

with st.container(border=True):
    st.markdown(f"<strong style='color:#1e3a8a; font-size:18px;'>{tr({'ar': 'أدوات التصفية والتحكم', 'en': 'Filters & Controls'})}</strong>", unsafe_allow_html=True)
    filter_col1, filter_col2, filter_col3 = st.columns([1, 1, 2])
    with filter_col1:
        start_date = st.date_input(tr({'ar': "من تاريخ", 'en': "Start Date"}), min_date)
    with filter_col2:
        end_date = st.date_input(tr({'ar': "إلى تاريخ", 'en': "End Date"}), max_date)
    with filter_col3:
        available_channels = orders_df['sales_channel'].dropna().unique().tolist()
        selected_channels = st.multiselect(tr({'ar': "قنوات البيع:", 'en': "Sales Channels:"}), available_channels, default=available_channels)

start_datetime = pd.to_datetime(start_date)
end_datetime = pd.to_datetime(end_date)

f_orders = orders_df[
    (orders_df['order_date'] >= start_datetime) & 
    (orders_df['order_date'] <= end_datetime) & 
    (orders_df['sales_channel'].isin(selected_channels))
]

f_items = items_df[items_df['sales_order_id'].isin(f_orders['sales_order_id'])]

total_sales = f_orders['net_before_tax_EGP'].sum()
total_profit = f_items['margin_EGP'].sum() if 'margin_EGP' in f_items.columns else 0
gross_margin = (total_profit / total_sales * 100) if total_sales > 0 else 0
total_discount = f_orders['discount_EGP'].sum()
gross_before_discount = f_orders['gross_EGP'].sum()
weighted_discount = (total_discount / gross_before_discount * 100) if gross_before_discount > 0 else 0
total_units = f_items['quantity'].sum()

total_refunds = returns_df['refund_amount_EGP'].sum() if not returns_df.empty else 0
return_rate = (len(returns_df) / len(f_items) * 100) if not f_items.empty and not returns_df.empty else 0

tab_analytics, tab_ai = st.tabs([tr({'ar': "التحليلات التنفيذية", 'en': "Executive Analytics"}), tr({'ar': "مجلس الإدارة الذكي", 'en': "AI Board of Directors"})])

with tab_analytics:
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar": "صافي المبيعات", "en": "Net Sales"})}</div><div class="kpi-value">{total_sales / 1000000:.1f}M EGP</div></div>', unsafe_allow_html=True)
    with c2:
        st.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar": "إجمالي الربح", "en": "Gross Profit"})}</div><div class="kpi-value">{total_profit / 1000000:.1f}M EGP</div></div>', unsafe_allow_html=True)
    with c3:
        st.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar": "هامش الربح", "en": "Gross Margin"})}</div><div class="kpi-value">{gross_margin:.1f}%</div></div>', unsafe_allow_html=True)
    with c4:
        st.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar": "نسبة الخصم", "en": "Discount %"})}</div><div class="kpi-value">{weighted_discount:.1f}%</div></div>', unsafe_allow_html=True)
    with c5:
        st.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar": "الوحدات المباعة", "en": "Units Sold"})}</div><div class="kpi-value">{total_units / 1000000:.2f}M</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    row2_col1, row2_col2 = st.columns(2)

    with row2_col1:
        with st.container(border=True):
            st.markdown(f"<h4 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'أداء القنوات', 'en': 'Channel Performance'})}</h4>", unsafe_allow_html=True)
            channel_perf = f_orders.groupby('sales_channel')['net_before_tax_EGP'].sum().reset_index()
            channel_perf.rename(columns={'sales_channel': 'Channel', 'net_before_tax_EGP': 'Net Sales'}, inplace=True)
            fig_ch = px.bar(channel_perf, x='Channel', y='Net Sales', text_auto='.2s', color_discrete_sequence=['#3b82f6'])
            fig_ch.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(l=0, r=0, t=10, b=0), height=350)
            st.plotly_chart(fig_ch, use_container_width=True)

    with row2_col2:
        with st.container(border=True):
            st.markdown(f"<h4 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'أداء الفئات', 'en': 'Category Performance'})}</h4>", unsafe_allow_html=True)
            if 'product_id' in f_items.columns and 'product_id' in products_df.columns:
                merged_items = f_items.merge(products_df, on='product_id', how='left')
                cat_perf = merged_items.groupby('category_en')['net_line_EGP'].sum().reset_index()
                fig_cat = px.pie(cat_perf, values='net_line_EGP', names='category_en', hole=0.5, color_discrete_sequence=px.colors.qualitative.Pastel)
                fig_cat.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(l=0, r=0, t=10, b=0), height=350)
                st.plotly_chart(fig_cat, use_container_width=True)

with tab_ai:
    st.markdown(f"<h3 style='color:#1e3a8a;'>{tr({'ar': 'مجلس الإدارة الذكي', 'en': 'Smart AI Board'})}</h3>", unsafe_allow_html=True)
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(current_dir, 'data') if os.path.exists(os.path.join(current_dir, 'data')) else os.path.join(os.path.dirname(current_dir), 'data')
    dec_file = os.path.join(data_dir, 'decisions_log.csv')
    
    with st.container(border=True):
        api_key_configured = False
        telegram_configured = False
        
        try:
            api_key = st.secrets["GROQ_API_KEY"]
            if api_key: api_key_configured = True
        except:
            st.warning(tr({'ar': "الرجاء إضافة GROQ_API_KEY في ملف secrets.toml", 'en': "Please add GROQ_API_KEY to secrets.toml"}))
            
        try:
            telegram_token = st.secrets["TELEGRAM_TOKEN"]
            telegram_chat_id = st.secrets["TELEGRAM_CHAT_ID"]
            telegram_configured = True
        except:
            pass

        if st.button(tr({'ar': "إنشاء الملخص التنفيذي اليومي", 'en': "Generate Daily Briefing"}), type="primary"):
            if api_key_configured:
                with st.spinner(tr({'ar': "يجري تحضير الملخص...", 'en': "Preparing briefing..."})):
                    facts = build_executive_facts(f_orders)
                    prompt = (
                        "أنت مستشار تنفيذي ذكي.\n"
                        f"إجمالي مبيعات الفترة: {total_sales/1e6:.1f} مليون | هامش الربح {gross_margin:.1f}% | المرتجعات {return_rate:.1f}%\n"
                        f"الأداء اليومي والتغيرات: {facts}\n\n"
                        "اكتب 'ملخص تنفيذي' في 5 أسطر دقيقة باللغة العربية كالتالي:\n"
                        "1. الموقف الحالي (جملة واحدة).\n"
                        "2. ما تغير في اليوم الأخير (جملة واحدة).\n"
                        "3. الخطر المحتمل أو الشذوذ (جملة واحدة).\n"
                        "4. الفرصة المتاحة (جملة واحدة).\n"
                        "5. التوصية السريعة (جملة واحدة)."
                    )
                    ai_response, ai_error = call_groq(api_key, prompt)
                    if ai_response:
                        st.session_state['daily_briefing'] = ai_response
                    else:
                        st.error(f"خطأ: {ai_error}")

        if 'daily_briefing' in st.session_state:
            render_ai_box(st.session_state['daily_briefing'])
            if st.button(tr({'ar': "إرسال الملخص إلى الإدارة", 'en': "Send Briefing to Management"})):
                if telegram_configured:
                    try:
                        message = f"*الملخص التنفيذي اليومي*\n\n{st.session_state['daily_briefing']}"
                        url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
                        payload = {"chat_id": telegram_chat_id, "text": message[:4000], "parse_mode": "Markdown"}
                        requests.post(url, json=payload, timeout=30)
                        st.success(tr({'ar': "تم إرسال الملخص بنجاح", 'en': "Briefing sent successfully"}))
                    except Exception as e:
                        st.error(str(e))
            st.markdown("---")

        st.markdown(f"**{tr({'ar': 'اطرح سؤالا استراتيجيا للتعمق:', 'en': 'Ask a strategic question to deep dive:'})}**")
        user_query = st.text_input(tr({'ar': "سؤالك لمجلس الإدارة:", 'en': "Your question to the board:"}), placeholder=tr({'ar': "مثال: كيف نعالج الهبوط في اليوم الأخير؟", 'en': "Type your question here..."}))
        
        if st.button(tr({'ar': "استشارة مجلس الإدارة", 'en': "Consult the Board"}), use_container_width=True):
            if api_key_configured and user_query:
                with st.spinner(tr({'ar': "مجلس الإدارة يدرس البيانات...", 'en': "The AI board is analyzing..."})):
                    channel_data_str = channel_perf.to_string(index=False)
                    facts = build_executive_facts(f_orders)
                    prompt = (
                        "أنت مجلس إدارة تنفيذي لشركة تجزئة كبرى.\n"
                        f"البيانات الكلية: المبيعات: {total_sales} جنيه | هامش الربح: {gross_margin}% | الإرجاع: {return_rate}%\n"
                        f"أداء القنوات:\n{channel_data_str}\n"
                        f"الأداء اليومي: {facts}\n\n"
                        f"سؤال المدير التنفيذي: {user_query}\n\n"
                        "المطلوب: أجب بوضوح بناء على الأرقام أعلاه. ابدأ بملخص مباشر للموقف، ثم قدم خطة عمل من 3 خطوات واضحة (بدون مقدمات، لغة حازمة)."
                    )
                    ai_response, ai_error = call_groq(api_key, prompt)
                    if ai_response:
                        st.session_state['last_exec_query'] = user_query
                        st.session_state['last_exec_ai_response'] = ai_response
                        st.rerun()
                    else:
                        st.error(f"خطأ: {ai_error}")
            elif not user_query:
                st.warning(tr({'ar': "الرجاء كتابة سؤال لتوجيهه لمجلس الإدارة أولا.", 'en': "Please enter a question for the board first."}))
                
        if 'last_exec_ai_response' in st.session_state:
            st.markdown(f"**سؤالك:** {st.session_state['last_exec_query']}")
            render_ai_box(st.session_state['last_exec_ai_response'])
            
            if st.button(tr({'ar': "إرسال القرار للإدارة وحفظه", 'en': "Send to Management & Save"}), type="secondary"):
                if telegram_configured:
                    try:
                        decision_id = str(int(time.time()))
                        message = f"*قرار استراتيجي*\n\n*السؤال:* {st.session_state['last_exec_query']}\n\n*قرار مجلس الإدارة:*\n{st.session_state['last_exec_ai_response']}"
                        
                        url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
                        payload = {
                            "chat_id": telegram_chat_id,
                            "text": message[:4000],
                            "parse_mode": "Markdown",
                            "reply_markup": {
                                "inline_keyboard": [[
                                    {"text": "اعتماد التنفيذ", "callback_data": f"Approve_{decision_id}"},
                                    {"text": "رفض/تأجيل", "callback_data": f"Reject_{decision_id}"}
                                ]]
                            }
                        }
                        response = requests.post(url, json=payload, timeout=30)
                        
                        if response.status_code == 200:
                            new_decision = pd.DataFrame([{
                                'ID': decision_id,
                                'Date': pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
                                'Decision': st.session_state['last_exec_query'],
                                'Status': "Pending"
                            }])
                            if os.path.exists(dec_file):
                                existing_df = pd.read_csv(dec_file)
                                updated_df = pd.concat([new_decision, existing_df], ignore_index=True)
                            else:
                                updated_df = new_decision
                            updated_df.to_csv(dec_file, index=False)
                            
                            st.success(tr({'ar': "تم إرسال القرار وحفظه بنجاح", 'en': "Decision sent and saved successfully"}))
                            time.sleep(1.5)
                            st.rerun()
                        else:
                            st.error(f"خطأ الإرسال للإدارة: {response.text}")
                    except Exception as e:
                        st.error(f"خطأ اتصال: {str(e)}")
                else:
                    st.error(tr({'ar': "بيانات الاتصال بالإدارة غير متوفرة في ملف secrets.toml", 'en': "Management credentials not found in secrets.toml"}))

    st.markdown(f"#### {tr({'ar': 'سجل القرارات التنفيذية', 'en': 'Executive Decision Log'})}")
    if telegram_configured:
        if st.button(tr({'ar': "تحديث حالات التنفيذ", 'en': "Sync Execution Status"})):
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
                                    df.loc[df['ID'].astype(str) == str(dec_id), 'Status'] = 'Approved' if action == 'Approve' else 'Rejected'
                                    updates_found = True
                        
                        if updates_found:
                            df.to_csv(dec_file, index=False)
                            requests.get(f"{url}?offset={highest_update_id + 1}", timeout=30)
                            st.success(tr({'ar': "تمت المزامنة بنجاح", 'en': "Synced successfully"}))
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.info(tr({'ar': "لا توجد تحديثات جديدة", 'en': "No new updates"}))
            except Exception as e:
                st.error(f"Sync error: {str(e)}")

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
    else:
        st.info(tr({'ar': "لا توجد قرارات مسجلة بعد", 'en': "No decisions logged yet"}))
