"""任务 7：上传节点可视化 - 简化版 e2e 测试

策略：用 Playwright 直接驱动
"""
import os
import sys
from playwright.sync_api import sync_playwright

URL = "http://localhost:5173/"
TEST_FILE = r"D:\code\个人开发项目\202605\知识库\frontend\tests\_test_upload.txt"

def test_upload_flow():
    print("========== e2e: 上传流程节点状态流 ==========")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        # 拦截 documents/upload 请求（避免真实后端耗时）
        page.route("**/documents/upload", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body='{"task_id":"mock_task_1","doc_id":"d1"}'
        ))
        # 拦截 progress 轮询：返回动态 progress
        progress_val = [0]
        def progress_handler(route):
            progress_val[0] = min(100, progress_val[0] + 10)
            payload = {
                "progress": progress_val[0],
                "status": f"处理中... {progress_val[0]}%",
                "done": progress_val[0] >= 100,
                "chunk_count": 5,
                "graph_result": {"nodes": 3, "edges": 2}
            }
            route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))
        page.route("**/documents/progress/*", progress_handler)

        page.goto(URL, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(1000)
        # 1) 注入文件
        file_input = page.locator('input[type="file"]')
        if file_input.count() == 0:
            print("  [ERR ] 找不到 file input"); browser.close(); return False
        file_input.set_input_files(TEST_FILE)
        page.wait_for_timeout(500)
        # 2) 点击"上传"
        upload_btn = page.locator('button:has-text("上传")').first
        upload_btn.click()
        page.wait_for_timeout(800)
        # 3) 立即检测节点
        nodes = page.locator('[data-testid^="node-"]')
        cnt = nodes.count()
        print(f"  节点 DOM 数: {cnt}")
        if cnt == 0:
            print("  [FAIL] 节点组件未渲染")
            page.screenshot(path=r"D:\code\个人开发项目\202605\知识库\frontend\tests\_e2e_no_nodes.png", full_page=True)
            browser.close()
            return False
        # 4) 状态流
        statuses_0 = [nodes.nth(i).get_attribute("data-status") for i in range(cnt)]
        print(f"  初始状态: {statuses_0}")
        # 5) 等 1.5s 看是否更新
        page.wait_for_timeout(1500)
        statuses_1 = [nodes.nth(i).get_attribute("data-status") for i in range(cnt)]
        print(f"  1.5s 后: {statuses_1}")
        # 6) in_progress 节点有 animate-pulse（检查所有子元素）
        ip = page.locator('[data-status="in_progress"]')
        if ip.count() > 0:
            # 检查 li 本身和所有内部 div
            html = ip.first.evaluate("el => el.outerHTML")
            has_pulse = "animate-pulse" in html
            print(f"  in_progress DOM 树含 animate-pulse: {has_pulse}")
            # 列出子元素的 class
            pulse_in_html = "animate-pulse" in html
            print(f"  outerHTML 截取: {html[:300]}")
        # 7) 截图
        out1 = r"D:\code\个人开发项目\202605\知识库\frontend\tests\_e2e_nodes_inprogress.png"
        page.screenshot(path=out1, full_page=True)
        print(f"  截图: {out1}")
        # 8) 等 12s 让进度走完
        page.wait_for_timeout(12000)
        statuses_done = [nodes.nth(i).get_attribute("data-status") for i in range(cnt)]
        print(f"  最终: {statuses_done}")
        all_done = all(s == "done" for s in statuses_done)
        print(f"  全部 done: {all_done}")
        out2 = r"D:\code\个人开发项目\202605\知识库\frontend\tests\_e2e_nodes_done.png"
        page.screenshot(path=out2, full_page=True)
        browser.close()
        return all_done


def test_responsive():
    print("\n========== 响应式：3 视口尺寸 ==========")
    sizes = [("Desktop 1440x900", 1440, 900), ("Laptop 1280x800", 1280, 800), ("Tablet 768x1024", 768, 1024)]
    for label, w, h in sizes:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": w, "height": h})
            page = ctx.new_page()
            page.goto(URL, wait_until="domcontentloaded", timeout=10000)
            page.wait_for_timeout(800)
            out = f"D:\\code\\个人开发项目\\202605\\知识库\\frontend\\tests\\_responsive_{w}_{h}.png"
            page.screenshot(path=out, full_page=False)
            print(f"  {label}: {out}")
            browser.close()
    return True


if __name__ == "__main__":
    import json
    ok1 = test_upload_flow()
    ok2 = test_responsive()
    print("\n========== 总览 ==========")
    print(f"  上传节点状态流: {'[PASS]' if ok1 else '[FAIL]'}")
    print(f"  响应式截图: {'[PASS]' if ok2 else '[FAIL]'}")
    sys.exit(0 if (ok1 and ok2) else 1)
