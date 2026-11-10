import asyncio
import json
import re
from datetime import datetime, timezone, timedelta
from playwright.async_api import async_playwright

async def scrape_upcoming_from_tour_listing():
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
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            user_agent=user_agent,
            viewport={"width": 1280, "height": 900}
        )
        page = await context.new_page()

        # Unnecessary media files block taaki GitHub Actions par fast chale
        await page.route("**/*.{png,jpg,jpeg,svg,woff,woff2,css}", lambda route: route.abort())

        target_url = "https://www.fancode.com/tour-listing/all"
        print(f"🟢 Opening All Tours Page: {target_url}")

        tours_list = []
        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(4)

            # Scroll karke saare Upcoming Tours load karwana
            for _ in range(4):
                await page.evaluate("window.scrollBy(0, 800);")
                await asyncio.sleep(1)

            # Step 1: Saare Tour Listing Links nikalna
            tours_list = await page.evaluate("""() => {
                let items = [];
                let links = document.querySelectorAll('a[href*="/tour/"]');
                links.forEach(a => {
                    let href = a.href;
                    let text = a.innerText.replace(/\\n/g, ' ').trim();
                    if (href && !items.some(i => i.href === href)) {
                        items.push({ href: href, title: text });
                    }
                });
                return items;
            }""")
        except Exception as e:
            print(f"🔴 Error loading tour listing: {str(e)}")

        print(f"🟢 Total Tours Found: {len(tours_list)}")

        seen_match_ids = set()

        # Step 2: Har Tour Page ke andar jakar "Upcoming" match cards parse karna
        for tour in tours_list[:12]:
            tour_url = tour["href"]
            print(f"👉 Visiting Tour: {tour_url}")

            try:
                await page.goto(tour_url, wait_until="domcontentloaded", timeout=20000)
                await asyncio.sleep(3)

                # Page ke embedded data aur HTML se Upcoming fixtures nikalna
                matches_data = await page.evaluate("""() => {
                    let results = [];
                    
                    // DOM parsing: Upcoming containers
                    let upcomingCards = document.querySelectorAll('a[href*="/matches/"], div[class*="matchCard"], div[role="article"]');
                    upcomingCards.forEach(card => {
                        let text = card.innerText ? card.innerText.replace(/\\n/g, ' | ') : '';
                        let linkEl = card.tagName === 'A' ? card : card.querySelector('a');
                        let href = linkEl ? linkEl.href : '';
                        
                        let img = card.querySelector('img');
                        let src = img ? (img.src || img.getAttribute('data-src') || '') : '';

                        if (text.length > 5 && (text.includes('Upcoming') || text.includes('vs') || text.includes('VS') || text.includes('Nov') || text.includes('Dec'))) {
                            results.push({
                                raw_text: text,
                                href: href,
                                src: src
                            });
                        }
                    });

                    // Agar card na mile toh Next data scan
                    if (results.length === 0 && window.__NEXT_DATA__) {
                        try {
                            let scanObj = (o) => {
                                if (!o) return;
                                if (typeof o === 'object') {
                                    if (o.status === 'UPCOMING' || (o.matchId && o.startTime)) {
                                        results.push({
                                            raw_text: (o.name || o.title || '') + ' | ' + (o.startTime || ''),
                                            href: '/matches/' + (o.matchId || o.id),
                                            src: o.src || ''
                                        });
                                    }
                                    for (let k in o) scanObj(o[k]);
                                }
                            };
                            scanObj(window.__NEXT_DATA__);
                        } catch(err) {}
                    }

                    return results;
                }""")

                # Sport Name detect karna
                sport_name = "Cricket"
                if "/football/" in tour_url:
                    sport_name = "Football"
                elif "/formula1/" in tour_url:
                    sport_name = "Formula 1"
                elif "/lawn-tennis/" in tour_url:
                    sport_name = "Tennis"
                elif "/motogp/" in tour_url:
                    sport_name = "MotoGP"

                for m in matches_data:
                    raw_text = m.get("raw_text", "")
                    href = m.get("href", "")

                    # Match ID extract
                    id_match = re.search(r'[-/](\d{6,8})(?:/|$)', href)
                    mid = id_match.group(1) if id_match else re.sub(r'[^0-9]', '', href)
                    if not mid:
                        mid = str(abs(hash(raw_text)))[:7]

                    if mid in seen_match_ids:
                        continue
                    seen_match_ids.add(mid)

                    # Text clean
                    clean_str = re.sub(r'(Upcoming|Completed|Highlights|Watch Live)', '', raw_text, flags=re.I)
                    clean_str = re.sub(r'[-–—|]', ' ', clean_str)
                    clean_str = re.sub(r'\s+', ' ', clean_str).strip()

                    # Teams detect
                    teams = re.split(r'\s+vs\s+|\s+VS\s+', clean_str, flags=re.I)
                    t1 = teams[0].strip() if len(teams) > 0 else clean_str
                    t2 = teams[1].strip() if len(teams) > 1 else ""

                    match_title = f"{t1} vs {t2}" if t2 else t1

                    entry = {
                        "event_category": sport_name,
                        "match_id": int(mid) if str(mid).isdigit() else mid,
                        "title": match_title,
                        "match_name": match_title,
                        "event_name": tour.get("title") or f"{sport_name} Championship",
                        "src": m.get("src", ""),
                        "team_1": t1,
                        "team_2": t2,
                        "status": "UPCOMING",
                        "startTime": now_ist
                    }

                    final_payload["matches"].append(entry)

            except Exception as tour_err:
                print(f"⚠️ Error on tour {tour_url}: {str(tour_err)}")
                continue

        await browser.close()

        with open(output_json_file, "w", encoding="utf-8") as f:
            json.dump(final_payload, f, indent=4, ensure_ascii=False)

        print(f"🟢 Successfully extracted {len(final_payload['matches'])} Upcoming matches in {output_json_file}")

if __name__ == "__main__":
    asyncio.run(scrape_upcoming_from_tour_listing())
    
