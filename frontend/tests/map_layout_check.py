"""
Browser check of the map page layout: Google's logo / "Keyboard shortcuts" / map data / "Terms" are never covered,
and the place card, the floating mic and the bottom nav don't overlap. Also the Home "Google Maps" line.

Needs: the dev server (npm run dev, http://localhost:5173), Chrome, and `pip install playwright`. Not part of npm test.
The app's own API and WebSockets are faked (no account, no Places calls); the map itself is the real Google map
(one map load per page). Headed Chrome: headless falls back to a raster map.
    python tests/map_layout_check.py [--out DIR] [--base URL]
"""
import argparse
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser()
ap.add_argument("--out", default="", help="folder for screenshots")
ap.add_argument("--base", default="http://localhost:5173")
ap.add_argument("--label", default="after")
args = ap.parse_args()
OUT = Path(args.out) if args.out else None
if OUT:
    OUT.mkdir(parents=True, exist_ok=True)

LAT, LNG = 26.9239, 75.8267
GAP_MIN, GAP_MAX = 6, 10          # px between the attribution strip and the card

SESSION = {
    "authenticated": True,
    "authUser": {"id": "usr_layout_check", "email": "layout-check@example.com", "status": "ACTIVE", "emailVerified": True},
    "userProfile": {"userId": "usr_layout_check", "fullName": "Layout Check", "onboardingStatus": "COMPLETED", "onboardingStep": "COMPLETED"},
    "userPreferences": {"userId": "usr_layout_check"},
}
PLACES = [{"id": f"ChIJlayoutcheck{i:04d}", "name": n, "category": c, "latitude": LAT + dy, "longitude": LNG + dx,
           "distance_meters": 200 + 150 * i, "address": "Badi Choupad, Pink City, Jaipur, Rajasthan 302002", "rating": 4.4}
          for i, (n, c, dy, dx) in enumerate([
              ("Test Palace with a fairly long name", "tourist_attraction", 0.002, 0.001), ("Test Cafe", "cafe", -0.002, 0.002),
              ("Test Museum", "museum", 0.001, -0.003), ("Test Hotel", "lodging", -0.003, -0.002)])]

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail != "" and not ok else ""), flush=True)


def api(route):
    req = route.request
    cors = {"Access-Control-Allow-Origin": args.base, "Access-Control-Allow-Credentials": "true",
            "Access-Control-Allow-Headers": req.headers.get("access-control-request-headers", "*"),
            "Access-Control-Allow-Methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS"}
    if req.method == "OPTIONS":
        return route.fulfill(status=204, headers=cors)
    path = re.sub(r"^https?://[^/]+", "", req.url).split("?")[0]
    if path == "/api/auth/me":
        body, status = SESSION, 200
    elif path == "/api/places/nearby":
        body, status = PLACES, 200
    elif path == "/api/tour-guide/nearby":
        body, status = {"places": [{**q, "distanceMeters": q["distance_meters"]} for q in PLACES],
                        "center": {"latitude": LAT, "longitude": LNG}, "radius_m": 5000}, 200
    elif path == "/api/location/reverse":
        body, status = {"display_name": "Jaipur, Rajasthan", "city": "Jaipur", "state": "Rajasthan"}, 200
    elif path in ("/api/trips", "/api/saved-places"):
        body, status = [], 200
    else:
        body, status = {"detail": "not in this check"}, 404
    route.fulfill(status=status, headers={**cors, "Content-Type": "application/json"}, body=json.dumps(body))


def fake_ws(ws):
    def on_message(msg):
        try:
            frame = json.loads(msg)
        except Exception:
            return
        rid = frame.get("id") or frame.get("requestId")
        if rid:
            data = [] if frame.get("action") in ("trips:list", "places:saved") else None
            ws.send(json.dumps({"id": rid, "requestId": rid, "action": frame.get("action"),
                                "status": "success" if data is not None else "error", "data": data,
                                "error": None if data is not None else "not in this check"}))
    ws.on_message(on_message)


MEASURE = """() => {
  const rect = (el) => { if (!el) return null; const r = el.getBoundingClientRect();
    return r.width && r.height ? { x: r.left, y: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height } : null; };
  const box = document.querySelector('.map-view [role=region][aria-label=Map]');
  const gm = box && box.querySelector('.gm-style');
  const logo = gm && [...gm.querySelectorAll('a[href*="maps.google.com/maps"] img, img[alt="Google"]')].find((e) => rect(e));
  const ccs = gm ? [...gm.querySelectorAll('.gm-style-cc')].filter((e) => rect(e)) : [];
  const att = [];
  if (logo) att.push(['logo', logo]);
  for (const cc of ccs) {
    // Narrow maps: Google itself shows a keyboard icon button instead of the words "Keyboard shortcuts".
    const label = (e) => e.textContent.trim() || e.getAttribute('aria-label') || e.getAttribute('title') || '';
    const inner = [...cc.querySelectorAll('button, a, span')].filter((e) => rect(e) && label(e));
    const el = inner[0] || cc;
    att.push([label(el).slice(0, 40), el]);
  }
  const covered = [];
  for (const [name, el] of att) {
    const r = rect(el);
    for (const fx of [0.05, 0.25, 0.5, 0.75, 0.95]) for (const fy of [0.2, 0.5, 0.8]) {
      const x = r.x + r.w * fx, y = r.y + r.h * fy;
      const top = document.elementFromPoint(x, y);
      if (!top || !gm.contains(top)) covered.push(name + ' by ' + (top ? (top.className || top.tagName).toString().slice(0, 60) : 'offscreen'));
    }
    const cs = getComputedStyle(el);
    if (cs.visibility !== 'visible' || Number(cs.opacity) < 1) covered.push(name + ' not visible');
  }
  const dot = document.querySelector('.vg-user__dot'); const dr = rect(dot);
  let dotHit = null;
  if (dr) { const t = document.elementFromPoint(dr.x + dr.w / 2, dr.y + dr.h / 2); dotHit = !!t && box.contains(t); }
  const typeBtns = [...document.querySelectorAll('.map-type-controls button')].map((e) => ({ name: e.getAttribute('aria-label'), ...rect(e) }));
  const cards = [...document.querySelectorAll('.map-places-overlay [role=button]')];
  const card = document.querySelector('.map-selected-sheet') || cards.find((c) => { const r = rect(c); return r && r.r > 40; });
  const cr = rect(card);
  let cardHit = null;
  if (cr) { const x = Math.min(Math.max(cr.x + 60, 20), innerWidth - 20), t = document.elementFromPoint(x, cr.y + 30); cardHit = !!t && card.contains(t); }
  const tools = [...document.querySelectorAll('.map-app-tools button')];
  return { box: rect(box), attribution: att.map(([n, e]) => ({ name: n, ...rect(e) })), covered,
    card: cr, cardHit, dot: dr, dotHit, typeBtns,
    fabs: tools.map((t) => ({ name: t.getAttribute('aria-label'), pos: getComputedStyle(t.closest('.map-app-tools')).position, ...rect(t) })),
    pins: [...document.querySelectorAll('.vg-pin__badge')].map((e) => rect(e)).filter(Boolean),
    nav: rect(document.querySelector('nav.guide-app-nav')),
    noteBottomY: innerHeight - parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--mic-note-bottom') || 'NaN'), vw: innerWidth, vh: innerHeight };
}"""


def overlap(a, b, pad=0):
    return bool(a and b and a["x"] < b["r"] - pad and a["r"] > b["x"] + pad and a["y"] < b["b"] - pad and a["b"] > b["y"] + pad)


def open_page(browser, w, h, dark=False):
    ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=2, is_mobile=True, has_touch=True,
                              geolocation={"latitude": LAT, "longitude": LNG, "accuracy": 20}, permissions=["geolocation"],
                              color_scheme="dark" if dark else "light")
    if dark:
        ctx.add_init_script("try { localStorage.setItem('cruiser_theme', 'dark') } catch (e) {}")
    page = ctx.new_page()
    page.route(re.compile(r"^https?://[^/]+/api/"), api)
    page.route_web_socket(re.compile(r"/ws/"), fake_ws)
    return ctx, page


def check_map(m, tag, portrait=True):
    names = " | ".join(a["name"] for a in m["attribution"])
    low = names.lower()
    check(f"{tag}: logo, keyboard shortcuts, map data and terms are all there",
          "logo" in low and ("shortcut" in low) and "terms" in low and ("map data" in low or "©" in low), names)
    check(f"{tag}: nothing covers the attribution", m["attribution"] and not m["covered"], sorted(set(m["covered"])))
    check(f"{tag}: attribution is inside the screen", all(a["x"] >= -0.5 and a["r"] <= m["vw"] + 0.5 and a["b"] <= m["vh"] + 1 for a in m["attribution"]),
          m["attribution"])
    strip_bottom = max(a["b"] for a in m["attribution"]) if m["attribution"] else 0
    box_bottom = m["box"]["b"]
    card = m["card"]
    check(f"{tag}: card shown and tappable", bool(card) and m["cardHit"], card)
    if card:
        check(f"{tag}: card does not overlap any attribution", not any(overlap(card, a) for a in m["attribution"]))
    if "sheet" not in tag and tag != "740x360":
        under = [r for r in m["pins"] if any(overlap(r, o) for o in [card, *m["fabs"]])]
        check(f"{tag}: all 4 place pins on the map, none under the card or mic", len(m["pins"]) == 4 and not under, (len(m["pins"]), under))
    if card and not portrait:
        check(f"{tag}: card ends {GAP_MIN}-{GAP_MAX + 6} px above the attribution strip", GAP_MIN <= box_bottom - 24 - card["b"] <= GAP_MAX + 6,
              f"{box_bottom - 24 - card['b']:.1f}")
    if card and portrait:
        check(f"{tag}: map ends {GAP_MIN}-{GAP_MAX} px from the card", GAP_MIN <= card["y"] - box_bottom <= GAP_MAX,
              f"gap {card['y'] - box_bottom:.1f}, strip bottom {strip_bottom:.1f}")
        check(f"{tag}: card sits just above the bottom nav", m["nav"] and 0 <= m["nav"]["y"] - card["b"] <= 16,
              f"{m['nav']['y'] - card['b']:.1f}" if m["nav"] else "no nav")
    check(f"{tag}: voice note sits above the floating mic", m["fabs"] and m["noteBottomY"] <= min(f["y"] for f in m["fabs"]), m["noteBottomY"])
    check(f"{tag}: only the mic floats over the map", len(m["fabs"]) == 1 and all(f["pos"] == "absolute" for f in m["fabs"]), m["fabs"])
    for f in m["fabs"]:
        others = [("card", card), ("nav", m["nav"]), ("location dot", m["dot"])] + [(a["name"], a) for a in m["attribution"]] + [(b["name"], b) for b in m["typeBtns"]]
        hits = [n for n, o in others if overlap(f, o)]
        check(f"{tag}: '{f['name']}' overlaps nothing", not hits, hits)
    box = m["box"]
    inside = m["dot"] and m["dot"]["x"] >= box["x"] and m["dot"]["r"] <= box["r"] and m["dot"]["y"] >= box["y"] and m["dot"]["b"] <= box["b"]
    if "sheet" in tag:
        # The sheet centres the map on the place, so the dot can be off the map; on the map it must not be hidden.
        check(f"{tag}: location dot not hidden by the sheet or mic", not inside or m["dotHit"], m["dot"])
    else:
        check(f"{tag}: location dot visible", inside and m["dotHit"], m["dot"])


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=False)
    for w, h, dark in [(320, 640, False), (360, 740, False), (390, 844, False), (360, 740, True)]:
        tag = f"{w}x{h}{' dark' if dark else ''}"
        name = tag.replace(" ", "-")
        ctx, page = open_page(browser, w, h, dark)
        page.goto(f"{args.base}/map", wait_until="domcontentloaded")
        page.wait_for_selector(".map-places-overlay [role=button]", timeout=30000)
        page.wait_for_selector(".gm-style .gm-style-cc", timeout=30000)
        page.wait_for_timeout(4000)
        m = page.evaluate(MEASURE)
        if OUT:
            page.screenshot(path=str(OUT / f"{args.label}-map-{name}.png"))
            (OUT / f"{args.label}-map-{name}.json").write_text(json.dumps(m, indent=1))
        check_map(m, tag)
        # The selected-place sheet (a card tap): a taller card, same rules.
        page.evaluate("document.querySelector('.vg-pin')?.dispatchEvent(new MouseEvent('click', {bubbles: true}))")
        page.wait_for_timeout(1800)
        if page.locator(".map-selected-sheet").count():
            m2 = page.evaluate(MEASURE)
            if OUT:
                page.screenshot(path=str(OUT / f"{args.label}-map-sheet-{name}.png"))
            check_map(m2, tag + " sheet")
        else:
            print(f"NOTE {tag}: the pin sheet did not open in this run; sheet not checked", flush=True)
        ctx.close()

    # Landscape phone and desktop: the card lies over a full map and ends above the strip.
    for w, h in [(740, 360), (1280, 800)]:
        tag = f"{w}x{h}"
        ctx, page = open_page(browser, w, h)
        page.goto(f"{args.base}/map", wait_until="domcontentloaded")
        page.wait_for_selector(".map-places-overlay [role=button]", timeout=30000)
        page.wait_for_selector(".gm-style .gm-style-cc", timeout=30000)
        page.wait_for_timeout(4000)
        m = page.evaluate(MEASURE)
        if OUT:
            page.screenshot(path=str(OUT / f"{args.label}-map-{tag}.png"))
        check_map(m, tag, portrait=False)
        ctx.close()

    for w, h, dark in [(360, 740, False), (390, 844, False), (360, 740, True)]:
        tag = f"{w}x{h}{' dark' if dark else ''}"
        ctx, page = open_page(browser, w, h, dark)
        page.goto(f"{args.base}/", wait_until="domcontentloaded")
        page.wait_for_selector("article", timeout=30000)
        page.wait_for_timeout(1500)
        loc = page.locator("[data-places-attribution]")
        if OUT:
            page.locator("article").first.scroll_into_view_if_needed()
            page.evaluate("(document.querySelector('[data-places-attribution]') || document.querySelector('article')).scrollIntoView({block: 'center'})")
            page.wait_for_timeout(400)
            page.screenshot(path=str(OUT / f"{args.label}-home-{tag.replace(' ', '-')}.png"))
        n = loc.count()
        check(f"home {tag}: one 'Places data: Google Maps' line", n == 1 and "Places data: Google Maps" in loc.first.inner_text(), n)
        if n == 1:
            info = loc.first.evaluate("""(el) => { const r = el.getBoundingClientRect(), a = [...document.querySelectorAll('article')].pop().getBoundingClientRect(),
              t = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2), s = getComputedStyle(el);
              return { below: r.top >= a.bottom - 1, visible: !!t && el.contains(t), size: parseFloat(s.fontSize), opacity: Number(s.opacity) }; }""")
            check(f"home {tag}: under the carousel, visible, readable", info["below"] and info["visible"] and info["size"] >= 11 and info["opacity"] == 1, info)
        ctx.close()
    browser.close()

print(f"\n{sum(results)}/{len(results)} passed", flush=True)
sys.exit(0 if all(results) else 1)
