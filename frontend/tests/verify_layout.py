"""验证：所有页面在视口固定下不被拉伸，独立滚动条正常"""
from playwright.sync_api import sync_playwright

PAGES = [
    ("/", "工作台"),
    ("/dashboard", "数据看板"),
    ("/documents", "文档管理"),
    ("/graph", "知识图谱"),
    ("/search", "搜索"),
    ("/chat", "智能问答"),
    ("/chunks", "分块管理"),
    ("/settings", "系统设置"),
]

BASE = "http://localhost:5173"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    for route, name in PAGES:
        url = f"{BASE}{route}"
        print(f"\n=== {name} ({route}) ===")
        try:
            page.goto(url, wait_until="networkidle", timeout=15000)
        except Exception as e:
            print(f"  [TIMEOUT] {e}")
            page.screenshot(path=f"D:/code/个人开发项目/202605/知识库/frontend/tests/_err_{name}.png", full_page=True)
            continue

        page.wait_for_timeout(500)
        # 1) body / html 滚动应被关闭
        body_overflow = page.evaluate("() => getComputedStyle(document.body).overflow")
        html_overflow = page.evaluate("() => getComputedStyle(document.documentElement).overflow")
        # 2) main 区域应有 overflow-y-auto
        main_overflow = page.evaluate("""() => {
            const m = document.querySelector('main');
            if (!m) return null;
            const s = getComputedStyle(m);
            return { overflowY: s.overflowY, height: m.clientHeight };
        }""")
        # 3) 视口尺寸
        vp = page.viewport_size
        # 4) main 的高度应当 = 视口高 - 顶部栏
        header_h = page.evaluate("() => { const h = document.querySelector('header'); return h ? h.clientHeight : 0; }")
        # 5) 截图
        out = f"D:/code/个人开发项目/202605/知识库/frontend/tests/_p_{name}.png"
        page.screenshot(path=out, full_page=False)
        print(f"  body.overflow={body_overflow}  html.overflow={html_overflow}")
        print(f"  main={main_overflow}  header_h={header_h}  viewport={vp}")
        print(f"  [OK] screenshot -> {out}")

    browser.close()
print("\nDONE")
