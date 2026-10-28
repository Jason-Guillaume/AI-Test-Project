// Fixture 输出契约表。
//
// §7.3：可编辑 name / value_type / source_path。保存一次 PUT 整表（PUT /fixtures/{id}/outputs）。
// 输出名在项目内唯一，冲突时后端返回 409，用 message.error 展示。
import { useEffect, useState } from 'react';
import { App, Button, Input, Popconfirm, Select, Space, Table } from 'antd';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { testDataApi } from '@/api/testData';
import { getErrorMessage } from '@/api/client';
import { VALUE_TYPE_OPTIONS } from './constants';
import type { FixtureDetail, FixtureOutputInput, ValueType } from '@/types';

interface Row {
  key: string;
  name: string;
  value_type: ValueType;
  source_path: string;
  description: string;
}

let rowSeq = 0;
const nextKey = () => `out_${Date.now()}_${rowSeq++}`;

/**
 * 输出契约表：行内编辑，新增/删除行，保存走整表 PUT。
 */
export function FixtureOutputTable({ fixture }: { fixture: FixtureDetail }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [rows, setRows] = useState<Row[]>([]);

  useEffect(() => {
    setRows(
      (fixture.outputs ?? []).map((o) => ({
        key: nextKey(),
        name: o.name,
        value_type: o.value_type,
        source_path: o.source_path,
        description: o.description ?? '',
      })),
    );
    // 仅在 outputs 引用变化时重置，避免编辑中被覆盖。
  }, [fixture.outputs]);

  const mutation = useMutation({
    mutationFn: (outputs: FixtureOutputInput[]) =>
      testDataApi.replaceOutputs(fixture.id, { outputs }),
    onSuccess: () => {
      message.success('输出已保存');
      queryClient.invalidateQueries({ queryKey: ['test-data', 'fixture', fixture.id] });
      queryClient.invalidateQueries({ queryKey: ['test-data', 'fixtures'] });
    },
    onError: (e) => message.error(getErrorMessage(e, '保存失败')),
  });

  const handleSave = () => {
    // 校验：名称与 source_path 必填，名称不重复。
    const names = rows.map((r) => r.name.trim());
    if (names.some((n) => !n)) {
      message.error('每行输出名称不能为空');
      return;
    }
    if (new Set(names).size !== names.length) {
      message.error('输出名称不能重复');
      return;
    }
    if (rows.some((r) => !r.source_path.trim())) {
      message.error('每行 source_path 不能为空');
      return;
    }
    const payload: FixtureOutputInput[] = rows.map((r, i) => ({
      name: r.name.trim(),
      value_type: r.value_type,
      source_path: r.source_path.trim(),
      description: r.description || null,
      sort: i + 1,
    }));
    mutation.mutate(payload);
  };

  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        <Button
          onClick={() =>
            setRows((rs) => [
              ...rs,
              { key: nextKey(), name: '', value_type: 'STRING', source_path: '', description: '' },
            ])
          }
        >
          新增输出
        </Button>
        <Button type="primary" loading={mutation.isPending} onClick={handleSave}>
          保存
        </Button>
      </Space>
      <Table<Row>
        rowKey="key"
        dataSource={rows}
        pagination={false}
        size="middle"
        columns={[
          {
            title: '#',
            width: 50,
            render: (_: unknown, __: Row, i: number) => i + 1,
          },
          {
            title: '名称',
            dataIndex: 'name',
            render: (_: unknown, r: Row) => (
              <Input
                value={r.name}
                onChange={(e) =>
                  setRows((rs) => rs.map((x) => (x.key === r.key ? { ...x, name: e.target.value } : x)))
                }
              />
            ),
          },
          {
            title: '类型',
            dataIndex: 'value_type',
            width: 150,
            render: (_: unknown, r: Row) => (
              <Select
                style={{ width: '100%' }}
                value={r.value_type}
                onChange={(v) =>
                  setRows((rs) => rs.map((x) => (x.key === r.key ? { ...x, value_type: v } : x)))
                }
                options={VALUE_TYPE_OPTIONS}
              />
            ),
          },
          {
            title: 'source_path',
            dataIndex: 'source_path',
            render: (_: unknown, r: Row) => (
              <Input
                value={r.source_path}
                onChange={(e) =>
                  setRows((rs) =>
                    rs.map((x) => (x.key === r.key ? { ...x, source_path: e.target.value } : x)),
                  )
                }
                placeholder="如 data.id 或 ."
              />
            ),
          },
          {
            title: '操作',
            width: 80,
            render: (_: unknown, r: Row) => (
              <Popconfirm
                title="删除该输出？"
                okText="删除"
                okButtonProps={{ danger: true }}
                cancelText="取消"
                onConfirm={() => setRows((rs) => rs.filter((x) => x.key !== r.key))}
              >
                <a style={{ color: '#ff4d4f' }}>删除</a>
              </Popconfirm>
            ),
          },
        ]}
      />
    </>
  );
}
