async def run_test(page, output_dir, page_url):
    import traceback
    try:
        await page.set_viewport_size({"width":1920,"height":1080})
        await page.wait_for_timeout(5000)
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(3000)
        print("URL after ticket:", page.url)
        await page.locator('[data-testid="nav-dashboard"]').wait_for(timeout=15000)
        print("PASS: authenticated AppShell and dashboard navigation loaded")
        dashboard_text = await page.locator('body').inner_text()
        assert "Dashboard" in dashboard_text
        print("Dashboard text present")
        navs = [
          ("nav-resumes", "Resume & Role Profiles"),
          ("nav-contacts", "HR Contacts"),
          ("nav-opportunities", "Job Opportunities"),
          ("nav-generator", "AI Email Generator"),
          ("nav-queue", "Application Queue"),
          ("nav-tracker", "Application Tracker"),
          ("nav-gmail", "Gmail Integration"),
          ("nav-settings", "Settings"),
        ]
        for testid, label in navs:
            el = page.locator(f'[data-testid="{testid}"]')
            await el.scroll_into_view_if_needed()
            await el.click()
            await page.wait_for_timeout(800)
            title = page.locator('[data-testid="page-title"]')
            await title.wait_for(timeout=5000)
            actual = await title.inner_text()
            if label not in actual:
                print(f"FINDING: {testid} title was {actual!r}, expected {label!r}")
            else:
                print(f"PASS: {label} page loaded")
        # Return to roles and verify dialog opens
        roles = page.locator('[data-testid="nav-resumes"]')
        await roles.scroll_into_view_if_needed(); await roles.click(); await page.wait_for_timeout(700)
        create = page.locator('[data-testid="create-role-button"]')
        await create.scroll_into_view_if_needed(); await create.click()
        await page.locator('[data-testid="role-dialog"]').wait_for(timeout=5000)
        await page.locator('[data-testid="role-title-input"]').fill("TEST_UI_ROLE")
        print("PASS: role creation dialog opens and accepts input")
        await page.locator('[data-testid="role-cancel-button"]').click()
        # Error scan
        error_text = await page.evaluate("""() => {
          const errorElements = Array.from(document.querySelectorAll('.error, [class*="error"], [id*="error"]'));
          return errorElements.map(el => el.textContent).join(', ');
        }""")
        if error_text:
            print(f"Found error message: {error_text}")
        else:
            print("No error messages found on authenticated pages")
        print("AUTH NAVIGATION TEST COMPLETE")
    except AssertionError as e:
        print(f"FINDING: authenticated assertion failed: {e}")
        traceback.print_exc()
    except Exception as e:
        print(f"FINDING: authenticated flow failed: {e}")
        traceback.print_exc()
