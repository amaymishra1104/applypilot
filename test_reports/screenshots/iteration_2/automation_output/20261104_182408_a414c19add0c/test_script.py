async def run_test(page, output_dir, page_url):
    try:
        await page.set_viewport_size({"width": 1920, "height": 1080})
        results = []
        # Dashboard upcoming interview
        await page.wait_for_selector('[data-testid="upcoming-interviews"]', timeout=8000)
        upcoming = await page.locator('[data-testid="upcoming-interviews"]').inner_text()
        assert 'NovaMesh AI' in upcoming, 'NovaMesh interview missing from dashboard'
        results.append('Dashboard upcoming interview visible')

        # Theme toggle and verify class changes
        before = await page.locator('html').get_attribute('class')
        theme = page.locator('[data-testid="theme-toggle"]')
        await theme.scroll_into_view_if_needed(); await theme.click()
        await page.wait_for_timeout(300)
        after = await page.locator('html').get_attribute('class')
        assert before != after, f'theme class did not change: {before} -> {after}'
        results.append('Theme toggle changed document theme')
        await theme.click(); await page.wait_for_timeout(200)

        # Tracker
        nav_tracker = page.locator('[data-testid="nav-tracker"]')
        await nav_tracker.scroll_into_view_if_needed(); await nav_tracker.click()
        await page.wait_for_selector('[data-testid="history-table"]', timeout=8000)
        row_text = await page.locator('[data-testid="history-row"]').first.inner_text()
        assert 'NovaMesh AI' in row_text and 'interview' in row_text.lower(), 'NovaMesh interview row missing'
        results.append('Tracker NovaMesh interview row visible')
        schedule = page.locator('[data-testid^="schedule-interview-"]').first
        await schedule.scroll_into_view_if_needed(); await schedule.click()
        await page.wait_for_selector('[data-testid="interview-dialog"]', timeout=3000)
        assert await page.locator('[data-testid="interview-datetime-input"]').input_value(), 'existing interview datetime not populated'
        results.append('Interview dialog opens with existing datetime')

        # Empty datetime validation
        dt = page.locator('[data-testid="interview-datetime-input"]')
        await dt.fill('')
        save = page.locator('[data-testid="interview-save-button"]')
        await save.scroll_into_view_if_needed(); await save.click()
        await page.wait_for_timeout(500)
        assert await page.locator('[data-testid="interview-dialog"]').is_visible(), 'dialog closed on empty datetime'
        toast_text = await page.locator('body').inner_text()
        assert 'Pick a date and time' in toast_text, 'empty datetime validation toast missing'
        results.append('Empty datetime validation blocks save')

        # Restore datetime and edit notes, save
        existing = '2026-11-04T20:22'
        await dt.fill(existing)
        notes = page.locator('[data-testid="interview-notes-input"]')
        await notes.fill('Technical round 2 - Google Meet')
        await save.click(); await page.wait_for_timeout(1200)
        assert not await page.locator('[data-testid="interview-dialog"]').is_visible(), 'dialog did not close after save'
        results.append('Interview datetime/notes save completed')

        # Settings card, change and persist; reload verifies displayed persisted value
        nav_settings = page.locator('[data-testid="nav-settings"]')
        await nav_settings.scroll_into_view_if_needed(); await nav_settings.click()
        await page.wait_for_selector('[data-testid="settings-interviews-card"]', timeout=8000)
        hours = page.locator('[data-testid="settings-interview-reminder-hours"]')
        await hours.fill('25')
        save_settings = page.locator('[data-testid="save-settings-button"]')
        await save_settings.scroll_into_view_if_needed(); await save_settings.click(); await page.wait_for_timeout(1000)
        assert await hours.input_value() == '25', 'settings input did not retain saved value'
        await page.reload(); await page.wait_for_selector('[data-testid="settings-interview-reminder-hours"]', timeout=8000)
        assert await page.locator('[data-testid="settings-interview-reminder-hours"]').input_value() == '25', 'reminder hours did not persist after reload'
        assert await page.locator('[data-testid="settings-notif-interview_reminder"]').count() == 1, 'interview reminder notification toggle missing'
        results.append('Interview reminder settings persisted after reload')

        # All nine sidebar routes load without visible error state
        routes = ['nav-dashboard','nav-resumes','nav-contacts','nav-opportunities','nav-generator','nav-queue','nav-tracker','nav-gmail','nav-settings']
        for testid in routes:
            link = page.locator(f'[data-testid="{testid}"]')
            await link.scroll_into_view_if_needed(); await link.click(); await page.wait_for_timeout(500)
            assert await page.locator('[data-testid="page-title"]').count() == 1, f'page title missing on {testid}'
            results.append(testid + ' loaded')

        # Specific error selector scan required by playbook
        error_text = await page.evaluate("""() => {
          const errorElements = Array.from(document.querySelectorAll('.error, [class*="error"], [id*="error"]'));
          return errorElements.map(el => el.textContent).join(", ");
        }""")
        if error_text:
            print('Found error message:', error_text)
        else:
            print('No error messages found on the page')
        print('PASS RESULTS:', results)
    except AssertionError as e:
        print('FINDING:', str(e))
    except Exception as e:
        print('SCRIPT ERROR:', str(e))
        raise
