import os, sys
from playwright.sync_api import sync_playwright

pairs = list(zip(sys.argv[1::2], sys.argv[2::2]))
with sync_playwright() as p:
    b = p.chromium.launch(
        executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    for html, out in pairs:
        pg = b.new_page(viewport={"width": 1056, "height": 816})
        pg.goto("file://" + os.path.abspath(html))
        pg.wait_for_function("window._map !== undefined")
        pg.wait_for_timeout(2500)
        pg.pdf(path=out, landscape=True, print_background=True,
               margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
        pg.screenshot(path=out.replace(".pdf", ".png"))
        pg.close()
        print("pdf ->", out)
    b.close()
