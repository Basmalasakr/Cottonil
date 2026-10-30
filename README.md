# Cotonil Command Center (Streamlit)

1. ثبّت Python 3.10 أو أحدث.
2. من فولدر المشروع:
       pip install -r requirements.txt
       streamlit run app.py
3. افتح http://localhost:8501

الداتا: ملفات parquet في فولدر data/ (اسم الملف = اسم الجدول، مثل data/sales_orders.parquet).

مكان الكود:
- كل صفحة: views/<اسم_الصفحة>.py  (اكتب كودك تحت سطر module_page)
- نصوص الصفحات (السؤال والداتا والمطلوب): content.py
- الألوان والكومبوننتات (kpi, pill, insight, plot): theme.py
- تحميل الداتا: data_loader.py  ->  load("sales_orders")
