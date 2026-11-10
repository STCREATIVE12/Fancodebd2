import asyncio
import json
import re
import urllib.request
from datetime import datetime, timezone, timedelta
from playwright.async_api import async_playwright

async def scrape_exact_fancode_feed():
    output_json_file = "fancode_matches.json"

    # IST Time format (UTC + 5:30)
    ist_zone = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist_zone)
    now_ist = now.strftime("%I:%M:%S %p %d-%m-%Y")

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

        # Styles aur fonts block taaki execution fast rahe
        await page.route("**/*.{woff,woff2,css}", lambda route: route.abort())

        # ==========================================
        # STEP 1: LIVE MATCHES & STREAM CAPTURE
        # ==========================================
        print("🟢 Step 1: Capturing Live Matches & Master Streams...")
        try:
            await page.goto("https://www.fancode.com/live-now/all-sports", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(4)

            live_links = await page.evaluate("""() => {
                let items = [];
                let anchors = document.querySelectorAll('a[href*="/matches/"]');
                anchors.forEach(a => {
                    let href = a.href;
                    if (href && !items.includes(href)) items.push(href);
                });
                return items;
            }""")

            for l_url in live_links[:5]:
                # 7-digit Match ID extract karna
                m_match = re.search(r'[-/](\d{6,8})(?:/|$)', l_url)
                if not m_match:
                    continue
                raw_mid = m_match.group(1)
                mid_eng = f"{raw_mid}_ENG"

                # Dedicated page par stream request listen karna
                stream_page = await context.new_page()
                captured_m3u8 = []
                stream_page.on("request", lambda req: captured_m3u8.append(req.url) if ".m3u8" in req.url else None)

                try:
                    await stream_page.goto(l_url, wait_until="domcontentloaded", timeout=20000)
                    await asyncio.sleep(6)
                except Exception:
                    pass

                # Page details extract
                match_meta = await stream_page.evaluate("""() => {
                    let title = document.title || '';
                    let img = document.querySelector('img[src*="cms-media"], img[class*="Casa"], img[class*="hero"]');
                    let src = img ? (img.src || img.getAttribute('data-src') || '') : '';
                    let text = document.body.innerText || '';
                    return { title, src, text };
                }""")

                await stream_page.close()

                # Master Stream URL find karna
                master_url = next((u for u in captured_m3u8 if "1080p.m3u8" in u or "index.m3u8" in u), None)
                if not master_url and captured_m3u8:
                    master_url = captured_m3u8[0]

                # Hexadecimal encode stream text
                m3u8_hex = None
                if master_url:
                    try:
                        req = urllib.request.Request(master_url, headers={"User-Agent": user_agent})
                        with urllib.request.urlopen(req, timeout=6) as resp:
                            raw_stream = resp.read().decode('utf-8', errors='ignore')
                            m3u8_hex = raw_stream.encode('utf-8').hex()
                    except Exception:
                        pass

                clean_t = match_meta["title"].split("|")[0].replace("Watch", "").strip()
                t_parts = re.split(r'\s+vs\s+|\s+VS\s+|\s+v\s+', clean_t, flags=re.I)
                t1 = t_parts[0].strip() if len(t_parts) > 0 else clean_t
                t2 = t_parts[1].strip() if len(t_parts) > 1 else ""

                banner_src = match_meta["src"]
                if not banner_src or "flags" in banner_src:
                    banner_src = f"https://www.fancode.com/skillup-uploads/cms-media/{raw_mid}_fc-Web.jpg"

                final_payload["matches"].append({
                    "event_category": "Cricket" if "cricket" in l_url else "Football",
                    "match_id": mid_eng,
                    "title": f"{clean_t} [English]",
                    "match_name": f"{t1} vs {t2} [English]" if t2 else f"{clean_t} [English]",
                    "event_name": clean_t,
                    "src": banner_src,
                    "team_1": t1,
                    "team_2": t2,
                    "status": "LIVE",
                    "startTime": now_ist,
                    "user-agent": user_agent,
                    "dai_url": master_url,
                    "adfree_url": master_url,
                    "google_m3u8_hex": m3u8_hex,
                    "akamai_m3u8_hex": None
                })
                print(f"🔴 Live Captured: {clean_t}")

        except Exception as e:
            print(f"🟡 Live phase skipped/error: {str(e)}")

        # ==========================================
        # STEP 2: SCHEDULE PAGES SE 1-WEEK FIXTURES
        # ==========================================
        print("🟢 Step 2: Extracting 1-Week Schedule across all sports...")

        sports_schedule_urls = [
            ("Cricket", "https://www.fancode.com/cricket/schedule"),
            ("Football", "https://www.fancode.com/football/schedule"),
            ("Tennis", "https://www.fancode.com/lawn-tennis/schedule"),
            ("Formula 1", "https://www.fancode.com/formula1/schedule"),
            ("MotoGP", "https://www.fancode.com/motogp/schedule"),
            ("Golf", "https://www.fancode.com/golf/schedule"),
            ("Motorsports", "https://www.fancode.com/racing/schedule"),
            ("Badminton", "https://www.fancode.com/badminton/schedule")
        ]

        seen_match_ids = {m["match_id"] for m in final_payload["matches"]}

        for sport_name, sched_url in sports_schedule_urls:
            print(f"👉 Scanning Schedule: {sched_url}")
            try:
                await page.goto(sched_url, wait_until="domcontentloaded", timeout=25000)
                await asyncio.sleep(3)

                # Niche ke dates (Tomorrow, Next Week) load karne ke liye 4 baar scroll
                for _ in range(4):
                    await page.evaluate("window.scrollBy(0, 1000);")
                    await asyncio.sleep(0.8)

                # Schedule page se structured match data nikalna
                matches_found = await page.evaluate("""() => {
                    let results = [];

                    // Next.js direct match queries (Agar available ho)
                    try {
                        let scan = (node) => {
                            if (!node) return;
                            if (typeof node === 'object') {
                                if ((node.matchId || node.id) && (node.startTime || node.teams)) {
                                    let mid = node.matchId || node.id;
                                    let t1 = '';
                                    let t2 = '';
                                    if (node.teams && node.teams.length >= 2) {
                                        t1 = node.teams[0].name || '';
                                        t2 = node.teams[1].name || '';
                                    }
                                    results.push({
                                        mid: mid,
                                        team_1: t1,
                                        team_2: t2,
                                        name: node.name || node.title || '',
                                        tour: node.tourName || node.seriesName || '',
                                        src: node.src || node.image || '',
                                        startTime: node.startTime || '',
                                        status: node.status || 'UPCOMING'
                                    });
                                }
                                for (let k in node) scan(node[k]);
                            }
                        };
                        if (window.__NEXT_DATA__) scan(window.__NEXT_DATA__);
                    } catch(e) {}

                    // DOM Match Cards parsing
                    let cards = document.querySelectorAll('a[href*="/matches/"]');
                    cards.forEach(c => {
                        let href = c.href;
                        let text = c.innerText ? c.innerText.replace(/\\n/g, ' - ') : '';
                        
                        // Banner image pakadna (flag icon nahi)
                        let img = c.querySelector('img:not([src*="flags"])');
                        let src = img ? (img.src || img.getAttribute('data-src') || '') : '';

                        let idMatch = href.match(/[-/](\\d{6,8})(?:/|$)/);
                        if (idMatch) {
                            results.push({
                                mid: idMatch[1],
                                href: href,
                                raw_text: text,
                                src: src,
                                status: text.includes('LIVE') ? 'LIVE' : 'UPCOMING'
                            });
                        }
                    });

                    return results;
                }""")

                for itm in matches_found:
                    mid_raw = str(itm.get("mid", ""))
                    if not mid_raw or not mid_raw.isdigit():
                        continue

                    mid_int = int(mid_raw)
                    if mid_int in seen_match_ids or f"{mid_int}_ENG" in seen_match_ids:
                        continue
                    seen_match_ids.add(mid_int)

                    # Teams resolve
                    t1 = itm.get("team_1", "")
                    t2 = itm.get("team_2", "")
                    raw_text = itm.get("raw_text") or itm.get("name") or ""

                    if not t1 or not t2:
                        clean_line = re.sub(r'(Upcoming|Completed|Highlights|Watch Live|Live Now)', '', raw_text, flags=re.I)
                        clean_line = re.sub(r'[-–—|]', ' ', clean_line).strip()
                        parts = re.split(r'\s+vs\s+|\s+VS\s+|\s+v\s+', clean_line, flags=re.I)
                        t1 = parts[0].strip() if len(parts) > 0 else clean_line
                        t2 = parts[1].strip() if len(parts) > 1 else ""

                    match_name = f"{t1} vs {t2}" if t2 else t1
                    event_name = itm.get("tour") or f"{sport_name} Series, 2026"
                    title = f"{match_name} ({event_name})"

                    # High-res poster image ensure karna
                    src_url = itm.get("src", "")
                    if not src_url or "flags" in src_url:
                        src_url = f"https://www.fancode.com/skillup-uploads/cms-media/{mid_int}_fc-web.jpg"

                    start_time = itm.get("startTime") or now_ist

                    final_payload["matches"].append({
                        "event_category": sport_name,
                        "match_id": mid_int,
                        "title": title,
                        "match_name": match_name,
                        "event_name": event_name,
                        "src": src_url,
                        "team_1": t1,
                        "team_2": t2,
                        "status": "UPCOMING",
                        "startTime": start_time
                    })

            except Exception as sched_err:
                print(f"⚠️ Error in {sport_name} schedule: {str(sched_err)}")
                continue

        await browser.close()

        # Output save
        with open(output_json_file, "w", encoding="utf-8") as f:
            json.dump(final_payload, f, indent=4, ensure_ascii=False)

        print(f"🟢 Successfully extracted: {len(final_payload['matches'])} matches in {output_json_file}")

if __name__ == "__main__":
    asyncio.run(scrape_exact_fancode_feed())
    
