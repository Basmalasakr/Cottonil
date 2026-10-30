"""Design system: colors, CSS, bilingual helpers, and small HTML helpers (KPI card, pill, header, sidebar)."""
import streamlit as st
from content import GROUPS, MODULES
from data_loader import have

# ---- Palette sampled from the approved dashboard screenshots -----------------------------------
NAVY = "#1B2F7A"      # page titles
BG = "#F4F6FA"        # page background
CARD = "#FFFFFF"      # cards / sidebar
BORDER = "#E3EBFA"    # card outline
TEXT = "#141A26"      # main text / KPI values
MUTED = "#667085"     # labels, subtitles
BLUE = "#2979FF"      # primary: KPI top border, buttons, key figures, active menu item
SKY = "#3AB8F4"       # panel-title underline, outlines, accents
PRIMARY = BLUE        # kept so existing imports (from theme import PRIMARY) keep working

KIND = {  # (text, background)
    "ok": ("#15803D", "#DCFCE7"), "warn": ("#B45309", "#FEF3C7"),
    "bad": ("#C62828", "#FEE2E2"), "info": ("#1B2F7A", "#DBEAFE"), "muted": ("#475569", "#E2E8F0"),
}
MOD = {m["slug"]: m for m in MODULES}
GRP = {g["id"]: g for g in GROUPS}

# Chart colours, in the same order as the donut in the screenshot: navy, sky, light sky, pale, slate
PALETTE = ["#1A365D", "#0EA5E9", "#38BDF8", "#BAE6FD", "#94A3B8"]


def lang():
    return st.session_state.get("lang", "ar")


def tr(d):
    """d = {'ar': ..., 'en': ...} (or any dict that has ar/en keys)."""
    return d[lang()]


def inject():
    ar = lang() == "ar"
    direction = "rtl" if ar else "ltr"

    st.markdown(f"""<style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@400;600;700&display=swap');

    /* Fonts. Material icons are excluded: overriding their font is what made the words
       "keyboard_double_arrow_left" / "expand_more" show up as plain text. */
    html, body, .stApp, [class*="st-"]:not([data-testid="stIconMaterial"]) {{ font-family:'IBM Plex Sans Arabic', sans-serif; }}
    [data-testid="stIconMaterial"], .material-symbols-rounded, .material-icons {{ font-family:'Material Symbols Rounded' !important; }}

    .stApp {{ background:{BG}; }}
    .block-container {{ padding-top:1.4rem; max-width:1400px; }}

    /* Layout direction: in Arabic the whole app is RTL, which also moves the sidebar to the right.
       In English it is LTR and the sidebar sits on the left. */
    [data-testid="stAppViewContainer"] {{ direction:{direction}; }}
    [data-testid="stMain"], section.main {{ direction:{direction}; text-align:{'right' if ar else 'left'}; }}
    [data-testid="stSidebar"] {{ direction:{direction}; text-align:{'right' if ar else 'left'}; }}
    [data-testid="stPlotlyChart"], .js-plotly-plot {{ direction:ltr; }}

    /* Sidebar: fixed width, no sliding, scrollbar never shifts the text */
    [data-testid="stSidebar"], [data-testid="stSidebar"] * {{ transition:none !important; animation:none !important; }}
    [data-testid="stSidebar"] {{ background:{CARD}; border-inline-end:1px solid {BORDER}; }}
    [data-testid="stSidebar"] * {{ color:{TEXT}; }}
    [data-testid="stSidebarContent"] {{ scrollbar-gutter:stable; }}
    [data-testid="stSidebarUserContent"] {{ padding-top:1rem; }}

    @media (min-width: 768px) {{
        [data-testid="stSidebar"] {{
            width:270px !important; min-width:270px !important; max-width:270px !important;
            transform:none !important; margin-inline:0 !important;
        }}
        /* no collapse / expand controls, no empty header strip above the brand */
        [data-testid="stSidebarCollapseButton"], [data-testid="stExpandSidebarButton"],
        [data-testid="stSidebarCollapsedControl"], [data-testid="collapsedControl"],
        [data-testid="stSidebarResizeHandle"], [data-testid="stSidebarHeader"],
        [data-testid="stSidebarNavViewButton"] {{ display:none !important; }}
    }}

    /* Streamlit top bar (Deploy / menu) */
    header[data-testid="stHeader"] {{ display:none !important; }}
    #MainMenu {{ visibility:hidden; }}
    footer {{ visibility:hidden; }}

    /* Brand block (top of sidebar) */
    [data-testid="stSidebar"] .brand {{ padding:.2rem .5rem 1rem .5rem; margin-bottom:.4rem; }}
    [data-testid="stSidebar"] .brand-n {{ font-size:1.7rem; font-weight:800; color:{NAVY}; line-height:1.1; }}
    [data-testid="stSidebar"] .brand-s {{ font-size:.8rem; color:{MUTED}; margin-top:2px; }}
    [data-testid="stSidebar"] .brand::after {{ content:""; display:block; width:38px; height:3px; border-radius:2px; background:{SKY}; margin-top:10px; }}

    /* Sidebar menu */
    [data-testid="stSidebar"] .nav-g {{ font-size:.72rem; font-weight:700; color:{MUTED}; margin:1rem .6rem .25rem .6rem; text-transform:uppercase; letter-spacing:.03em; }}
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {{ gap:.15rem; }}
    [data-testid="stPageLink-NavLink"] {{ border-radius:8px; padding:5px 12px; }}
    [data-testid="stPageLink-NavLink"]:hover {{ background:#EEF4FF; }}
    [data-testid="stPageLink-NavLink"][aria-current="page"] {{ background:{BLUE}; }}
    [data-testid="stPageLink-NavLink"][aria-current="page"] * {{ color:#fff !important; font-weight:600; }}

    div[data-testid="stVerticalBlockBorderWrapper"] {{ background:{CARD}; border-radius:12px; border:1px solid {BORDER}; }}

    /* Primary buttons (e.g. "approve and execute") */
    button[kind="primary"], [data-testid="stBaseButton-primary"] {{ background:{BLUE}; border-color:{BLUE}; color:#fff; border-radius:8px; }}
    button[kind="primary"]:hover, [data-testid="stBaseButton-primary"]:hover {{ background:#1F63D6; border-color:#1F63D6; color:#fff; }}

    .kpi {{ background:{CARD}; border:1px solid {BORDER}; border-radius:12px; padding:14px 16px; height:100%; min-height:112px; border-top:3px solid {BLUE}; }}
    .kpi .l {{ color:{MUTED}; font-size:.78rem; }}
    .kpi .v {{ color:{TEXT}; font-size:1.55rem; font-weight:700; line-height:1.25; white-space:nowrap; }}
    .kpi .s {{ color:{MUTED}; font-size:.74rem; }}
    .pill {{ display:inline-block; padding:1px 9px; border-radius:999px; font-size:.72rem; font-weight:600; margin:0 0 4px 0; margin-inline-start:6px; }}
    .pg-title {{ font-size:1.7rem; font-weight:800; color:{NAVY}; margin:0; }}
    .pg-sub {{ color:{MUTED}; margin:0 0 1rem 0; }}
    .panel-t {{ font-weight:700; color:{TEXT}; font-size:1rem; padding-bottom:.6rem; margin-bottom:.8rem; border-bottom:2px solid {SKY}; }}
    .insight {{ background:#EFF6FF; border-inline-start:4px solid {SKY}; padding:10px 14px; border-radius:8px; color:{TEXT}; margin:1rem 0; }}
    </style>""", unsafe_allow_html=True)


def sidebar(pages_by_group):
    """Custom sidebar: brand on top, language switch, then the grouped menu.

    pages_by_group = {group_id: [(module_dict, st.Page), ...]}
    Replaces Streamlit's built-in navigation list (which always renders above anything else
    and adds the 'expand more' / collapse icons).
    """
    sub = tr({"ar": "مركز القيادة الذكي", "en": "AI Command Center"})
    with st.sidebar:
        st.markdown(f'<div class="brand"><div class="brand-n">Cotonil</div><div class="brand-s">{sub}</div></div>',
                    unsafe_allow_html=True)
        st.radio("Language / اللغة", ["ar", "en"], key="lang", horizontal=True,
                 format_func=lambda x: "العربية" if x == "ar" else "English")
        for g in GROUPS:
            st.markdown(f'<div class="nav-g">{tr(g)}</div>', unsafe_allow_html=True)
            for m, page in pages_by_group.get(g["id"], []):
                st.page_link(page, label=tr(m))


def header(title, subtitle="", kicker=""):
    k = f'<p style="color:{BLUE};font-weight:700;font-size:.8rem;margin:0">{kicker}</p>' if kicker else ""
    st.markdown(f'{k}<p class="pg-title">{title}</p><p class="pg-sub">{subtitle}</p>', unsafe_allow_html=True)


def panel_title(text):
    """Card section title with the sky-blue underline used in the screenshots."""
    st.markdown(f'<div class="panel-t">{text}</div>', unsafe_allow_html=True)


def pill(text, kind="muted"):
    c, b = KIND[kind]
    return f'<span class="pill" style="color:{c};background:{b}">{text}</span>'


def kpi(label, value, sub="", badge=None, kind="ok"):
    b = pill(badge, kind) if badge else ""
    return f'<div class="kpi"><div class="l">{label}</div><div class="v">{value} {b}</div><div class="s">{sub}</div></div>'


def insight(text):
    st.markdown(f'<div class="insight">💡 {text}</div>', unsafe_allow_html=True)


def module_page(slug):
    """صفحة أساسية: السؤال، الداتا، المطلوب بناؤه. اكتب الكود الفعلي بعد استدعائها."""
    m = MOD[slug]
    header(tr(m), tr(m["q"]), tr(GRP[m["group"]]))
    with st.container(border=True):
        st.markdown("**" + tr({"ar": "البيانات المستخدمة", "en": "Data used"}) + "**")
        pills = []
        for f in m["files"]:
            if f.endswith("?"):
                pills.append(pill(f[:-1] + " · " + tr({"ar": "غير موجود", "en": "missing"}), "warn"))
            elif have(f):
                pills.append(pill(f + " ✓", "ok"))
            else:
                pills.append(pill(f, "muted"))
        st.markdown(" ".join(pills), unsafe_allow_html=True)
        st.markdown("**" + tr({"ar": "المطلوب بناؤه", "en": "To build"}) + "**\n" + "\n".join(f"- {b}" for b in m["build"][lang()]))
        if m.get("ai"):
            insight(tr(m["ai"]))


def plot(fig, h=280, legend=False):
    """Consistent chart styling."""
    fig.update_layout(height=h, margin=dict(l=0, r=0, t=10, b=0), plot_bgcolor="rgba(0,0,0,0)",
                      paper_bgcolor="rgba(0,0,0,0)", xaxis_title=None, yaxis_title=None,
                      font=dict(color=TEXT), showlegend=legend, colorway=PALETTE)
    fig.update_yaxes(gridcolor=BORDER)
    st.plotly_chart(fig, width="stretch")
