import streamlit as st
import pandas as pd
import plotly.express as px
import os
import re
import html
import requests
import time
import datetime
import traceback

st.set_page_config(layout="wide", page_title="Product Profitability & Margin Intelligence")

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
    
    /* تصميم الورقة الرسمية للمذكرة */
    .ai-response-box {
        padding: 40px; background-color: #ffffff; border: 1px solid #cbd5e1;
        border-radius: 8px; font-size: 17px; line-height: 2.2; color: #0f172a;
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1); font-family: 'Arial', sans-serif;
    }
    
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 12px; border: 2px solid #94a3b8 !important; 
        background-color: #ffffff; padding: 15px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    }
    </style>
""", unsafe_allow_html=True)

# ----------------------------------------------------------------------------------------------
# Data Loading 
# ----------------------------------------------------------------------------------------------
@st.cache_data
def load_profitability_data():
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(current_dir, 'data') if os.path.exists(os.path.join(current_dir, 'data')) else os.path.join(os.path.dirname(current_dir), 'data')
        
        # التعديل هنا: استخدام read_csv بدلاً من read_parquet و usecols بدلاً من columns
        df_so_items = pd.read_csv(os.path.join(data_dir, 'sales_order_items.csv'), 
                                      usecols=['order_date', 'branch_id', 'sku_id', 'product_id', 'quantity', 'net_line_EGP', 'margin_EGP'])
        
        df_products = pd.read_parquet(os.path.join(data_dir, 'products_catalog.parquet'), 
                                      columns=['product_id', 'product_name_ar', 'category_en'])
        
        df_sku = pd.read_parquet(os.path.join(data_dir, 'sku_variants.parquet'), 
                                 columns=['sku_id', 'size', 'color_ar'])
                                 
        df_branches = pd.read_parquet(os.path.join(data_dir, 'branches.parquet'), 
                                      columns=['branch_id', 'branch_name_ar'])
        
        df_products = df_products.drop_duplicates('product_id')
        df_sku = df_sku.drop_duplicates('sku_id')
        df_branches = df_branches.drop_duplicates('branch_id')

        df = df_so_items.merge(df_products, on='product_id', how='inner')
        df = df.merge(df_sku, on='sku_id', how='inner')
        df = df.merge(df_branches, on='branch_id', how='inner')
        
        df['order_date'] = pd.to_datetime(df['order_date'], errors='coerce')
        df.dropna(subset=['order_date'], inplace=True)
        
        return df
    except Exception as e:
        return traceback.format_exc()

data = load_profitability_data()

if isinstance(data, str):
    st.error(f"حدث خطأ أثناء تحميل البيانات:\n\n{data}")
    st.stop()

# ----------------------------------------------------------------------------------------------
# Sidebar Filters
# ----------------------------------------------------------------------------------------------
st.sidebar.markdown(f"<h3>{tr({'ar': 'إعدادات النظام', 'en': 'System Settings'})}</h3>", unsafe_allow_html=True)
selected_lang = st.sidebar.radio(tr({'ar': "اللغة", 'en': "Language"}), ['ar', 'en'], index=0 if st.session_state.lang == 'ar' else 1)
if selected_lang != st.session_state.lang:
    st.session_state.lang = selected_lang
    st.rerun()

st.markdown(f"<h2 style='color:#1e3a8a; margin-bottom: 20px;'>{tr({'ar': 'ربحية المنتجات والذكاء المالي', 'en': 'Product Profitability & Margin Intelligence'})}</h2>", unsafe_allow_html=True)

min_date, max_date = data['order_date'].min().date(), data['order_date'].max().date()
available_categories = data['category_en'].dropna().unique().tolist()

with st.container(border=True):
    c1, c2, c3 = st.columns([1, 1, 2])
    start_date = c1.date_input(tr({'ar': "من تاريخ", 'en': "Start Date"}), min_date)
    end_date = c2.date_input(tr({'ar': "إلى تاريخ", 'en': "End Date"}), max_date)
    selected_cats = c3.multiselect(tr({'ar': "تحديد التصنيفات", 'en': "Categories"}), available_categories, default=available_categories)

mask = (data['order_date'].dt.date >= start_date) & (data['order_date'].dt.date <= end_date)
df_filtered = data[mask]
if selected_cats:
    df_filtered = df_filtered[df_filtered['category_en'].isin(selected_cats)]

# ==========================================
# Core Calculations
# ==========================================
total_sales = df_filtered['net_line_EGP'].sum()
total_profit = df_filtered['margin_EGP'].sum()
total_qty = df_filtered['quantity'].sum()

gross_margin_pct = (total_profit / total_sales * 100) if total_sales > 0 else 0
margin_per_unit = (total_profit / total_qty) if total_qty > 0 else 0

sku_full_profit = df_filtered.groupby('sku_id').agg({'net_line_EGP': 'sum', 'margin_EGP': 'sum'})
sku_full_profit['margin_pct'] = sku_full_profit['margin_EGP'] / sku_full_profit['net_line_EGP']
profitable_sales = sku_full_profit[sku_full_profit['margin_pct'] > 0.30]['net_line_EGP'].sum()
profitable_sales_share = (profitable_sales / total_sales * 100) if total_sales > 0 else 0

prod_profit = df_filtered.groupby(['product_name_ar', 'category_en']).agg(
    Sales=('net_line_EGP', 'sum'),
    Profit=('margin_EGP', 'sum')
).reset_index()
prod_profit['Margin %'] = (prod_profit['Profit'] / prod_profit['Sales'] * 100).fillna(0)
top_10_products = prod_profit.sort_values('Profit', ascending=False).head(10)

sku_profit = df_filtered.groupby(['product_name_ar', 'color_ar', 'size', 'category_en']).agg(
    Sales=('net_line_EGP', 'sum'),
    Profit=('margin_EGP', 'sum')
).reset_index()
sku_profit['Margin %'] = (sku_profit['Profit'] / sku_profit['Sales'] * 100).fillna(0)
low_margin_alerts = sku_profit[sku_profit['Sales'] > 1000].sort_values('Margin %', ascending=True).head(10)

trend_df = df_filtered.groupby(df_filtered['order_date'].dt.to_period('M')).agg(
    Sales=('net_line_EGP', 'sum'),
    Profit=('margin_EGP', 'sum')
).reset_index()
trend_df['order_date'] = trend_df['order_date'].dt.to_timestamp()
trend_df['Margin %'] = (trend_df['Profit'] / trend_df['Sales'] * 100).fillna(0)

branch_profit = df_filtered.groupby('branch_name_ar').agg(
    Sales=('net_line_EGP', 'sum'),
    Profit=('margin_EGP', 'sum')
).reset_index()
branch_profit['Margin %'] = (branch_profit['Profit'] / branch_profit['Sales'] * 100).fillna(0)
branch_profit = branch_profit.sort_values('Profit', ascending=False)

# ----------------------------------------------------------------------------------------------
# Dashboard UI
# ----------------------------------------------------------------------------------------------
tab_dashboard, tab_ai = st.tabs([
    tr({'ar': "تحليلات الربحية", 'en': "Profitability Analytics"}),
    tr({'ar': "مركز التكليفات (التسعير والإنتاج)", 'en': "Directives Center (Pricing & Production)"})
])

with tab_dashboard:
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"هامش الربح الإجمالي", "en":"Gross Margin"})}</div><div class="kpi-value">{gross_margin_pct:.1f}%</div></div>', unsafe_allow_html=True)
    k2.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"صافي الأرباح التشغيلية", "en":"Operating Profit"})}</div><div class="kpi-value">EGP {total_profit:,.0f}</div></div>', unsafe_allow_html=True)
    k3.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"حصة المبيعات المربحة", "en":"Profitable Sales Share"})}</div><div class="kpi-value">{profitable_sales_share:.0f}%</div></div>', unsafe_allow_html=True)
    k4.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"ربحية القطعة الواحدة", "en":"Margin per Unit"})}</div><div class="kpi-value">EGP {margin_per_unit:.1f}</div></div>', unsafe_allow_html=True)
    k5.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"إجمالي المبيعات", "en":"Total Sales"})}</div><div class="kpi-value">EGP {total_sales:,.0f}</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    
    r1c1, r1c2 = st.columns(2)
    
    with r1c1:
        st.markdown(f"<h5 style='color:#1e3a8a;'>{tr({'ar': 'أعلى 10 منتجات ربحية', 'en': 'Top 10 Profitable Products'})}</h5>", unsafe_allow_html=True)
        disp_top = top_10_products.copy()
        disp_top.rename(columns={'product_name_ar': 'Product', 'category_en': 'Category'}, inplace=True)
        st.dataframe(disp_top.style.format({'Sales': '{:,.0f}', 'Profit': '{:,.0f}', 'Margin %': '{:.1f}%'}), use_container_width=True, hide_index=True)

    with r1c2:
        st.markdown(f"<h5 style='color:#ef4444;'>{tr({'ar': 'أقل 10 منتجات في هامش الربح (تحذيرات)', 'en': 'Lowest Margin Alerts (SKU Level)'})}</h5>", unsafe_allow_html=True)
        disp_low = low_margin_alerts.copy()
        disp_low.rename(columns={'product_name_ar': 'Product', 'color_ar': 'Color', 'size': 'Size', 'category_en': 'Category'}, inplace=True)
        st.dataframe(disp_low.style.format({'Sales': '{:,.0f}', 'Profit': '{:,.0f}', 'Margin %': '{:.1f}%'}).map(lambda x: 'color: #ef4444; font-weight: bold;', subset=['Margin %']), use_container_width=True, hide_index=True)

    st.markdown("<br>", unsafe_allow_html=True)
    
    r2c1, r2c2 = st.columns(2)
    
    with r2c1:
        st.markdown(f"<h5 style='color:#1e3a8a;'>{tr({'ar': 'اتجاه هامش الربح خلال الفترة', 'en': 'Margin Trend'})}</h5>", unsafe_allow_html=True)
        fig_trend = px.line(trend_df, x='order_date', y='Margin %', markers=True)
        fig_trend.update_layout(xaxis_title="", yaxis_title="Margin %", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        fig_trend.update_traces(line_color='#10b981')
        st.plotly_chart(fig_trend, use_container_width=True)

    with r2c2:
        st.markdown(f"<h5 style='color:#1e3a8a;'>{tr({'ar': 'ربحية الفروع', 'en': 'Branch Profitability'})}</h5>", unsafe_allow_html=True)
        disp_branch = branch_profit.head(10).copy()
        disp_branch.rename(columns={'branch_name_ar': 'Branch'}, inplace=True)
        st.dataframe(disp_branch.style.format({'Sales': '{:,.0f}', 'Profit': '{:,.0f}', 'Margin %': '{:.1f}%'}), use_container_width=True, hide_index=True)

# ----------------------------------------------------------------------------------------------
# Directives Tab (PDF Generation & Telegram)
# ----------------------------------------------------------------------------------------------
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

def build_profitability_facts():
    if top_10_products.empty or low_margin_alerts.empty:
        return None

    top_str = top_10_products.head(3)[['product_name_ar', 'category_en', 'Margin %']].to_dict('records')
    low_str = low_margin_alerts.head(4)[['product_name_ar', 'color_ar', 'size', 'Margin %']].to_dict('records')
    
    facts = (
        f"متوسط هامش الربح الإجمالي للشركة: {gross_margin_pct:.1f}%.\n"
        f"أعلى ثلاثة منتجات ربحية: {top_str}\n"
        f"المنتجات ذات أقل هامش ربح (مع ألوانها ومقاساتها): {low_str}\n"
    )
    return facts

def generate_arabic_pdf(text_content):
    try:
        import directive_pdf
        return directive_pdf.generate_directive_pdf(text_content, lang='ar', title="أمر تكليف - إدارة التسعير والإنتاج")
    except Exception as e:
        return None, str(e)

with tab_ai:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(current_dir, 'data') if os.path.exists(os.path.join(current_dir, 'data')) else os.path.join(os.path.dirname(current_dir), 'data')
    dec_file = os.path.join(data_dir, 'pricing_decisions_log.csv') 
    
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

    st.markdown(f"<h4 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'إصدار قرارات التسعير والإنتاج', 'en': 'Generate Pricing & Production Decisions'})}</h4>", unsafe_allow_html=True)
    
    if st.button(tr({'ar': "توليد المذكرة الإدارية الآن", 'en': "Generate Directive Now"}), type="primary", use_container_width=True):
        facts_text = build_profitability_facts()
        if not api_key_configured:
            st.warning(tr({'ar': "الرجاء إعداد GROQ_API_KEY", 'en': "Please configure GROQ_API_KEY"}))
        elif facts_text is None:
            st.warning(tr({'ar': "لا توجد بيانات ربحية كافية للفترة المحددة.", 'en': "Not enough profitability data."}))
        else:
            with st.spinner(tr({'ar': "يتم صياغة المذكرة الإدارية لمديري التسعير والإنتاج...", 'en': "Drafting pricing directive..."})):
                sys_lang = "Arabic" if st.session_state.lang == 'ar' else "English"
                
                prompt = (
                    f"أنت المدير التجاري لشركة قطونيل. اكتب باللغة {sys_lang} مذكرة رسمية (Business Memo) حازمة لإدارة التسعير والإنتاج.\n"
                    f"بناءً على البيانات التالية حصرياً:\n{facts_text}\n"
                    "المطلوب حرفياً لتنسيق المذكرة:\n"
                    "1. يمنع منعاً باتاً استخدام الجداول، استخدم فقط القوائم النقطية (Bullet points).\n"
                    "2. اكتب النص الخاص بكل نقطة على نفس السطر الذي توجد به علامة (-) ولا تقم بإضافة سطر فارغ أو مسافة (Enter) بين العلامة والنص.\n"
                    "3. يمنع استخدام أي رموز تعبيرية (Emojis).\n"
                    "4. اذكر قائمة المنتجات ذات أقل هامش ربح وأصدر قراراً حاسماً بشأن كل منها (زيادة سعر، تقليل تكلفة، إلخ).\n"
                    "5. أصدر توجيهاً لزيادة التركيز التسويقي على المنتجات الأعلى ربحية المذكورة.\n"
                    "6. لا تقم بتأليف بيانات غير موجودة."
                )
                
                ai_res, ai_err = call_groq(api_key, prompt)
                if ai_res:
                    st.session_state['prof_ai_response'] = ai_res
                else:
                    st.error(ai_err)

    if 'prof_ai_response' in st.session_state:
        st.markdown("<br>", unsafe_allow_html=True)
        
        # تنظيف فواصل الأسطر العشوائية للماركدوان قبل العرض
        safe_html = st.session_state['prof_ai_response']
        safe_html = re.sub(r"([*+-])\s*\n\s*", r"\1 ", safe_html) # معالجة النقاط المعلقة (Hanging Bullets)
        safe_html = html.escape(safe_html).replace("\n", "<br>")
        safe_html = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", safe_html)
        safe_html = safe_html.replace("* ", "• ").replace("- ", "• ")
        
        st.markdown(f"<div class='ai-response-box' dir='auto'>{safe_html}</div>", unsafe_allow_html=True)
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        c_btn1, c_btn2 = st.columns(2)
        with c_btn1:
            if st.button(tr({'ar': "إرسال المذكرة لاعتمادها (تليجرام)", 'en': "Send Directive via Telegram"}), use_container_width=True, key="send_tg_prof"):
                if telegram_configured:
                    try:
                        decision_id = "PROF_" + str(int(time.time()))
                        message = f"*مذكرة تسعير وإنتاج (قطونيل)*\n\n{st.session_state['prof_ai_response']}"
                        
                        url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
                        t_payload = {
                            "chat_id": telegram_chat_id,
                            "text": message[:4000],
                            "parse_mode": "Markdown",
                            "reply_markup": {
                                "inline_keyboard": [[
                                    {"text": "تم استلام القرارات وجاري التنفيذ", "callback_data": f"Approve_{decision_id}"}
                                ]]
                            }
                        }
                        requests.post(url, json=t_payload, timeout=30)
                        
                        new_dec = pd.DataFrame([{'ID': decision_id, 'Date': pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"), 'Topic': "قرارات تسعير وإنتاج", 'Status': "Pending"}])
                        if os.path.exists(dec_file):
                            df = pd.read_csv(dec_file)
                            df = pd.concat([new_dec, df], ignore_index=True)
                        else:
                            df = new_dec
                        df.to_csv(dec_file, index=False)
                        st.success(tr({'ar': "تم إرسال أمر التكليف بنجاح", 'en': "Sent successfully"}))
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))
                else:
                     st.warning(tr({'ar': "تليجرام غير مفعل في secrets", 'en': "Telegram not configured"}))
                     
        with c_btn2:
            # استخدام النص المنظف لضمان ظهوره في الـ PDF بشكل ممتاز
            clean_text_for_pdf = re.sub(r"([*+-])\s*\n\s*", r"\1 ", st.session_state['prof_ai_response'])
            pdf_bytes, pdf_error = generate_arabic_pdf(clean_text_for_pdf)
            if pdf_bytes:
                st.download_button(
                    label=tr({'ar': "📄 تحميل المذكرة (PDF)", 'en': "📄 Download Directive (PDF)"}),
                    data=pdf_bytes,
                    file_name=f"Pricing_Production_Memo_{datetime.date.today()}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                    key="dl_pdf_prof"
                )
            else:
                st.error(f"حدث خطأ أثناء بناء ملف PDF: {pdf_error}")

        st.markdown("<br><hr>", unsafe_allow_html=True)
        
        c_ai1, c_ai2 = st.columns([2, 1])
        with c_ai1:
            st.markdown(f"#### {tr({'ar': 'سجل القرارات الإدارية', 'en': 'Decisions Log'})}")
        with c_ai2:
            if telegram_configured:
                if st.button(tr({'ar': "تحديث حالات التنفيذ", 'en': "Sync Executions"}), key="sync_prof"):
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
                                            action, dec_id = cb_data.split("_", 1)
                                            if 'ID' in df.columns:
                                                df.loc[df['ID'].astype(str) == str(dec_id), 'Status'] = 'Executed' if action == 'Approve' else 'Rejected'
                                                updates_found = True
                                if updates_found:
                                    df.to_csv(dec_file, index=False)
                                    requests.get(f"{url}?offset={highest_update_id + 1}", timeout=30)
                                    st.success(tr({'ar': "تمت مزامنة التنفيذ بنجاح", 'en': "Synced successfully"}))
                                    time.sleep(1)
                                    st.rerun()
                    except Exception as e:
                        st.error(f"Sync error: {e}")

        if os.path.exists(dec_file):
            dec_df = pd.read_csv(dec_file)
            display_cols = {
                'ID': 'ID', 
                'Date': tr({'ar': 'التاريخ', 'en': 'Date'}), 
                'Topic': tr({'ar': 'أمر التكليف', 'en': 'Topic'}), 
                'Status': tr({'ar': 'حالة التنفيذ', 'en': 'Status'})
            }
            if 'Status' in dec_df.columns:
                dec_df.rename(columns=display_cols, inplace=True)
                def color_status(val):
                    color = '#f59e0b' if val == 'Pending' else '#10b981' if val == 'Executed' else '#ef4444'
                    return f'color: {color}; font-weight: bold'
                st.dataframe(dec_df.style.map(color_status, subset=[display_cols['Status']]), hide_index=True, use_container_width=True)
            else:
                st.dataframe(dec_df, hide_index=True, use_container_width=True)