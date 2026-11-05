async def run_test(page, output_dir, page_url):
    import traceback
    try:
        await page.set_viewport_size({"width": 1920, "height": 1080})
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(2000)
        title = await page.title()
        print(f"Page title: {title}")
        assert await page.locator('body').is_visible()
        sign_in = page.locator('text=Sign in').first
        await sign_in.wait_for(timeout=10000)
        print("Sign-in UI loaded")
        await page.screenshot(path="/app/test_reports/screenshots/automation_output/20261104_181555_50a7d61e699c/sign-in.jpeg", type="jpeg", quality=40, full_page=False)
        error_text = await page.evaluate("""() => {
          const errorElements = Array.from(document.querySelectorAll('.error, [class*="error"], [id*="error"]'));
          return errorElements.map(el => el.textContent).join(', ');
        }""")
        if error_text:
            print(f"Found error message: {error_text}")
        else:
            print("No error messages found on the page")
        print("PASS: sign-in render")
    except AssertionError as e:
        print(f"FINDING: sign-in assertion failed: {e}")
        traceback.print_exc()
    except Exception as e:
        print(f"FINDING: sign-in flow failed: {e}")
        traceback.print_exc()
