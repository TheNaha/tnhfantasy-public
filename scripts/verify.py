import re
from playwright.sync_api import sync_playwright

def run_cuj(page):
    # Navigate to Advanced Generate page, which renders QueueVisualization inside GenerateLayout
    page.goto("http://localhost:5174/generate/advanced")
    page.wait_for_timeout(2000)

    page.evaluate("""
        () => {
            localStorage.setItem('job-storage', JSON.stringify({
                state: {
                    activeJobs: [
                        { id: '1', status: 'running', progress: 45, prompt: 'Running Job 1' },
                        { id: '2', status: 'running', progress: 12, prompt: 'Running Job 2' },
                        { id: '3', status: 'pending', queue_position: 1, prompt: 'Pending Job 1' },
                        { id: '4', status: 'pending', queue_position: 2, prompt: 'Pending Job 2' }
                    ],
                    history: [],
                    queuePosition: 2
                },
                version: 1
            }));
            window.location.reload();
        }
    """)
    page.wait_for_timeout(2000)

    # Let's just take a screenshot and see what rendered on the advanced page
    page.screenshot(path="/home/jules/verification/screenshots/verification.png")
    page.wait_for_timeout(1000)

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            record_video_dir="/home/jules/verification/videos",
            viewport={'width': 1280, 'height': 800}
        )
        page = context.new_page()
        try:
            run_cuj(page)
        finally:
            context.close()
            browser.close()
