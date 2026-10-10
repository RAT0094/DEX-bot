async def call_cleanapis(payload, headers):
    url = f"{CLEANAPIS_BASE_URL}/v1/chat/completions"
    print(f"DEBUG: Attempting request to: {url}") 
    
    async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
        try:
            r = await client.post(url, headers=headers, json=payload)
            
            # اینجا اگه ۴۰۴ هم باشه، محتوا رو چاپ می‌کنیم قبل از اینکه خطا بگیریم
            if r.status_code != 200:
                print(f"🚨 CRITICAL DEBUG: Server returned {r.status_code}")
                print(f"🚨 RESPONSE BODY: {r.text}")
            
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
            
        except httpx.HTTPStatusError as e:
            # اینجا جزئیات دقیق ارور رو می‌گیریم
            print(f"🚨 HTTP Error details: {e.response.text}")
            raise e
