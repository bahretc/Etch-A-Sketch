import sys
from playwright.sync_api import sync_playwright

html, out = sys.argv[1], sys.argv[2]
with sync_playwright() as p:
    b = p.chromium.launch(
        executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    pg = b.new_page(viewport={"width": 1056, "height": 816})
    pg.goto(f"file://{html}")
    pg.wait_for_function("window._map !== undefined")
    pg.wait_for_timeout(2500)
    pg.pdf(path=out, landscape=True, print_background=True,
           margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
    b.close()
print("pdf ->", out)
