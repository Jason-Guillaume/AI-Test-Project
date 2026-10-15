// Fixture Cleanup 步骤列表：复用 FixtureStepList，phase=CLEANUP。
//
// §7.3：Cleanup 同一 FixtureStepList，phase=CLEANUP。
import { FixtureStepList } from './FixtureStepList';
import type { FixtureDetail } from '@/types';

/** Cleanup 步骤表，行为与生成流程一致，仅 phase 不同。 */
export function FixtureCleanupList({ fixture }: { fixture: FixtureDetail }) {
  return <FixtureStepList fixture={fixture} phase="CLEANUP" />;
}
