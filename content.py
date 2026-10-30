"""محتوى الصفحات: السؤال، الداتا، المطلوب بناؤه. عدّل النصوص من هنا."""
# ملفات تنتهي بعلامة ? غير موجودة في الداتا الحالية
GROUPS = [
 {
  "id": "leadership",
  "ar": "القيادة",
  "en": "Leadership"
 },
 {
  "id": "ops",
  "ar": "المخزون والتشغيل",
  "en": "Inventory & Operations"
 },
 {
  "id": "product",
  "ar": "المنتج والتسعير",
  "en": "Product & Pricing"
 },
 {
  "id": "customer",
  "ar": "العميل والتسويق",
  "en": "Customer & Marketing"
 },
 {
  "id": "growth",
  "ar": "الجودة والنمو",
  "en": "Quality & Growth"
 },
 {
  "id": "ai",
  "ar": "الذكاء",
  "en": "Intelligence"
 }
]

MODULES = [
 {
  "slug": "executive-dashboard",
  "group": "leadership",
  "ar": "لوحة الإدارة التنفيذية",
  "en": "Executive Dashboard",
  "q": {
   "ar": "كيف حال الشركة الآن، وما القرار المطلوب؟",
   "en": "How is the company doing, and what should we decide?"
  },
  "files": [
   "sales_orders",
   "operating_expenses",
   "payroll",
   "monthly_stock",
   "branches"
  ],
  "build": {
   "ar": [
    "مؤشرات المبيعات والهامش والمصروفات",
    "مقارنة بالفترة السابقة",
    "ملخص توصيات المجلس"
   ],
   "en": [
    "Sales, margin and expense KPIs",
    "Comparison with the previous period",
    "Board recommendations summary"
   ]
  },
  "ai": {
   "ar": "مجلس الإدارة الذكي: وكلاء (مبيعات، مخازن، مشتريات، مالية، تسويق) يناقشون الأرقام ويقترحون خطة، ولكل توصية مصدرها (فكرة 15)",
   "en": "Smart board: agents (sales, stock, procurement, finance, marketing) debate the numbers and propose a plan, each with its data source (idea 15)"
  }
 },
 {
  "slug": "sales-performance",
  "group": "leadership",
  "ar": "أداء المبيعات",
  "en": "Sales Performance",
  "q": {
   "ar": "أين تنمو المبيعات وأين تتراجع؟",
   "en": "Where are sales growing and where are they falling?"
  },
  "files": [
   "sales_orders",
   "sales_payments",
   "delivery_shipments"
  ],
  "build": {
   "ar": [
    "الاتجاه الشهري والموسمية",
    "القنوات وطرق الدفع",
    "أثر الخصومات"
   ],
   "en": [
    "Monthly trend and seasonality",
    "Channels and payment methods",
    "Discount impact"
   ]
  },
  "ai": {
   "ar": "شرح تلقائي لأي هبوط أو طفرة",
   "en": "Automatic explanation of any drop or spike"
  }
 },
 {
  "slug": "branch-performance",
  "group": "leadership",
  "ar": "أداء الفروع",
  "en": "Branch Performance",
  "q": {
   "ar": "أي الفروع الأقوى وأيها يحتاج تدخل؟",
   "en": "Which branches are strongest and which need action?"
  },
  "files": [
   "sales_orders",
   "branches",
   "employees",
   "operating_expenses"
  ],
  "build": {
   "ar": [
    "ترتيب الفروع",
    "المبيعات لكل موظف",
    "الربحية بعد المصروفات"
   ],
   "en": [
    "Branch ranking",
    "Sales per employee",
    "Profitability after expenses"
   ]
  },
  "ai": {
   "ar": "كشف الفروع الشاذة",
   "en": "Outlier branch detection"
  }
 },
 {
  "slug": "inventory-warehouse",
  "group": "ops",
  "ar": "المخزون والمخازن",
  "en": "Inventory & Warehouse",
  "q": {
   "ar": "هل المخزون في المكان والكمية الصحيحين؟",
   "en": "Is stock in the right place and quantity?"
  },
  "files": [
   "monthly_stock",
   "warehouses",
   "inventory_transfers"
  ],
  "build": {
   "ar": [
    "تغطية المخزون",
    "الراكد ومخاطر النفاد",
    "سعة المخازن (المخزون على مستوى الفئة وليس المنتج)"
   ],
   "en": [
    "Stock cover",
    "Slow movers and stockout risk",
    "Warehouse capacity (stock is at category level, not product)"
   ]
  }
 },
 {
  "slug": "smart-replenishment",
  "group": "ops",
  "ar": "التوزيع الذكي للمخزون",
  "en": "Smart Replenishment",
  "q": {
   "ar": "كم نرسل لكل فرع ومن أي مخزن؟",
   "en": "How much should we send to each branch, from which warehouse?"
  },
  "files": [
   "inventory_transfers",
   "inventory_transfer_items",
   "monthly_stock",
   "sales_order_items?"
  ],
  "build": {
   "ar": [
    "توصية التحويلات",
    "مقاسات كل محافظة",
    "تكلفة النقل"
   ],
   "en": [
    "Transfer recommendations",
    "Sizes per governorate",
    "Transport cost"
   ]
  },
  "ai": {
   "ar": "التوزيع الذكي وتحليل المقاسات جغرافيًا (فكرة 3 و4)",
   "en": "Smart allocation and geographic size profiling (ideas 3 and 4)"
  }
 },
 {
  "slug": "supply-chain",
  "group": "ops",
  "ar": "سلسلة الإمداد",
  "en": "Supply Chain",
  "q": {
   "ar": "أين التأخير في الاستيراد والشحن؟",
   "en": "Where are the delays in imports and shipping?"
  },
  "files": [
   "import_shipments",
   "import_partners",
   "delivery_shipments"
  ],
  "build": {
   "ar": [
    "زمن الشحن",
    "تكلفة الشحن والجمارك",
    "أداء شركات الشحن"
   ],
   "en": [
    "Shipping lead time",
    "Freight and customs cost",
    "Carrier performance"
   ]
  }
 },
 {
  "slug": "procurement-suppliers",
  "group": "ops",
  "ar": "المشتريات والموردين",
  "en": "Procurement & Suppliers",
  "q": {
   "ar": "من أفضل مورد من حيث السعر والالتزام؟",
   "en": "Which supplier is best on price and reliability?"
  },
  "files": [
   "purchase_orders",
   "purchase_order_items",
   "suppliers"
  ],
  "build": {
   "ar": [
    "تقييم الموردين",
    "تطور التكلفة",
    "شروط الدفع"
   ],
   "en": [
    "Supplier scoring",
    "Cost trend",
    "Payment terms"
   ]
  }
 },
 {
  "slug": "loss-prevention",
  "group": "ops",
  "ar": "منع الفاقد",
  "en": "Loss Prevention",
  "q": {
   "ar": "أين يحدث الفاقد أو التلاعب؟",
   "en": "Where does loss or fraud happen?"
  },
  "files": [
   "sales_returns",
   "operating_expenses",
   "payroll",
   "monthly_stock",
   "sales_orders"
  ],
  "build": {
   "ar": [
    "مرتجعات غير طبيعية",
    "خصومات شاذة",
    "فروق المخزون"
   ],
   "en": [
    "Unusual returns",
    "Abnormal discounts",
    "Stock variances"
   ]
  },
  "ai": {
   "ar": "كشف الشذوذ والاحتيال",
   "en": "Anomaly and fraud detection"
  }
 },
 {
  "slug": "workforce-store-ops",
  "group": "ops",
  "ar": "القوى العاملة وتشغيل المتاجر",
  "en": "Workforce & Store Ops",
  "q": {
   "ar": "هل تكلفة العمالة مناسبة لحجم المبيعات؟",
   "en": "Is labor cost right for the sales volume?"
  },
  "files": [
   "employees",
   "payroll",
   "branches",
   "sales_orders"
  ],
  "build": {
   "ar": [
    "تكلفة العمالة إلى المبيعات",
    "الأوفر تايم",
    "عدد الموظفين لكل فرع"
   ],
   "en": [
    "Labor cost to sales",
    "Overtime",
    "Headcount per branch"
   ]
  }
 },
 {
  "slug": "product-profitability",
  "group": "product",
  "ar": "ربحية المنتجات",
  "en": "Product Profitability",
  "q": {
   "ar": "أي المنتجات تربح وأيها يخسر؟",
   "en": "Which products earn and which lose?"
  },
  "files": [
   "sales_order_items?",
   "products_catalog",
   "sku_variants"
  ],
  "build": {
   "ar": [
    "هامش كل منتج",
    "المقاس واللون",
    "منتجات تحتاج قرارًا"
   ],
   "en": [
    "Margin per product",
    "Size and color",
    "Products needing a decision"
   ]
  }
 },
 {
  "slug": "price-promotion",
  "group": "product",
  "ar": "التسعير والعروض",
  "en": "Price & Promotion",
  "q": {
   "ar": "ما السعر والخصم الأمثل؟",
   "en": "What is the best price and discount?"
  },
  "files": [
   "sales_order_items?",
   "products_catalog",
   "competitor_prices?"
  ],
  "build": {
   "ar": [
    "مرونة السعر",
    "أثر الخصم",
    "مقارنة المنافسين"
   ],
   "en": [
    "Price elasticity",
    "Discount effect",
    "Competitor comparison"
   ]
  },
  "ai": {
   "ar": "التسعير الديناميكي ومقارنة المنافسين (فكرة 6 و8)",
   "en": "Dynamic pricing and competitive intelligence (ideas 6 and 8)"
  }
 },
 {
  "slug": "demand-forecasting",
  "group": "product",
  "ar": "التنبؤ بالطلب",
  "en": "Demand Forecasting",
  "q": {
   "ar": "كم سنبيع من كل قطعة؟",
   "en": "How much will we sell of each item?"
  },
  "files": [
   "sales_order_items?",
   "products_catalog",
   "marketing_campaigns"
  ],
  "build": {
   "ar": [
    "تنبؤ لكل منتج وفرع",
    "الموسمية والعروض",
    "دقة النموذج"
   ],
   "en": [
    "Forecast per product and branch",
    "Seasonality and promotions",
    "Model accuracy"
   ]
  },
  "ai": {
   "ar": "المحرك الأساسي الذي يغذي باقي الصفحات",
   "en": "Core engine that feeds the other pages"
  }
 },
 {
  "slug": "visual-merchandising",
  "group": "product",
  "ar": "العرض البصري",
  "en": "Visual Merchandising",
  "q": {
   "ar": "هل العرض في الفروع مطابق للخطة؟",
   "en": "Does in-store display match the plan?"
  },
  "files": [
   "shelf_photos?"
  ],
  "build": {
   "ar": [
    "رفع صورة الرف",
    "مقارنة بخطة العرض",
    "قائمة المخالفات"
   ],
   "en": [
    "Upload shelf photo",
    "Compare with planogram",
    "Violations list"
   ]
  },
  "ai": {
   "ar": "تدقيق آلي بـ Claude Vision (فكرة 5)",
   "en": "Automatic audit with Claude Vision (idea 5)"
  }
 },
 {
  "slug": "customer-segmentation",
  "group": "customer",
  "ar": "شرائح العملاء",
  "en": "Customer Segmentation",
  "q": {
   "ar": "من هم عملاؤنا وماذا يريدون؟",
   "en": "Who are our customers and what do they want?"
  },
  "files": [
   "customers",
   "sales_orders",
   "social_comments?"
  ],
  "build": {
   "ar": [
    "تحليل RFM",
    "الشرائح حسب المحافظة والعمر",
    "آراء كل شريحة"
   ],
   "en": [
    "RFM analysis",
    "Segments by governorate and age",
    "Opinions per segment"
   ]
  },
  "ai": {
   "ar": "تحليل آراء السوشيال (فكرة 10)",
   "en": "Social sentiment analysis (idea 10)"
  }
 },
 {
  "slug": "clv-churn",
  "group": "customer",
  "ar": "قيمة العميل والتسرب",
  "en": "CLV & Churn",
  "q": {
   "ar": "من العميل الذي سنخسره ومن الأعلى قيمة؟",
   "en": "Which customer will we lose, and who is most valuable?"
  },
  "files": [
   "customers",
   "sales_orders"
  ],
  "build": {
   "ar": [
    "قيمة العميل",
    "احتمال التسرب",
    "عروض مخصصة"
   ],
   "en": [
    "Customer lifetime value",
    "Churn probability",
    "Personalized offers"
   ]
  },
  "ai": {
   "ar": "توقع تسرب العملاء والتخصيص (فكرة 11)",
   "en": "Churn prediction and personalization (idea 11)"
  }
 },
 {
  "slug": "marketing-roi",
  "group": "customer",
  "ar": "عائد التسويق",
  "en": "Marketing ROI",
  "q": {
   "ar": "أي قناة وحملة تعطي أفضل عائد؟",
   "en": "Which channel and campaign give the best return?"
  },
  "files": [
   "marketing_campaigns",
   "sales_orders"
  ],
  "build": {
   "ar": [
    "CTR وتكلفة الطلب",
    "ROAS لكل قناة",
    "الصرف مقابل الميزانية"
   ],
   "en": [
    "CTR and cost per order",
    "ROAS per channel",
    "Spend vs budget"
   ]
  },
  "ai": {
   "ar": "محاكاة رد فعل الجمهور على الإعلان (فكرة 9)",
   "en": "Ad audience-response simulation (idea 9)"
  }
 },
 {
  "slug": "omnichannel",
  "group": "customer",
  "ar": "تعدد القنوات",
  "en": "Omnichannel",
  "q": {
   "ar": "كيف يتصرف العميل عبر القنوات؟",
   "en": "How do customers behave across channels?"
  },
  "files": [
   "sales_orders",
   "delivery_shipments",
   "chat_logs?"
  ],
  "build": {
   "ar": [
    "توزيع القنوات",
    "زمن التوصيل",
    "أسئلة العملاء"
   ],
   "en": [
    "Channel mix",
    "Delivery time",
    "Customer questions"
   ]
  },
  "ai": {
   "ar": "مستشار المقاسات ووكيل خدمة العملاء (فكرة 7 و12)",
   "en": "Size advisor and customer-service agent (ideas 7 and 12)"
  }
 },
 {
  "slug": "returns-quality",
  "group": "growth",
  "ar": "المرتجعات والجودة",
  "en": "Returns & Quality",
  "q": {
   "ar": "لماذا يرجع العملاء المنتجات؟",
   "en": "Why do customers return products?"
  },
  "files": [
   "sales_returns",
   "sku_variants",
   "factories",
   "batch_ids?"
  ],
  "build": {
   "ar": [
    "معدل المرتجعات وأسبابها",
    "حسب المقاس والمنتج",
    "الربط برقم التشغيلة"
   ],
   "en": [
    "Return rate and reasons",
    "By size and product",
    "Link to production batch"
   ]
  },
  "ai": {
   "ar": "فحص الجودة بالرؤية الحاسوبية وتتبع التشغيلات (فكرة 1 و2)",
   "en": "Computer-vision quality check and batch tracking (ideas 1 and 2)"
  }
 },
 {
  "slug": "new-store-expansion",
  "group": "growth",
  "ar": "التوسع في فروع جديدة",
  "en": "New Store Expansion",
  "q": {
   "ar": "أين نفتح الفرع القادم؟",
   "en": "Where should we open the next branch?"
  },
  "files": [
   "branches",
   "sales_orders",
   "customers"
  ],
  "build": {
   "ar": [
    "أداء الفروع المشابهة",
    "الطلب حسب المحافظة",
    "توقع أداء الفرع الجديد"
   ],
   "en": [
    "Similar branch performance",
    "Demand by governorate",
    "New branch forecast"
   ]
  },
  "ai": {
   "ar": "اختيار مواقع الفروع (فكرة 14)",
   "en": "Branch site selection (idea 14)"
  }
 },
 {
  "slug": "wholesale-distributors",
  "group": "growth",
  "ar": "الجملة والموزعين",
  "en": "Wholesale & Distributors",
  "q": {
   "ar": "كيف نبني صفقات الجملة؟",
   "en": "How do we structure wholesale deals?"
  },
  "files": [
   "sales_orders",
   "import_partners"
  ],
  "build": {
   "ar": [
    "مبيعات الجملة",
    "أكبر الموزعين",
    "هامش الصفقة"
   ],
   "en": [
    "Wholesale sales",
    "Top distributors",
    "Deal margin"
   ]
  }
 },
 {
  "slug": "sustainability-esg",
  "group": "growth",
  "ar": "الاستدامة وESG",
  "en": "Sustainability & ESG",
  "q": {
   "ar": "ما بصمتنا البيئية والتشغيلية؟",
   "en": "What is our environmental and operating footprint?"
  },
  "files": [
   "operating_expenses",
   "import_shipments",
   "warehouses"
  ],
  "build": {
   "ar": [
    "الشحن والطاقة",
    "الشحنات المستوردة",
    "مؤشرات ESG (تحتاج بيانات طاقة وانبعاثات)"
   ],
   "en": [
    "Freight and energy",
    "Imported shipments",
    "ESG indicators (needs energy and emissions data)"
   ]
  }
 },
 {
  "slug": "ai-assistant",
  "group": "ai",
  "ar": "المساعد الذكي للأعمال",
  "en": "AI Business Assistant"
 }
]
