import sys
import time

from playwright.sync_api import sync_playwright

URL = "https://marketsector.streamlit.app/"
WAKE_TEXT = "get this app back up"
HOLD_SECONDS = 30
BOOT_TIMEOUT = 180


def app_frame(page):
    for fr in page.frames:
        try:
            if fr.locator('[data-testid="stApp"]').count() > 0:
                return fr
        except Exception:
            pass
    return None


def wake_button(page):
    for fr in page.frames:
        try:
            btn = fr.get_by_role("button", name=WAKE_TEXT, exact=False)
            if btn.count() > 0:
                return btn.first
            btn = fr.get_by_text(WAKE_TEXT, exact=False)
            if btn.count() > 0:
                return btn.first
        except Exception:
            pass
    return None


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)

        woke = False
        deadline = time.time() + BOOT_TIMEOUT
        frame = None
        while time.time() < deadline:
            frame = app_frame(page)
            if frame:
                break
            btn = wake_button(page)
            if btn and not woke:
                print("App was hibernating - clicking wake button")
                btn.click()
                woke = True
            time.sleep(3)

        if not frame:
            print("FAIL: dashboard never rendered and no wake button handled")
            page.screenshot(path="ping_failure.png", full_page=True)
            browser.close()
            return 1

        print(f"App is up (woke={woke}); holding session {HOLD_SECONDS}s")
        time.sleep(HOLD_SECONDS)
        browser.close()
        return 0


if __name__ == "__main__":
    sys.exit(main())
