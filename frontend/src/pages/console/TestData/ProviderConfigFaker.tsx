// FAKER Provider 配置：generator + locale。
//
// §9.4 FAKER：generator 决定 Faker 字段方法，locale 决定本地化。
import { Form, Input, Select } from 'antd';

interface ConfigProps {
  value: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
  projectId: number;
}

const FAKER_GENERATORS = [
  'name', 'first_name', 'last_name', 'email', 'phone_number',
  'user_name', 'password', 'uuid4', 'date_of_birth', 'address',
  'city', 'word', 'sentence', 'pyint', 'pyfloat', 'boolean',
  'credit_card_number', 'iban', 'swift', 'url', 'ipv4', 'mac_address',
];

const FAKER_LOCALES = ['zh_CN', 'en_US', 'en_GB', 'ja_JP', 'ko_KR', 'de_DE'];

/**
 * FAKER 配置。
 */
export function ProviderConfigFaker({ value, onChange }: ConfigProps) {
  return (
    <>
      <Form.Item label="generator" required>
        <Select
          showSearch
          value={(value.generator as string) ?? undefined}
          onChange={(v) => onChange({ ...value, generator: v })}
          options={FAKER_GENERATORS.map((g) => ({ label: g, value: g }))}
          placeholder="选择 Faker 字段方法"
        />
      </Form.Item>
      <Form.Item label="locale">
        <Select
          allowClear
          value={(value.locale as string) ?? undefined}
          onChange={(v) => onChange({ ...value, locale: v ?? '' })}
          options={FAKER_LOCALES.map((l) => ({ label: l, value: l }))}
          placeholder="zh_CN"
        />
      </Form.Item>
      <Form.Item label="变量名（可选）" tooltip="输出变量名，留空用 generator">
        <Input
          value={(value.variable_name as string) ?? ''}
          onChange={(e) => onChange({ ...value, variable_name: e.target.value })}
          placeholder="如 username"
        />
      </Form.Item>
    </>
  );
}
