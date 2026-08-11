# Deep Research Prompt

من روی پروژه کارشناسی برق با عنوان زیر کار می‌کنم:

«طراحی و پیاده‌سازی سامانه بلادرنگ پایش ECG، تشخیص موج‌های PQRST و تخمین اولیه احتمال آریتمی با استفاده از Arduino، ماژول AD8232 و پردازش سیگنال دیجیتال روی کامپیوتر»

لطفا یک مرور پژوهشی دقیق و قابل استناد تهیه کن و فقط از منابع معتبر علمی، مقاله، دیتاست رسمی، مستندات PhysioNet و منابع دانشگاهی/ژورنالی استفاده کن. خروجی را طوری بنویس که بتوانم فصل مرور ادبیات، روش پیشنهادی، فصل پیاده‌سازی و فصل ارزیابی پایان‌نامه کارشناسی را با آن اصلاح کنم.

مواردی که باید پوشش بدهی:

1. بهترین و مناسب‌ترین الگوریتم‌های real-time برای تشخیص QRS/R-peak در ECG تک‌لید کم‌هزینه، مخصوصا Pan-Tompkins، نسخه‌های اصلاح‌شده، Hamilton/Tompkins، wavelet-based، matched filter و روش‌های سبک دیگر.
2. مقایسه الگوریتم‌ها از نظر دقت، latency، پیچیدگی محاسباتی، قابلیت اجرای real-time روی کامپیوتر، مقاومت به نویز، و مناسب بودن برای داده AD8232/Arduino.
3. روش‌های مناسب ECG delineation برای تخمین P, Q, S, T پس از تشخیص R، شامل روش‌های fiducial/time-window، مشتق/curvature، wavelet و الگوریتم‌های کم‌پیچیدگی.
4. روش‌های قابل دفاع برای Signal Quality Index در ECG تک‌لید و چگونگی تشخیص poor signal / lead-off / motion artifact.
5. قواعد clinically safe اما غیرتشخیصی برای هشدار اولیه آریتمی در پروژه آموزشی: bradycardia، tachycardia، irregular RR، premature beat suspicion، wide QRS warning. تاکید کن خروجی medical diagnosis نیست.
6. دیتاست‌های استاندارد مناسب ارزیابی: MIT-BIH Arrhythmia Database، QT Database، MIT-BIH Noise Stress Test Database و هر دیتاست مفید دیگر. برای هرکدام کاربرد، نرخ نمونه‌برداری، نوع annotation و معیارهای ارزیابی را توضیح بده.
7. معیارهای ارزیابی دقیق: Sensitivity، Positive Predictive Value، F1-score، timing error برای R-peak، خطای زمانی P/Q/S/T، false alarm rate، latency و packet loss.
8. منابع مربوط به استفاده از Arduino و AD8232 برای ECG آموزشی/پژوهشی، همراه با محدودیت‌های ایمنی، تک‌لید بودن، نویز و non-medical بودن سامانه.
9. آیا برای پروژه کارشناسی بهتر است ماژول آریتمی rule-based بماند یا یک مدل سبک ML مثل Logistic Regression، SVM، Decision Tree یا Random Forest هم اضافه شود؟ پاسخ را با tradeoff و پیشنهاد عملی بده.
10. در پایان، یک معماری پیشنهادی نهایی برای پیاده‌سازی ارائه بده: Arduino acquisition، Python processing، فیلترها، QRS detection، PQRST delineation، feature extraction، arrhythmia warning، ارزیابی با دیتاست.

برای هر ادعا citation بده. منابع نامطمئن، مقاله‌های جعلی یا بدون DOI/لینک معتبر را وارد نکن. اگر مقاله‌ای فقط ادعای ضعیف دارد یا مستقیما به پروژه مربوط نیست، جداگانه مشخص کن. خروجی شامل جدول مقایسه الگوریتم‌ها، جدول دیتاست‌ها، پیشنهاد نهایی الگوریتم برای این پروژه، و فهرست منابع کامل در قالب IEEE باشد.
