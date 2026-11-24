"""Repeatable browser regression for case range navigation."""
from __future__ import annotations
import os, re, subprocess, sys
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright, expect
from app.core.models.identity import User
from tests.conftest import DEFAULT_PASSWORD, unique
from tests.test_31_web_ui_console import free_port, wait_http
from tests.test_47_test_scope import _project, _case


@pytest.fixture
def case_site(db, tmp_path):
    root = Path(__file__).resolve().parents[2]; frontend = root / 'frontend'
    modules = tmp_path / 'node_modules'; modules.mkdir()
    for entry in (frontend / 'node_modules').iterdir():
        if entry.name != '.vite-temp':
            (modules / entry.name).symlink_to(entry.resolve(), target_is_directory=entry.is_dir())
    config = (frontend / 'vite.config.ts').read_text().replace("fileURLToPath(new URL('./src', import.meta.url))", repr(str(frontend / 'src')))
    config_path = tmp_path / 'vite.config.ts'; config_path.write_text(config)
    bp, fp = free_port(), free_port(); base = f'http://127.0.0.1:{fp}'
    back = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(bp)], cwd=root / 'backend', env={**os.environ, 'CORS_ORIGINS':base}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    front = None
    try:
        wait_http(f'http://127.0.0.1:{bp}/healthz', back)
        front = subprocess.Popen([str(frontend / 'node_modules/.bin/vite'), str(frontend), '--config', str(config_path), '--host','127.0.0.1','--port',str(fp),'--strictPort'], cwd=frontend, env={**os.environ,'VITE_API_PROXY_TARGET':f'http://127.0.0.1:{bp}'}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait_http(base, front)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            yield base, browser
            browser.close()
    finally:
        for proc in (front, back):
            if proc:
                proc.terminate()
                try: proc.wait(timeout=10)
                except subprocess.TimeoutExpired: proc.kill(); proc.wait()


def test_case_scopes_selection_and_history(api, admin, db, case_site):
    project = _project(api, admin)
    a = api.post(f'/projects/{project}/test-scopes', username=admin, json={'direction':'API','node_type':'FOLDER','name':unique('目录A')}).json()
    b = api.post(f'/projects/{project}/test-scopes', username=admin, json={'direction':'API','node_type':'FOLDER','name':unique('目录B')}).json()
    for i in range(23):
        case = _case(api, admin, project, unique('页面用例'), priority='P0')
        assert api.post(f'/projects/{project}/test-scope-cases/move', username=admin, json={'case_ids':[case['id']], 'scope_node_id':a['id']}).status_code == 200
    base, browser = case_site; page = browser.new_page(viewport={'width':1440,'height':900}); page.set_default_timeout(15000)
    page.goto(base + '/login'); page.get_by_label('用户名', exact=True).fill(admin); page.get_by_label('密码', exact=True).fill(DEFAULT_PASSWORD); page.get_by_role('button',name=re.compile('登\\s*录')).click(); page.wait_for_url('**/console')
    page.goto(f'{base}/console/test-cases?projectId={project}')
    expect(page.get_by_text('方向总数 23')).to_be_visible(); expect(page.get_by_text('筛选命中 23')).to_be_visible()
    page.get_by_role('button', name=re.compile('P0')).click()
    page.get_by_text(a['name'], exact=True).first.click()
    expect(page.get_by_placeholder('搜索当前目录及子目录')).to_be_visible()
    first_id = page.locator('tbody tr.ant-table-row').first.locator('td').nth(1).inner_text()
    page.locator('tbody tr.ant-table-row .ant-checkbox-input').first.check(); expect(page.get_by_text('已选 1 条')).to_be_visible()
    page.locator('.ant-pagination-item-2').click()
    expect(page.locator('tbody tr.ant-table-row').first.locator('td').nth(1)).not_to_have_text(first_id)
    page.locator('tbody tr.ant-table-row .ant-checkbox-input').first.check(); expect(page.get_by_text('已选 2 条')).to_be_visible()
    page.get_by_text(b['name'], exact=True).first.click(); expect(page.get_by_text('已选 0 条')).to_be_visible(); assert 'page=2' not in page.url
    page.get_by_role('button', name='全部用例', exact=True).click()
    search = page.get_by_placeholder('搜索全部 API 用例'); search.fill('不存在的用例abc'); search.press('Enter')
    expect(page.get_by_text('当前筛选无结果')).to_be_visible(); page.get_by_role('button', name='清除筛选').click()
    page.locator('.ant-pagination-item-2').click(); page.locator('tbody tr.ant-table-row button.ant-btn-link').first.click()
    expect(page).to_have_url(re.compile('page=2.*caseId=')); page.reload(); expect(page).to_have_url(re.compile('page=2.*caseId='))
    page.keyboard.press('Escape'); expect(page).to_have_url(re.compile('page=2'))
    page.goto(f'{base}/console/test-cases?projectId={project}&direction=API&page=3')
    expect(page.locator('.ant-pagination-item-3')).to_have_class(re.compile('ant-pagination-item-active'))
    page.reload(); expect(page.locator('.ant-pagination-item-3')).to_have_class(re.compile('ant-pagination-item-active'))
    failed = {'active': True}
    def fail_list(route):
        if failed['active']: route.fulfill(status=503, json={'message':'测试故障'})
        else: route.continue_()
    page.route('**/test-scope-cases?*', fail_list); page.reload()
    expect(page.get_by_text('加载失败')).to_be_visible()
    expect(page.get_by_text('方向总数 23')).to_be_visible()
    failed['active'] = False
    page.get_by_text('重试', exact=True).click()
    expect(page.locator('tbody tr.ant-table-row').first).to_be_visible()
    page.close()
