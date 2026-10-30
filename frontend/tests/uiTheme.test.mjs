import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import Module, { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import React from 'react';
import { renderToString } from 'react-dom/server';
import { ConfigProvider, Layout, Menu, Progress, Table, Tabs, Tag, Typography, theme } from 'antd';
import ts from 'typescript';

const require = createRequire(import.meta.url);
const { StyleProvider, createCache, extractStyle } = require('@ant-design/cssinjs');
const filename = fileURLToPath(new URL('../src/shared/theme/index.ts', import.meta.url));
const source = await readFile(filename, 'utf8');
const compiled = new Module(filename);
compiled.filename = filename;
compiled.paths = Module._nodeModulePaths(fileURLToPath(new URL('..', import.meta.url)));
compiled._compile(ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText, filename);
const { buildTheme } = compiled.exports;

for (const dark of [false, true]) {
  test(`component CSS uses resolved colors in ${dark ? 'dark' : 'light'} mode`, () => {
    const config = buildTheme(dark);
    const resolved = theme.getDesignToken(config);
    const cache = createCache();
    renderToString(React.createElement(StyleProvider, { cache },
      React.createElement(ConfigProvider, { theme: config },
        React.createElement(Layout, null,
          React.createElement(Menu, { items: [{ key: '1', label: '首页' }], selectedKeys: ['1'] }),
          React.createElement(Table, {
            columns: [{ title: '名称', dataIndex: 'name' }],
            dataSource: [{ key: '1', name: '示例' }], pagination: false,
          }),
          React.createElement(Tabs, { items: [{ key: '1', label: '概览', children: '内容' }] }),
          React.createElement(Tag, null, '状态'),
          React.createElement(Typography.Title, { level: 4 }, '标题'),
          React.createElement(Progress, { percent: 50 }),
        ),
      ),
    ));
    const css = extractStyle(cache, true);
    assert.ok(css.length > 1000, 'must inspect actual generated component styles');
    assert.doesNotMatch(css, /:\s*token\.[a-zA-Z]+/, 'token references must not leak into CSS values');
    assert.equal(config.components.Menu.itemSelectedColor, resolved.colorPrimary);
    assert.equal(config.components.Table.headerColor, resolved.colorTextHeading);
    assert.match(css, new RegExp(resolved.colorPrimary.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  });
}
