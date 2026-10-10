import socket
import httpx
import asyncio

async def test_connectivity():
    print("--- شروع تست اتصال ---")
    
    # تست ۱: آیا می‌تونه به IP وصل بشه؟ (بدون استفاده از DNS)
    try:
        print("تست ۱: تلاش برای اتصال به 8.8.8.8 (Google DNS)...")
        # یک درخواست ساده به IP گوگل
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get("https://8.8.8.8")
            print(f"✅ موفق! اتصال به IP برقرار شد. (کد: {response.status_code})")
    except Exception as e:
        print(f"❌ شکست! حتی به IP هم وصل نشد: {e}")

    # تست ۲: آیا می‌تونه DNS رو حل کنه؟
    try:
        print("تست ۲: تلاش برای حل دامین api.cleanapis.com...")
        ip = socket.gethostbyname("api.cleanapis.com")
        print(f"✅ موفق! دامین به {ip} ترجمه شد.")
    except Exception as e:
        print(f"❌ شکست! دامین حل نشد: {e}")

    print("--- پایان تست ---")

if __name__ == "__main__":
    asyncio.run(test_connectivity())
    
