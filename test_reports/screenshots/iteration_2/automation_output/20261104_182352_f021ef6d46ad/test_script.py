async def run_test(page, output_dir, page_url):
    try:
        ticket = 'eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJlaXMiOjYwMCwiZXhwIjoxNzkzODE3MjI3LCJpaWQiOiJpbnNfM0xlV1VPOU5JN3FZcXUxTVBGRDB6VDlmcHdaIiwic2lkIjoic2l0XzNMZVpqSTNtYVdaTElKN21MUXBrTkFZRmE5SyIsInN0Ijoic2lnbl9pbl90b2tlbiJ9.eT8qvHoaQ9AuuLa73jsr-8aaANpu_lMDKZuy34g4hHk6QyvINcfWYHq54edtO-EO6aisdHp3e5I2GWdpPfjihhGwopoSnaTIIpqHyXfxS08NPKlJu1nr9KMGXRdJC7jUbhwpDM63RVL83m6OpCLiMUpZbzneGDsbBQ8RuSIjSlQcr76NgNSxXxQFTEZHn0x7sItxXUesSut-1w9cvXmqL4LWcPWem94gaZa9qkB7q5-qQAzvA5etxM3SO_Idq61feCg8-p0XHr37D2ECAlQdZnUuS7rPJcGUmCk4PoqnZNBNifKZ_LCJ5bLMYV0SSoZLijW2OHXh9gxOuLLr72LWOA'
        await page.goto('https://apply-pilot-10--6p4n0df3.preview.emergentagent.com/sign-in?__clerk_ticket=' + ticket, wait_until='domcontentloaded', timeout=20000)
        await page.wait_for_timeout(4000)
        print('Ticket URL:', page.url)
        print('Page title:', await page.locator('[data-testid="page-title"]').first.inner_text() if await page.locator('[data-testid="page-title"]').count() else 'none')
        print('Body start:', (await page.locator('body').inner_text())[:500])
        if '/sign-in' in page.url and not await page.locator('[data-testid="nav-tracker"]').count():
            print('FINDING: Clerk ticket did not establish app session')
    except Exception as e:
        print('FINDING: ticket flow failed:', str(e))
        raise
