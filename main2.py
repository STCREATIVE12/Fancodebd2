import asyncio
import json
import re
from datetime import datetime, timezone, timedelta
from playwright.async_api import async_playwright

async def scrape_complete_fancode_data():
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

    user_agent = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            user_agent=user_agent,
            viewport={"width": 1440, "height": 900}
        )
        page = await context.new_page()

        # Network interceptor: FanCode backend API se aane wale pure JSON responses pakadna
        captured_api_matches = []

        async def intercept_response(response):
            try:
                url = response.url
                # FanCode matches / tour / schedule GraphQL aur REST calls
                if any(x in url for x in ["graphql", "api.fancode.com", "/matches", "/schedule"]):
                    content_type = response.headers.get("content-type", "")
                    if "application/json" in content_type:
                        res_json = await response.json()
                        captured_api_matches.append(res_json)
            except Exception:
                pass

        page.on("response", intercept_response)

        # Images/fonts block karo taaki har tour page 1 second mein open ho
        await page.route("**/*.{png,jpg,jpeg,svg,woff,woff2,css}", lambda route: route.abort())

        target_url = "https://www.fancode.com/tour-listing/all"
        print(f"🟢 Fetching All Tours from: {target_url}")

        tours_list = []
        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)

            # Scroll karke saare active / upcoming tours load karna
            for _ in range(5):
                await page.evaluate("window.scrollBy(0, 1000);")
                await asyncio.sleep(0.8)

            # Step 1: Saare Tour Links aur Names nikalna
            tours_list = await page.evaluate("""() => {
                let items = [];
                let anchors = document.querySelectorAll('a[href*="/tour/"]');
                anchors.forEach(a => {
                    let href = a.href;
                    let text = a.innerText.replace(/\\n/g, ' - ').trim();
                    if (href && !items.some(i => i.href === href)) {
                        items.push({ href: href, title: text });
                    }
                });
                return items;
            }""")
        except Exception as e:
            print(f"🔴 Error loading tours list: {str(e)}")

        print(f"🟢 Total Tours Found: {len(tours_list)}")

        seen_match_ids = set()

        # Step 2: Sabhi active tours ke andar jakar matches nikalna
        for index, tour in enumerate(tours_list):
            tour_url = tour["href"]
            matches_url = tour_url if "/matches" in tour_url else f"{tour_url.rstrip('/')}/matches"
            print(f"[{index + 1}/{len(tours_list)}] ↳ Scanning Matches: {matches_url}")

            # Sport category detect karna
            sport_name = "Cricket"
            if "/football/" in tour_url:
                sport_name = "Football"
            elif "/tennis/" in tour_url or "/lawn-tennis/" in tour_url:
                sport_name = "Tennis"
            elif "/formula1/" in tour_url:
                sport_name = "Formula 1"
            elif "/motogp/" in tour_url:
                sport_name = "MotoGP"
            elif "/badminton/" in tour_url:
                sport_name = "Badminton"
            elif "/golf/" in tour_url:
                sport_name = "Golf"
            elif "/racing/" in tour_url:
                sport_name = "Motorsports"

            try:
                await page.goto(matches_url, wait_until="domcontentloaded", timeout=18000)
                await asyncio.sleep(2)
                await page.evaluate("window.scrollBy(0, 1000);")
                await asyncio.sleep(1)

                # Tour page ke state aur cards se pure upcoming & live matches parse karna
                matches_in_tour = await page.evaluate("""() => {
                    let extracted = [];
                    
                    // Tarika A: Page ke DOM Cards
                    let cards = document.querySelectorAll('a[href*="/matches/"]');
                    cards.forEach(a => {
                        let href = a.href;
                        let text = a.innerText.replace(/\\n/g, ' | ').trim();
                        let img = a.querySelector('img');
                        let src = img ? (img.src || img.getAttribute('data-src') || '') : '';
                        
                        if (href && text.length > 3) {
                            extracted.push({
                                href: href,
                                text: text,
                                src: src
                            });
                        }
                    });

                    // Tarika B: Next.js Dehydrated Query State (100% complete data)
                    try {
                        let scan = (node) => {
                            if (!node) return;
                            if (typeof node === 'object') {
                                if ((node.matchId || node.id) && (node.startTime || node.teams || node.status)) {
                                    extracted.push({
                                        id: node.matchId || node.id,
                                        name: node.name || node.title || '',
                                        tourName: node.tourName || node.seriesName || '',
                                        src: node.src || node.image || '',
                                        status: node.status || 'UPCOMING',
                                        startTime: node.startTime || '',
                                        teams: node.teams || []
                                    });
                                }
                                for (let k in node) scan(node[k]);
                            }
                        };
                        if (window.__NEXT_DATA__) scan(window.__NEXT_DATA__);
                    } catch(e) {}

                    return extracted;
                }""")

                # Format karna exact JSON Schema mein
                for item in matches_in_tour:
                    # Match ID nikalna
                    mid = None
                    if "id" in item:
                        mid = item["id"]
                    elif "href" in item:
                        id_m = re.search(r'[-/](\d{6,8})(?:/|$)', item["href"])
                        mid = id_m.group(1) if id_m else re.sub(r'[^0-9]', '', item["href"])

                    if not mid or mid in seen_match_ids:
                        continue
                    seen_match_ids.add(mid)

                    # Title aur Teams format
                    raw_text = item.get("text") or item.get("name") or "Match"
                    clean_str = re.sub(r'(Upcoming|Completed|Highlights|Watch Live|Live Now)', '', raw_text, flags=re.I)
                    clean_str = re.sub(r'[-–—|]', ' ', clean_str)
                    clean_str = re.sub(r'\s+', ' ', clean_str).strip()

                    teams = item.get("teams", [])
                    t1 = teams[0].get("name", "") if len(teams) > 0 and isinstance(teams[0], dict) else ""
                    t2 = teams[1].get("name", "") if len(teams) > 1 and isinstance(teams[1], dict) else ""

                    if not t1:
                        split_teams = re.split(r'\s+vs\s+|\s+VS\s+|\s+v\s+', clean_str, flags=re.I)
                        t1 = split_teams[0].strip() if len(split_teams) > 0 else clean_str
                        t2 = split_teams[1].strip() if len(split_teams) > 1 else ""

                    match_title = f"{t1} vs {t2}" if t2 else t1
                    event_title = item.get("tourName") or tour.get("title") or f"{sport_name} Championship"
                    full_title = f"{match_title} ({event_title})"

                    # Status detect (LIVE vs UPCOMING)
                    status = "UPCOMING"
                    if "LIVE" in str(item.get("status", "")).upper() or "LIVE" in raw_text.upper():
                        status = "LIVE"

                    # Start time formatting
                    start_time = item.get("startTime") or now_ist

                    # Exact JSON Key Structure
                    match_entry = {
                        "event_category": sport_name,
                        "match_id": int(mid) if str(mid).isdigit() else mid,
                        "title": full_title,
                        "match_name": match_title,
                        "event_name": event_title,
                        "src": item.get("src", ""),
                        "team_1": t1,
                        "team_2": t2,
                        "status": status,
                        "startTime": start_time
                    }

                    # Live match streaming links agar available ho
                    if status == "LIVE":
                        match_entry["user-agent"] = user_agent
                        match_entry["dai_url"] = None
                        match_entry["adfree_url"] = None
                        match_entry["google_m3u8_hex"] = None
                        match_entry["akamai_m3u8_hex"] = None

                    final_payload["matches"].append(match_entry)

            except Exception as tour_err:
                continue

        await browser.close()

        # Save exact JSON Output
        with open(output_json_file, "w", encoding="utf-8") as f:
            json.dump(final_payload, f, indent=4, ensure_ascii=False)

        print(f"🟢 Successfully extracted and saved {len(final_payload['matches'])} matches in {output_json_file}")

if __name__ == "__main__":
    asyncio.run(scrape_complete_fancode_data())
    
