"""Browser checks. Requires separate Playwright installation and local dev servers.
The chat route below is a TEST FIXTURE, not a real model.
"""
from pathlib import Path
import json
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/usr/bin/chromium', headless=True, args=['--no-sandbox', '--no-proxy-server'])
    page = browser.new_page(viewport={'width':1440,'height':1000})
    page.set_default_timeout(15000)
    errors=[]
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto('http://127.0.0.1:5173',wait_until='domcontentloaded')
    page.locator('.status').filter(has_text='模型未连接').wait_for()
    page.screenshot(path=str(ROOT/'docs/home-desktop.png'),full_page=True)
    page.get_by_role('textbox').fill('如何练习左前压步？')
    page.get_by_role('button',name='发送问题').click()
    assert '尚未连接模型' in page.get_by_role('alert').inner_text()
    page.screenshot(path=str(ROOT/'docs/missing-api-key.png'),full_page=True)
    page.get_by_role('button',name='专项知识库').click()
    page.get_by_text('原有摘要与课程资料',exact=False).click()
    assert '原PDF第39页／印刷29页' in page.inner_text('body')
    page.screenshot(path=str(ROOT/'docs/sources.png'),full_page=True)
    page.set_viewport_size({'width':390,'height':844})
    page.reload(wait_until='domcontentloaded')
    page.locator('.status').filter(has_text='模型未连接').wait_for()
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    page.screenshot(path=str(ROOT/'docs/home-mobile.png'),full_page=True)
    # Browser-only mock responses validate rendering, history, stop and clear.
    status=page.request.get('http://127.0.0.1:8000/api/status').json()
    status['configured']=True
    page.route('**/api/status',lambda route:route.fulfill(json={**status,'connection':'unverified'}))
    payloads=[]
    def chat(route):
        payloads.append(route.request.post_data_json)
        route.fulfill(json={'textbook_facts':['测试显示：摘要介绍逐步进行连续压步的练习。'],'suggestions':'【模拟测试响应】可与现场教练讨论分解练习。','limitations':'测试响应，非真实模型。教材摘要待专业审核。','citations':[status['sources'][3]],'model':'test-fixture'})
    page.route('**/api/evidence',lambda route:route.fulfill(json={'results':[],'has_documents':False}))
    page.route('**/api/chat',chat)
    page.reload(wait_until='domcontentloaded')
    page.locator('.status').filter(has_text='已配置 · 待验证').wait_for()
    for question in ['左前压步如何练习？','那下一步呢？']:
        page.get_by_role('textbox').fill(question)
        page.get_by_role('button',name='发送问题').click()
        page.get_by_role('button',name='停止生成').wait_for(state='hidden')
    assert len(payloads[1]['messages'])==3
    assert '原PDF第93页／印刷79页' in page.inner_text('body')
    page.set_viewport_size({'width':1440,'height':1000})
    page.screenshot(path=str(ROOT/'docs/chat-mocked.png'),full_page=True)
    page.get_by_role('button',name='开始新对话').click()
    page.get_by_text('从一个教学问题开始').wait_for()
    page.unroute('**/api/chat')
    page.evaluate("""() => {
      const originalFetch = window.fetch;
      window.fetch = (url, options) => url === '/api/chat'
        ? new Promise((resolve, reject) => options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError'))))
        : originalFetch(url, options);
    }""")
    page.get_by_role('textbox').fill('停止测试')
    page.get_by_role('button',name='发送问题').click()
    page.get_by_role('button',name='停止生成').click()
    page.screenshot(path=str(ROOT/'docs/stopped.png'))
    assert '已停止等待' in page.get_by_role('alert').inner_text()
    assert not errors, errors
    browser.close()
    print('PASS: desktop/mobile, missing key, catalog, mocked multi-turn/citation, clear, stop, no JS errors')
