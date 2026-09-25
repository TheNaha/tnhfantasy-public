import os
from playwright.sync_api import sync_playwright

SCREENSHOT_DIR = os.environ.get("VERIFY_SCREENSHOT_DIR", "/tmp/verification/screenshots")
VIDEO_DIR = os.environ.get("VERIFY_VIDEO_DIR", "/tmp/verification/videos")
VERIFY_URL = os.environ.get("VERIFY_URL", "http://localhost:5174/advanced")


def run_cuj(page):
    page.goto(VERIFY_URL, wait_until="domcontentloaded")
    page.locator("h1").first.wait_for(state="visible")
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    page.screenshot(path=os.path.join(SCREENSHOT_DIR, "verification.png"), full_page=True)


def main():
    os.makedirs(VIDEO_DIR, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            record_video_dir=VIDEO_DIR,
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()
        try:
            run_cuj(page)
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
