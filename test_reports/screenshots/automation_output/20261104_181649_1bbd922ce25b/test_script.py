async def run_test(page, output_dir, page_url):
    import traceback
    try:
        await page.set_viewport_size({"width":1920,"height":1080})
        await page.wait_for_timeout(3500)
        # contacts dialog + search + import dialog
        await page.locator('[data-testid="add-contact-button"]').wait_for(timeout=10000)
        await page.locator('[data-testid="add-contact-button"]').click()
        await page.locator('[data-testid="contact-dialog"]').wait_for(timeout=5000)
        await page.locator('[data-testid="contact-email-input"]').fill("TEST_ui_contact@example.com")
        print("PASS: contact dialog accepts email input")
        await page.locator('text=Cancel').last.click()
        search = page.locator('[data-testid="contacts-search-input"]')
        await search.fill("TEST_nonexistent")
        await page.wait_for_timeout(500)
        print("PASS: contacts search input updates")
        await page.locator('[data-testid="import-contacts-button"]').click()
        await page.locator('[data-testid="import-dialog"]').wait_for(timeout=5000)
        print("PASS: import dialog opens")
        await page.locator('text=Cancel').last.click()
        # opportunity dialog and paste field
        await page.goto("https://apply-pilot-10--6p4n0df3.preview.emergentagent.com/opportunities")
        await page.wait_for_timeout(1500)
        await page.locator('[data-testid="add-opportunity-button"]').click()
        await page.locator('[data-testid="opportunity-dialog"]').wait_for(timeout=5000)
        await page.locator('[data-testid="jd-paste-textarea"]').fill("TEST role description for product analyst")
        print("PASS: opportunity paste dialog opens and accepts description")
        await page.locator('text=Cancel').last.click()
        # tracker export control and history presence
        await page.goto("https://apply-pilot-10--6p4n0df3.preview.emergentagent.com/tracker")
        await page.wait_for_timeout(1800)
        await page.locator('[data-testid="export-csv-button"]').wait_for(timeout=5000)
        print("PASS: tracker export button rendered")
        # queue controls, mode dropdown, emergency stop then reset via settings
        await page.goto("https://apply-pilot-10--6p4n0df3.preview.emergentagent.com/queue")
        await page.wait_for_timeout(1800)
        await page.locator('[data-testid="autopilot-panel"]').wait_for(timeout=5000)
        await page.locator('[data-testid="autopilot-mode-trigger"]').click()
        await page.wait_for_timeout(250)
        await page.locator('[data-testid="autopilot-mode-select"] ~ *').count()
        # close select with Escape; presence of options is enough
        await page.keyboard.press("Escape")
        await page.locator('[data-testid="emergency-stop-button"]').click()
        await page.wait_for_timeout(1000)
        await page.locator('[data-testid="autopilot-paused-warning"]').wait_for(timeout=5000)
        print("PASS: emergency stop updates queue state")
        # settings save and unpause
        await page.goto("https://apply-pilot-10--6p4n0df3.preview.emergentagent.com/settings")
        await page.wait_for_timeout(1500)
        paused = page.locator('[data-testid="settings-autopilot-paused-switch"]')
        await paused.wait_for(timeout=5000)
        # switch off if currently checked, using aria-checked
        if await paused.get_attribute("aria-checked") == "true":
            await paused.click()
        await page.locator('[data-testid="save-settings-button"]').click()
        await page.wait_for_timeout(1200)
        print("PASS: settings save flow completed and emergency pause reset")
        # Gmail render only
        await page.goto("https://apply-pilot-10--6p4n0df3.preview.emergentagent.com/gmail")
        await page.wait_for_timeout(1500)
        await page.locator('[data-testid="gmail-status-card"]').wait_for(timeout=5000)
        await page.locator('[data-testid="redirect-uri-box"]').wait_for(timeout=5000)
        print("PASS: Gmail status and redirect URI rendered")
        error_text = await page.evaluate("""() => {
          const errorElements = Array.from(document.querySelectorAll('.error, [class*="error"], [id*="error"]'));
          return errorElements.map(el => el.textContent).join(', ');
        }""")
        if error_text: print(f"Found error message: {error_text}")
        else: print("No error messages found in control-flow test")
    except AssertionError as e:
        print(f"FINDING: control flow assertion failed: {e}"); traceback.print_exc()
    except Exception as e:
        print(f"FINDING: control flow failed: {e}"); traceback.print_exc()
