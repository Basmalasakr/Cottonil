# -*- coding: utf-8 -*-
"""
لوحة العرض البصري وتحليلات البلانوجرام - قطونيل
"""
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import html

# =====================================================================
# 1) إعدادات الصفحة واللغة
# =====================================================================
try:
    st.set_page_config(layout="wide", page_title="العرض البصري والبلانوجرام")
except Exception:
    pass

if 'lang' not in st.session_state:
    st.session_state.lang = 'ar'

def tr(text_dict):
    return text_dict.get(st.session_state.lang, text_dict.get('en', ''))

# إضافة اختيار اللغة في الشريط الجانبي (مثل باقي الصفحات)
st.sidebar.markdown(f"<h3>{tr({'ar': 'إعدادات النظام', 'en': 'System Settings'})}</h3>", unsafe_allow_html=True)
selected_lang = st.sidebar.radio(tr({'ar': "اللغة", 'en': "Language"}), ['ar', 'en'], index=0 if st.session_state.lang == 'ar' else 1)
if selected_lang != st.session_state.lang:
    st.session_state.lang = selected_lang
    st.rerun()

is_ar = st.session_state.lang == 'ar'
direction = "rtl" if is_ar else "ltr"
text_align = "right" if is_ar else "left"

# =====================================================================
# 2) التصميم (CSS الديناميكي)
# =====================================================================
st.markdown(f"""
<style>
.stApp {{ background-color: #f8fafc; color: #1e3a8a; }}
h1, h2, h3, h4, h5, h6 {{ color: #1e3a8a !important; }}
.kpi-card {{
    background-color: #ffffff; padding: 20px; border-radius: 12px;
    border: 2px solid #cbd5e1; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    text-align: center; margin-bottom: 15px; transition: transform 0.2s;
}}
.kpi-card:hover {{ transform: scale(1.02); border-color: #3b82f6; }}
.kpi-value {{ font-size: 24px; font-weight: bold; color: #1e3a8a; margin-bottom: 5px; }}
.kpi-label {{ font-size: 13px; color: #64748b; font-weight: 600; }}
div[data-testid="stVerticalBlockBorderWrapper"] {{
    border-radius: 12px; border: 2px solid #94a3b8 !important; 
    background-color: #ffffff; padding: 20px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    margin-bottom: 20px;
}}
.chart-title {{ font-size: 16px; font-weight: bold; color: #1e3a8a; text-align: {text_align}; margin-bottom: 15px; }}
.branch-table {{ width: 100%; text-align: {text_align}; border-collapse: collapse; margin-top: 10px; }}
.branch-table th {{ background-color: #f1f5f9; color: #1e3a8a; padding: 8px; border: 1px solid #cbd5e1; text-align: {text_align}; }}
.branch-table td {{ padding: 8px; border: 1px solid #cbd5e1; color: #0f172a; font-weight: 500; text-align: {text_align}; }}
.good-score {{ background-color: #dcfce7; color: #166534; font-weight: bold; border-radius: 4px; padding: 2px 6px; }}
.bad-score {{ background-color: #fef08a; color: #854d0e; font-weight: bold; border-radius: 4px; padding: 2px 6px; }}
[data-testid="stMarkdownContainer"] {{ direction: {direction}; text-align: {text_align}; }}
</style>
""", unsafe_allow_html=True)

def get_kpi_html(label, value, delta_text=""):
    color = "#16a34a" if "+" in str(delta_text) else "#dc2626"
    delta_html = f"<div style='font-size:12px; margin-top:5px; color:{color};' dir='ltr'>{html.escape(str(delta_text))}</div>" if delta_text else ""
    return f"""
    <div class="kpi-card">
        <div class="kpi-label">{html.escape(str(label))}</div>
        <div class="kpi-value">{html.escape(str(value))}</div>
        {delta_html}
    </div>
    """

# =====================================================================
# 3) توليد بيانات العرض البصري (Simulation Data)
# =====================================================================
@st.cache_data
def generate_vm_data(lang):
    months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'] if lang == 'en' else \
             ['يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو', 'يوليو', 'أغسطس', 'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر']
    
    trend_data = pd.DataFrame({
        'Month': months,
        'Compliance': [75, 78, 80, 82, 85, 84, 88, 89, 90, 91, 91, 92],
        'Space_Productivity': [1000, 1050, 1020, 1100, 1150, 1180, 1200, 1190, 1210, 1230, 1220, 1240],
        'Audit_Score': [85, 86, 88, 87, 89, 90, 92, 91, 94, 95, 95, 96]
    })
    
    cat_names = ["Men's Basics", "Women's Basics", "Underwear", "Home Textiles", "Accessories"] if lang == 'en' else \
                ["أساسيات رجالي", "أساسيات حريمي", "ملابس داخلية", "مفروشات", "إكسسوارات"]
    categories_data = pd.DataFrame({
        'Category': cat_names,
        'Score': [92, 88, 85, 90, 82]
    })
    
    zone_names = ["Entrance", "Men's Apparel", "Women's Apparel", "Underwear", "Promotions"] if lang == 'en' else \
                 ["المدخل", "ملابس رجالي", "ملابس حريمي", "ملابس داخلية", "العروض"]
    zones_data = pd.DataFrame({
        'Zone': zone_names,
        'Value': [18, 28, 24, 16, 14]
    })
    
    top_branches = pd.DataFrame({
        '#': [1, 2, 3, 4, 5],
        'Branch': ['Cairo City Stars', 'Mall of Egypt', 'Alexandria City C.', 'Mansoura', 'Dandy Mall'] if lang == 'en' else \
                  ['سيتي ستارز', 'مول مصر', 'سيتي سنتر الإسكندرية', 'المنصورة', 'داندي مول'],
        'Score': [98, 96, 95, 94, 93]
    })
    
    bottom_branches = pd.DataFrame({
        '#': [1, 2, 3, 4, 5],
        'Branch': ['Tanta', 'Beni Suef', 'Ismailia', 'Sohag', 'Aswan'] if lang == 'en' else \
                  ['طنطا', 'بني سويف', 'الإسماعيلية', 'سوهاج', 'أسوان'],
        'Score': [72, 75, 76, 78, 80]
    })
    
    return trend_data, categories_data, zones_data, top_branches, bottom_branches

trend_df, cat_df, zone_df, top_br, bot_br = generate_vm_data(st.session_state.lang)

# =====================================================================
# 4) الواجهة العلوية والمؤشرات (KPIs)
# =====================================================================
c_title, c_btn = st.columns([8, 2])
with c_title:
    st.markdown(f"<h2 style='text-align: {text_align};'>{tr({'ar': 'العرض البصري وتحليلات البلانوجرام', 'en': 'Visual Merchandising & Planogram'})}</h2>", unsafe_allow_html=True)
    st.markdown(f"<p style='color: #64748b; text-align: {text_align};'>{tr({'ar': 'تحسين تنفيذ العرض، إنتاجية المساحة، والاتساق البصري عبر الفروع', 'en': 'Optimize display execution, space productivity, and visual consistency'})}</p>", unsafe_allow_html=True)
with c_btn:
    if st.button(tr({'ar': 'تحديث التقييمات', 'en': 'Refresh Audits'}), use_container_width=True):
        st.rerun()

st.markdown("<br>", unsafe_allow_html=True)

k1, k2, k3, k4, k5 = st.columns(5)
k1.markdown(get_kpi_html(tr({'ar': 'توافق البلانوجرام', 'en': 'Planogram Compliance'}), "92%", "+8% vs. LY"), unsafe_allow_html=True)
k2.markdown(get_kpi_html(tr({'ar': 'نقاط العرض', 'en': 'Display Score'}), "88/100", "+12% vs. LY"), unsafe_allow_html=True)
curr = "ج.م" if is_ar else "EGP"
k3.markdown(get_kpi_html(tr({'ar': 'إنتاجية المساحة', 'en': 'Space Productivity'}), f"1,240 {curr}", "+18% vs. LY"), unsafe_allow_html=True)
k4.markdown(get_kpi_html(tr({'ar': 'مناطق العرض النشطة', 'en': 'Active Display Zones'}), "124", "+6% vs. LY"), unsafe_allow_html=True)
k5.markdown(get_kpi_html(tr({'ar': 'نتائج تفتيش الفروع', 'en': 'Store Audit Results'}), "96%", "+10% vs. LY"), unsafe_allow_html=True)

# =====================================================================
# 5) لوحة الرسوم البيانية (Dashboard)
# =====================================================================
# --- الصف الأول ---
r1c1, r1c2, r1c3 = st.columns([1.2, 1, 1])

with r1c1:
    with st.container(border=True):
        st.markdown(f"<div class='chart-title'>{tr({'ar': 'تطور توافق البلانوجرام', 'en': 'Planogram Compliance Trend'})}</div>", unsafe_allow_html=True)
        fig1 = go.Figure()
        fig1.add_trace(go.Scatter(x=trend_df['Month'], y=trend_df['Compliance'], mode='lines+markers',
                                  line=dict(color='#3b82f6', width=3), marker=dict(size=8, color='#1e3a8a')))
        fig1.update_layout(margin=dict(l=0, r=0, t=10, b=0), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', 
                           yaxis=dict(range=[0, 100]), height=250)
        st.plotly_chart(fig1, use_container_width=True)

with r1c2:
    with st.container(border=True):
        st.markdown(f"<div class='chart-title'>{tr({'ar': 'نقاط العرض حسب القسم', 'en': 'Display Score by Category'})}</div>", unsafe_allow_html=True)
        fig2 = px.bar(cat_df, x='Score', y='Category', orientation='h', text='Score')
        fig2.update_traces(marker_color='#3b82f6', textposition='outside')
        fig2.update_layout(margin=dict(l=0, r=0, t=10, b=0), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', 
                           xaxis=dict(range=[0, 110]), height=250, yaxis_title="")
        st.plotly_chart(fig2, use_container_width=True)

with r1c3:
    with st.container(border=True):
        st.markdown(f"<div class='chart-title'>{tr({'ar': 'أداء مناطق العرض', 'en': 'Display Zones Performance'})}</div>", unsafe_allow_html=True)
        fig3 = px.pie(zone_df, values='Value', names='Zone', hole=0.65, 
                      color_discrete_sequence=['#1e3a8a', '#3b82f6', '#93c5fd', '#64748b', '#cbd5e1'])
        fig3.update_traces(textinfo='none')
        fig3.add_annotation(text="124<br>Zones", x=0.5, y=0.5, font_size=20, showarrow=False, font_color="#1e3a8a", font_weight="bold")
        fig3.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=250, legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1))
        st.plotly_chart(fig3, use_container_width=True)

# --- الصف الثاني ---
r2c1, r2c2, r2c3 = st.columns([1.2, 1, 1])

with r2c1:
    with st.container(border=True):
        st.markdown(f"<div class='chart-title'>{tr({'ar': 'إنتاجية المساحة (المبيعات / متر مربع)', 'en': 'Space Productivity Trend'})}</div>", unsafe_allow_html=True)
        fig4 = go.Figure()
        fig4.add_trace(go.Scatter(x=trend_df['Month'], y=trend_df['Space_Productivity'], mode='lines', fill='tozeroy',
                                  line=dict(color='#10b981', width=3), fillcolor='rgba(16, 185, 129, 0.2)'))
        fig4.update_layout(margin=dict(l=0, r=0, t=10, b=0), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', height=250)
        st.plotly_chart(fig4, use_container_width=True)

with r2c2:
    with st.container(border=True):
        st.markdown(f"<div class='chart-title'>{tr({'ar': 'نتائج تفتيش الفروع', 'en': 'Store Audit Results'})}</div>", unsafe_allow_html=True)
        fig5 = px.bar(trend_df, x='Month', y='Audit_Score')
        fig5.update_traces(marker_color='#1e3a8a')
        fig5.update_layout(margin=dict(l=0, r=0, t=10, b=0), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', yaxis=dict(range=[0, 100]), height=250)
        st.plotly_chart(fig5, use_container_width=True)

with r2c3:
    with st.container(border=True):
        st.markdown(f"<div class='chart-title'>{tr({'ar': 'أفضل وأسوأ الفروع في التنفيذ', 'en': 'Top & Bottom Branches'})}</div>", unsafe_allow_html=True)
        
        t1_html = "".join([f"<tr><td>{row['#']}</td><td style='text-align:{text_align};'>{row['Branch']}</td><td><span class='good-score'>{row['Score']}</span></td></tr>" for _, row in top_br.iterrows()])
        t2_html = "".join([f"<tr><td>{row['#']}</td><td style='text-align:{text_align};'>{row['Branch']}</td><td><span class='bad-score'>{row['Score']}</span></td></tr>" for _, row in bot_br.iterrows()])
        
        l_top = tr({'ar': 'أفضل 5 فروع', 'en': 'Top 5 Branches'})
        l_bot = tr({'ar': 'أسوأ 5 فروع', 'en': 'Bottom 5 Branches'})
        l_br = tr({'ar': 'الفرع', 'en': 'Branch'})
        l_sc = tr({'ar': 'النقاط', 'en': 'Score'})
        
        st.markdown(f'''
        <div style="display:flex; gap:15px; height:210px; overflow-y:auto; flex-direction: {'row' if not is_ar else 'row-reverse'};">
            <div style="flex:1;">
                <div style="font-size:12px; font-weight:bold; color:#1e3a8a; margin-bottom:5px; text-align:{text_align};">{l_top}</div>
                <table class="branch-table">
                    <tr><th>#</th><th>{l_br}</th><th>{l_sc}</th></tr>
                    {t1_html}
                </table>
            </div>
            <div style="flex:1;">
                <div style="font-size:12px; font-weight:bold; color:#1e3a8a; margin-bottom:5px; text-align:{text_align};">{l_bot}</div>
                <table class="branch-table">
                    <tr><th>#</th><th>{l_br}</th><th>{l_sc}</th></tr>
                    {t2_html}
                </table>
            </div>
        </div>
        ''', unsafe_allow_html=True)