import asyncio
from datetime import datetime
import json
import pytz
from playwright.async_api import async_playwright

async def scrape_fancode_matches():
    output_json_file = "fancode_matches.json"
    
    # IST Timezone setup
    ist = pytz.timezone("Asia/Kolkata")
    now_ist = datetime.now(ist).strftime("%I:%M:%S %p %d-%m-%Y")

    final_payload = {
        "name": "Fancode Live Matches Data in Json",
        "telegram": "https://t.me/+rQTz5VL8CRpjNTZl",
        "last update time": now_ist,
        "matches": []
    }

    user_agent = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=user_agent,
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()

        captured_api_responses = []

        # Background mein FanCode ke internal match/schedule API responses intercept karna
        async def handle_response(response):
            url = response.url
            if any(endpoint in url for endpoint in ["/matches", "/schedule", "/tour-listing", "graphql"]):
                try:
                    if "application/json" in response.headers.get("content-type", ""):
                        data = await response.json()
                        captured_api_responses.append(data)
                except Exception:
                    pass

        page.on("response", handle_response)

        print("🟢 Opening FanCode Schedule page...")
        try:
            await page.goto("https://www.fancode.com/schedule", wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(6)

            # Lazy-load matches load karne ke liye scroll
            for _ in range(5):
                await page.evaluate("window.scrollBy(0, window.innerHeight);")
                await asyncio.sleep(2)

            # Agar API intercept nahi hoti toh DOM se exact data extract karna
            dom_matches = await page.evaluate("""() => {
                let items = [];
                let cards = document.querySelectorAll('a[href*="/matches/"]');

                cards.forEach(a => {
                    let href = a.href;
                    let matchIdMatch = href.match(/\\/matches\\/([0-9]+)/);
                    let matchId = matchIdMatch ? matchIdMatch[1] : '';

                    let rawText = a.innerText.replace(/\\n/g, ' | ').trim();
                    let isLive = rawText.toUpperCase().includes('LIVE');
                    
                    let img = a.querySelector('img');
                    let src = img ? (img.src || img.getAttribute('data-src') || '') : '';

                    // Teams split
                    let teamParts = rawText.split(/\\s+vs\\s+|\\s+VS\\s+|\\s+v\\s+/i);
                    let team1 = teamParts[0] ? teamParts[0].split('|')[0].replace('LIVE', '').trim() : '';
                    let team2 = teamParts[1] ? teamParts[1].split('|')[0].trim() : '';

                    if (matchId && !items.some(i => i.match_id === matchId)) {
                        items.push({
                            match_id: matchId,
                            title: rawText,
                            match_name: team1 && team2 ? `${team1} vs ${team2}` : rawText,
                            event_name: "FanCode Match Series",
                            src: src,
                            team_1: team1,
                            team_2: team2,
                            status: isLive ? "LIVE" : "UPCOMING",
                            startTime: new Date().toLocaleTimeString()
                        });
                    }
                });
                return items;
            }""")

        except Exception as e:
            print(f"🔴 Page Load Error: {str(e)}")
            dom_matches = []
        finally:
            await browser.close()

        print(f"🟢 Matches Extracted: {len(dom_matches)}")

        # Target JSON format schema mapping
        for m in dom_matches:
            status = m.get("status", "UPCOMING")
            match_entry = {
                "event_category": "Cricket", # Default / category detect
                "match_id": int(m["match_id"]) if str(m["match_id"]).isdigit() else m["match_id"],
                "title": m["title"],
                "match_name": m["match_name"],
                "event_name": m["event_name"],
                "src": m["src"],
                "team_1": m["team_1"],
                "team_2": m["team_2"],
                "status": status,
                "startTime": m["startTime"]
            }

            # Agar LIVE match hai toh streaming fields add honge
            if status == "LIVE":
                match_entry["user-agent"] = user_agent
                match_entry["dai_url"] = None
                match_entry["adfree_url"] = None
                match_entry["google_m3u8_hex"] = None
                match_entry["akamai_m3u8_hex"] = None

            final_payload["matches"].append(match_entry)

        # JSON file save
        with open(output_json_file, "w", encoding="utf-8") as jf:
            json.dump(final_payload, jf, indent=4, ensure_ascii=False)

        print(f"🟢 Successfully created {output_json_file} with {len(final_payload['matches'])} matches.")

if __name__ == "__main__":
    asyncio.run(scrape_fancode_matches())
