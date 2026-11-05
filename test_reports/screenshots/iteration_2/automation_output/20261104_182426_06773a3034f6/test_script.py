async def run_test(page, output_dir, page_url):
    try:
        ticket = 'eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJlaXMiOjYwMCwiZXhwIjoxNzkzODE3MjI3LCJpaWQiOiJpbnNfM0xlV1VPOU5JN3FZcXUxTVBGRDB6VDlmcHdaIiwic2lkIjoic2l0XzNMZVpqSTNtYVdaTElKN21MUXBrTkFZRmE5SyIsInN0Ijoic2lnbl9pbl90b2tlbiJ9.eT8qvHoaQ9AuuLa73jsr-8aaANpu_lMDKZuy34g4hHk6QyvINcfWYHq54edtO-EO6aisdHp3e5I2GWdpPfjihhGwopoSnaTIIpqHyXfxS08NPKlJu1nr9KMGXRdJC7jUbhwpDM63RVL83m6OpCLiMUpZbzneGDsbBQ8RuSIjSlQcr76NgNSxXxQFTEZHn0x7sItxXUesSut-1w9cvXmqL4LWcPWem94gaZa9qkB7q5-qQAzvA5etxM3SO_Idq61feCg8-p0XHr37D2ECAlQdZnUuS7rPJcGUmCk4PoqnZNBNifKZ_LCJ5bLMYV0SSoZLijW2OHXh9gxOuLLr72LWOA'
        await page.goto('https://apply-pilot-10--6p4n0df3.preview.emergentagent.com/sign-in?__clerk_ticket=' + ticket, wait_until='domcontentloaded', timeout=20000)
        await page.wait_for_selector('[data-testid="page-title"]', timeout=10000)
        results = []
        upcoming = page.locator('[data-testid="upcoming-interviews"]')
        await upcoming.scroll_into_view_if_needed(); text = await upcoming.inner_text()
        assert 'NovaMesh AI' in text, 'NovaMesh interview missing from dashboard'
        results.append('Dashboard upcoming interview visible')
        theme = page.locator('[data-testid="theme-toggle"]'); before = await page.locator('html').get_attribute('class'); await theme.click(); await page.wait_for_timeout(250); after = await page.locator('html').get_attribute('class'); assert before != after; await theme.click(); results.append('Theme toggle works')
        await page.locator('[data-testid="nav-tracker"]').click(); await page.wait_for_selector('[data-testid="history-table"]', timeout=8000)
        row = page.locator('[data-testid="history-row"]').first; row_text = await row.inner_text(); assert 'NovaMesh AI' in row_text and 'interview' in row_text.lower(); results.append('Tracker NovaMesh row visible')
        await page.locator('[data-testid^="schedule-interview-"]').first.click(); await page.wait_for_selector('[data-testid="interview-dialog"]', timeout=3000)
        dt = page.locator('[data-testid="interview-datetime-input"]'); original = await dt.input_value(); assert original; results.append('Interview dialog populated')
        await dt.fill(''); await page.locator('[data-testid="interview-save-button"]').click(); await page.wait_for_timeout(400); body = await page.locator('body').inner_text(); assert 'Pick a date and time' in body and await page.locator('[data-testid="interview-dialog"]').is_visible(); results.append('Empty datetime validation works')
        await dt.fill(original); await page.locator('[data-testid="interview-notes-input"]').fill('Technical round 2 - Google Meet'); await page.locator('[data-testid="interview-save-button"]').click(); await page.wait_for_timeout(1000); assert not await page.locator('[data-testid="interview-dialog"]').is_visible(); results.append('Interview edit/save works')
        await page.locator('[data-testid="nav-settings"]').click(); await page.wait_for_selector('[data-testid="settings-interviews-card"]', timeout=8000)
        hours = page.locator('[data-testid="settings-interview-reminder-hours"]'); await hours.fill('25'); await page.locator('[data-testid="save-settings-button"]').click(); await page.wait_for_timeout(900); await page.reload(); await page.wait_for_selector('[data-testid="settings-interview-reminder-hours"]', timeout=8000); assert await page.locator('[data-testid="settings-interview-reminder-hours"]').input_value() == '25'; assert await page.locator('[data-testid="settings-notif-interview_reminder"]').count() == 1; results.append('Interview settings persist after reload')
        for testid in ['nav-dashboard','nav-resumes','nav-contacts','nav-opportunities','nav-generator','nav-queue','nav-tracker','nav-gmail','nav-settings']:
            link = page.locator(f'[data-testid="{testid}"]'); await link.scroll_into_view_if_needed(); await link.click(); await page.wait_for_timeout(450); assert await page.locator('[data-testid="page-title"]').count() == 1; results.append(testid + ' loaded')
        error_text = await page.evaluate("""() => { const errorElements = Array.from(document.querySelectorAll('.error, [class*="error"], [id*="error"]')); return errorElements.map(el => el.textContent).join(', '); }""")
        if error_text: print('Found error message:', error_text)
        else: print('No error messages found on the page')
        print('PASS RESULTS:', results)
    except AssertionError as e:
        print('FINDING:', str(e))
    except Exception as e:
        print('SCRIPT ERROR:', str(e)); raise
