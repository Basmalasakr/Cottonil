import streamlit as st

st.set_page_config(page_title="Cotonil | Command Center", page_icon="🧵", layout="wide",
                   initial_sidebar_state="expanded")

from content import GROUPS, MODULES
from theme import inject, sidebar, tr

if "lang" not in st.session_state:
    st.session_state.lang = "ar"
inject()

# Register every page once (flat list); the visible menu is drawn by theme.sidebar().
pages_by_group = {g["id"]: [] for g in GROUPS}
all_pages = []
for g in GROUPS:
    for m in MODULES:
        if m["group"] == g["id"]:
            page = st.Page(f"views/{m['slug'].replace('-', '_')}.py", title=tr(m), url_path=m["slug"],
                           default=(m["slug"] == "executive-dashboard"))
            pages_by_group[g["id"]].append((m, page))
            all_pages.append(page)

try:
    nav = st.navigation(all_pages, position="hidden")   # hide Streamlit's own menu
except TypeError:                                       # very old Streamlit without `position`
    nav = st.navigation(all_pages)

sidebar(pages_by_group)   # brand on top, language switch, grouped menu
nav.run()
