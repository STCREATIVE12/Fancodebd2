import asyncio
import json
import re
from datetime import datetime, timezone, timedelta
from playwright.async_api import async_playwright

async def scrape_all_fancode_schedules():
    output_json_file = "fancode_matches.json"

    # IST Time format (UTC + 5:30)
    ist_zone = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(ist_zone).strftime("%I:%M:%S %p %d-%m-%Y")

    final_payload = {
        "name": "Fancode Live Matches Data in Json",
        "telegram": "https://t.me/+rQTz5VL8CRpjNTZl",
        "last update time": now_ist,
        "matches": []
    }

    # Aapke screenshot mein dikh rahi saari specific categories
    sports_categories = [
        {"name": "Cricket", "path": "/cricket/schedule"},
        {"name": "Football", "path": "/football/schedule"},
        {"name": "Tennis", "path": "/lawn-tennis/schedule"},
        {"name": "Formula 1", "path": "/formula1/schedule"},
        {"name": "MotoGP", "path": "/motogp/schedule"},
        {"name": "Golf", "path": "/golf/schedule"},
        {"name": "Motorsports", "path": "/racing/schedule"},
        {"name": "Badminton", "path": "/badminton/schedule"}
    ]

    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            user_agent=user_agent,
            viewport={"width": 1280, "height": 900}
        )
        page = await context.new_page()

        # Images aur styles block karein taaki execution fast ho
        await page.route("**/*.{png,jpg,jpeg,svg,woff,woff2,css}", lambda route: route.abort())

        seen_match_ids = set()

        for sport in sports_categories:
            sport_name = sport["name"]
            url = f"https://www.fancode.com{sport['path']}"
            print(f"🟢 Processing {sport_name}: {url}")

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=25000)
                await asyncio.sleep(3)

                # Niche Tomorrow/Upcoming matches load karne ke liye 2-3 scroll
                for _ in range(3):
                    await page.evaluate("window.scrollBy(0, 1000);")
                    await asyncio.sleep(1)

                # Page ke saare cards aur links extract karna
                items = await page.evaluate("""() => {
                    let results = [];
                    // Match detail page links
                    let anchors = document.querySelectorAll('a[href*="/matches/"]');

                    anchors.forEach(a => {
                        let href = a.href;
                        let text = a.innerText.replace(/\\n/g, ' - ').trim();
                        let cleanText = text.replace(/\\s+/g, ' ').trim();
                        
                        let img = a.querySelector('img');
                        let src = img ? (img.src || img.getAttribute('data-src') || '') : '';

                        if (href && cleanText.length > 3) {
                            results.push({
                                href: href,
                                text: cleanText,
                                src: src
                            });
                        }
                    });
                    return results;
                }""")

                print(f"👉 Found {len(items)} items in {sport_name}")

                for itm in items:
                    href = itm["href"]
                    raw_text = itm["text"]
                    
                    # Match ID extract karna href se (jaise ...-4250404/...)
                    id_match = re.search(r'[-/](\d{6,8})(?:/|$)', href)
                    mid = id_match.group(1) if id_match else href.split("/")[-1]

                    if mid in seen_match_ids:
                        continue
                    seen_match_ids.add(mid)

                    # Status detect (LIVE vs UPCOMING)
                    is_live = "LIVE" in raw_text.upper() or "WATCH LIVE" in raw_text.upper()
                    status = "LIVE" if is_live else "UPCOMING"

                    # Title Clean up
                    clean_title = re.sub(r'(LIVE|WATCH LIVE|COMPLETED|HIGHLIGHTS)', '', raw_text, flags=re.I)
                    clean_title = re.sub(r'[-–—]', ' ', clean_title)
                    clean_title = re.sub(r'\s+', ' ', clean_title).strip()

                    # Teams split
                    teams = re.split(r'\s+vs\s+|\s+-\s+', clean_title, flags=re.I)
                    t1 = teams[0].strip() if len(teams) > 0 else clean_title
                    t2 = teams[1].strip() if len(teams) > 1 else ""

                    match_name = f"{t1} vs {t2}" if t2 else clean_title

                    match_entry = {
                        "event_category": sport_name,
                        "match_id": int(mid) if str(mid).isdigit() else mid,
                        "title": clean_title,
                        "match_name": match_name,
                        "event_name": f"{sport_name} Championship",
                        "src": itm["src"],
                        "team_1": t1,
                        "team_2": t2,
                        "status": status,
                        "startTime": now_ist
                    }

                    if status == "LIVE":
                        match_entry["user-agent"] = user_agent
                        match_entry["dai_url"] = None
                        match_entry["adfree_url"] = None
                        match_entry["google_m3u8_hex"] = None
                        match_entry["akamai_m3u8_hex"] = None

                    final_payload["matches"].append(match_entry)

            except Exception as e:
                print(f"🟡 Warning for {sport_name}: {str(e)}")
                continue

        await browser.close()

        with open(output_json_file, "w", encoding="utf-8") as f:
            json.dump(final_payload, f, indent=4, ensure_ascii=False)

        print(f"🟢 Successfully extracted and saved {len(final_payload['matches'])} matches in {output_json_file}")

if __name__ == "__main__":
    asyncio.run(scrape_all_fancode_schedules())
    
