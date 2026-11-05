async def run_test(page, output_dir, page_url):
    try:
        await page.set_viewport_size({"width": 1920, "height": 1080})
        email = page.locator('input[name="identifier"]')
        await email.fill('pilot-tester@applypilot.dev')
        btn = page.get_by_role('button', name='Continue', exact=True)
        await btn.scroll_into_view_if_needed()
        await btn.click()
        await page.wait_for_timeout(1200)
        print('After email URL:', page.url)
        print('Body:', (await page.locator('body').inner_text())[-700:])
        print('Password inputs:', await page.locator('input[type="password"]').count())
        if await page.locator('input[type="password"]').count():
            await page.locator('input[type="password"]').fill('PilotTest#2026!')
            btn2 = page.get_by_role('button', name='Continue', exact=True)
            await btn2.scroll_into_view_if_needed(); await btn2.click()
            await page.wait_for_timeout(2500)
        print('Post-login URL:', page.url)
        print('Title:', await page.locator('[data-testid="page-title"]').first.inner_text() if await page.locator('[data-testid="page-title"]').count() else 'none')
        if '/sign-in' in page.url:
            print('FINDING: login did not reach authenticated app')
    except Exception as e:
        print('FINDING: login flow failed:', str(e))
        raise
