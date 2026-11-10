// 测试用例库。
// 由 /console/test-cases 挂载，不再放进测试资产。
// 组织方式：被测对象（接口/界面/业务流程/业务动作）× 测试维度（功能/边界/安全/…）双维过滤，
// 替代旧的「范围树」嵌套——树节点的「接口数/用例数」就是覆盖矩阵的一个单元格。
// 空组合（某对象下没有该维度用例）不出现在维度 Tab 里。
// 接口对象按接口归组（优先对上接口管理的接口名）；其余对象按测试点归组。
// 用例内容按接口管理的方式只读展示：基本信息、前置条件、测试数据、断言、步骤。
//
// 权限（服务端为准）：读 = 项目可见（viewer+）。
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Col, Descriptions, Input, Row, Segmented, Table, Tabs, Tag, Typography } from 'antd';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { apiCatalogApi } from '@/features/api-catalog/api/apiCatalog';
import { testManagementApi } from '@/features/test-management/api/testManagement';
import { collectArrayPages, collectPages } from '@/shared/api/pagination';
import { EmptyState, ErrorState, LoadingState, PageContainer } from '@/shared/ui/PageState';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import type { TestCase, TestCaseDetail } from '@/features/test-management/contracts';

const HTTP_PATTERN = /(GET|POST|PUT|PATCH|DELETE)\s+(\/[^\s]+)/;
const METHOD_COLOR: Record<string, string> = {
  GET: 'green',
  POST: 'blue',
  PUT: 'orange',
  PATCH: 'gold',
  DELETE: 'red',
};

// 被测对象 facet。顺序固定，界面文案用短名，和后端 target_type 枚举一一对应。
const OBJECT_FACETS = ['API', 'WEB', 'AI', 'BUSINESS_FLOW', 'BUSINESS_ACTION'] as const;
type ObjectFacet = (typeof OBJECT_FACETS)[number];
const OBJECT_LABEL: Record<ObjectFacet, string> = {
  API: '接口',
  WEB: '界面',
  AI: 'AI 能力',
  BUSINESS_FLOW: '业务流程',
  BUSINESS_ACTION: '业务动作',
};

// 测试维度短名。NEGATIVE 与 EXCEPTION 都含「异常」，这里用「负向/异常」区分开。
const DIMENSION_LABEL: Record<string, string> = {
  FUNCTIONAL: '功能',
  BUSINESS: '业务',
  NEGATIVE: '负向',
  BOUNDARY: '边界',
  PERMISSION: '权限',
  SECURITY: '安全',
  EXCEPTION: '异常',
};
const ALL_DIMENSIONS = 'ALL';
// 接口对象下解析不出方法+路径的用例归入这个兜底组，不再静默丢失。
const UNMATCHED_KEY = 'unmatched';

interface CaseGroup {
  key: string;
  title: string;
  subtitle: string;
  method?: string;
  path?: string;
  cases: TestCase[];
}

/** 取出描述里某一行标签后面的文字。没有这一行时返回空串。 */
function labeled(description: string | null, label: string): string {
  if (!description) return '';
  const line = description.split('\n').find((item) => item.startsWith(`${label}：`) || item.startsWith(`${label}:`));
  return line ? line.split(/：|:/).slice(1).join('：').trim() : '';
}

/** 把路径参数收成 {}，方便和接口管理里的 path 对齐。 */
function normalizePath(path: string): string {
  return path.replace(/\/+$/, '').replace(/\{[^}]+\}/g, '{}');
}

/** 从用例描述里取出这条用例打到的接口。对不上方法和路径时返回空。 */
function endpointOf(item: TestCase): { method: string; path: string } | null {
  const source = `${labeled(item.description, '模块路径')}\n${labeled(item.description, '画布')}`;
  const matched = source.match(HTTP_PATTERN);
  if (!matched) return null;
  return { method: matched[1], path: matched[2] };
}

/** 一条用例在当前对象 facet 下归属的分组 key，选中态和归组共用。 */
function groupKeyOf(item: TestCase, facet: ObjectFacet): string {
  if (facet === 'API') {
    const endpoint = endpointOf(item);
    return endpoint ? `${endpoint.method} ${normalizePath(endpoint.path)}` : UNMATCHED_KEY;
  }
  return `point:${item.test_point_id ?? 'none'}`;
}

/**
 * 按接口把用例归在一起。
 * 标题优先用接口管理里的接口名；没有同名接口时用「方法 + 路径」，不用画布里的模块名。
 * 解析不出接口的用例进兜底组，保证列表条数和覆盖矩阵一致。
 */
function groupByInterface(cases: TestCase[], catalog: { name: string; method: string; path: string }[]): CaseGroup[] {
  const groups = new Map<string, CaseGroup>();
  for (const item of cases) {
    const endpoint = endpointOf(item);
    if (!endpoint) {
      const fallback = groups.get(UNMATCHED_KEY) ?? {
        key: UNMATCHED_KEY,
        title: '未匹配接口的用例',
        subtitle: '',
        cases: [],
      };
      fallback.cases.push(item);
      groups.set(UNMATCHED_KEY, fallback);
      continue;
    }
    const key = `${endpoint.method} ${normalizePath(endpoint.path)}`;
    const known = catalog.find((api) => api.method.toUpperCase() === endpoint.method && normalizePath(api.path) === normalizePath(endpoint.path));
    const current = groups.get(key) ?? {
      key,
      title: known?.name || `${endpoint.method} ${endpoint.path}`,
      subtitle: '',
      method: endpoint.method,
      path: endpoint.path,
      cases: [],
    };
    current.cases.push(item);
    groups.set(key, current);
  }
  return [...groups.values()]
    .map((group) => ({
      ...group,
      subtitle: `${group.path ? `${group.path} · ` : ''}${group.cases.length} 条用例`,
    }))
    .sort((left, right) => {
      if (left.key === UNMATCHED_KEY) return 1;
      if (right.key === UNMATCHED_KEY) return -1;
      return left.subtitle.localeCompare(right.subtitle) || left.title.localeCompare(right.title);
    });
}

/** 非接口对象按测试点归组；没挂测试点的用例进「未关联测试点」组。 */
function groupByPoint(cases: TestCase[], pointNames: Map<number, string>): CaseGroup[] {
  const groups = new Map<string, CaseGroup>();
  for (const item of cases) {
    const key = `point:${item.test_point_id ?? 'none'}`;
    const current = groups.get(key) ?? {
      key,
      title: item.test_point_id != null ? pointNames.get(item.test_point_id) ?? `测试点 #${item.test_point_id}` : '未关联测试点',
      subtitle: '',
      cases: [],
    };
    current.cases.push(item);
    groups.set(key, current);
  }
  return [...groups.values()]
    .map((group) => ({ ...group, subtitle: `${group.cases.length} 条用例` }))
    .sort((left, right) => left.title.localeCompare(right.title));
}

/** 测试用例页。未选项目时不请求。 */
export function ConsoleTestCasesPage() {
  const { currentProjectId } = useConsoleScope();
  const [searchParams] = useSearchParams();
  const requestedCaseId = Number(searchParams.get('caseId'));
  const requestedProjectId = Number(searchParams.get('projectId'));
  const [objectFacet, setObjectFacet] = useState<ObjectFacet>('API');
  const [dimension, setDimension] = useState<string>(ALL_DIMENSIONS);
  const [keyword, setKeyword] = useState('');
  const [selectedKey, setSelectedKey] = useState<string>();
  const [selectedCaseId, setSelectedCaseId] = useState<number | null>(null);

  // 覆盖矩阵驱动两个 facet：对象选项的用例总数、维度 Tab 的单元格计数。
  const coverageQuery = useQuery({
    queryKey: ['test-cases', currentProjectId, 'coverage'],
    queryFn: () => testManagementApi.getCaseCoverage(currentProjectId!),
    enabled: currentProjectId != null,
  });
  const casesQuery = useQuery({
    queryKey: ['test-cases', currentProjectId, 'grouped', objectFacet, dimension],
    queryFn: () => collectArrayPages(
      (page) => testManagementApi.listCases(currentProjectId!, {
        page,
        page_size: 100,
        target_type: objectFacet,
        case_type: dimension === ALL_DIMENSIONS ? undefined : dimension,
      }),
      100,
    ),
    enabled: currentProjectId != null,
  });
  const catalogQuery = useQuery({
    queryKey: ['api-catalog', currentProjectId, 'case-interfaces'],
    queryFn: () => collectPages((page) => apiCatalogApi.listApis(currentProjectId!, { page, page_size: 200 })),
    enabled: currentProjectId != null && objectFacet === 'API',
  });
  const pointsQuery = useQuery({
    queryKey: ['test-points', currentProjectId, 'case-groups'],
    queryFn: () => testManagementApi.listPoints(currentProjectId!, { page: 1, page_size: 100 }),
    enabled: currentProjectId != null && objectFacet !== 'API',
  });
  const detailQuery = useQuery({
    queryKey: ['test-case-detail', selectedCaseId],
    queryFn: () => testManagementApi.getCaseDetail(selectedCaseId!),
    enabled: selectedCaseId != null,
  });
  // 深链 caseId 可能指向别的对象 facet：先取一次基本信息，把 facet 对齐过去。
  const requestedCaseQuery = useQuery({
    queryKey: ['test-case-brief', requestedCaseId],
    queryFn: () => testManagementApi.getCase(requestedCaseId),
    enabled: Number.isSafeInteger(requestedCaseId) && requestedCaseId > 0,
  });

  const coverageCells = coverageQuery.data?.items ?? [];
  const objectCount = useMemo(() => {
    const totals = new Map<string, number>();
    for (const cell of coverageCells) {
      totals.set(cell.target_type, (totals.get(cell.target_type) ?? 0) + cell.case_count);
    }
    return totals;
  }, [coverageCells]);
  const dimensionCells = useMemo(
    () => coverageCells.filter((cell) => cell.target_type === objectFacet && cell.case_count > 0),
    [coverageCells, objectFacet],
  );

  // 切对象后当前维度在新对象下可能没有用例：收回「全部」，空组合不留入口。
  useEffect(() => {
    if (dimension === ALL_DIMENSIONS) return;
    if (!dimensionCells.some((cell) => cell.case_type === dimension)) {
      setDimension(ALL_DIMENSIONS);
    }
  }, [dimension, dimensionCells]);

  useEffect(() => {
    const brief = requestedCaseQuery.data;
    if (!brief) return;
    if ((OBJECT_FACETS as readonly string[]).includes(brief.target_type) && brief.target_type !== objectFacet) {
      setObjectFacet(brief.target_type as ObjectFacet);
      setDimension(ALL_DIMENSIONS);
    }
    // 只对齐一次：facet 切换后由下方选中 effect 接手。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestedCaseQuery.data]);

  const groups = useMemo(() => {
    const cases = casesQuery.data ?? [];
    if (objectFacet === 'API') {
      return groupByInterface(cases, catalogQuery.data?.items ?? []);
    }
    const pointNames = new Map((pointsQuery.data ?? []).map((point) => [point.id, point.name]));
    return groupByPoint(cases, pointNames);
  }, [casesQuery.data, catalogQuery.data, pointsQuery.data, objectFacet]);
  const visibleGroups = useMemo(() => {
    const text = keyword.trim().toLowerCase();
    if (!text) return groups;
    return groups.filter((group) => `${group.title} ${group.subtitle}`.toLowerCase().includes(text));
  }, [groups, keyword]);
  const selected = groups.find((group) => group.key === selectedKey) ?? null;

  useEffect(() => {
    if (!Number.isSafeInteger(requestedCaseId) || requestedCaseId <= 0 || !casesQuery.data) return;
    const item = casesQuery.data.find((row) => row.id === requestedCaseId);
    if (!item) return;
    setSelectedKey(groupKeyOf(item, objectFacet));
    setSelectedCaseId(item.id);
    // objectFacet 由对齐 effect 先切好，这里不依赖它，避免重复选中。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [casesQuery.data, requestedCaseId]);

  if (currentProjectId == null) {
    return <PageContainer><EmptyState description="请先在顶部选择一个项目" /></PageContainer>;
  }
  if (requestedProjectId > 0 && requestedProjectId !== currentProjectId) {
    return <PageContainer><EmptyState description={`此链接指向项目 #${requestedProjectId}，请先在顶部切换项目`} /></PageContainer>;
  }

  const changeFacet = (value: string | number) => {
    setObjectFacet(value as ObjectFacet);
    setSelectedKey(undefined);
    setSelectedCaseId(null);
  };

  return (
    <PageContainer>
      <div style={{ marginBottom: 12, display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center' }}>
        <Segmented
          value={objectFacet}
          onChange={changeFacet}
          options={OBJECT_FACETS
            .filter((facet) => facet === objectFacet || (objectCount.get(facet) ?? 0) > 0)
            .map((facet) => ({ value: facet, label: `${OBJECT_LABEL[facet]} ${objectCount.get(facet) ?? 0}` }))}
        />
        <Tabs
          size="small"
          activeKey={dimension}
          onChange={setDimension}
          style={{ flex: 1, minWidth: 320, marginBottom: -12 }}
          items={[
            { key: ALL_DIMENSIONS, label: `全部 ${dimensionCells.reduce((sum, cell) => sum + cell.case_count, 0)}` },
            ...dimensionCells.map((cell) => ({
              key: cell.case_type,
              label: `${DIMENSION_LABEL[cell.case_type] ?? cell.case_type} ${cell.case_count}`,
            })),
          ]}
        />
      </div>
      <Row gutter={16} wrap={false}>
        <Col flex="320px">
          <div style={{ border: '1px solid #f0f0f0', borderRadius: 8, padding: 8, height: 'calc(100vh - 230px)', minHeight: 380, display: 'flex', flexDirection: 'column' }}>
            <Typography.Text strong style={{ margin: '4px 8px 8px' }}>{objectFacet === 'API' ? '接口' : '测试点'}</Typography.Text>
            <Input.Search
              allowClear
              placeholder={objectFacet === 'API' ? '搜索接口名称或路径' : '搜索测试点'}
              style={{ marginBottom: 8 }}
              onSearch={setKeyword}
            />
            <div style={{ overflow: 'auto', flex: 1 }}>
              {casesQuery.isPending ? <LoadingState /> : casesQuery.isError ? <ErrorState error={casesQuery.error} onRetry={casesQuery.refetch} /> : visibleGroups.length === 0 ? <EmptyState description="该维度下没有用例" /> : visibleGroups.map((group) => (
                <button
                  key={group.key}
                  type="button"
                  onClick={() => { setSelectedKey(group.key); setSelectedCaseId(null); }}
                  style={{
                    display: 'block',
                    width: '100%',
                    textAlign: 'left',
                    border: 0,
                    borderRadius: 8,
                    padding: '8px 10px',
                    marginBottom: 4,
                    cursor: 'pointer',
                    background: group.key === selectedKey ? '#edf3ff' : 'transparent',
                  }}
                >
                  <span style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    {group.method ? <Tag color={METHOD_COLOR[group.method] ?? 'default'} style={{ marginInlineEnd: 0 }}>{group.method}</Tag> : null}
                    <Typography.Text strong ellipsis>{group.title}</Typography.Text>
                  </span>
                  <Typography.Text type="secondary" ellipsis style={{ display: 'block', fontSize: 12 }}>{group.subtitle}</Typography.Text>
                </button>
              ))}
            </div>
          </div>
        </Col>
        <Col flex="1 1 0" style={{ minWidth: 0 }}>
          <div style={{ border: '1px solid #f0f0f0', borderRadius: 8, padding: 16, height: 'calc(100vh - 230px)', minHeight: 380, overflow: 'auto' }}>
            {!selected ? <EmptyState description={objectFacet === 'API' ? '请在左侧选择一个接口' : '请在左侧选择一个测试点'} /> : (
              <>
                <Typography.Text type="secondary">{objectFacet === 'API' ? '接口名称' : '测试点'}</Typography.Text>
                <Typography.Title level={4} style={{ marginTop: 4 }}>{selected.title}</Typography.Title>
                {selected.method ? (
                  <Typography.Paragraph>
                    <Tag color={METHOD_COLOR[selected.method] ?? 'default'}>{selected.method}</Tag>
                    <Typography.Text code>{selected.path}</Typography.Text>
                  </Typography.Paragraph>
                ) : null}
                <CasePicker cases={selected.cases} selectedId={selectedCaseId} onSelect={setSelectedCaseId} />
                {selectedCaseId == null ? null : detailQuery.isPending ? <LoadingState /> : detailQuery.isError ? <ErrorState error={detailQuery.error} onRetry={detailQuery.refetch} /> : detailQuery.data ? <CaseContent detail={detailQuery.data} /> : <EmptyState description="没有获取到用例内容" />}
              </>
            )}
          </div>
        </Col>
      </Row>
    </PageContainer>
  );
}

/** 当前分组下的用例标题。点一条才加载它的前置条件、数据和断言。 */
function CasePicker({ cases, selectedId, onSelect }: { cases: TestCase[]; selectedId: number | null; onSelect: (id: number) => void }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 16 }}>
      {cases.map((item) => (
        <button
          key={item.id}
          type="button"
          onClick={() => onSelect(item.id)}
          style={{
            textAlign: 'left',
            border: '1px solid #e7eef6',
            borderRadius: 8,
            padding: '8px 12px',
            cursor: 'pointer',
            background: item.id === selectedId ? '#f3f7ff' : '#fff',
          }}
        >
          <Typography.Text strong>{item.name}</Typography.Text>
          <Typography.Text type="secondary" style={{ marginLeft: 8 }}>{item.priority} · {DIMENSION_LABEL[item.case_type] ?? item.case_type}</Typography.Text>
        </button>
      ))}
    </div>
  );
}

/** 用接口详情那样的说明表展示一条用例，不提供子表编辑。 */
function CaseContent({ detail }: { detail: TestCaseDetail }) {
  return (
    <>
      <Descriptions bordered size="small" column={2} style={{ marginBottom: 16 }}>
        <Descriptions.Item label="用例标题" span={2}>{detail.name}</Descriptions.Item>
        <Descriptions.Item label="优先级">{detail.priority}</Descriptions.Item>
        <Descriptions.Item label="类型">{DIMENSION_LABEL[detail.case_type] ?? detail.case_type}</Descriptions.Item>
        <Descriptions.Item label="状态">{detail.status}</Descriptions.Item>
        <Descriptions.Item label="启用">{detail.enabled ? '是' : '否'}</Descriptions.Item>
      </Descriptions>
      <Section title="前置条件">
        <Table
          size="small"
          pagination={false}
          rowKey="id"
          dataSource={detail.preconditions}
          locale={{ emptyText: '没有前置条件' }}
          columns={[
            { title: '类型', dataIndex: 'type', width: 120 },
            { title: '目标', dataIndex: 'target', width: 160, render: (value: string | null) => value || '-' },
            { title: '期望', dataIndex: 'expected_value', render: (value: string | null) => value || '-' },
          ]}
        />
      </Section>
      <Section title="测试数据">
        <Table
          size="small"
          pagination={false}
          rowKey="id"
          dataSource={detail.test_data}
          locale={{ emptyText: '没有测试数据' }}
          columns={[
            { title: '名称', dataIndex: 'name', width: 180 },
            { title: '来源', dataIndex: 'source_type', width: 120 },
            { title: '值', dataIndex: 'value', render: (value: string | null) => value || '-' },
          ]}
        />
      </Section>
      <Section title="断言">
        <Table
          size="small"
          pagination={false}
          rowKey="id"
          dataSource={detail.assertions}
          locale={{ emptyText: '没有断言' }}
          columns={[
            { title: '类型', dataIndex: 'assertion_type', width: 140 },
            { title: '路径', dataIndex: 'path', width: 180, render: (value: string | null) => value || '-' },
            { title: '操作', dataIndex: 'operator', width: 100 },
            { title: '期望', dataIndex: 'expected_value', render: (value: string | null) => value || '-' },
          ]}
        />
      </Section>
      <Section title="步骤">
        <Table
          size="small"
          pagination={false}
          rowKey="id"
          dataSource={detail.steps}
          locale={{ emptyText: '没有步骤' }}
          columns={[
            { title: '顺序', dataIndex: 'sort', width: 80 },
            { title: '类型', dataIndex: 'step_type', width: 120 },
            { title: '步骤', dataIndex: 'name' },
          ]}
        />
      </Section>
    </>
  );
}

/** 一块只读内容，标题和接口管理里的分区一致。 */
function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section style={{ marginBottom: 16 }}>
      <Typography.Title level={5}>{title}</Typography.Title>
      {children}
    </section>
  );
}
