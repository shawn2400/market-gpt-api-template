import asyncio
from auto_executor import start_auto_executor

if __name__ == "__main__":
    # הפעלת סריקה אוטומטית כל 60 שניות
    asyncio.run(start_auto_executor(
        delay=60,        # זמן המתנה בין סריקות (שניות)
        min_quality=6,   # ציון איכות מינימלי לכניסה
        max_budget=100   # תקציב השקעה לכל טרייד
    ))
