import asyncio
import json
import re
from datetime import datetime, timezone, timedelta
from playwright.async_api import async_playwright

async def scrape_all_sports_events():
    target_url = "https://www.fancode.com/schedule"
    output_json_file = "fancode_matches.json"

    # IST Timezone (UTC + 5:30)
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
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            user_agent=user_agent,
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()

        # Page speed badhane ke liye media files block
        await page.route("**/*.{png,jpg,jpeg,svg,woff,woff2,css}", lambda route: route.abort())

        print("🟢 Opening FanCode Schedule page...")
        raw_matches = []

        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=40000)
            await asyncio.sleep(4)

            # Step 1: Saare sport tabs dhundo aur click karo (Cricket, Football, Basketball, etc.)
            sport_tabs = await page.query_selector_all('button[role="tab"], div[role="tablist"] > *, nav a')
            print(f"🟡 Found {len(sport_tabs)} potential sport category tabs.")

            for tab in sport_tabs[:8]:  # Top categories ko cycle karega
                try:
                    tab_text = await tab.inner_text()
                    if any(s in tab_text.lower() for s in ["cricket", "football", "basketball", "kabaddi", "hockey", "baseball", "all"]):
                        print(f"👉 Switching to category: {tab_text.strip()}")
                        await tab.click()
                        await asyncio.sleep(2)
                        await page.evaluate("window.scrollBy(0, 800);")
                except Exception:
                    continue

            # Step 2: Next.js State se deep scan karke sabhi sports ka data nikalna
            raw_matches = await page.evaluate("""() => {
                let found = [];
                try {
                    let nextData = document.getElementById('__NEXT_DATA__');
                    if (nextData) {
                        let parsed = JSON.parse(nextData.innerText);
                        let scan = (obj) => {
                            if (!obj) return;
                            if (typeof obj === 'object') {
                                if ((obj.matchId || obj.id) && (obj.startTime || obj.status || obj.teams || obj.sport)) {
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

            # Step 3: DOM Fallback (Agar Next.js empty ho toh rendered HTML se extract karna)
            if not raw_matches:
                print("🟡 Fallback: Reading all rendered cards from DOM...")
                raw_matches = await page.evaluate("""() => {
                    let items = [];
                    let links = document.querySelectorAll('a[href*="/matches/"], a[href*="/cricket/"], a[href*="/football/"]');
                    links.forEach(a => {
                        let href = a.href;
                        let text = a.innerText.replace(/\\n/g, ' - ').trim();
                        let img = a.querySelector('img');
                        let src = img ? (img.src || img.getAttribute('data-src') || '') : '';
                        
                        // Detect sport from href
                        let sport = "Cricket";
                        if (href.includes("football")) sport = "Football";
                        else if (href.includes("basketball")) sport = "Basketball";
                        else if (href.includes("kabaddi")) sport = "Kabaddi";
                        else if (href.includes("hockey")) sport = "Hockey";
                        else if (href.includes("baseball")) sport = "Baseball";

                        if (href && text.length > 3) {
                            items.push({
                                href: href,
                                name: text,
                                src: src,
                                sport: sport
                            });
                        }
                    });
                    return items;
                }""")

        except Exception as e:
            print(f"🔴 Error loading page: {str(e)}")
        finally:
            await browser.close()

        print(f"🟢 Total Raw matches captured across all sports: {len(raw_matches)}")

        seen_ids = set()
        for item in raw_matches:
            mid = item.get("matchId") or item.get("id")
            if not mid and "href" in item:
                m_match = re.search(r'(\d+)', item["href"])
                mid = m_match.group(1) if m_match else item["href"].split("/")[-1]

            if not mid or mid in seen_ids:
                continue
            seen_ids.add(mid)

            title = item.get("title") or item.get("name") or "Upcoming Match"
            clean_title = re.sub(r'[-–—]', ' ', title)
            clean_title = re.sub(r'\s+', ' ', clean_title).strip()

            raw_status = str(item.get("status", "UPCOMING")).upper()
            status = "LIVE" if "LIVE" in raw_status else "UPCOMING"

            # Dynamic Sport Category Resolution
            category = item.get("sport") or item.get("sportName") or item.get("eventCategory")
            if not category or category.strip() == "":
                lower_title = clean_title.lower()
                if any(w in lower_title for w in ["fc", "united", "real madrid", "chelsea", "champions league", "uefa", "arsenal"]):
                    category = "Football"
                elif any(w in lower_title for w in ["nba", "basketball"]):
                    category = "Basketball"
                elif any(w in lower_title for w in ["kabaddi", "yuva"]):
                    category = "Kabaddi"
                elif any(w in lower_title for w in ["hockey"]):
                    category = "Hockey"
                else:
                    category = "Cricket"

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
                "event_category": category.capitalize(),
                "match_id": int(mid) if str(mid).isdigit() else mid,
                "title": clean_title,
                "match_name": match_name,
                "event_name": item.get("tourName") or item.get("seriesName") or f"FanCode {category.capitalize()} Series",
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
    asyncio.run(scrape_all_sports_events())
    
