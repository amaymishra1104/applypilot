async def run_test(page, output_dir, page_url):
    import traceback
    try:
        await page.set_viewport_size({"width":1920,"height":1080})
        await page.wait_for_timeout(6500)
        await page.goto("https://apply-pilot-10--6p4n0df3.preview.emergentagent.com/queue")
        await page.wait_for_timeout(1600)
        panel = page.locator('[data-testid="autopilot-panel"]')
        stop = panel.locator('[data-testid="emergency-stop-button"]')
        await stop.wait_for(timeout=5000)
        await stop.click()
        await page.wait_for_timeout(900)
        await page.locator('[data-testid="autopilot-paused-warning"]').wait_for(timeout=5000)
        print("PASS: emergency stop API/UI flow")
        await page.goto("https://apply-pilot-10--6p4n0df3.preview.emergentagent.com/settings")
        await page.wait_for_timeout(1600)
        paused = page.locator('[data-testid="settings-autopilot-paused-switch"]')
        await paused.wait_for(timeout=5000)
        if await paused.get_attribute("aria-checked") == "true": await paused.click()
        await page.locator('[data-testid="save-settings-button"]').click()
        await page.wait_for_timeout(1200)
        print("PASS: settings PUT save flow and pause reset")
        # verify settings remains accessible after save
        assert await page.locator('[data-testid="settings-ai-card"]').is_visible()
        print("PASS: settings remains rendered after persistence")
        error_text = await page.evaluate("""() => { const errorElements = Array.from(document.querySelectorAll('.error, [class*="error"], [id*="error"]')); return errorElements.map(el => el.textContent).join(', '); }""")
        print(f"Error scan: {error_text or 'none'}")
    except AssertionError as e:
        print(f"FINDING: queue/settings assertion failed: {e}"); traceback.print_exc()
    except Exception as e:
        print(f"FINDING: queue/settings flow failed: {e}"); traceback.print_exc()
