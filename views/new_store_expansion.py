import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os
import requests
import html
import re
import time
import datetime
import tempfile
import sys
import traceback

st.set_page_config(layout="wide", page_title="New Store Expansion & Site Selection")

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
    return '/content' # Fallback for Colab/direct paths

if 'lang' not in st.session_state:
    st.session_state.lang = 'ar'

def tr(text_dict):
    return text_dict.get(st.session_state.lang, text_dict.get('en', ''))

def get_secret(name, default=""):
    value = None
    try:
        value = st.secrets.get(name, None)
    except Exception:
        value = None
    if not value:
        value = os.environ.get(name, default)
    return str(value).strip() if value else default

def redact(message, *secrets):
    msg = str(message)
    for s in secrets:
        if s:
            msg = msg.replace(s, "***")
    return re.sub(r"bot\d+:[A-Za-z0-9_-]+", "bot***", msg)

# --- Number Formatting Helper ---
def format_number(num):
    if num >= 1e9:
        return f"{num / 1e9:.1f}B"
    elif num >= 1e6:
        return f"{num / 1e6:.1f}M"
    elif num >= 1e3:
        return f"{num / 1e3:.1f}K"
    else:
        return f"{num:,.0f}"

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
    .ai-response-box {
        padding: 40px; background-color: #ffffff; border: 1px solid #cbd5e1;
        border-radius: 8px; font-size: 17px; line-height: 2.2; color: #0f172a;
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1); font-family: 'Arial', sans-serif;
    }
    .chart-subtitle {
        font-size: 12px; color: #64748b; text-align: center; 
        margin-top: -10px; margin-bottom: 15px;
    }
    .kanban-card {
        background-color: #ffffff; padding: 15px; border-radius: 8px; margin-bottom: 15px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); border-right: 5px solid #cbd5e1;
        transition: transform 0.2s ease;
    }
    .k-pending { border-right-color: #f59e0b; }
    .k-executed { border-right-color: #10b981; }
    .k-rejected { border-right-color: #ef4444; }
    .k-title { font-weight: bold; color: #0f172a; font-size: 15px; margin-bottom: 8px; }
    .k-date { font-size: 12px; color: #64748b; }
    </style>
""", unsafe_allow_html=True)

# --- Data Loading ---
@st.cache_data(show_spinner=False)
def load_expansion_data():
    try:
        data_dir = resolve_data_dir()
        
        path_orders = os.path.join(data_dir, 'sales_orders.parquet')
        path_customers = os.path.join(data_dir, 'customers.parquet')
        path_branches = os.path.join(data_dir, 'branches.parquet')
        
        if not os.path.exists(path_orders): raise FileNotFoundError(f"Missing file: {path_orders}")
        if not os.path.exists(path_customers): raise FileNotFoundError(f"Missing file: {path_customers}")
        if not os.path.exists(path_branches): raise FileNotFoundError(f"Missing file: {path_branches}")

        df_orders = pd.read_parquet(path_orders, columns=['sales_order_id', 'order_date', 'customer_id', 'paid_total_EGP'])
        df_customers = pd.read_parquet(path_customers, columns=['customer_id', 'governorate_ar', 'age_band'])
        df_branches = pd.read_parquet(path_branches, columns=['branch_id', 'governorate_ar'])
        
        df_orders['order_date'] = pd.to_datetime(df_orders['order_date'], errors='coerce')
        df_orders.dropna(subset=['order_date'], inplace=True)
        
        df_merged = df_orders.merge(df_customers, on='customer_id', how='inner')
        
        return df_merged, df_branches, df_customers, None
    except Exception as e:
        return None, None, None, str(e)

df_merged, df_branches, df_customers, load_error = load_expansion_data()

if df_merged is None:
    st.error(f"خطأ في تحميل البيانات. التفاصيل: {load_error}")
    st.stop()

# --- Sidebar ---
st.sidebar.markdown(f"<h3>{tr({'ar': 'إعدادات النظام', 'en': 'System Settings'})}</h3>", unsafe_allow_html=True)
selected_lang = st.sidebar.radio(tr({'ar': "اللغة", 'en': "Language"}), ['ar', 'en'], index=0 if st.session_state.lang == 'ar' else 1)
if selected_lang != st.session_state.lang:
    st.session_state.lang = selected_lang
    st.rerun()

st.markdown(f"<h2 style='color:#1e3a8a; margin-bottom: 20px;'>{tr({'ar': 'التوسع المستقبلي وتحليل المواقع', 'en': 'New Store Expansion & Site Selection'})}</h2>", unsafe_allow_html=True)

# --- Date Filter ---
min_date, max_date = df_merged['order_date'].min().date(), df_merged['order_date'].max().date()

with st.container(border=True):
    c1, c2 = st.columns(2)
    start_date = c1.date_input(tr({'ar': "من تاريخ", 'en': "Start Date"}), min_date)
    end_date = c2.date_input(tr({'ar': "إلى تاريخ", 'en': "End Date"}), max_date)

mask = (df_merged['order_date'].dt.date >= start_date) & (df_merged['order_date'].dt.date <= end_date)
df_filtered = df_merged[mask].copy()

# --- Location Analytics Logic ---
gov_demand = df_filtered.groupby('governorate_ar')['paid_total_EGP'].sum().reset_index()
gov_demand.rename(columns={'paid_total_EGP': 'total_demand'}, inplace=True)

branch_counts = df_branches.groupby('governorate_ar')['branch_id'].count().reset_index()
branch_counts.rename(columns={'branch_id': 'branch_count'}, inplace=True)

analysis_df = gov_demand.merge(branch_counts, on='governorate_ar', how='left').fillna(0)

max_demand = analysis_df['total_demand'].max() if not analysis_df.empty else 1
analysis_df['demand_norm'] = analysis_df['total_demand'] / max_demand * 100

analysis_df['saturation_penalty'] = analysis_df['branch_count'] * 15 
analysis_df['Site_Score'] = (analysis_df['demand_norm'] - analysis_df['saturation_penalty']).clip(lower=10, upper=98)

network_avg_sales = (df_filtered['paid_total_EGP'].sum() / df_branches['branch_id'].nunique()) if not df_branches.empty else 0
analysis_df['Projected_Sales'] = (network_avg_sales * (analysis_df['Site_Score'] / 50)).clip(lower=network_avg_sales * 0.3)

def get_recommendation(score):
    if score >= 85: return tr({'ar': 'أولوية قصوى', 'en': 'Top Priority'})
    elif score >= 60: return tr({'ar': 'توسع مستقبلي', 'en': 'Priority'})
    else: return tr({'ar': 'مكتفي حالياً', 'en': 'Saturated'})

analysis_df['Recommendation'] = analysis_df['Site_Score'].apply(get_recommendation)
analysis_df = analysis_df.sort_values('Site_Score', ascending=False)

# KPIs
total_addressable_market = df_filtered['paid_total_EGP'].sum()
top_location = analysis_df.iloc[0]['governorate_ar'] if not analysis_df.empty else "N/A"
top_location_sales = analysis_df.iloc[0]['Projected_Sales'] if not analysis_df.empty else 0
avg_site_score = analysis_df['Site_Score'].mean() if not analysis_df.empty else 0

# --- Dashboard Layout ---
tab_dashboard, tab_ai = st.tabs([
    tr({'ar': "تحليلات المواقع والديموغرافيا", 'en': "Location & Demographic Analytics"}),
    tr({'ar': "قرارات التوسع الاستراتيجية", 'en': "Strategic Expansion Decisions"})
])

with tab_dashboard:
    k1, k2, k3 = st.columns(3)
    k1.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"إجمالي حجم السوق المتاح (TAM)", "en":"Total Addressable Market"})}</div><div class="kpi-value">{format_number(total_addressable_market)} ج.م</div></div>', unsafe_allow_html=True)
    k2.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"أعلى موقع تقييماً", "en":"Top Rated Location"})}</div><div class="kpi-value">{top_location}</div></div>', unsafe_allow_html=True)
    k3.markdown(f'<div class="kpi-card"><div class="kpi-label">{tr({"ar":"المبيعات المتوقعة للفرع الجديد", "en":"Projected Sales (Yr 1)"})}</div><div class="kpi-value">{format_number(top_location_sales)} ج.م</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    r1c1, r1c2 = st.columns([1.5, 1])

    with r1c1:
        with st.container(border=True):
            st.markdown(f"<h5 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'فجوة الطلب مقابل كثافة الفروع (حسب المحافظة)', 'en': 'Demand Gap vs. Branch Density'})}</h5>", unsafe_allow_html=True)
            st.markdown(f"<p class='chart-subtitle'>{tr({'ar': 'يقارن بين حجم إنفاق العملاء في المحافظة وعدد الفروع المتاحة لخدمتهم', 'en': 'Compares customer spending in a region vs available branches'})}</p>", unsafe_allow_html=True)
            
            top_gaps = analysis_df.head(10)
            fig_bar = go.Figure()
            fig_bar.add_trace(go.Bar(x=top_gaps['governorate_ar'], y=top_gaps['total_demand'], name=tr({'ar':'حجم الطلب (ج.م)','en':'Demand (EGP)'}), marker_color='#3b82f6', yaxis='y1'))
            fig_bar.add_trace(go.Scatter(x=top_gaps['governorate_ar'], y=top_gaps['branch_count'], name=tr({'ar':'عدد الفروع الحالية','en':'Existing Branches'}), mode='lines+markers', marker=dict(size=12, color='#1e3a8a'), line=dict(width=3), yaxis='y2'))
            
            fig_bar.update_layout(
                yaxis=dict(title=tr({'ar':"حجم الطلب (ج.م)", 'en':"Demand (EGP)"}), showgrid=False),
                yaxis2=dict(title=tr({'ar':"عدد الفروع", 'en':"Branch Count"}), overlaying='y', side='right', showgrid=False),
                legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5),
                paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(t=10, b=10, l=10, r=10)
            )
            st.plotly_chart(fig_bar, use_container_width=True)

    with r1c2:
        with st.container(border=True):
            st.markdown(f"<h5 style='color:#1e3a8a; text-align:center;'>{tr({'ar': f'التركيبة السكانية لأفضل موقع ({top_location})', 'en': f'Demographics for Top Location ({top_location})'})}</h5>", unsafe_allow_html=True)
            st.markdown(f"<p class='chart-subtitle'>{tr({'ar': 'التوزيع العمري للعملاء في المنطقة المستهدفة لتحديد تشكيلة المنتجات المناسبة', 'en': 'Age distribution in the target area to determine product assortment'})}</p>", unsafe_allow_html=True)
            
            demo_df = df_filtered[df_filtered['governorate_ar'] == top_location].groupby('age_band')['customer_id'].nunique().reset_index()
            
            if not demo_df.empty:
                fig_donut = px.pie(demo_df, names='age_band', values='customer_id', hole=0.6,
                                   color_discrete_sequence=px.colors.sequential.Blues_r)
                fig_donut.update_layout(showlegend=True, legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5), margin=dict(t=10, b=10, l=10, r=10))
                st.plotly_chart(fig_donut, use_container_width=True)
            else:
                st.info(tr({'ar': "لا توجد بيانات ديموغرافية كافية.", 'en': "Not enough demographic data."}))

    st.markdown("<br>", unsafe_allow_html=True)
    
    with st.container(border=True):
        st.markdown(f"<h5 style='color:#1e3a8a;'>{tr({'ar': 'التوصيات النهائية لمواقع التوسع (Top Recommended Locations)', 'en': 'Top Recommended Locations'})}</h5>", unsafe_allow_html=True)
        
        table_cols = {
            'governorate_ar': tr({'ar': 'المحافظة / الموقع', 'en': 'Location (Gov)'}),
            'Site_Score': tr({'ar': 'تقييم الموقع (من 100)', 'en': 'Site Score (/100)'}),
            'total_demand': tr({'ar': 'حجم الطلب الحالي (ج.م)', 'en': 'Current Demand'}),
            'branch_count': tr({'ar': 'الفروع الحالية', 'en': 'Existing Branches'}),
            'Projected_Sales': tr({'ar': 'المبيعات المتوقعة للفرع (ج.م)', 'en': 'Projected Sales (Yr 1)'}),
            'Recommendation': tr({'ar': 'حالة التوصية', 'en': 'Recommendation'})
        }
        
        display_df = analysis_df.head(7).copy()
        display_df['total_demand'] = display_df['total_demand'].apply(format_number)
        display_df['Projected_Sales'] = display_df['Projected_Sales'].apply(format_number)
        
        display_df = display_df.rename(columns=table_cols)
        display_cols = list(table_cols.values())
        
        st.dataframe(display_df[display_cols].style.format({
            table_cols['Site_Score']: '{:.1f}',
            table_cols['branch_count']: '{:.0f}'
        }).map(lambda x: 'color: #10b981; font-weight: bold;' if 'قصوى' in str(x) or 'Top' in str(x) else '', subset=[table_cols['Recommendation']]), 
        use_container_width=True, hide_index=True)


# --- AI Strategic Decisions Tab ---
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-20b"

def call_groq(api_key, prompt):
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": GROQ_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1, "max_completion_tokens": 1000}
    try:
        r = requests.post(GROQ_URL, headers=headers, json=payload, timeout=90)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"].get("content", "").strip(), None
    except requests.exceptions.RequestException as e:
        return None, redact(f"Groq connection error: {e}", api_key)
    return None, redact(f"Groq error {r.status_code}: {r.text[:200]}", api_key)

def render_ai_box(text):
    lines = []
    for line in text.split("\n"):
        s = html.escape(line)
        s = re.sub(r"^\s*#{1,6}\s+(.*)$", r"<b>\1</b>", s)
        s = re.sub(r"^(\s*)[*+-]\s+", r"\1• ", s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        lines.append(s)
    safe_html = "<br>".join(lines)
    st.markdown(f"<div class='ai-response-box' dir='auto'>{safe_html}</div>", unsafe_allow_html=True)

TG_CHUNK = 3500
def telegram_html(text):
    out = []
    for line in text.split("\n"):
        s = html.escape(line, quote=False)
        s = re.sub(r"^\s*#{1,6}\s+(.*)$", r"<b>\1</b>", s)
        s = re.sub(r"^(\s*)[*+-]\s+", r"\1• ", s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        s = s.replace("**", "")
        out.append(s)
    return "\n".join(out)

def split_for_telegram(body, limit=TG_CHUNK):
    chunks, cur = [], ""
    for line in body.split("\n"):
        while len(line) > limit:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(cur) + len(line) + 1 > limit and cur:
            chunks.append(cur)
            cur = line
        else:
            cur = line if not cur else cur + "\n" + line
    if cur:
        chunks.append(cur)
    return chunks or [""]

def send_telegram_directive(token, chat_id, memo_text, decision_id, lang):
    title = "قرارات التوسع واختيار المواقع" if lang == 'ar' else "Expansion & Site Selection Decisions"
    button = "تم الاستلام وجاري دراسة التنفيذ" if lang == 'ar' else "Received - under review"
    chunks = split_for_telegram(telegram_html(memo_text))
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for i, chunk in enumerate(chunks):
        text = (f"<b>{html.escape(title)}</b>\n\n" if i == 0 else "") + chunk
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if i == len(chunks) - 1:
            payload["reply_markup"] = {"inline_keyboard": [[{"text": button, "callback_data": f"Approve_{decision_id}"}]]}
        try:
            r = requests.post(url, json=payload, timeout=30)
            data = r.json() if r.status_code == 200 else {}
            if r.status_code != 200 or not data.get("ok"):
                return False, redact(f"Telegram error {r.status_code}", token)
        except Exception as e:
            return False, redact(f"Telegram connection error: {e}", token)
    return True, None

LOG_COLS = ['ID', 'Date', 'Topic', 'Status']
class DecisionLogError(Exception): pass

def read_decisions(path):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return pd.DataFrame(columns=LOG_COLS)
    df = pd.read_csv(path, dtype=str, encoding='utf-8-sig').fillna('')
    for col in LOG_COLS:
        if col not in df.columns: df[col] = ''
    return df

def write_decisions(df, path):
    import tempfile
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
    os.close(fd)
    df.to_csv(tmp, index=False, encoding='utf-8-sig')
    os.replace(tmp, path)

def append_decision(path, row):
    existing = read_decisions(path)
    new_row = pd.DataFrame([row], columns=LOG_COLS)
    write_decisions(pd.concat([new_row, existing], ignore_index=True), path)

def sync_telegram_statuses(token, path):
    try: df = read_decisions(path)
    except: return 0, "Log read error"
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=30)
        res = r.json()
    except: return 0, "Telegram connection error"
    if not res.get("ok"): return 0, "Telegram API error"
    updated = 0
    for update in res.get("result", []):
        data = (update.get("callback_query") or {}).get("data") or ""
        if "_" not in data: continue
        action, dec_id = data.split("_", 1)
        if not dec_id.startswith("EXP_"): continue
        new_status = {'Approve': 'Executed', 'Reject': 'Rejected'}.get(action)
        mask = df['ID'].astype(str) == dec_id
        if new_status and mask.any() and (df.loc[mask, 'Status'] != new_status).any():
            df.loc[mask, 'Status'] = new_status
            updated += 1
    if updated: write_decisions(df, path)
    return updated, None

def status_style(val):
    color = '#f59e0b' if val == 'Pending' else '#10b981' if val == 'Executed' else '#ef4444'
    return f'color: {color}; font-weight: bold'

with tab_ai:
    dec_file = os.path.join(resolve_data_dir(), 'expansion_decisions_log.csv')
    groq_key = get_secret("GROQ_API_KEY")
    telegram_token = get_secret("TELEGRAM_TOKEN")
    telegram_chat_id = get_secret("TELEGRAM_CHAT_ID")
    api_key_configured = bool(groq_key)
    telegram_configured = bool(telegram_token and telegram_chat_id)

    flash = st.session_state.pop('exp_flash', None)
    if flash:
        getattr(st, flash[0])(flash[1])

    st.markdown(f"<h4 style='color:#1e3a8a; text-align:center;'>{tr({'ar': 'إصدار قرارات التوسع وفتح الفروع الجديدة', 'en': 'Generate Expansion & Site Decisions'})}</h4>", unsafe_allow_html=True)
    
    if st.button(tr({'ar': "توليد القرارات الآن", 'en': "Generate Decisions Now"}), type="primary", use_container_width=True):
        if not api_key_configured:
            st.warning(tr({'ar': "الرجاء إعداد GROQ_API_KEY", 'en': "Please configure GROQ_API_KEY"}))
        elif analysis_df.empty:
            st.warning(tr({'ar': "لا توجد بيانات كافية.", 'en': "Not enough data."}))
        else:
            with st.spinner(tr({'ar': "يتم تحليل خريطة الطلب لاستخراج أوامر التوسع...", 'en': "Analyzing demand map for expansion directives..."})):
                sys_lang = "Arabic" if st.session_state.lang == 'ar' else "English"
                
                top_1 = analysis_df.iloc[0] if len(analysis_df) > 0 else None
                top_2 = analysis_df.iloc[1] if len(analysis_df) > 1 else None
                worst = analysis_df.iloc[-1] if len(analysis_df) > 0 else None
                
                data_summary = ""
                if top_1 is not None:
                    data_summary += f"- أولوية أولى للتوسع: محافظة {top_1['governorate_ar']} (الطلب: {format_number(top_1['total_demand'])} ج.م، الفروع الحالية: {top_1['branch_count']}، المبيعات المتوقعة للفرع الجديد: {format_number(top_1['Projected_Sales'])} ج.م)\n"
                if top_2 is not None:
                    data_summary += f"- أولوية ثانية للتوسع: محافظة {top_2['governorate_ar']} (الطلب: {format_number(top_2['total_demand'])} ج.م، الفروع الحالية: {top_2['branch_count']}، المبيعات المتوقعة: {format_number(top_2['Projected_Sales'])} ج.م)\n"
                if worst is not None:
                    data_summary += f"- محافظة متخمة بالفروع (خطر أكل المبيعات): {worst['governorate_ar']} (الفروع الحالية: {worst['branch_count']}، التقييم ضعيف للفتح الجديد).\n"
                
                prompt = (
                    f"أنت مدير تطوير أعمال تنفيذي (Business Development Director) في شركة بيع تجزئة. استخرج 3 قرارات استراتيجية حاسمة لفتح فروع جديدة باللغة {sys_lang}.\n"
                    f"البيانات التحليلية للفجوة بين الطلب والفروع:\n{data_summary}\n"
                    "قواعد قرارات التوسع:\n"
                    "- المحافظة ذات الطلب العالي والفروع القليلة: أعطِ أمراً فورياً ببدء البحث عن موقع عقاري فيها لتلبية الطلب وتقليل الاعتماد على الشحن.\n"
                    "- المحافظة المتخمة بالفروع: أصدر قراراً حازماً بوقف أي استثمار عقاري جديد فيها (CAPEX Freeze) لتجنب أكل المبيعات (Cannibalization).\n\n"
                    "شروط الإجابة:\n"
                    "1. اكتب 3 قرارات في شكل نقاط (Bullet points) وكل قرار في سطر واحد مباشر.\n"
                    "2. لا تخترع أرقاماً غير موجودة في البيانات، استخدم الأرقام المقدمة لك فقط.\n"
                    "3. لا تستخدم التقسيمات مثل [الهدف/التأثير] ولا تستخدم الرموز التعبيرية (Emojis).\n"
                    "4. ادخل في القرارات مباشرة بدون أي مقدمة أو خاتمة."
                )
                
                ai_res, ai_err = call_groq(groq_key, prompt)
                if ai_res:
                    st.session_state['exp_ai_response'] = ai_res
                    st.session_state['exp_ai_lang'] = st.session_state.lang
                else:
                    st.error(ai_err)

    if 'exp_ai_response' in st.session_state:
        memo_text = st.session_state['exp_ai_response']
        memo_lang = st.session_state.get('exp_ai_lang', st.session_state.lang)

        st.markdown("<br>", unsafe_allow_html=True)
        render_ai_box(memo_text)
        st.markdown("<br>", unsafe_allow_html=True)
        
        c_btn1, c_btn2 = st.columns([1, 2])
        with c_btn1:
            if st.button(tr({'ar': "إرسال القرارات لاعتمادها (تليجرام)", 'en': "Send Decisions via Telegram"}), use_container_width=True):
                if not telegram_configured:
                    st.warning(tr({'ar': "تليجرام غير مفعل", 'en': "Telegram not configured"}))
                else:
                    decision_id = "EXP_" + str(int(time.time()))
                    ok, err = send_telegram_directive(telegram_token, telegram_chat_id, memo_text, decision_id, memo_lang)
                    if not ok:
                        st.error(err)
                    else:
                        topic = "قرارات التوسع واختيار المواقع" if memo_lang == 'ar' else "Expansion & Site Decisions"
                        try:
                            append_decision(dec_file, {'ID': decision_id, 'Date': pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"), 'Topic': topic, 'Status': "Pending"})
                            st.session_state['exp_flash'] = ('success', tr({'ar': "تم إرسال القرارات بنجاح", 'en': "Sent successfully"}))
                        except Exception as e:
                            st.session_state['exp_flash'] = ('warning', f"Sent to Telegram but log failed: {e}")
                        st.rerun()

    st.markdown("<br><hr>", unsafe_allow_html=True)
    c_ai1, c_ai2 = st.columns([2, 1])
    with c_ai1:
        st.markdown(f"#### {tr({'ar': 'سجل قرارات التوسع العقاري', 'en': 'Expansion Decisions Log'})}")
    with c_ai2:
        if telegram_configured:
            if st.button(tr({'ar': "تحديث حالات التنفيذ", 'en': "Sync Executions"})):
                n_updated, sync_err = sync_telegram_statuses(telegram_token, dec_file)
                if sync_err:
                    st.error(f"Sync error: {sync_err}")
                elif n_updated:
                    st.session_state['exp_flash'] = ('success', tr({'ar': "تمت المزامنة بنجاح", 'en': "Synced successfully"}))
                    st.rerun()
                else:
                    st.info(tr({'ar': "لا توجد تحديثات جديدة.", 'en': "No new updates."}))

    try:
        dec_df = read_decisions(dec_file)
    except DecisionLogError as e:
        dec_df = None
        st.error(str(e))
    if dec_df is not None and not dec_df.empty:
        display_cols = {
            'ID': 'ID', 
            'Date': tr({'ar': 'التاريخ', 'en': 'Date'}), 
            'Topic': tr({'ar': 'موضوع القرار', 'en': 'Topic'}), 
            'Status': tr({'ar': 'حالة التنفيذ', 'en': 'Status'})
        }
        dec_df = dec_df.rename(columns=display_cols)
        styler = dec_df.style
        styler = (styler.map if hasattr(styler, 'map') else styler.applymap)(status_style, subset=[display_cols['Status']])
        st.dataframe(styler, hide_index=True, use_container_width=True)