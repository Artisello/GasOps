"""Manual browser smoke check against a running local GasOps app.

Dev dependency only: pip install playwright. Use an installed Chromium/Chrome
via --chrome, or Playwright's Chromium. No production dependency is added.
All outbound browser requests are blocked; no source refresh button is used.
"""
import argparse
import json
import math
from pathlib import Path


def project(box, position, camera):
    lon, lat = position
    mercator = lambda latitude: math.log(math.tan(math.pi/4+math.radians(latitude)/2))
    scale = 512*2**camera["zoom"]
    return (box["x"]+box["width"]/2+scale*(lon-camera["longitude"])/360,
            box["y"]+box["height"]/2-scale*(mercator(lat)-mercator(camera["latitude"]))/ (2*math.pi))


def main():
    from playwright.sync_api import sync_playwright, expect
    from gasops_app.italian_network_map import fit_italy
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8766")
    parser.add_argument("--chrome", type=Path)
    parser.add_argument("--output", type=Path, default=Path("/tmp/igor-map-browser"))
    args = parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    features = json.loads((root/"data/italian-network/infrastructure.geojson").read_text())["features"]
    geometry = {f["id"]:f["geometry"] for f in features}
    boundary = json.loads((root/"data/italian-network/italy.geojson").read_text())
    report = {"viewports":[],"blocked":[],"errors":[]}
    with sync_playwright() as p:
        launch = {"headless":True,"args":["--use-angle=swiftshader","--enable-unsafe-swiftshader"]}
        if args.chrome:
            launch["executable_path"] = str(args.chrome)
        browser = p.chromium.launch(**launch)
        def new_page(width,height):
            context = browser.new_context(viewport={"width":width,"height":height})
            page = context.new_page()
            page.on("pageerror",lambda error:report["errors"].append(str(error)))
            def gate(route):
                if route.request.url.startswith((args.url,"data:","blob:")):
                    route.continue_()
                else:
                    report["blocked"].append(route.request.url)
                    route.abort()
            page.route("**/*",gate)
            page.goto(args.url)
            expect(page.locator("#deckgl-overlay")).to_be_visible(timeout=30000)
            page.wait_for_function('document.querySelector("[data-testid=stApp]").dataset.testScriptState === "notRunning"')
            page.wait_for_timeout(1800)  # Viewport measurement and software WebGL shader warmup.
            return page,context
        def check_layout(page,width):
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"),"Horizontal overflow"
            assert not page.locator('[data-testid="stException"]').count()
            assert page.locator("#deckgl-overlay").evaluate("e=>!!e.getContext('webgl2')"),"WebGL2 unavailable"
            map_box = page.locator("#deckgl-overlay").bounding_box()
            title_box = page.locator("h1").first.bounding_box()
            assert map_box["y"] >= title_box["y"]+title_box["height"]+6,"Title descenders overlap the map"
            detail_box = page.locator(".st-key-network_home_detail").bounding_box()
            if width > 1100:
                assert detail_box["x"] >= map_box["x"]+map_box["width"],"Detail must be right of map"
            else:
                assert detail_box["y"] >= map_box["y"]+map_box["height"],"Map must precede detail"
            # No geographic city names; operational names remain visible.
            assert not page.locator(".gas-map-legend").filter(has_text="Roma").count()
            report["viewports"].append({"width":width,"map":map_box,"detail":detail_box})
        page,context = new_page(1440,1000)
        check_layout(page,1440)
        page.screenshot(path=str(args.output/"desktop.png"),full_page=True)
        box = page.locator("#deckgl-overlay").bounding_box()
        camera = fit_italy(boundary,box["width"],box["height"])
        def click_at(position,label):
            page.bring_to_front()
            x,y = project(box,position,camera)
            page.mouse.move(x-20,y,steps=6)
            page.mouse.move(x,y,steps=6)
            expect(page.locator(".deck-tooltip")).to_contain_text(label,timeout=15000)
            page.wait_for_timeout(500)
            page.mouse.click(x,y,delay=120)
            expect(page.locator(".st-key-network_home_detail h3")).to_have_text(label,timeout=15000)
        click_at(geometry["INET_BP_89"]["coordinates"],"Tarvisio")
        a,b = geometry["INET_PL_5"]["coordinates"]
        click_at([(a[0]+b[0])/2,(a[1]+b[1])/2],"Alessandria – Cortemaggiore")
        before = page.locator("#deckgl-overlay").screenshot()
        page.mouse.move(box["x"]+box["width"]*.5,box["y"]+box["height"]*.5)
        page.mouse.wheel(0,-200)
        page.wait_for_timeout(600)
        page.mouse.down()
        page.mouse.move(box["x"]+box["width"]*.5+35,box["y"]+box["height"]*.5+20,steps=8)
        page.mouse.up()
        page.wait_for_timeout(600)
        assert before != page.locator("#deckgl-overlay").screenshot(),"Pan/zoom did not change map"
        expect(page.locator(".st-key-network_home_detail h3")).to_have_text("Alessandria – Cortemaggiore")
        page.screenshot(path=str(args.output/"desktop-selected.png"),full_page=True)
        page.get_by_role("button",name="Esplora la rete",exact=True).click()
        expect(page.locator(".st-key-network_detail h3")).to_have_text("Alessandria – Cortemaggiore",timeout=30000)
        period = page.locator('[data-testid="stDateInput"] input').evaluate_all('(inputs)=>inputs.map(e=>e.value).join(" – ")')
        assert any(d in period for d in ("14/11/2026","2026-11-14")) and any(d in period for d in ("20/11/2026","2026-11-20")),"Period transfer failed: "+period
        combo = page.locator(".st-key-network_detail").get_by_role("combobox").first
        combo.fill("Tarvisio")
        combo.press("Enter")
        expect(page.locator(".st-key-network_detail h3")).to_have_text("Tarvisio",timeout=15000)
        chart = page.locator(".st-key-network_detail .js-plotly-plot").first
        expect(chart).to_be_visible(timeout=15000)
        ticks = chart.locator(".xtick text")
        assert ticks.count() >= 2,"Date labels missing"
        bounds = chart.bounding_box()
        for tick in ticks.all():
            r = tick.bounding_box()
            assert r["y"]+r["height"] <= bounds["y"]+bounds["height"],"Date label clipped"
        chart.screenshot(path=str(args.output/"history.png"))
        page.screenshot(path=str(args.output/"desktop-full.png"),full_page=True)
        page.get_by_role("link",name="Panoramica",exact=True).click()
        expect(page.locator(".st-key-network_home_detail h3")).to_have_text("Tarvisio",timeout=30000)
        context.close()
        for width,height in [(820,1180),(390,844),(375,812)]:
            page,context = new_page(width,height)
            check_layout(page,width)
            page.screenshot(path=str(args.output/f"viewport-{width}.png"),full_page=True)
            context.close()
        browser.close()
    assert not report["errors"],report["errors"]
    assert not any(any(host in url for host in ("cartocdn","mapbox.com","entsog","gie.eu","openstreetmap"))
                   for url in report["blocked"]),"Map tried to reach an external data or tile service"
    (args.output/"checks.json").write_text(json.dumps(report,indent=2))
    print("PASS: offline WebGL, point/pipe clicks, tooltip, pan/zoom, navigation, keyboard selection, date axis, four viewports")


if __name__ == "__main__":
    main()
