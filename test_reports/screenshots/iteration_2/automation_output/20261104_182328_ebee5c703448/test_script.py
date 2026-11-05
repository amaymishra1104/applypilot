async def run_test(page, output_dir, page_url):
    import json

    try:
        await page.set_viewport_size({"width": 1920, "height": 1080})
        await page.wait_for_timeout(2500)
        print('URL after load:', page.url)
        print('Sign-in body:', (await page.locator('body').inner_text())[:1000])
        inputs = await page.locator('input').count()
        print('Input count:', inputs)
        for i in range(inputs):
            el = page.locator('input').nth(i)
            print('input', i, await el.get_attribute('name'), await el.get_attribute('placeholder'), await el.get_attribute('type'))
    except Exception as e:
        print('FINDING: sign-in page inspection failed:', str(e))
        raise
