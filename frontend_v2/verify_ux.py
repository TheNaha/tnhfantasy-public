from playwright.sync_api import sync_playwright

def verify_copy_ux():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        # Mock API requests
        page.route("**/api/**", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{}'
        ))

        page.route("**/api/prompts*", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='''{
                "prompts": [
                    {
                        "id": "1",
                        "name": "UX Test Prompt",
                        "text": "This is a test prompt",
                        "category": "Custom",
                        "description": "Test description",
                        "tags": ["test"],
                        "createdAt": "2024-03-04T12:00:00Z",
                        "favorite": false,
                        "usageCount": 0
                    }
                ],
                "categories": ["All", "Custom"]
            }'''
        ))

        try:
            print("Navigating...")
            page.goto("http://localhost:5174/create")

            # Wait for content
            print("Waiting for page content...")
            # Wait for main container
            page.wait_for_selector('h1:has-text("Create")', timeout=20000)

            # Click "Library" button
            print("Opening Library...")

            # Use specific aria-label selector as primary
            if page.is_visible('button[aria-label="Open prompt library"]'):
                page.click('button[aria-label="Open prompt library"]')
            else:
                # Fallback to visual text search if aria-label fails or changed
                # Look for "Library" text in buttons
                page.click('button:has-text("Library")')

            # Wait for modal
            print("Waiting for modal...")
            page.wait_for_selector('text=Prompt Library', timeout=10000)

            # Wait for mock prompt
            print("Waiting for test prompt...")
            page.wait_for_selector('h3:has-text("UX Test Prompt")', timeout=10000)

            # Find the card
            print("Finding card...")
            card = page.locator('.group', has=page.locator('h3', has_text='UX Test Prompt')).first

            # Find copy button
            print("Clicking copy button...")
            copy_btn = card.locator('button[title="Copy to clipboard"]')

            # Click it
            copy_btn.click()

            # Verify "Copied!" state
            print("Verifying Copied state...")
            copied_btn = card.locator('button[title="Copied!"]')
            copied_btn.wait_for(state="visible", timeout=5000)

            # Verify class for green color
            classes = copied_btn.get_attribute("class")
            if "text-green-400" in classes:
                print("SUCCESS: Button turned green!")
            else:
                print(f"FAILURE: Button did not turn green. Classes: {classes}")

            page.screenshot(path="frontend_v2/verification_copy_success.png")
            print("Screenshot saved to frontend_v2/verification_copy_success.png")

        except Exception as e:
            print(f"Error: {e}")
            page.screenshot(path="frontend_v2/error_state.png")
            print("Error screenshot saved to frontend_v2/error_state.png")
            # Dump page content for debugging
            with open("frontend_v2/error_page.html", "w") as f:
                f.write(page.content())
        finally:
            browser.close()

if __name__ == "__main__":
    verify_copy_ux()
