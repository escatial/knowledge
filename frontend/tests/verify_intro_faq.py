"""验证：聊天界面「介绍知识库」后端内容已聚焦知识库自身 + 引用来源在答案之后"""
from playwright.sync_api import sync_playwright

URL = "http://localhost:5173/chat"

def run_test(viewport_w, viewport_h, label):
    print(f"\n========== {label} ({viewport_w}x{viewport_h}) ==========")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": viewport_w, "height": viewport_h})
        page = ctx.new_page()
        page.goto(URL, wait_until="networkidle", timeout=20000)
        page.wait_for_timeout(1500)
        # 找到输入框
        try:
            input_box = page.locator('textarea, input[placeholder*="问题"]').first
            input_box.fill("介绍一下知识库")
            input_box.press("Enter")
        except Exception as e:
            print(f"  [ERR ] 找不到输入框: {e}")
            browser.close()
            return False
        # 等待 AI 回答完成
        page.wait_for_timeout(8000)
        # 截图
        out = f"D:\\code\\个人开发项目\\202605\\知识库\\frontend\\tests\\_chat_{label}.png"
        page.screenshot(path=out, full_page=True)
        # 提取文本：检查"系统使用说明"是否还出现 + 知识库介绍是否出现
        body_text = page.content()
        has_old_title = "系统使用说明" in body_text
        has_old_title2 = "系统能力" in body_text
        has_new_title1 = "知识库介绍" in body_text
        has_new_title2 = "知识库资源与使用方式" in body_text
        # 顺序检查：找到"正式回答"section和"引用来源"section的DOM位置
        answer_idx = body_text.find("正式回答")
        cite_idx = body_text.find("引用来源")
        print(f"  旧标题(系统使用说明): {'[残留]' if has_old_title else '[已清理]'}")
        print(f"  旧标题(系统能力): {'[残留]' if has_old_title2 else '[已清理]'}")
        print(f"  新标题(知识库介绍): {'[已显示]' if has_new_title1 else '[未显示]'}")
        print(f"  新标题(知识库资源与使用方式): {'[已显示]' if has_new_title2 else '[未显示]'}")
        print(f"  '正式回答' DOM 位置: {answer_idx}")
        print(f"  '引用来源' DOM 位置: {cite_idx}")
        if answer_idx != -1 and cite_idx != -1:
            order_ok = answer_idx < cite_idx
            print(f"  顺序(先答案后引用): {'[正确]' if order_ok else '[顺序反了]'}")
        else:
            order_ok = None
            print(f"  [WARN] 未找到 '正式回答' 或 '引用来源' section")
        print(f"  截图: {out}")
        browser.close()
        return (not has_old_title) and (not has_old_title2) and (has_new_title1 or has_new_title2) and (order_ok is True)

results = []
results.append(("Desktop 1440x900", run_test(1440, 900, "desktop_1440_900")))
results.append(("Laptop 1280x800", run_test(1280, 800, "laptop_1280_800")))
results.append(("Tablet 768x1024", run_test(768, 1024, "tablet_768_1024")))

print("\n========== 总览 ==========")
all_pass = True
for label, ok in results:
    print(f"  {'[PASS]' if ok else '[FAIL]'} {label}")
    if not ok: all_pass = False
print(f"\n  全部通过: {'[PASS]' if all_pass else '[FAIL]'}")
