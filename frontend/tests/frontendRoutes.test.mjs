// 路由完整性回归。
// 1. 原始静态审查基线中的每个入口都必须仍然注册。
// 2. 基线之后新增的入口必须逐条列在 ADDITIVE_ROUTES 里：新增或删除路由都会让测试失败，
//    不再依赖一个“基线 + N”的魔法数字。
// 3. 守卫边界：/admin 整支受 RequireAdmin，/console 整支受 RequireAuth，
//    登录/注册只给游客，公开分享页不挂任何平台登录守卫。
// 4. Nginx：所有合法前端路由刷新时都会回落到 index.html，且不会被 API 反向代理截走。
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const baseline = JSON.parse(await readFile(new URL('../../docs/agent-cluster-refactor/frontend-refactor-validation/baseline-routes.json', import.meta.url), 'utf8'));
const app = await readFile(new URL('../src/app/App.tsx', import.meta.url), 'utf8');
const nginx = await readFile(new URL('../nginx.conf', import.meta.url), 'utf8');

/**
 * 基线之后新增的路由。键是完整路径（index 路由用父路径 + "#index" 表示）。
 * 新增页面时在这里补一行并说明来源；删除页面会因为缺失而失败。
 */
const ADDITIVE_ROUTES = [
  '/admin/knowledge',
  '/admin/agent-runtime',
  '/admin/recycle-bin',
  // 用例管理中心从 test-asset 拆出的独立用例页。
  '/console/test-cases',
  '/console/automation-projects',
  '/console/automation-runs',
  '/console/automation-history',
  '/console/automation-reports/:reportId',
  '/console/automation-integration',
  '/console/knowledge',
  '/console/asr/audio',
  '/console/model-center',
  '/console/asr/connections',
  '/console/asr/jobs',
  '/console/asr/jobs/:jobId',
  '/console/asr/runs/:runId',
  '/console/asr/runs/:runId/listen',
  '/console/asr/comparisons',
  '/console/asr/comparisons/:comparisonId',
  '/console/asr/experiments',
  '/console/asr/funasr',
  '/console/tasks/inbox',
  '/console/tasks/templates',
  '/console/recycle-bin',
  // 缺陷免登录分享页（0089_defect_public_share）。必须位于所有登录守卫之外。
  '/public/defects/share/:shareId',
];

const PUBLIC_SHARE_ROUTE = '/public/defects/share/:shareId';

/**
 * 从 JSX 源码里提取 <Route> 树。
 * 只做路由声明需要的最小解析：按花括号深度找到开标签结束位置，区分自闭合与成对标签。
 */
function parseRoutes(source) {
  const root = { children: [], fullPath: '', guard: null };
  const stack = [root];
  const tokenPattern = /<Route\b|<\/Route>/g;
  let match;
  while ((match = tokenPattern.exec(source)) !== null) {
    if (match[0] === '</Route>') {
      assert.ok(stack.length > 1, 'unbalanced </Route>');
      stack.pop();
      continue;
    }
    let depth = 0;
    let index = match.index + match[0].length;
    for (; index < source.length; index += 1) {
      const char = source[index];
      if (char === '{') depth += 1;
      else if (char === '}') depth -= 1;
      else if (char === '>' && depth === 0) break;
    }
    const openTag = source.slice(match.index, index + 1);
    const selfClosing = source[index - 1] === '/';
    const parent = stack[stack.length - 1];
    const pathMatch = openTag.match(/\bpath="([^"]+)"/);
    const isIndex = /\sindex[\s/>]/.test(openTag);
    const element = openTag.match(/element=\{([\s\S]*)\}\s*\/?>$/)?.[1] ?? '';
    const ownGuard = ['RequireAdmin', 'RequireAuth', 'GuestOnly'].find((name) => element.includes(`<${name}`)) ?? null;
    let fullPath;
    if (isIndex) fullPath = `${parent.fullPath}#index`;
    else if (!pathMatch) fullPath = parent.fullPath;
    else if (pathMatch[1].startsWith('/') || pathMatch[1] === '*') fullPath = pathMatch[1];
    else fullPath = `${parent.fullPath}/${pathMatch[1]}`;
    const node = {
      path: pathMatch?.[1] ?? null,
      fullPath,
      element,
      guard: ownGuard ?? parent.guard,
      children: [],
      line: source.slice(0, match.index).split('\n').length,
    };
    parent.children.push(node);
    tokenPattern.lastIndex = index + 1;
    if (!selfClosing) stack.push(node);
  }
  assert.equal(stack.length, 1, 'unclosed <Route>');
  const flat = [];
  const walk = (node) => node.children.forEach((child) => { flat.push(child); walk(child); });
  walk(root);
  return { root, flat };
}

const { root, flat } = parseRoutes(app);
const byPath = new Map(flat.map((node) => [node.fullPath, node]));
const baselinePaths = baseline
  .filter((item) => item.route.path)
  .map((item) => JSON.parse(item.route.path));
// 基线 JSON 只记录相对 path；把它映射成完整路径，便于和当前树逐条比对。
const baselineFullPaths = new Set(flat.filter((node) => node.path && baselinePaths.includes(node.path)).map((node) => node.fullPath));

test('route tree parses without duplicates and every route has an element', () => {
  assert.equal(flat.length, [...app.matchAll(/<Route\b/g)].length, 'parser must see every <Route>');
  const seen = new Map();
  for (const node of flat) {
    assert.ok(node.element.trim(), `route at line ${node.line} has no element`);
    assert.ok(!seen.has(node.fullPath), `duplicate route ${node.fullPath} (lines ${seen.get(node.fullPath)} and ${node.line})`);
    seen.set(node.fullPath, node.line);
  }
});

test('all original routes remain registered', () => {
  const currentRelative = new Set(flat.map((node) => node.path).filter(Boolean));
  for (const path of baselinePaths) {
    assert.ok(currentRelative.has(path), `missing baseline route: ${path}`);
  }
  // 基线中的 index 路由（两个）同样必须保留。
  const baselineIndexCount = baseline.filter((item) => !item.route.path).length;
  assert.equal(flat.filter((node) => node.fullPath.endsWith('#index')).length, baselineIndexCount);
});

test('every route added after the baseline is declared explicitly', () => {
  const additive = flat
    .filter((node) => !node.fullPath.endsWith('#index') && !baselinePaths.includes(node.path))
    .map((node) => node.fullPath)
    .filter((path) => !baselineFullPaths.has(path));
  assert.deepEqual([...additive].sort(), [...ADDITIVE_ROUTES].sort());
  assert.equal(flat.length, baseline.length + ADDITIVE_ROUTES.length);
});

test('route guards: admin requires admin, console requires login, auth pages are guest-only', () => {
  const admin = byPath.get('/admin');
  const consoleRoot = byPath.get('/console');
  assert.equal(admin.guard, 'RequireAdmin');
  assert.equal(consoleRoot.guard, 'RequireAuth');
  for (const node of flat) {
    if (node.fullPath.startsWith('/admin')) assert.equal(node.guard, 'RequireAdmin', `${node.fullPath} must be admin-only`);
    if (node.fullPath.startsWith('/console')) assert.equal(node.guard, 'RequireAuth', `${node.fullPath} must require login`);
  }
  assert.equal(byPath.get('/login').guard, 'GuestOnly');
  assert.equal(byPath.get('/register').guard, 'GuestOnly');
  // 兜底页不需要登录，避免未登录访问不存在地址时进入登录死循环。
  for (const path of ['/403', '/404', '*']) assert.equal(byPath.get(path).guard, null);
});

test('public defect share page is top-level and never wrapped by a platform login guard', () => {
  const share = byPath.get(PUBLIC_SHARE_ROUTE);
  assert.ok(share, 'public share route must be registered');
  assert.equal(share.guard, null);
  assert.ok(root.children.includes(share), 'public share route must not be nested in a guarded layout');
  assert.match(share.element, /<PublicDefectSharePage\s*\/>/);
  // 登录态失效回调必须跳过公开页，否则持有过期平台令牌的访问者会被踢到登录页。
  assert.match(app, /onAuthExpired[\s\S]{0,400}pathname\.startsWith\('\/public\/'\)\)\s*return;/);
});

/** 把 Nginx 中所有 location 解析成匹配器，模拟 Nginx 的选择顺序（正则优先于普通前缀）。 */
function nginxLocations(conf) {
  const locations = [];
  const pattern = /location\s+(~\*?|=|\^~)?\s*([^\s{]+)\s*\{([\s\S]*?)\n\s{4}\}/g;
  let match;
  while ((match = pattern.exec(conf)) !== null) {
    const [, modifier = '', target, body] = match;
    locations.push({ modifier, target, body });
  }
  return locations;
}

function resolveLocation(locations, uri) {
  const exact = locations.find((loc) => loc.modifier === '=' && loc.target === uri);
  if (exact) return exact;
  const prefixes = locations
    .filter((loc) => (loc.modifier === '' || loc.modifier === '^~') && uri.startsWith(loc.target))
    .sort((a, b) => b.target.length - a.target.length);
  if (prefixes[0]?.modifier === '^~') return prefixes[0];
  const regex = locations.find((loc) => loc.modifier.startsWith('~') && new RegExp(loc.target, loc.modifier === '~*' ? 'i' : '').test(uri));
  return regex ?? prefixes[0];
}

test('nginx serves index.html for every SPA route on refresh and never proxies them to the API', () => {
  const locations = nginxLocations(nginx);
  assert.ok(locations.length >= 3, 'nginx locations must be parsed');
  const concrete = flat
    .map((node) => node.fullPath.replace(/#index$/, ''))
    .filter((path) => path && path !== '*')
    .map((path) => path.replace(/:[A-Za-z]+/g, '123'));
  concrete.push('/console/some-unknown-page', '/public/defects/share/AbC_123-xyz');
  for (const uri of new Set(concrete)) {
    const location = resolveLocation(locations, uri);
    assert.ok(location, `no nginx location for ${uri}`);
    assert.doesNotMatch(location.body, /proxy_pass/, `${uri} would be proxied instead of served by the SPA`);
    assert.match(location.body, /try_files\s+\$uri\s+\$uri\/\s+\/index\.html;/, `${uri} has no SPA fallback`);
  }
  // 公开分享页额外要求禁止缓存、禁止索引、禁止 Referer 外泄。
  const share = resolveLocation(locations, '/public/defects/share/abc');
  assert.match(share.body, /Cache-Control "no-store"/);
  assert.match(share.body, /Referrer-Policy "no-referrer"/);
  assert.match(share.body, /X-Robots-Tag "noindex, nofollow"/);
  // API 前缀仍然走反向代理。
  assert.match(resolveLocation(locations, '/api/v1/auth/me').body, /proxy_pass/);
});
