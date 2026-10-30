# -*- coding: utf-8 -*-
"""
المساعد الذكي للأعمال - قطونيل (نسخة مستقرة للإنترنت الضعيف)
"""
import os
import re
import ast
import sys
import json
import html
import time
import builtins
from datetime import datetime

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import streamlit as st

# =====================================================================
# 0) إعدادات ومساعدات عامة + تحسين استقرار الاتصال بالإنترنت
# =====================================================================
APP_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
for _p in (APP_DIR, os.path.dirname(APP_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

def get_secret(name, default=""):
    value = None
    try: value = st.secrets.get(name, None)
    except Exception: value = None
    if not value: value = os.environ.get(name, default)
    return str(value).strip() if value else default

def resolve_data_dir():
    forced = os.environ.get("DATA_DIR")
    if forced and os.path.exists(forced): return forced
    for d in (os.path.join(APP_DIR, "data"), os.path.join(os.path.dirname(APP_DIR), "data")):
        if os.path.exists(d): return d
    return "/content"

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = get_secret("GROQ_MODEL", "openai/gpt-oss-20b")

# إعداد Session قوية لتحمل انقطاعات الإنترنت
session = requests.Session()
retry = Retry(connect=3, backoff_factor=1)
adapter = HTTPAdapter(max_retries=retry)
session.mount('http://', adapter)
session.mount('https://', adapter)

def ask_groq(messages, temp=0.3, max_tokens=4000):
    key = get_secret("GROQ_API_KEY")
    if not key: return None, "GROQ_API_KEY غير مضبوط."
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {"model": GROQ_MODEL, "messages": messages, "temperature": temp, "max_completion_tokens": max_tokens}
    
    for attempt in range(3):
        try:
            r = session.post(GROQ_URL, headers=headers, json=payload, timeout=45)
            if r.status_code == 429:
                time.sleep(3)
                continue
            if r.status_code == 200:
                txt = (r.json()["choices"][0]["message"].get("content") or "").strip()
                return (txt, None) if txt else (None, "رد فارغ من النموذج.")
            return None, f"Groq API Error {r.status_code}: {r.text[:200]}"
        except requests.exceptions.RequestException as e:
            if attempt < 2: 
                time.sleep(2)
                continue
            return None, "عذراً، يبدو أن هناك مشكلة في اتصالك بالإنترنت. يرجى المحاولة مرة أخرى."
    return None, "الخدمة مشغولة حالياً، حاول بعد قليل."

def find_col(df, candidates):
    if df is None: return None
    cols = {str(c).lower(): c for c in df.columns}
    for n in candidates:
        if n.lower() in cols: return cols[n.lower()]
    return None

def find_date_col(df, extra=()):
    c = find_col(df, list(extra) + ["order_date", "order_datetime", "date", "created_at", "invoice_date", "start_date", "timestamp"])
    if c: return c
    for col in df.columns:
        if str(df[col].dtype).startswith("datetime64"): return col
    return None

def num(s):
    return pd.to_numeric(s, errors="coerce").fillna(0)

def to_dt(s):
    return pd.to_datetime(s, errors="coerce", utc=True).dt.tz_localize(None)

def pct_delta(new, old):
    return f"{(new / old - 1) * 100:+.1f}%" if old else None

def fmt(x, nd=0):
    try: return f"{x:,.{nd}f}"
    except Exception: return str(x)

def period_filter(df, start, end, cands):
    if df is None or start is None or end is None: return df
    dc = find_col(df, cands)
    if not dc: return df
    d = to_dt(df[dc])
    if d.isna().all(): return df
    f = df[(d >= start) & (d <= end + pd.Timedelta(days=1))]
    return f if len(f) else df

REV_COLS = ["paid_total_EGP", "total_amount", "net_amount", "revenue", "total_EGP"]
CANCEL_RX = r"cancel|void|fail|ملغ|فشل"

LOG_LABELS = {"branch_decisions_log": "الفروع", "distribution_decisions_log": "التوزيع",
              "loyalty_decisions_log": "الولاء", "pricing_decisions_log": "التسعير",
              "supply_chain_decisions_log": "سلسلة الإمداد", "workforce_decisions_log": "القوى العاملة",
              "decisions_log": "عام", "marketing_decisions_log": "التسويق", "crm_decisions_log": "العملاء"}

# =====================================================================
# 1) طبقة البيانات
# =====================================================================
def read_any(path):
    if path.lower().endswith(".parquet"): return pd.read_parquet(path)
    try: return pd.read_csv(path, encoding="utf-8-sig")
    except UnicodeDecodeError: return pd.read_csv(path, encoding="cp1256")

@st.cache_resource(show_spinner="جاري تحميل قواعد البيانات...")
def load_tables():
    d = resolve_data_dir()
    tables = {}
    if os.path.isdir(d):
        files = sorted(os.listdir(d), key=lambda f: (not f.lower().endswith(".parquet"), f))
        for f in files:
            low = f.lower()
            if not (low.endswith(".parquet") or low.endswith(".csv")): continue
            stem = f.rsplit(".", 1)[0]
            if stem in tables: continue
            try: tables[stem] = read_any(os.path.join(d, f))
            except Exception: pass
    return tables

def append_decision(text, status="Pending", file="decisions_log.csv"):
    path = os.path.join(resolve_data_dir(), file)
    row = pd.DataFrame([{"ID": int(time.time()), "Date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                         "Decision": text, "Status": status}])
    exists = os.path.exists(path)
    row.to_csv(path, mode="a", header=not exists, index=False, encoding="utf-8" if exists else "utf-8-sig")

def decisions_frame(T):
    cols = ["القسم", "التاريخ", "القرار", "الحالة"]
    rows = []
    for name, label in LOG_LABELS.items():
        df = T.get(name)
        if df is None or df.empty: continue
        tc, dc, sc = find_col(df, ["Decision", "Topic"]), find_col(df, ["Date"]), find_col(df, ["Status"])
        for _, r in df.iterrows():
            rows.append({"القسم": label, "التاريخ": str(r[dc]) if dc else "",
                         "القرار": str(r[tc]) if tc else "", "الحالة": str(r[sc]) if sc else ""})
    out = pd.DataFrame(rows, columns=cols)
    return out.sort_values("التاريخ", ascending=False).reset_index(drop=True) if len(out) else out

@st.cache_data(show_spinner=False)
def compute_kpis(_tables, filter_start=None, filter_end=None):
    T = _tables
    k = {
        "sales": {"revenue": 0.0, "orders": 0, "aov": 0.0, "discount_rate": 0.0},
        "marketing": {"spend": 0.0, "roas": 0.0, "top_channel": "غير محدد", "cpo": 0.0},
        "customers": {"total": 0, "at_risk": 0, "champions": 0, "retention": 0.0, "repeat_share": 0.0},
        "products": {"items_sold": 0, "top_category": "غير محدد"},
        "pnl": {"revenue_net": 0.0, "cogs": 0.0, "refunds": 0.0, "spend": 0.0, "opex": 0.0, "payroll": 0.0,
                "gross_margin": 0.0, "op_profit": 0.0, "op_margin": 0.0},
        "returns": {}, "decisions": {}, "cogs_ratio": 0.40, "cogs_assumed": True, "weekly": {}, "notes": []
    }
    
    start = pd.to_datetime(filter_start) if filter_start else None
    end = pd.to_datetime(filter_end) if filter_end else None
    valid_ids = None

    try:
        o = T.get("sales_orders")
        rc = find_col(o, REV_COLS)
        if rc:
            mask = pd.Series(True, index=o.index)
            stc = find_col(o, ["status"])
            if stc: mask = ~o[stc].astype(str).str.contains(CANCEL_RX, case=False, na=False, regex=True)
            oo = o[mask]
            
            dc = find_date_col(oo)
            if dc: 
                oo = oo.copy()
                oo["_date"] = to_dt(oo[dc])
                if start and end:
                    oo = oo[(oo["_date"] >= start) & (oo["_date"] <= end + pd.Timedelta(days=1))]
            
            oid = find_col(oo, ["sales_order_id"])
            if oid: valid_ids = set(oo[oid])
            
            o_df = pd.DataFrame()
            if "_date" in oo: o_df["_date"] = oo["_date"]
            
            nb = find_col(oo, ["net_before_tax_EGP"])
            grs = find_col(oo, ["gross_EGP"])
            dsc = find_col(oo, ["discount_EGP"])
            
            if nb: o_df["_net"] = num(oo[nb])
            elif grs and dsc: o_df["_net"] = num(oo[grs]) - num(oo[dsc])
            else: o_df["_net"] = num(oo[rc])
                
            rev, n = float(o_df["_net"].sum()), len(o_df)
            k["sales"].update({"revenue": rev, "orders": n, "aov": rev / n if n else 0.0})
            k["pnl"]["revenue_net"] = rev
            
            c = find_col(oo, ["customer_id"])
            if c:
                o_df["_cust"] = oo[c]
                g = o_df.groupby("_cust")["_net"].agg(["count", "sum"])
                N = len(g)
                rep = g[g["count"] >= 2]
                k["customers"]["total"] = N
                k["customers"]["retention"] = len(rep) / N if N else 0.0
                k["customers"]["repeat_share"] = float(rep["sum"].sum() / rev) if rev else 0.0
                
            if "_date" in o_df and o_df["_date"].notna().any():
                d = o_df["_date"]
                max_d = d.max()
                cur = o_df[d > max_d - pd.Timedelta(days=7)]
                prev = o_df[(d > max_d - pd.Timedelta(days=14)) & (d <= max_d - pd.Timedelta(days=7))]
                k["weekly"] = {"end": str(max_d.date()), "start": str((max_d - pd.Timedelta(days=7)).date()),
                               "cur_rev": float(cur["_net"].sum()), "cur_orders": len(cur),
                               "prev_rev": float(prev["_net"].sum()), "prev_orders": len(prev)}
                
                if not start: start = d.min()
                if not end: end = max_d
    except Exception as e: k["notes"].append(f"قسم المبيعات: {type(e).__name__}")

    try:
        i, p = T.get("sales_order_items"), T.get("products_catalog")
        if i is not None:
            oid_i = find_col(i, ["sales_order_id"])
            ii = i[i[oid_i].isin(valid_ids)] if (valid_ids is not None and oid_i) else pd.DataFrame()
            
            qty = find_col(ii, ["quantity", "qty"])
            uc = find_col(ii, ["unit_cost_EGP"])
            nl = find_col(ii, ["net_line_EGP", "line_total_EGP", "total_EGP", "line_total"])
            mg = find_col(ii, ["margin_EGP"])
            cogs = None
            if nl and uc and qty: cogs = float((num(ii[qty]) * num(ii[uc])).sum())
            elif nl and mg: cogs = float(num(ii[nl]).sum() - num(ii[mg]).sum())
            if cogs is not None and num(ii[nl]).sum() > 0:
                ratio = cogs / float(num(ii[nl]).sum())
                if 0.05 < ratio < 0.98:
                    k["cogs_ratio"], k["cogs_assumed"] = ratio, False
            pid = find_col(ii, ["product_id"])
            cat = find_col(p, ["category_en", "category_ar", "category"]) if p is not None else None
            if pid and cat and nl and pid in p.columns:
                tmp = pd.DataFrame({pid: ii[pid].values, "_w": num(ii[nl]).values})
                tmp = tmp.merge(p[[pid, cat]].drop_duplicates(pid), on=pid, how="left")
                s = tmp.groupby(cat)["_w"].sum().sort_values(ascending=False)
                if len(s): k["products"]["top_category"] = str(s.index[0])
    except Exception as e: pass

    try:
        m = period_filter(T.get("marketing_campaigns"), start, end, ["start_date"])
        sc = find_col(m, ["spend_EGP", "spend", "cost"])
        if m is not None and sc:
            spend = float(num(m[sc]).sum())
            k["marketing"]["spend"] = spend
            k["pnl"]["spend"] = spend
            k["marketing"]["roas"] = k["pnl"]["revenue_net"] / spend if spend > 0 else 0.0
            oa = find_col(m, ["orders_attributed"])
            if oa and k["sales"]["orders"]:
                att = float(num(m[oa]).sum())
                k["marketing"]["cpo"] = spend / att if att else (spend / k["sales"]["orders"])
                k["marketing"]["attributed_orders"] = att
            if k["weekly"]:
                dc = find_col(m, ["start_date", "date"])
                if dc:
                    d, s_ = to_dt(m[dc]), num(m[sc])
                    e = pd.Timestamp(k["weekly"]["end"])
                    k["weekly"]["mkt_cur"] = float(s_[d > e - pd.Timedelta(days=7)].sum())
                    k["weekly"]["mkt_prev"] = float(s_[(d > e - pd.Timedelta(days=14)) & (d <= e - pd.Timedelta(days=7))].sum())
    except Exception as e: pass

    try:
        c = T.get("customers")
        if c is not None:
            if not k["customers"]["total"]: k["customers"]["total"] = len(c)
            sg = find_col(c, ["customer_segment", "segment"])
            if sg:
                s = c[sg].astype(str)
                k["customers"]["at_risk"] = int(s.str.contains("Risk|خطر", na=False, case=False).sum())
                k["customers"]["champions"] = int(s.str.contains("Champion|أبطال|ابطال", na=False, case=False).sum())
    except Exception as e: pass

    try:
        r = period_filter(T.get("sales_returns"), start, end, ["return_date"])
        if r is not None:
            rf = find_col(r, ["refund_amount_EGP"])
            refunds = float(num(r[rf]).sum()) if rf else 0.0
            k["pnl"]["refunds"] = refunds
            k["returns"]["rate"] = refunds / k["pnl"]["revenue_net"] if k["pnl"]["revenue_net"] else 0.0
    except Exception as e: pass

    try:
        ox = period_filter(T.get("operating_expenses"), start, end, ["expense_date"])
        if ox is not None:
            ac = find_col(ox, ["amount_EGP"])
            if ac: k["pnl"]["opex"] = float(num(ox[ac]).sum())
        pr = period_filter(T.get("payroll"), start.replace(day=1) if start is not None else None, end, ["pay_month"])
        if pr is not None:
            npc = find_col(pr, ["net_paid_EGP"])
            if npc: k["pnl"]["payroll"] = float(num(pr[npc]).sum())
    except Exception as e: pass

    pn = k["pnl"]
    pn["cogs"] = pn["revenue_net"] * k["cogs_ratio"]
    pn["gross_margin"] = 1 - k["cogs_ratio"]
    pn["op_profit"] = pn["revenue_net"] - pn["cogs"] - pn["refunds"] - pn["spend"] - pn["opex"] - pn["payroll"]
    pn["op_margin"] = pn["op_profit"] / pn["revenue_net"] if pn["revenue_net"] else 0.0

    try:
        df = decisions_frame(T)
        if len(df):
            k["decisions"] = {
                "total": len(df),
                "by_status": [(a, int(b)) for a, b in df["الحالة"].value_counts().items()],
                "pending": [f"{r['القسم']}: {r['القرار'][:60]}" for _, r in df[df["الحالة"].str.lower() == "pending"].head(5).iterrows()],
            }
    except Exception as e: pass
    return k

def enterprise_text(k):
    s, m, c, p, pn = k["sales"], k["marketing"], k["customers"], k["products"], k["pnl"]
    est = " (تقديري)" if k.get("cogs_assumed") else ""
    L = [
        f"- المبيعات: {fmt(s['revenue'])} ج.م، متوسط الطلب {fmt(s['aov'])} ج.م",
        f"- الربحية: إيراد صافي {fmt(pn['revenue_net'])}، هامش إجمالي {pn['gross_margin'] * 100:.1f}%{est}، صافي ربح تشغيلي {fmt(pn['op_profit'])} ({pn['op_margin'] * 100:.1f}%){est}.",
        f"- المرتجعات: {fmt(pn['refunds'])} ج.م ({k['returns'].get('rate', 0.0) * 100:.1f}% من الإيراد).",
        f"- المصاريف التشغيلية: {fmt(pn['opex'])} ج.م، الرواتب: {fmt(pn['payroll'])} ج.م.",
        f"- التسويق: إنفاق {fmt(m['spend'])} ج.م، ROAS {m['roas']:.2f}x.",
        f"- العملاء: {fmt(c['total'])} عميل، نسبة الاحتفاظ {c['retention'] * 100:.1f}%، الأبطال {fmt(c['champions'])}، المعرضون للخطر {fmt(c['at_risk'])}."
    ]
    return "\n".join(L)

def weekly_text(k):
    w = k.get("weekly") or {}
    if not w:
        return "لا تتوفر بيانات أسبوعية كافية."
    aov_c = w["cur_rev"] / w["cur_orders"] if w["cur_orders"] else 0.0
    aov_p = w["prev_rev"] / w["prev_orders"] if w["prev_orders"] else 0.0
    na = "غير متاح"
    L = [
        f"- الفترة: الأسبوع المنتهي في {w['end']} مقارنة بالأسبوع السابق له.",
        f"- الإيراد: {fmt(w['cur_rev'])} ج.م مقابل {fmt(w['prev_rev'])} ج.م ({pct_delta(w['cur_rev'], w['prev_rev']) or na}).",
        f"- الطلبات: {fmt(w['cur_orders'])} مقابل {fmt(w['prev_orders'])} ({pct_delta(w['cur_orders'], w['prev_orders']) or na}).",
        f"- متوسط الطلب: {fmt(aov_c)} ج.م مقابل {fmt(aov_p)} ج.م ({pct_delta(aov_c, aov_p) or na}).",
    ]
    if "mkt_cur" in w:
        L.append(f"- إنفاق التسويق: {fmt(w['mkt_cur'])} ج.م مقابل {fmt(w['mkt_prev'])} ج.م ({pct_delta(w['mkt_cur'], w['mkt_prev']) or na}).")
    return "\n".join(L)

# =====================================================================
# 2) وكيل الدردشة مع البيانات (Text-to-Pandas)
# =====================================================================
SAFE_BUILTIN_NAMES = ["len", "sum", "min", "max", "sorted", "range", "round", "abs", "list", "dict",
                      "set", "tuple", "str", "int", "float", "bool", "enumerate", "zip", "any", "all",
                      "isinstance", "map", "filter", "reversed", "True", "False", "None"]
SAFE_BUILTINS = {n: getattr(builtins, n) for n in SAFE_BUILTIN_NAMES}
FORBIDDEN_NAMES = {"eval", "exec", "open", "compile", "__import__", "input", "globals", "locals",
                   "getattr", "setattr", "delattr", "vars", "os", "sys", "subprocess", "breakpoint"}
FORBIDDEN_ATTRS = {"read_csv", "read_parquet", "read_excel", "read_json", "read_pickle", "read_sql",
                   "read_table", "to_csv", "to_parquet", "to_pickle", "to_excel", "to_sql", "to_json",
                   "to_hdf", "to_feather", "eval", "system", "popen"}

def validate_code(code):
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)): raise ValueError("الاستيراد غير مسموح")
        if isinstance(node, ast.Attribute) and (node.attr.startswith("_") or node.attr in FORBIDDEN_ATTRS):
            raise ValueError(f"الوصول غير مسموح")
        if isinstance(node, ast.Name) and (node.id in FORBIDDEN_NAMES or node.id.startswith("__")):
            raise ValueError(f"استخدام غير مسموح")

def run_code(code, tables):
    validate_code(code)
    g = {"__builtins__": SAFE_BUILTINS, "pd": pd, "np": np}
    g.update({name: df.copy(deep=False) for name, df in tables.items()})
    exec(code, g)
    if "result" not in g: raise ValueError("لم يتم تعريف المتغير result")
    return g["result"]

def result_to_text(res):
    df = None
    if isinstance(res, pd.Series): df = res.rename(res.name if res.name is not None else "value").reset_index()
    elif isinstance(res, pd.DataFrame): df = res.reset_index(drop=not isinstance(res.index, pd.MultiIndex) and res.index.name is None)
    if df is not None:
        if df.empty: return "لا توجد بيانات مطابقة.", None
        return df.head(30).to_string(index=False)[:4000], df.head(200)
    return str(res)[:3000], None

def extract_code(raw):
    m = re.search(r"```(?:python)?\s*\n(.*?)```", raw, flags=re.S)
    return (m.group(1) if m else raw).strip()

@st.cache_data(show_spinner=False)
def schema_text(_tables):
    out = []
    for name, df in _tables.items():
        if name == "data_dictionary": continue
        cols = []
        for c in df.columns:
            if pd.api.types.is_numeric_dtype(df[c]): cols.append(f"{c}:n")
            elif pd.api.types.is_datetime64_any_dtype(df[c]): cols.append(f"{c}:d")
            else: cols.append(f"{c}:s")
        out.append(f"[{name}] cols: {', '.join(cols)}")
    return "\n".join(out)

PLANNER_RULES = (
    "You are a senior data analyst. Write pandas code that answers the user's question using ONLY the "
    "tables listed below. Each table is already loaded as a DataFrame variable with the same name; "
    "`pd` and `np` are available.\n"
    "Rules: no imports; no file/network access; assign the final answer to a variable named `result` "
    "(DataFrame, Series or scalar) and keep it small (<= 30 rows); join tables on shared id columns; "
    "parse dates with pd.to_datetime(errors='coerce'); round money to 0 decimals. "
    "If the question cannot be answered from these tables, output exactly NO_DATA.\n"
    "Output ONLY one ```python code block.\n"
)

def answer_question(q, tables, k, prev):
    schema = schema_text(tables)
    hist = "\n".join(f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content'][:300]}" for m in prev[-6:])
    msgs = [{"role": "system", "content": PLANNER_RULES + "\n\nTABLES:\n" + schema},
            {"role": "user", "content": (f"Conversation so far:\n{hist}\n\n" if hist else "") + f"Question: {q}"}]
    code, res_text, res_df, last_err, no_data = None, None, None, None, False

    for _ in range(2):
        raw, err = ask_groq(msgs, temp=0.1)
        if err: return {"content": f"تنبيه: {err}"}
        if "NO_DATA" in raw and "```" not in raw:
            no_data = True
            break
        code = extract_code(raw)
        try:
            res_text, res_df = result_to_text(run_code(code, tables))
            last_err = None
            break
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            msgs += [{"role": "assistant", "content": raw},
                     {"role": "user", "content": f"The code failed with: {last_err}\nFix it and return only the corrected ```python block."}]

    if res_text is None and not no_data:
        return {"content": f"لم أتمكن من استخراج الإجابة مباشرة من الجداول. يرجى توضيح السؤال أو تحديد القسم المراد البحث فيه."}

    sys_msg = ("أنت مستشار أعمال تنفيذي لشركة قطونيل (مصر). أجب بالعربية الفصحى المبسطة والمهنية.\n"
               "قواعد: اعتمد حصراً على النتيجة التي أمامك ولا تخترع أرقاماً؛ اذكر الأرقام مع الوحدة (ج.م)؛ "
               "لا تذكر الكود أو أي تفاصيل برمجية نهائياً في إجابتك.")
    if res_text is not None:
        user_msg = f"السؤال: {q}\n\nنتيجة التحليل من البيانات:\n{res_text}\n"
    else:
        user_msg = (f"السؤال: {q}\n\nلا توجد بيانات محددة، أجب استناداً لهذا الملخص العام فقط:\n{enterprise_text(k)}")
        
    ans, err = ask_groq([{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}], temp=0.2)
    return {"content": ans or f"تنبيه: {err}", "df": res_df}

# =====================================================================
# 3) محرك المحاكاة المباشر (Data-Driven Simulation)
# =====================================================================
def simulate_data_driven(base, mkt_pct, price_pct, disc_pct, cov_pct, cogs_pct, pay_pct, opx_pct, elasticity=-1.2, mkt_beta=0.5):
    R, O, S = base["revenue_net"], base["orders"], base["spend"]
    AOV = R / O if O > 0 else 0
    new_spend = S * (1 + mkt_pct / 100)
    att = min(base.get("attributed_orders", 0.35 * O), O)       
    att_new = att * (new_spend / S) ** mkt_beta if S > 0 else att  
    eff_price = (1 + price_pct / 100) * (1 - disc_pct / 100 * cov_pct / 100) - 1
    p_factor = max(1 + eff_price, 0.01)                          
    units = ((O - att) + att_new) / O * p_factor ** elasticity if O > 0 else 0
    new_orders = O * units
    new_aov = AOV * p_factor
    new_rev = new_orders * new_aov
    new_cogs = R * base["cogs_ratio"] * units * (1 + cogs_pct / 100)   
    new_refunds = new_rev * base["refund_rate"]
    new_opex = base["opex"] * (1 + opx_pct / 100)
    new_payroll = base["payroll"] * (1 + pay_pct / 100)
    new_op = new_rev - new_cogs - new_refunds - new_spend - new_opex - new_payroll
    return {"revenue": new_rev, "orders": new_orders, "aov": new_aov, "spend": new_spend,
            "roas": new_rev / new_spend if new_spend > 0 else 0, "cogs": new_cogs,
            "refunds": new_refunds, "opex": new_opex, "payroll": new_payroll,
            "contrib": new_rev - new_cogs - new_refunds - new_spend, "op": new_op,
            "gross_margin": (new_rev - new_cogs) / new_rev if new_rev > 0 else 0}

# =====================================================================
# 4) التقرير الأسبوعي + Telegram
# =====================================================================
def generate_weekly_report(k):
    prompt = (
        "اكتب تقريراً تنفيذياً أسبوعياً موجزاً لمدير شركة قطونيل (مصر) بالعربية الفصحى، اعتماداً على الأرقام التالية فقط ولا تخترع أرقاماً:\n\n"
        f"أرقام الأسبوع الأخير:\n{weekly_text(k)}\n\n"
        f"صورة الشركة الكلية:\n{enterprise_text(k)}\n\n"
        "الأقسام المطلوبة:\n"
        "1. ملخص الأداء (مبيعات، طلبات، متوسط الطلب)\n"
        "2. الربحية والتكاليف (هامش، مرتجعات، مصاريف، رواتب)\n"
        "3. التسويق والولاء (الإنفاق، ROAS، العملاء الأبطال والمعرضين للخطر)\n"
        "4. إجراء استراتيجي مقترح\n"
        "لا تستخدم علامات البرمجة نهائياً. استخدم ** للنقاط المهمة.")
    return ask_groq([{"role": "user", "content": prompt}], temp=0.2)

def to_tg_html(text):
    t = html.escape(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    return re.sub(r"^#+\s*", "", t, flags=re.M)

def send_telegram(token, chat_id, text):
    body = to_tg_html(text)
    chunks, cur = [], ""
    for para in body.split("\n\n"):
        if cur and len(cur) + len(para) + 2 > 3500:
            chunks.append(cur)
            cur = para
        else:
            cur = f"{cur}\n\n{para}" if cur else para
    if cur: chunks.append(cur)
    url = f"[https://api.telegram.org/bot](https://api.telegram.org/bot){token}/sendMessage"
    for c in chunks:
        try:
            r = session.post(url, json={"chat_id": chat_id, "text": c, "parse_mode": "HTML"}, timeout=30)
            if r.status_code != 200:
                plain = html.unescape(re.sub(r"<[^>]+>", "", c))
                r2 = session.post(url, json={"chat_id": chat_id, "text": plain}, timeout=30)
                if r2.status_code != 200:
                    return False, f"Telegram Error {r2.status_code}: {r2.text[:200]}"
        except Exception as e:
            return False, "خطأ في الاتصال بتليجرام. يرجى التأكد من اتصال الإنترنت."
    return True, "ok"

# =====================================================================
# دالة بناء كروت المؤشرات (KPI HTML Generator)
# =====================================================================
def get_kpi_html(label, value, delta_text="", tone="auto"):
    color = "#64748b"
    d = str(delta_text).strip() if delta_text else ""
    if d and tone != "neutral" and re.sub(r"[^0-9]", "", d).strip("0"):
        up = d.startswith("+")
        down = d.startswith("-") or d.startswith("\u2212")
        if up or down:
            good = up if tone == "auto" else down
            color = "#16a34a" if good else "#dc2626"
    delta_html = f"<div style='font-size:12px; margin-top:5px; color:{color};' dir='ltr'>{html.escape(d)}</div>" if d else ""
    return f"""
    <div class="kpi-card">
        <div class="kpi-label">{html.escape(str(label))}</div>
        <div class="kpi-value">{html.escape(str(value))}</div>
        {delta_html}
    </div>
    """

# =====================================================================
# 5) الواجهة الرئيسية
# =====================================================================
try:
    st.set_page_config(layout="wide", page_title="المساعد الذكي للأعمال")
except Exception:
    pass

st.markdown("""
<style>
.stApp { background-color: #f8fafc; color: #1e3a8a; }
h1, h2, h3, h4, h5, h6 { color: #1e3a8a !important; }
.kpi-card {
    background-color: #ffffff; padding: 20px; border-radius: 12px;
    border: 2px solid #cbd5e1; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    text-align: center; margin-bottom: 15px; transition: transform 0.2s;
}
.kpi-card:hover { transform: scale(1.02); border-color: #3b82f6; }
.kpi-value { font-size: 24px; font-weight: bold; color: #1e3a8a; margin-bottom: 5px; }
.kpi-label { font-size: 13px; color: #64748b; font-weight: 600; }
div[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 12px; border: 2px solid #94a3b8 !important; 
    background-color: #ffffff; padding: 20px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    margin-bottom: 20px;
}
.chat-msg { padding: 15px; border-radius: 10px; margin-bottom: 15px; font-size: 16px; line-height: 1.8; color: #1e3a8a; }
.user-msg { background-color: #e0f2fe; border-right: 5px solid #1e3a8a; text-align: right; }
.ai-msg { background-color: #ffffff; border: 1px solid #cbd5e1; border-right: 5px solid #3b82f6; text-align: right; }
[data-testid="stMarkdownContainer"], [data-testid="stChatMessage"] { direction: rtl; text-align: right; color: #1e3a8a; }
[data-testid="stDataFrame"] { direction: ltr; text-align: left; }
.report-box { padding: 24px; background:#fff; border:1px solid #cbd5e1; border-radius:12px;
              line-height:2; box-shadow:0 4px 10px rgba(0,0,0,.06); direction:rtl; text-align:right; color:#1e3a8a;}
/* منع تأثير الـ RTL على السايد بار لإرجاع العناوين لليسار */
[data-testid="stSidebarNavGroup"] {
    direction: ltr !important;
    text-align: left !important;
}
</style>
""", unsafe_allow_html=True)

# ----------------- العنوان الرئيسي -----------------
st.markdown("<h2 style='color:#1e3a8a; text-align: right; margin-bottom: 5px;'>المساعد الذكي للأعمال</h2>", unsafe_allow_html=True)
st.markdown("<p style='color:#64748b; text-align: right; margin-bottom: 25px;'>تحليل بيانات الشركة، محاكاة القرارات المالية، وتوليد تقارير الإدارة تلقائياً</p>", unsafe_allow_html=True)

# ----------------- فلتر التاريخ وأزرار التحكم -----------------
tables = load_tables()

st.markdown("#### نطاق البيانات")
date_c1, date_c2, date_c3 = st.columns([4, 4, 2])
try:
    if "sales_orders" in tables and not tables["sales_orders"].empty:
        df_orders = tables["sales_orders"]
        d_col = find_date_col(df_orders)
        if d_col:
            min_date = to_dt(df_orders[d_col]).min().date()
            max_date = to_dt(df_orders[d_col]).max().date()
        else:
            min_date, max_date = datetime(2020, 1, 1).date(), datetime.now().date()
    else:
        min_date, max_date = datetime(2020, 1, 1).date(), datetime.now().date()
except:
    min_date, max_date = datetime(2020, 1, 1).date(), datetime.now().date()

start_d = date_c1.date_input("من تاريخ", min_date)
end_d = date_c2.date_input("إلى تاريخ", max_date)
with date_c3:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("تحديث البيانات", use_container_width=True):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.rerun()

k = compute_kpis(tables, filter_start=start_d, filter_end=end_d)
# ------------------------------------------------

if not tables:
    st.error("لم يتم العثور على أي ملفات بيانات في مجلد البيانات. تأكد من المسار.")
    st.stop()

if k.get("notes"):
    with st.sidebar:
        st.warning("تنبيهات حساب المؤشرات")
        for note in k["notes"]:
            st.caption(note)

# ---- شريط المؤشرات الرئيسي ----
s, m, c, p, pn = k["sales"], k["marketing"], k["customers"], k["products"], k["pnl"]
dcs = k["decisions"]
est = " (تقديري)" if k["cogs_assumed"] else ""

k1, k2, k3, k4 = st.columns(4)
k1.markdown(get_kpi_html("عائد التسويق (ROAS)", f"{m['roas']:.2f}x"), unsafe_allow_html=True)
k2.markdown(get_kpi_html("إجمالي العملاء", fmt(c["total"])), unsafe_allow_html=True)
k3.markdown(get_kpi_html("عدد الطلبات", fmt(s["orders"])), unsafe_allow_html=True)
k4.markdown(get_kpi_html("إجمالي المبيعات", f"{fmt(s['revenue'])} ج.م"), unsafe_allow_html=True)

k5, k6, k7, k8 = st.columns(4)
k5.markdown(get_kpi_html("قرارات معلّقة", fmt(sum(b for a, b in dcs.get("by_status", []) if a.lower() == "pending")) if dcs else "0"), unsafe_allow_html=True)
k6.markdown(get_kpi_html("الفئة الأعلى مبيعاً", p["top_category"]), unsafe_allow_html=True)
k7.markdown(get_kpi_html("نسبة الاحتفاظ", f"{c['retention'] * 100:.1f}%"), unsafe_allow_html=True)
k8.markdown(get_kpi_html(f"صافي الربح التشغيلي{est}", f"{fmt(pn['op_profit'])} ج.م"), unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

tab_chat, tab_whatif, tab_report, tab_dec = st.tabs(["الدردشة مع البيانات", "محاكي السيناريوهات", "التقرير الأسبوعي", "سجل القرارات"])

# ---------------------------------------------------------------------
# 1) الدردشة
# ---------------------------------------------------------------------
def render_msg(msg):
    if msg["role"] == "user":
        st.markdown(f"<div class='chat-msg user-msg' dir='rtl'><b>أنت:</b><br>{html.escape(msg['content'])}</div>", unsafe_allow_html=True)
    elif msg["role"] == "assistant":
        clean_ans = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(msg['content'])).replace('\n', '<br>')
        st.markdown(f"<div class='chat-msg ai-msg' dir='rtl'><b>المساعد:</b><br>{clean_ans}</div>", unsafe_allow_html=True)
        if msg.get("df") is not None:
            st.dataframe(msg["df"], use_container_width=True, hide_index=True)

with tab_chat:
    with st.container(border=True):
        c_head, c_clear = st.columns([8, 2])
        with c_head:
            st.markdown("<h4>محلل البيانات الذكي - اطرح أسئلتك للحصول على إجابات مدعومة ببيانات الشركة</h4>", unsafe_allow_html=True)
        with c_clear:
            if st.button("مسح المحادثة", use_container_width=True):
                st.session_state.pop("chat", None)
                st.rerun()
                
        st.session_state.setdefault("chat", [])
        
        for msg in st.session_state.chat:
            render_msg(msg)

        q = st.chat_input("اكتب سؤالك عن المبيعات أو العملاء أو التسويق...")
        if q:
            prev = list(st.session_state.chat)
            st.session_state.chat.append({"role": "user", "content": q})
            with st.spinner("جاري تحليل قاعدة بيانات قطونيل..."):
                res = answer_question(q, tables, k, prev)
            st.session_state.chat.append({"role": "assistant", **res})
            st.rerun()

# ---------------------------------------------------------------------
# 2) محاكي السيناريوهات 
# ---------------------------------------------------------------------
with tab_whatif:
    with st.container(border=True):
        st.markdown("<h4>اختبر قرارات الإدارة استناداً لأرقام الشركة الحقيقية</h4>", unsafe_allow_html=True)
        if pn["revenue_net"] <= 0:
            st.warning("لا توجد بيانات مبيعات كافية لتشغيل المحاكاة.")
        else:
            st.markdown("<h5>مفاتيح التحكم في السيناريو (النسبة %)</h5>", unsafe_allow_html=True)
            c1, c2, c3, c4 = st.columns(4)
            wi_mkt = c1.number_input("ميزانية التسويق", value=0, step=5, key="wi_mkt")
            wi_price = c2.number_input("تعديل الأسعار", value=0, step=1, key="wi_price")
            wi_disc = c3.number_input("عمق الخصم", value=0, step=1, key="wi_disc")
            wi_cov = c4.number_input("نسبة الطلبات المشمولة بالخصم", value=30, min_value=0, max_value=100, step=5, key="wi_cov")
            
            c5, c6, c7, c8 = st.columns(4)
            wi_cogs = c5.number_input("تكلفة البضاعة", value=0, step=1, key="wi_cogs")
            wi_pay = c6.number_input("الرواتب", value=0, step=5, key="wi_pay")
            wi_opx = c7.number_input("المصاريف التشغيلية", value=0, step=5, key="wi_opx")
            wi_el = c8.number_input("مرونة الطلب السعرية", value=-1.2, max_value=0.0, step=0.1,
                                    help="افتراض: نسبة التغير في الطلبات مقابل 1% تغير في السعر. صفر = السعر لا يؤثر على الطلبات.")

            c9, c10 = st.columns(2)
            wi_beta = c9.number_input("تناقص عائد التسويق (0 إلى 1)", value=0.5, min_value=0.0, max_value=1.0, step=0.05,
                                      help="افتراض: 1 = الطلبات الإعلانية تزيد بنفس نسبة الميزانية، أقل من 1 = عائد متناقص.")
            c10.caption("افتراضات المحاكاة: مرونة الطلب وتناقص عائد التسويق ليست من البيانات، وتغييرها يغيّر النتيجة مباشرة.")

            # البيانات الأساسية من الـ Parquet
            base = {
                "revenue_net": pn["revenue_net"], "orders": s["orders"], "spend": m["spend"], 
                "cogs_ratio": k["cogs_ratio"], "refund_rate": k["returns"].get("rate", 0.0), 
                "opex": pn["opex"], "payroll": pn["payroll"], "op_profit": pn["op_profit"],
                "attributed_orders": m.get("attributed_orders", 0.35 * s["orders"])
            }
            
            # تشغيل المحاكاة
            N = simulate_data_driven(base, wi_mkt, wi_price, wi_disc, wi_cov, wi_cogs, wi_pay, wi_opx,
                                     elasticity=wi_el, mkt_beta=wi_beta)
            
            st.markdown("<br><h5>النتيجة المتوقعة مقابل الوضع الحالي</h5>", unsafe_allow_html=True)
            
            mc = st.columns(4)
            mc[0].markdown(get_kpi_html("الإيراد الصافي", f"{fmt(N['revenue'])} ج.م", pct_delta(N['revenue'], base['revenue_net'])), unsafe_allow_html=True)
            mc[1].markdown(get_kpi_html("الطلبات", fmt(N["orders"]), pct_delta(N["orders"], base["orders"])), unsafe_allow_html=True)
            mc[2].markdown(get_kpi_html("متوسط الطلب", f"{fmt(N['aov'])} ج.م", pct_delta(N["aov"], s["aov"])), unsafe_allow_html=True)
            mc[3].markdown(get_kpi_html("ROAS", f"{N['roas']:.2f}x", pct_delta(N["roas"], m["roas"])), unsafe_allow_html=True)
            
            mc2 = st.columns(4)
            mc2[0].markdown(get_kpi_html(f"هامش الربح الإجمالي{est}", f"{N['gross_margin'] * 100:.1f}%", f"{(N['gross_margin'] - pn['gross_margin']) * 100:+.1f} نقطة"), unsafe_allow_html=True)
            mc2[1].markdown(get_kpi_html("هامش المساهمة", f"{fmt(N['contrib'])} ج.م"), unsafe_allow_html=True)
            mc2[2].markdown(get_kpi_html(f"صافي الربح التشغيلي{est}", f"{fmt(N['op'])} ج.م", f"{N['op'] - base['op_profit']:+,.0f} ج.م"), unsafe_allow_html=True)

            if N["op"] < base["op_profit"]:
                st.warning("تنبيه: هذا السيناريو يقلل صافي الربح التشغيلي عن الوضع الحالي.")
            elif N["op"] > base["op_profit"]:
                st.success("توضيح: هذا السيناريو يحسّن صافي الربح التشغيلي عن الوضع الحالي.")

            with st.container(border=True):
                ch = pd.DataFrame(
                    {"الحالي": [base["revenue_net"] * base["cogs_ratio"], base["revenue_net"] * base["refund_rate"], base["spend"], base["opex"], base["payroll"], base["op_profit"]],
                     "السيناريو": [N["cogs"], N["refunds"], N["spend"], N["opex"], N["payroll"], N["op"]]},
                    index=["تكلفة البضاعة", "المرتجعات", "التسويق", "المصاريف التشغيلية", "الرواتب", "صافي الربح"])
                st.bar_chart(ch)

            sv = st.columns([3, 1])
            label = sv[0].text_input("اسم السيناريو للتسجيل", value=f"سيناريو {len(st.session_state.get('saved_sc', [])) + 1}")
            if sv[1].button("تسجيل كقرار", use_container_width=True):
                scen_txt = (f"محاكاة: تسويق {wi_mkt:+}% | أسعار {wi_price:+}% | خصم {wi_disc}% على {wi_cov}% من الطلبات | "
                            f"تكلفة {wi_cogs:+}% | رواتب {wi_pay:+}% | مصاريف تشغيلية {wi_opx:+}% | "
                            f"مرونة {wi_el} | تناقص التسويق {wi_beta} → تغير الربح {N['op'] - base['op_profit']:+,.0f} ج.م")
                try:
                    append_decision(f"{label} — {scen_txt}")
                    st.session_state.setdefault("saved_sc", []).append(label)
                    st.cache_resource.clear()
                    st.cache_data.clear()
                    st.success("تم تسجيل القرار بنجاح")
                except Exception as e:
                    st.error(f"تعذر الحفظ: {e}")

            if st.button("طلب تفسير المستشار للسيناريو", type="primary", use_container_width=True):
                prompt = (
                    "أنت مستشار أعمال تنفيذي لشركة قطونيل. قم بتفسير نتيجة هذا السيناريو المبني حصراً على البيانات:\n\n"
                    f"السيناريو: ميزانية التسويق {wi_mkt:+}% ، الأسعار {wi_price:+}% ، خصم {wi_disc}% على "
                    f"{wi_cov}% من الطلبات ، تكلفة البضاعة {wi_cogs:+}% ، رواتب {wi_pay:+}% ، مصاريف تشغيلية {wi_opx:+}%.\n"
                    f"النتائج (حالي → سيناريو): الإيراد {fmt(base['revenue_net'])} → {fmt(N['revenue'])} ؛ "
                    f"الطلبات {fmt(base['orders'])} → {fmt(N['orders'])} ؛ ROAS {m['roas']:.2f} → {N['roas']:.2f} ؛ "
                    f"صافي الربح التشغيلي {fmt(base['op_profit'])} → {fmt(N['op'])}.\n\n"
                    "المطلوب بالعربية في نقاط موجزة (بدون حشو):\n"
                    "1. قراءة النتيجة (أهم 3 دلالات)\n"
                    "2. الأثر على الأقسام\n"
                    "3. التوصية (معتمد أو مرفوض مع السبب)")
                with st.spinner("جاري التحليل..."):
                    txt, err = ask_groq([{"role": "user", "content": prompt}], temp=0.4)
                if txt:
                    clean_ans = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(txt)).replace('\n', '<br>')
                    st.markdown(f"<div class='report-box'>{clean_ans}</div>", unsafe_allow_html=True)
                else:
                    st.error(err)

# ---------------------------------------------------------------------
# 3) التقرير الأسبوعي
# ---------------------------------------------------------------------
with tab_report:
    with st.container(border=True):
        st.markdown("<h4>التقرير التنفيذي الأسبوعي</h4>", unsafe_allow_html=True)
        
        w = k.get("weekly")
        if w:
            wc = st.columns(4)
            aov_c = w["cur_rev"] / w["cur_orders"] if w["cur_orders"] else 0
            aov_p = w["prev_rev"] / w["prev_orders"] if w["prev_orders"] else 0
            
            wc[0].markdown(get_kpi_html(f"إيراد الأسبوع (حتى {w['end']})", f"{fmt(w['cur_rev'])} ج.م", pct_delta(w["cur_rev"], w["prev_rev"])), unsafe_allow_html=True)
            wc[1].markdown(get_kpi_html("الطلبات", fmt(w["cur_orders"]), pct_delta(w["cur_orders"], w["prev_orders"])), unsafe_allow_html=True)
            wc[2].markdown(get_kpi_html("متوسط الطلب", f"{fmt(aov_c)} ج.م", pct_delta(aov_c, aov_p)), unsafe_allow_html=True)
            if "mkt_cur" in w:
                wc[3].markdown(get_kpi_html("إنفاق التسويق", f"{fmt(w['mkt_cur'])} ج.م", pct_delta(w["mkt_cur"], w["mkt_prev"]), tone="neutral"), unsafe_allow_html=True)
        else:
            st.info("لا توجد بيانات تواريخ كافية لحساب الأداء الأسبوعي، سيتم الاعتماد على المؤشرات الكلية فقط.")

        if st.button("توليد التقرير الأسبوعي الآن", type="primary"):
            with st.spinner("جاري صياغة التقرير..."):
                txt, err = generate_weekly_report(k)
            if txt:
                st.session_state["weekly_edit"] = txt
            else:
                st.error(err)

        if st.session_state.get("weekly_edit"):
            st.text_area("راجع أو عدّل التقرير قبل الإرسال", key="weekly_edit", height=360)
            disp = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(st.session_state["weekly_edit"])).replace("\n", "<br>")
            st.markdown(f"<div class='report-box'>{disp}</div><br>", unsafe_allow_html=True)
            tok, chat_id = get_secret("TELEGRAM_TOKEN"), get_secret("TELEGRAM_CHAT_ID")
            if st.button("إرسال للإدارة عبر Telegram"):
                if not (tok and chat_id):
                    st.warning("يرجى ضبط TELEGRAM_TOKEN و TELEGRAM_CHAT_ID.")
                else:
                    ok, msg = send_telegram(tok, chat_id, f"التقرير الأسبوعي — قطونيل\n\n{st.session_state['weekly_edit']}")
                    st.success("تم الإرسال بنجاح") if ok else st.error(f"فشل الإرسال: {msg}")

# ---------------------------------------------------------------------
# 4) سجل القرارات
# ---------------------------------------------------------------------
with tab_dec:
    with st.container(border=True):
        st.markdown("<h4>كل قرارات الأقسام في مكان واحد</h4>", unsafe_allow_html=True)
        dfd = decisions_frame(tables)
        if dfd.empty:
            st.info("لا توجد قرارات مسجلة بعد.")
        else:
            stc = dfd["الحالة"].value_counts()
            dm = st.columns(max(len(stc), 1))
            for col, (name, cnt) in zip(dm, stc.items()):
                col.markdown(get_kpi_html(name, int(cnt)), unsafe_allow_html=True)
            
            f1, f2 = st.columns(2)
            sec_f = f1.multiselect("القسم", sorted(dfd["القسم"].unique()))
            st_f = f2.multiselect("الحالة", sorted(dfd["الحالة"].unique()))
            view = dfd
            if sec_f:
                view = view[view["القسم"].isin(sec_f)]
            if st_f:
                view = view[view["الحالة"].isin(st_f)]
            st.dataframe(view, use_container_width=True, hide_index=True)