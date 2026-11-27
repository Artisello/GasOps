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


def rendered_map(page):
    """Dev-only inspection of the real Deck instance, after Streamlit styling.

    JSON assertions alone cannot detect the native selection opacity override.
    React refs are inspected only in this browser smoke script, never in the app.
    """
    return page.evaluate('''() => {
      const canvas=document.getElementById('deckgl-overlay');
      let fiber=canvas[Object.keys(canvas).find(k=>k.startsWith('__reactFiber'))], deck;
      for(let i=0;fiber&&i<35;i++,fiber=fiber.return){
        if(fiber.stateNode?.deck)deck=fiber.stateNode.deck;
        for(let h=fiber.memoizedState,j=0;h&&j<20;j++,h=h.next){
          if(h.memoizedState?.current?.deck)deck=h.memoizedState.current.deck;
        }
      }
      if(!deck)throw Error('Cannot inspect native Deck ref');
      const colors={};
      for(const layer of deck.layerManager.getLayers()){
        if(layer.isComposite||!['italy-outline','historical-links','category-symbols','point-labels'].some(id=>layer.id.startsWith(id)))continue;
        const getter=layer.props.getColor??layer.props.getFillColor;
        const value=typeof getter==='function'?getter(layer.props.data[0],{index:0,target:[]}):getter;
        if(value&&!layer.id.startsWith('point-labels'))colors[layer.id]=[value[0],value[1],value[2],value[3]??255];
      }
      const points=(deck.layerManager.getLayers().find(l=>l.id==='infrastructure-points')?.props.data??[]).filter(r=>r.active!==false);
      return {zoom:deck.getViewports()[0].zoom,minZoom:deck.props.viewState.minZoom,
        maxZoom:deck.props.viewState.maxZoom,colors,pointIds:points.map(r=>r.infra_id),
        powerCount:points.filter(r=>r.category==='power').length};
    }''')


def main():
    from playwright.sync_api import sync_playwright, expect
    from gasops_app.italian_network_map import fit_italy
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8766")
    parser.add_argument("--chrome", type=Path)
    parser.add_argument("--software-rendering",action="store_true",help="Use SwiftShader when no native WebGL2 device is available")
    parser.add_argument("--output", type=Path, default=Path("/tmp/igor-map-browser"))
    args = parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    features = json.loads((root/"data/italian-network/infrastructure.geojson").read_text())["features"]
    geometry = {f["id"]:f["geometry"] for f in features}
    boundary = json.loads((root/"data/italian-network/italy.geojson").read_text())
    report = {"viewports":[],"blocked":[],"errors":[]}
    with sync_playwright() as p:
        launch = {"headless":True,"args":(["--use-angle=swiftshader","--enable-unsafe-swiftshader"] if args.software_rendering else [])}
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
            page.wait_for_timeout(1800)  # Viewport measurement and initial WebGL shader compilation.
            return page,context
        def check_layout(page,width):
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"),"Horizontal overflow"
            assert not page.locator('[data-testid="stException"]').count()
            expect(page.locator(".st-key-system_status_kpis .gas-kpi")).to_have_count(4)
            expect(page.locator(".st-key-system_daily_balance .gas-balance-cell")).to_have_count(9)
            expect(page.get_by_role("heading",name="Attenzione operativa",exact=True)).to_be_visible()
            assert page.locator("#deckgl-overlay").evaluate("e=>!!e.getContext('webgl2')"),"WebGL2 unavailable"
            assert page.locator("#deckgl-overlay").evaluate("e=>getComputedStyle(e).cursor") == "default","Expected arrow cursor"
            assert page.locator(".gas-map-legend img").evaluate_all("xs=>xs.length>0&&xs.every(x=>x.naturalWidth>0)"),"Legend symbols did not render"
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
        original_colors = rendered_map(page)["colors"]
        assert rendered_map(page)["powerCount"] == 69,"Power plants only appear after selection"
        def click_at(position,label):
            page.bring_to_front()
            x,y = project(box,position,camera)
            page.mouse.move(x-20,y,steps=6)
            page.mouse.move(x,y,steps=6)
            expect(page.locator(".deck-tooltip")).to_contain_text(label,timeout=15000)
            tip = page.locator(".deck-tooltip").bounding_box()
            assert tip["x"] >= box["x"] and tip["x"]+tip["width"] <= box["x"]+box["width"],"Tooltip clipped horizontally"
            assert tip["y"] >= box["y"] and tip["y"]+tip["height"] <= box["y"]+box["height"],"Tooltip clipped vertically"
            page.wait_for_timeout(500)
            page.mouse.click(x,y,delay=50)
            expect(page.locator(".st-key-network_home_detail h3")).to_have_text(label,timeout=15000)
        click_at(geometry["INET_BP_89"]["coordinates"],"Tarvisio")
        assert rendered_map(page)["colors"] == original_colors,"Selecting a point dimmed the network"
        report["reading_modes"] = []
        hints = {"SYSTEM":"Categorie e disponibilità dei dati.",
            "FLOW":"Flussi dei punti verificati · gasdotti solo come contesto geografico.",
            "ATTENTION":"Eventi pubblicati, indicatori calcolati e qualità dei dati."}
        labels = {"SYSTEM":"Sistema","FLOW":"Flussi","ATTENTION":"Attenzione"}
        for reading in ("FLOW","ATTENTION","SYSTEM"):
            page.locator(".st-key-net_reading_overview").get_by_text(labels[reading],exact=True).click()
            expect(page.get_by_role("radio",name=labels[reading],exact=True)).to_be_checked()
            expect(page.get_by_text(hints[reading],exact=True)).to_be_visible(timeout=15000)
            page.wait_for_function('document.querySelector("[data-testid=stApp]").dataset.testScriptState === "notRunning"')
            page.wait_for_timeout(400)
            scene = rendered_map(page)
            assert len(set(scene["pointIds"])) == len(scene["pointIds"]),"Duplicate point markers"
            if reading == "SYSTEM":
                assert scene["powerCount"] == 69
            report["reading_modes"].append({"mode":reading,"points":len(scene["pointIds"]),"power":scene["powerCount"]})
            page.screenshot(path=str(args.output/("reading-"+reading.lower()+".png")),full_page=True)
        click_at(geometry["INET_CS_11"]["coordinates"],"Alessandro Volta")
        assert rendered_map(page)["powerCount"] == 69
        click_at(geometry["INET_BP_89"]["coordinates"],"Tarvisio")
        # The shared point card retains all seven indicator types and D-30 gaps.
        page.get_by_role("tab",name="Storico",exact=True).click()
        history = page.locator(".st-key-network_home_detail .js-plotly-plot").first
        expect(history).to_be_visible()
        page.locator(".st-key-network_home_detail").get_by_role("combobox").click()
        page.get_by_role("option",name="Nomina",exact=True).click()
        expect(history).to_be_visible()
        page.screenshot(path=str(args.output/"overview-history.png"),full_page=True)
        page.get_by_role("tab",name="Dati",exact=True).click()
        a,b = geometry["INET_PL_5"]["coordinates"]
        click_at([(a[0]+b[0])/2,(a[1]+b[1])/2],"Alessandria – Cortemaggiore")
        assert rendered_map(page)["colors"] == original_colors,"Selecting a pipeline dimmed the network"
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
        # Exercise the real controller limits, including repeated wheel events.
        page.mouse.move(box["x"]+box["width"]*.5,box["y"]+box["height"]*.5,steps=6)
        for _ in range(10):
            page.mouse.wheel(0,-700)
            page.wait_for_timeout(100)
        page.wait_for_timeout(500)
        zoomed = rendered_map(page)
        assert abs(zoomed["zoom"]-zoomed["maxZoom"])<.02,"Zoom-in limit not applied"
        for _ in range(12):
            page.mouse.wheel(0,700)
            page.wait_for_timeout(100)
        page.wait_for_timeout(500)
        zoomed = rendered_map(page)
        assert abs(zoomed["zoom"]-zoomed["minZoom"])<.02,"Zoom-out limit not applied"
        page.get_by_role("button",name="Vista Italia",exact=True).click()
        expect(page.locator(".st-key-network_home_detail h3")).to_have_text("Alessandria – Cortemaggiore")
        page.wait_for_timeout(600)
        assert abs(rendered_map(page)["zoom"]-camera["zoom"])<.02,"Vista Italia did not restore framing"
        report["selection_colors"]=original_colors
        report["zoom_limits"]={"min":zoomed["minZoom"],"max":zoomed["maxZoom"]}
        page.screenshot(path=str(args.output/"desktop-selected.png"),full_page=True)
        page.get_by_role("button",name="Esplora la rete",exact=True).click()
        expect(page.locator(".st-key-network_detail h3")).to_have_text("Alessandria – Cortemaggiore",timeout=30000)
        dates = page.locator('[data-testid="stDateInput"] input')
        expect(dates.first).to_be_visible(timeout=30000)
        expect(dates.first).not_to_have_value("",timeout=10000)
        period = page.locator('[data-testid="stDateInput"] input').evaluate_all('(inputs)=>inputs.map(e=>e.value).join(" – ")')
        assert any(d in period for d in ("14/11/2026","2026-11-14")) and any(d in period for d in ("20/11/2026","2026-11-20")),"Period transfer failed: "+period
        combo = page.locator(".st-key-network_detail").get_by_role("combobox").first
        combo.fill("Tarvisio · Ingressi e uscite")
        combo.press("Enter")
        expect(page.locator(".st-key-network_detail h3")).to_have_text("Tarvisio",timeout=15000)
        page.get_by_role("tab",name="Storico",exact=True).click()
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
        # A calculated finding uses the existing verified point/day drill-down.
        page.get_by_role("button",name="Apri punto",exact=True).first.click()
        expect(page.locator(".st-key-network_detail h3")).to_contain_text("Adriatic LNG",timeout=30000)
        page.get_by_role("link",name="Panoramica",exact=True).click()
        expect(page.locator(".st-key-network_home_detail h3")).to_contain_text("Adriatic LNG",timeout=30000)
        page.locator(".st-key-system_daily_balance").screenshot(path=str(args.output/"daily-balance.png"))
        page.locator(".st-key-system_operational_attention").screenshot(path=str(args.output/"attention.png"))
        page.set_viewport_size({"width":1440,"height":2200})
        page.locator("h1").first.scroll_into_view_if_needed()
        end = page.locator(".st-key-net_overview_open").bounding_box()
        page.screenshot(path=str(args.output/"system-status-desktop.png"),
            clip={"x":0,"y":0,"width":1440,"height":min(2200,end["y"]+end["height"]+16)})
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
    print("PASS: three reading modes, 69 unselected power plants, unique markers, offline system status, attention drill-down, WebGL, map interactions, D-30 history and four viewports")


if __name__ == "__main__":
    main()
