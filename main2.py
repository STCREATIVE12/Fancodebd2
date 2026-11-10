import asyncio
import json
import re
from datetime import datetime, timezone, timedelta
from playwright.async_api import async_playwright

async def scrape_all_tour_fixtures():
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

        # Images, CSS, fonts block karein taaki GitHub Actions 1-2 second mein page load kare
        await page.route("**/*.{png,jpg,jpeg,svg,woff,woff2,css}", lambda route: route.abort())

        target_url = "https://www.fancode.com/tour-listing/all"
        print(f"🟢 Opening All Tours Page: {target_url}")

        tours_list = []
        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)

            # Scroll karke saare active tours load karna
            for _ in range(5):
                await page.evaluate("window.scrollBy(0, 1000);")
                await asyncio.sleep(0.8)

            # Tours URLs aur Tour Names extract karna
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

        # Ab saare active tours visit honge (top 35 active tours limit taaki GitHub job timeout na ho)
        for index, tour in enumerate(tours_list[:35]):
            tour_url = tour["href"]
            # Ensure URL points to matches tab
            matches_url = tour_url if "/matches" in tour_url else f"{tour_url.rstrip('/')}/matches"
            print(f"[{index + 1}/{min(len(tours_list), 35)}] ↳ Checking Fixtures: {matches_url}")

            try:
                await page.goto(matches_url, wait_until="domcontentloaded", timeout=18000)
                await asyncio.sleep(2)
                # Tour page scroll karo taaki niche ke upcoming match cards load ho sakein
                await page.evaluate("window.scrollBy(0, 800);")
                await asyncio.sleep(1)

                # Tour page ke andar ke saare individual match fixtures dhoondhna
                fixtures = await page.evaluate("""() => {
                    let list = [];
                    
                    // Match container cards
                    let matchElements = document.querySelectorAll('a[href*="/matches/"], div[class*="matchCard"], div[role="article"]');
                    
                    matchElements.forEach(el => {
                        let text = el.innerText ? el.innerText.replace(/\\n/g, ' | ') : '';
                        let link = el.tagName === 'A' ? el.href : (el.querySelector('a') ? el.querySelector('a').href : '');
                        
                        let img = el.querySelector('img');
                        let src = img ? (img.src || img.getAttribute('data-src') || '') : '';

                        // Upcoming check: Card text mein Upcoming/VS/date info ho
                        let isCompleted = text.includes('Completed') || text.includes('Highlights');
                        
                        if (text.length > 5 && !isCompleted) {
                            list.push({
                                raw_text: text,
                                href: link,
                                src: src
                            });
                        }
                    });

                    // Next.js direct state scan (Deep Search)
                    if (window.__NEXT_DATA__) {
                        try {
                            let scan = (node) => {
                                if (!node) return;
                                if (typeof node === 'object') {
                                    if ((node.matchId || node.id) && (node.startTime || node.status === 'UPCOMING' || node.teams)) {
                                        let tName = node.name || node.title || '';
                                        list.push({
                                            raw_text: tName + ' | ' + (node.startTime || ''),
                                            href: '/matches/' + (node.matchId || node.id),
                                            src: node.src || node.image || '',
                                            obj: node
                                        });
                                    }
                                    for (let k in node) scan(node[k]);
                                }
                            };
                            scan(window.__NEXT_DATA__);
                        } catch(e) {}
                    }

                    return list;
                }""")

                # Sport Name detect
                sport_name = "Cricket"
                if "/football/" in tour_url:
                    sport_name = "Football"
                elif "/formula1/" in tour_url:
                    sport_name = "Formula 1"
                elif "/lawn-tennis/" in tour_url:
                    sport_name = "Tennis"
                elif "/motogp/" in tour_url:
                    sport_name = "MotoGP"
                elif "/badminton/" in tour_url:
                    sport_name = "Badminton"

                for item in fixtures:
                    raw_text = item.get("raw_text", "")
                    href = item.get("href", "")
                    node_obj = item.get("obj", {})

                    # Match ID
                    id_m = re.search(r'[-/](\d{6,8})(?:/|$)', href)
                    mid = id_m.group(1) if id_m else node_obj.get("matchId") or node_obj.get("id")
                    
                    if not mid:
                        mid = str(abs(hash(raw_text)))[:7]

                    if mid in seen_match_ids:
                        continue
                    seen_match_ids.add(mid)

                    # Clean Title & Teams
                    clean_title = re.sub(r'(Upcoming|View Details|Watch Live|Live Now)', '', raw_text, flags=re.I)
                    clean_title = re.sub(r'[-–—|]', ' ', clean_title)
                    clean_title = re.sub(r'\s+', ' ', clean_title).strip()

                    teams = re.split(r'\s+vs\s+|\s+VS\s+|\s+v\s+', clean_title, flags=re.I)
                    t1 = teams[0].strip() if len(teams) > 0 else clean_title
                    t2 = teams[1].strip() if len(teams) > 1 else ""

                    # Agar startTime text mein ho
                    start_time = node_obj.get("startTime") or now_ist

                    match_title = f"{t1} vs {t2}" if t2 else t1

                    entry = {
                        "event_category": sport_name,
                        "match_id": int(mid) if str(mid).isdigit() else mid,
                        "title": match_title,
                        "match_name": match_title,
                        "event_name": tour.get("title") or f"{sport_name} Championship",
                        "src": item.get("src", ""),
                        "team_1": t1,
                        "team_2": t2,
                        "status": "UPCOMING",
                        "startTime": start_time
                    }

                    final_payload["matches"].append(entry)

            except Exception as tour_err:
                continue

        await browser.close()

        with open(output_json_file, "w", encoding="utf-8") as f:
            json.dump(final_payload, f, indent=4, ensure_ascii=False)

        print(f"🟢 Extraction Finished! Total {len(final_payload['matches'])} Upcoming matches saved in {output_json_file}")

if __name__ == "__main__":
    asyncio.run(scrape_all_tour_fixtures())
    
