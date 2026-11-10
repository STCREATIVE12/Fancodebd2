import asyncio
import json
import os
import re
from playwright.async_api import async_playwright

async def scrape_upcoming_events():
    # Upcoming ইভেন্টের জন্য URL
    target_url = "https://www.fancode.com/schedule"
    output_json_file = "upcoming_events.json"
    output_html_file = "upcoming_events.html"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()

        print("🟢 Opening FanCode Schedule / Upcoming page...")
        upcoming_matches = []

        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(5)

            # Lazy loading এলিমেন্টগুলোর জন্য স্ক্রল করা
            for _ in range(3):
                await page.evaluate("window.scrollBy(0, window.innerHeight);")
                await asyncio.sleep(2)

            # পেজ থেকে ম্যাচ কার্ডের তথ্য সংগ্রহ
            upcoming_matches = await page.evaluate("""() => {
                let items = [];
                let cards = document.querySelectorAll('a[href*="/matches/"]');

                cards.forEach(a => {
                    let href = a.href;
                    let text = a.innerText.replace(/\\n/g, ' | ').trim();

                    // লাইভ ব্যাজ থাকলে বাদ দিয়ে শুধুমাত্র টেক্সট ফিল্টার
                    let cleanText = text.replace(/\\s+/g, ' ').trim();

                    let imgTag = a.querySelector('img');
                    let logoUrl = imgTag ? (imgTag.src || imgTag.getAttribute('data-src') || '') : '';

                    if (href && cleanText.length > 5 && !items.some(i => i.href === href)) {
                        items.push({
                            raw_details: cleanText,
                            href: href,
                            logo: logoUrl
                        });
                    }
                });

                return items;
            }""")

        except Exception as e:
            print(f"🔴 Error loading page: {str(e)}")
        finally:
            await browser.close()

        print(f"🟢 Total Upcoming events found: {len(upcoming_matches)}")

        processed_data = []
        html_cards = []

        for item in upcoming_matches:
            raw_details = item["raw_details"]
            href = item["href"]
            logo = item["logo"]

            # টেক্সট ক্লিন করা
            title_clean = re.sub(r'[-–—]', ' ', raw_details)
            title_clean = re.sub(r'\s+', ' ', title_clean).strip()

            slug = re.sub(r'[^a-zA-Z0-9]', '_', title_clean)
            slug = re.sub(r'_+', '_', slug).strip('_')

            entry = {
                "id": slug,
                "title": title_clean,
                "match_url": href,
                "thumbnail": logo
            }
            processed_data.append(entry)

            html_cards.append(f"""
                <div class="card">
                    <img src="{logo}" alt="Poster" />
                    <div class="info">
                        <h3>{title_clean}</h3>
                        <a href="{href}" target="_blank">Match Page</a>
                    </div>
                </div>
            """)

        # JSON ফাইলে সংরক্ষণ
        with open(output_json_file, "w", encoding="utf-8") as jf:
            json.dump(processed_data, jf, indent=4, ensure_ascii=False)

        # HTML প্রিভিউ তৈরি
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>FanCode Upcoming Events</title>
    <style>
        body {{ font-family: Arial, sans-serif; background: #181818; color: #fff; padding: 20px; }}
        h1 {{ color: #ff6600; }}
        .grid {{ display: flex; flex-direction: column; gap: 15px; max-width: 800px; }}
        .card {{ display: flex; align-items: center; background: #242424; padding: 12px; border-radius: 8px; }}
        .card img {{ width: 60px; height: 60px; object-fit: contain; margin-right: 15px; border-radius: 4px; }}
        .info h3 {{ margin: 0 0 8px 0; font-size: 16px; }}
        .info a {{ color: #00bcd4; text-decoration: none; font-size: 14px; }}
        .info a:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <h1>FanCode Upcoming Matches</h1>
    <div class="grid">
        {"".join(html_cards) if html_cards else "<p>No upcoming matches listed.</p>"}
    </div>
</body>
</html>"""

        with open(output_html_file, "w", encoding="utf-8") as hf:
            hf.write(html_content)

        print(f"🟢 Done! Saved to {output_json_file} and {output_html_file}")

if __name__ == "__main__":
    asyncio.run(scrape_upcoming_events())
