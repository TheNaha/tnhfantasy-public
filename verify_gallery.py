
import os
import sys
import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()

        # Navigate to the dashboard
        try:
            # Check if port 5174 is active (Vite default)
            await page.goto("http://localhost:5174", timeout=10000)
            print("Navigated to http://localhost:5174")
        except:
            print("Could not navigate to localhost:5174. Please ensure the server is running.")
            await browser.close()
            return

        # Wait for the gallery to load
        try:
            await page.wait_for_selector("text=Gallery", timeout=10000)
            print("Gallery header found.")
        except:
            print("Gallery header not found.")

        # Take a screenshot of the grid view
        os.makedirs("verification", exist_ok=True)
        await page.screenshot(path="verification/gallery_grid.png")
        print("Screenshot saved to verification/gallery_grid.png")

        # Switch to Timeline View
        try:
            # Click the timeline view button (4th button in the view mode selector)
            # The buttons are: Grid, List, Feed, Timeline
            # We can target by title attribute
            await page.click('button[title="Timeline View - Chronological history"]')
            print("Clicked Timeline View button.")

            # Wait for timeline element (either content or empty state)
            try:
                await page.wait_for_selector("text=End of timeline", timeout=5000)
            except:
                await page.wait_for_selector("text=No items in timeline", timeout=5000)

            await page.screenshot(path="verification/gallery_timeline.png")
            print("Screenshot saved to verification/gallery_timeline.png")

        except Exception as e:
            print(f"Error switching to timeline view: {e}")
            await page.screenshot(path="verification/gallery_timeline_error.png")
            print("Error screenshot saved to verification/gallery_timeline_error.png")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
