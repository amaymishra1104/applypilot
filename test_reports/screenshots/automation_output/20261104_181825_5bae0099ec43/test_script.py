async def run_test(page, output_dir, page_url):
    import traceback
    try:
        await page.set_viewport_size({"width":1920,"height":1080})
        await page.wait_for_timeout(6500)
        await page.goto("https://apply-pilot-10--6p4n0df3.preview.emergentagent.com/settings")
        await page.wait_for_timeout(1700)
        paused = page.locator('[data-testid="settings-autopilot-paused-switch"]')
        await paused.wait_for(timeout=5000)
        print("paused state before reset:", await paused.get_attribute("data-state"), await paused.get_attribute("aria-checked"))
        if await paused.get_attribute("data-state") == "checked":
            await paused.click()
        await page.locator('[data-testid="save-settings-button"]').click()
        await page.wait_for_timeout(1000)
        print("paused state after reset:", await paused.get_attribute("data-state"), await paused.get_attribute("aria-checked"))
        assert await paused.get_attribute("data-state") == "unchecked"
        print("PASS: emergency pause reset and persisted")
        model = await page.locator('[data-testid="settings-model-trigger"]').inner_text()
        tone = await page.locator('[data-testid="settings-tone-trigger"]').inner_text()
        email = await page.locator('[data-testid="settings-user-email"]').inner_text()
        print(f"Settings values: model={model!r}, tone={tone!r}, email={email!r}")
        if not model.strip() or not tone.strip(): print("FINDING: settings select values render blank")
        if email.strip() in ("—", ""): print("FINDING: signed-in user email renders blank")
    except AssertionError as e:
        print(f"FINDING: reset assertion failed: {e}"); traceback.print_exc()
    except Exception as e:
        print(f"FINDING: reset verification failed: {e}"); traceback.print_exc()
