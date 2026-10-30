"""تحميل جداول parquet من فولدر data/ مع كاش."""
from pathlib import Path
import pandas as pd
import streamlit as st

DATA = Path(__file__).parent / "data"

def have(name: str) -> bool:
    return (DATA / f"{name}.parquet").exists()

@st.cache_data(show_spinner="Loading data...")
def load(name: str, columns=None) -> pd.DataFrame:
    return pd.read_parquet(DATA / f"{name}.parquet", columns=columns)
