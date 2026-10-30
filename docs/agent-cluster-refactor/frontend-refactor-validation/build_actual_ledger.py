#!/usr/bin/env python3
"""Build the U0->U12 per-file migration record from the frozen inventory and current tree."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / 'frontend' / 'src'
BASELINE = ROOT / 'docs' / 'agent-cluster-refactor' / 'frontend-file-migration-map.json'
OUT = Path(__file__).resolve().parent

SPLITS = {
    'App.tsx': ['app/App.tsx', 'app/providers/AuthProvider.tsx', 'app/providers/ConsoleScopeProvider.tsx', 'app/router/AppErrorBoundary.tsx'],
    'components/QueryProvider.tsx': ['app/providers/AppProviders.tsx'],
    'hooks/useAuth.tsx': ['app/providers/AuthProvider.tsx'],
    'hooks/useConsoleScope.tsx': ['app/providers/ConsoleScopeProvider.tsx'],
    'components/RouteGuards.tsx': ['app/router/RouteGuards.tsx'],
    'components/ResultPages.tsx': ['pages/errors/ResultPages.tsx'],
    'components/JsonView.tsx': ['shared/ui/JsonView.tsx'],
    'components/DetailDrawer.tsx': ['shared/ui/DetailDrawer.tsx'],
    'components/FilterToolbar.tsx': ['shared/ui/FilterToolbar.tsx'],
    'components/MetricCard.tsx': ['shared/ui/MetricCard.tsx'],
    'components/PageHeader.tsx': ['shared/ui/PageHeader.tsx'],
    'components/PageState.tsx': ['shared/ui/PageState.tsx'],
    'components/ResourceTable.tsx': ['shared/ui/ResourceTable.tsx'],
    'components/RoleTag.tsx': ['features/identity/components/RoleTag.tsx'],
    'components/StatusBadge.tsx': ['shared/ui/StatusBadge.tsx'],
    'components/exec/CaseExecutionDetail.tsx': ['widgets/execution-detail/CaseExecutionDetail.tsx', 'widgets/execution-detail/ExecutionDetailPanel.tsx'],
    'components/exec/AssertionViewer.tsx': ['widgets/execution-detail/AssertionViewer.tsx'],
    'components/exec/DefectOrigins.tsx': ['widgets/execution-detail/DefectOrigins.tsx'],
    'components/exec/DefectSourceLinks.tsx': ['widgets/execution-detail/DefectSourceLinks.tsx'],
    'components/exec/ExecutionTimeline.tsx': ['widgets/execution-detail/ExecutionTimeline.tsx'],
    'components/exec/ScreenshotViewer.tsx': ['widgets/execution-detail/ScreenshotViewer.tsx'],
    'components/exec/TraceViewer.tsx': ['widgets/execution-detail/TraceViewer.tsx'],
    'components/exec/types.ts': ['widgets/execution-detail/types.ts'],
    'components/tasks/TaskCreateModal.tsx': ['widgets/task-assistant/TaskCreateModal.tsx'],
    'components/tasks/TaskSchedulerDrawer.tsx': ['widgets/task-assistant/TaskSchedulerDrawer.tsx'],
    'components/tasks/TaskSourceLinks.tsx': ['features/tasks/components/TaskSourceLinks.tsx'],
    'hooks/useCapabilities.ts': ['features/identity/hooks/useCapabilities.ts'],
    'pages/admin/AgentGovernance.tsx': ['pages/admin/AgentGovernance.tsx', 'pages/admin/AgentGovernance/AgentPane.tsx', 'pages/admin/AgentGovernance/McpPane.tsx', 'pages/admin/AgentGovernance/SkillPane.tsx', 'pages/admin/AgentGovernance/ToolsPane.tsx'],
    'pages/console/TestManagement/TestAsset.tsx': ['pages/console/TestManagement/TestAsset.tsx', 'pages/console/TestManagement/TestAssetWorkspace.tsx', 'pages/console/TestManagement/TestAssetDialogs.tsx', 'pages/console/TestManagement/TestAssetEditTabs.tsx', 'pages/console/TestManagement/TestAssetExecutionTabs.tsx'],
    'pages/console/Agent/AgentPage.tsx': ['pages/console/Agent/AgentPage.tsx', 'pages/console/Agent/AgentPanels.tsx', 'pages/console/Agent/AgentWorkspacePanel.tsx'],
    'pages/console/WebUIAgent/index.tsx': ['pages/console/WebUIAgent/index.tsx', 'pages/console/WebUIAgent/webAgentPanels.tsx'],
    'pages/console/Reports/ReportDetail.tsx': ['pages/console/Reports/ReportDetail.tsx', 'pages/console/Reports/ReportOverview.tsx', 'pages/console/Reports/ReportWorkspace.tsx', 'pages/console/Reports/ReportSummaryPanels.tsx', 'pages/console/Reports/ReportFailureClusterGrid.tsx'],
    'pages/console/SecurityTesting/CasesTab.tsx': ['pages/console/SecurityTesting/CasesTab.tsx', 'pages/console/SecurityTesting/PlanPreviewModal.tsx'],
    'pages/console/SecurityTesting/StrategyTab.tsx': ['pages/console/SecurityTesting/StrategyTab.tsx', 'pages/console/SecurityTesting/StrategyFormModals.tsx', 'pages/console/SecurityTesting/SecuritySettingModal.tsx', 'pages/console/SecurityTesting/strategyConstants.ts'],
    'pages/console/SecurityTesting/zap/jobPanels.tsx': ['pages/console/SecurityTesting/zap/panels/JobEventsPanel.tsx', 'pages/console/SecurityTesting/zap/panels/JobAlertsPanel.tsx', 'pages/console/SecurityTesting/zap/panels/JobCoveragePanel.tsx', 'pages/console/SecurityTesting/zap/panels/JobFindingsPanel.tsx', 'pages/console/SecurityTesting/zap/panels/JobReportPanel.tsx', 'pages/console/SecurityTesting/zap/panels/ScanJobStatusBadge.tsx', 'pages/console/SecurityTesting/zap/panels/constants.ts'],
    'pages/console/SecurityTesting/zap/policies.tsx': ['pages/console/SecurityTesting/zap/policies.tsx', 'pages/console/SecurityTesting/zap/ScanProfiles.tsx', 'pages/console/SecurityTesting/zap/AuthProfiles.tsx', 'pages/console/SecurityTesting/zap/policyUtils.ts'],
    'pages/console/MockManagement/ServiceList.tsx': ['pages/console/MockManagement/ServiceList.tsx', 'pages/console/MockManagement/components/TokenResultModal.tsx', 'pages/console/MockManagement/components/ServiceFormModal.tsx', 'pages/console/MockManagement/components/FromApiModal.tsx'],
    'pages/console/MockManagement/ExecutionList.tsx': ['pages/console/MockManagement/ExecutionList.tsx', 'pages/console/MockManagement/components/MockContextsCard.tsx', 'pages/console/MockManagement/components/MockExecutionDrawer.tsx', 'pages/console/MockManagement/components/contextPresentation.ts'],
    'pages/console/MockManagement/ScenarioEditor.tsx': ['pages/console/MockManagement/ScenarioEditor.tsx', 'pages/console/MockManagement/ScenarioTestDrawer.tsx', 'pages/console/MockManagement/scenarioFormUtils.ts'],
    'shared/format.ts': ['shared/lib/format.ts'],
    'shared/options.ts': ['shared/lib/options.ts'],
    'shared/notify.ts': ['features/notifications/constants.ts'],
    'shared/status.ts': ['features/test-management/status.ts', 'features/reports/status.ts', 'features/web-testing/status.ts'],
    'shared/webSnapshot.ts': ['features/web-testing/lib/webSnapshot.ts'],
    'types/index.ts': ['features/agent/contracts.ts', 'features/agent-governance/contracts.ts', 'features/api-catalog/contracts.ts', 'features/browser-authoring/contracts.ts', 'features/defects/contracts.ts', 'features/environments/contracts.ts', 'features/identity/contracts.ts', 'features/mocking/contracts.ts', 'features/notifications/contracts.ts', 'features/projects/contracts.ts', 'features/reports/contracts.ts', 'features/security-testing/contracts.ts', 'features/tasks/contracts.ts', 'features/test-data/contracts.ts', 'features/test-management/contracts.ts', 'features/web-testing/contracts.ts', 'shared/api/contracts.ts'],
    'api/securityTesting.ts': ['features/security-testing/api/securityTesting.ts', 'features/security-testing/zap/api.ts', 'features/security-testing/contracts.ts', 'features/security-testing/zap/contracts.ts'],
    'api/webUI.ts': ['features/web-testing/api/webUI.ts', 'features/browser-authoring/api.ts', 'features/browser-authoring/contracts.ts'],
}

source_files = sorted(p for p in SRC.rglob('*') if p.is_file() and p.suffix in {'.ts', '.tsx', '.css', '.mjs'})
current = {p.relative_to(SRC).as_posix(): p for p in source_files}
baseline = json.loads(BASELINE.read_text())['entries']
ledger = []
for entry in baseline:
    old = entry['source'].removeprefix('frontend/src/')
    targets = SPLITS.get(old)
    if targets is None:
        if old in current:
            targets = [old]
        else:
            candidates = [name for name in current if Path(name).name == Path(old).name]
            if len(candidates) == 1:
                targets = candidates
            else:
                hints = [x.removeprefix('frontend/src/') for x in entry.get('proposedTargets', []) if not x.endswith('/')]
                narrowed = [name for name in candidates if any(name == h or name.endswith('/' + Path(h).name) for h in hints)]
                if len(narrowed) == 1:
                    targets = narrowed
                else:
                    raise RuntimeError(f'Cannot map {old}: {candidates}')
    absent = [t for t in targets if t not in current]
    if absent:
        raise RuntimeError(f'Missing actual target(s) for {old}: {absent}')
    status = 'split' if len(targets) > 1 else ('retained' if targets[0] == old else 'moved')
    ledger.append({
        'source': entry['source'],
        'baselineSha256': entry['sourceSha256'],
        'baselineLines': entry['sourceLines'],
        'workPackage': entry['workPackage'],
        'outcome': status,
        'actualTargets': ['frontend/src/' + t for t in targets],
        'action': entry['action'],
    })

target_set = {t.removeprefix('frontend/src/') for row in ledger for t in row['actualTargets']}
extras = [f'frontend/src/{name}' for name in sorted(current) if name not in target_set]
inventory = []
for name, path in sorted(current.items()):
    data = path.read_bytes()
    text = data.decode('utf-8', errors='replace')
    inventory.append({'path': f'frontend/src/{name}', 'lines': len(text.splitlines()), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
summary = {
    'baselineSources': len(ledger),
    'baselineRetained': sum(x['outcome'] == 'retained' for x in ledger),
    'baselineMoved': sum(x['outcome'] == 'moved' for x in ledger),
    'baselineSplit': sum(x['outcome'] == 'split' for x in ledger),
    'currentSourceFiles': len(inventory),
    'newCurrentFilesNotMappedFromBaseline': len(extras),
    'currentLines': sum(x['lines'] for x in inventory),
    'currentFilesOver500Lines': [x['path'] for x in inventory if x['lines'] > 500],
}
(OUT / 'frontend-actual-migration-ledger.json').write_text(json.dumps({'generatedAt': '2026-10-30', 'summary': summary, 'entries': ledger, 'newFiles': extras}, ensure_ascii=False, indent=2) + '\n')
(OUT / 'frontend-current-file-inventory.json').write_text(json.dumps({'generatedAt': '2026-10-30', 'summary': summary, 'files': inventory}, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(summary, ensure_ascii=False, indent=2))
