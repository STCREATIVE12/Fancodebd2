import asyncio
import json
import re
from datetime import datetime, timezone, timedelta
from playwright.async_api import async_playwright

async def scrape_upcoming_events():
    target_url = "https://www.fancode.com/schedule"
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

    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

    async with async_playwright() as p:
        # Browser launch with lightweight flags to prevent timeouts
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            user_agent=user_agent,
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()

        # Unnecessary images/fonts block karo taaki page 2 second mein khul jaye
        await page.route("**/*.{png,jpg,jpeg,svg,woff,woff2,css}", lambda route: route.abort())

        print("🟢 Opening FanCode Schedule page...")
        raw_matches = []

        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=40000)
            await asyncio.sleep(4)

            # Tarika 1: Direct Next.js embedded data read karna (100% accurate & fast)
            raw_matches = await page.evaluate("""() => {
                let found = [];
                try {
                    let nextData = document.getElementById('__NEXT_DATA__');
                    if (nextData) {
                        let parsed = JSON.parse(nextData.innerText);
                        let scan = (obj) => {
                            if (!obj) return;
                            if (typeof obj === 'object') {
                                if ((obj.matchId || obj.id) && (obj.startTime || obj.status || obj.teams)) {
                                    found.push(obj);
                                }
                                for (let k in obj) scan(obj[k]);
                            }
                        };
                        scan(parsed);
                    }
                } catch(e) {}
                return found;
            }""")

            # Tarika 2: Agar Next.js data empty mile toh DOM backup
            if not raw_matches:
                print("🟡 Fallback: Reading from DOM cards...")
                for _ in range(3):
                    await page.evaluate("window.scrollBy(0, 1000);")
                    await asyncio.sleep(1)

                raw_matches = await page.evaluate("""() => {
                    let items = [];
                    let links = document.querySelectorAll('a[href*="/matches/"]');
                    links.forEach(a => {
                        let href = a.href;
                        let text = a.innerText.replace(/\\n/g, ' - ').trim();
                        let img = a.querySelector('img');
                        let src = img ? (img.src || img.getAttribute('data-src') || '') : '';
                        if (href && text.length > 3) {
                            items.push({
                                href: href,
                                name: text,
                                src: src
                            });
                        }
                    });
                    return items;
                }""")

        except Exception as e:
            print(f"🔴 Error loading page: {str(e)}")
        finally:
            await browser.close()

        print(f"🟢 Raw entries captured: {len(raw_matches)}")

        seen_ids = set()
        for item in raw_matches:
            # Match ID nikalna
            mid = item.get("matchId") or item.get("id")
            if not mid and "href" in item:
                m_match = re.search(r'(\d+)', item["href"])
                mid = m_match.group(1) if m_match else item["href"].split("/")[-1]

            if not mid or mid in seen_ids:
                continue
            seen_ids.add(mid)

            # Match details
            title = item.get("title") or item.get("name") or "Upcoming Match"
            clean_title = re.sub(r'[-–—]', ' ', title)
            clean_title = re.sub(r'\s+', ' ', clean_title).strip()

            # Status check
            raw_status = str(item.get("status", "UPCOMING")).upper()
            status = "LIVE" if "LIVE" in raw_status else "UPCOMING"

            # Teams mapping
            teams = item.get("teams", [])
            team1 = teams[0].get("name", "") if len(teams) > 0 and isinstance(teams[0], dict) else item.get("team1", "")
            team2 = teams[1].get("name", "") if len(teams) > 1 and isinstance(teams[1], dict) else item.get("team2", "")

            if not team1 and "vs" in clean_title.lower():
                parts = re.split(r'\s+vs\s+', clean_title, flags=re.I)
                team1 = parts[0].strip()
                team2 = parts[1].strip() if len(parts) > 1 else ""

            match_name = f"{team1} vs {team2}" if (team1 and team2) else clean_title

            match_entry = {
                "event_category": item.get("sport") or item.get("sportName") or "Cricket",
                "match_id": int(mid) if str(mid).isdigit() else mid,
                "title": clean_title,
                "match_name": match_name,
                "event_name": item.get("tourName") or item.get("seriesName") or "FanCode Event",
                "src": item.get("src") or item.get("image") or item.get("thumbnail") or "",
                "team_1": team1,
                "team_2": team2,
                "status": status,
                "startTime": item.get("startTime") or item.get("startDate") or now_ist
            }

            if status == "LIVE":
                match_entry["user-agent"] = user_agent
                match_entry["dai_url"] = None
                match_entry["adfree_url"] = None
                match_entry["google_m3u8_hex"] = None
                match_entry["akamai_m3u8_hex"] = None

            final_payload["matches"].append(match_entry)

        with open(output_json_file, "w", encoding="utf-8") as f:
            json.dump(final_payload, f, indent=4, ensure_ascii=False)

        print(f"🟢 Successfully saved {len(final_payload['matches'])} matches in {output_json_file}")

if __name__ == "__main__":
    asyncio.run(scrape_upcoming_events())
    
