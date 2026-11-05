async def run_test(page, output_dir, page_url):
    try:
        ticket = 'eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJlaXMiOjYwMCwiZXhwIjoxNzkzODE3MjgyLCJpaWQiOiJpbnNfM0xlV1VPOU5JN3FZcXUxTVBGRDB6VDlmcHdaIiwic2lkIjoic2l0XzNMZVpxQ1VYNUhxc3dXaDBiQzFIbno2WnY0OCIsInN0Ijoic2lnbl9pbl90b2tlbiJ9.2yGosCeJ_AJo-RaTLOTusAJVd9iTuyG-1wYFl99L-IHEwGgU6bB6AIojpDDNfwquSblkaAHRX3yQOdgDaFB0axD8zztSlxUhvcYtyg_PS-zo1gDKob6lvMT1HRr_PuwFIxkk7FU0oZyuAAgUKJV-zFlCcatBWQ2qkwod6sSUP9UECdGCG-x6tnTLl2B47NXjqE2gre6tVq60oFJ6ColCcooRS-oZ8rA5B5SnU6FZI6EZmjZdKR8kl18zK2rstUmmlLkOakBN7jkGzgUZ1UY2VLWt5ePLKw8639Fwk2eu0uS7L2w-qAzg10XQ6_HiaCL91cY60e_OyJoWI-bYObF7-Q'
        await page.goto('https://apply-pilot-10--6p4n0df3.preview.emergentagent.com/sign-in?__clerk_ticket=' + ticket, wait_until='domcontentloaded', timeout=20000)
        await page.wait_for_selector('[data-testid="page-title"]', timeout=12000)
        results=[]
        assert 'NovaMesh AI' in await page.locator('[data-testid="upcoming-interviews"]').inner_text(); results.append('Dashboard upcoming interview visible')
        theme=page.locator('[data-testid="theme-toggle"]'); b=await page.locator('html').get_attribute('class'); await theme.click(); await page.wait_for_timeout(200); a=await page.locator('html').get_attribute('class'); assert b!=a; await theme.click(); results.append('Theme toggle works')
        await page.locator('[data-testid="nav-tracker"]').click(); await page.wait_for_selector('[data-testid="history-table"]',timeout=8000); row=page.locator('[data-testid="history-row"]').first; assert 'NovaMesh AI' in await row.inner_text(); results.append('Tracker NovaMesh row visible')
        await page.locator('[data-testid^="schedule-interview-"]').first.click(); await page.wait_for_selector('[data-testid="interview-dialog"]',timeout=3000); dt=page.locator('[data-testid="interview-datetime-input"]'); original=await dt.input_value(); assert original; results.append('Interview dialog populated')
        await dt.fill(''); await page.locator('[data-testid="interview-save-button"]').click(); await page.wait_for_timeout(350); assert 'Pick a date and time' in await page.locator('body').inner_text(); results.append('Empty datetime validation works')
        await dt.fill(original); await page.locator('[data-testid="interview-notes-input"]').fill('Technical round 2 - Google Meet'); await page.locator('[data-testid="interview-save-button"]').click(); await page.wait_for_timeout(900); assert not await page.locator('[data-testid="interview-dialog"]').is_visible(); results.append('Interview edit/save works')
        await page.locator('[data-testid="nav-settings"]').click(); await page.wait_for_selector('[data-testid="settings-interviews-card"]',timeout=8000); hours=page.locator('[data-testid="settings-interview-reminder-hours"]'); await hours.fill('25'); await page.locator('[data-testid="save-settings-button"]').click(); await page.wait_for_timeout(900); await page.reload(); await page.wait_for_selector('[data-testid="settings-interview-reminder-hours"]',timeout=8000); assert await page.locator('[data-testid="settings-interview-reminder-hours"]').input_value()=='25'; assert await page.locator('[data-testid="settings-notif-interview_reminder"]').count()==1; results.append('Interview settings persist after reload')
        for tid in ['nav-dashboard','nav-resumes','nav-contacts','nav-opportunities','nav-generator','nav-queue','nav-tracker','nav-gmail','nav-settings']:
            link=page.locator(f'[data-testid="{tid}"]'); await link.scroll_into_view_if_needed(); await link.click(); await page.wait_for_timeout(450); assert await page.locator('[data-testid="page-title"]').count()==1; results.append(tid+' loaded')
        error_text=await page.evaluate("""() => { const errorElements = Array.from(document.querySelectorAll('.error, [class*="error"], [id*="error"]')); return errorElements.map(el => el.textContent).join(', '); }""")
        print('Found error message:' if error_text else 'No error messages found on the page', error_text)
        print('PASS RESULTS:',results)
    except AssertionError as e:
        print('FINDING:',str(e))
    except Exception as e:
        print('SCRIPT ERROR:',str(e)); raise
