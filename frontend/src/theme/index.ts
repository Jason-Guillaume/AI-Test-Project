// 全局设计系统：唯一的 antd 主题配置（ThemeConfig）。
//
// 设计原则（对应重构计划 §2）：
// - 8px 基础间距体系：沿用 antd 的 4×4 网格（sizeUnit=4, sizeStep=4），与代码库里
//   实测分布的 8/12/16/24 完全一致，不改基线，避免全站排版位移。
// - 中性色为主体，品牌色只用于主要操作与选中状态：只给一个 colorPrimary 种子，
//   所有主色浅底（colorPrimaryBg 等）交给 algorithm 派生，不写死。
// - 当前产品界面固定使用浅色主题；Ant Design 颜色由 defaultAlgorithm 派生。
// - 单一真源：本文件是全项目唯一主题入口，唯一 ConfigProvider 在 QueryProvider.tsx。
//   业务代码取设计值一律走 theme.useToken()，禁止再新增裸 hex。
//
// 注意：components 里每个键都必须是当前 antd 版本（5.29）真实存在的 ComponentToken。
// 已验证的无效键（勿回加）：Menu.itemPaddingBlock、Table.headerTitleFontSize、
// Statistic.titleColor、Typography.titleMarginLG/headingMargin*、Modal.headerPadding*、
// Drawer.headerBg/headerHeight、Alert.messageFontSize/descriptionFontSize、
// Progress.successColor、Descriptions.borderedLabelBg、Tabs.itemPadding*/itemMarginInline、
// Form.labelColonMarginRight、Select.selectorHeight。

import type { ThemeConfig } from 'antd';
import { theme as antdTheme } from 'antd';

/** 与深浅模式无关的尺寸、字体、圆角种子：两种 algorithm 共用。 */
const sharedSeeds = {
  // 圆角三档：对齐代码库实测的 4 / 6 / 8
  borderRadius: 8,
  borderRadiusSM: 6,
  borderRadiusLG: 12,
  // 8px 基础间距体系：4×4 网格
  sizeUnit: 4,
  sizeStep: 4,
  // 字号：实测 12 为次要文字、13 为表格、14 为正文，保持 antd 默认层级
  fontSize: 14,
  fontSizeSM: 12,
  fontSizeLG: 16,
  fontSizeXL: 20,
  fontWeightStrong: 600,
  fontFamily:
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif",
  fontFamilyCode: "'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace",
  lineHeight: 1.5714,
};

/** 浅色模式种子：品牌色 + 语义色 + 两个底色种子。 */
const lightSeeds = {
  // 品牌蓝更柔和，减少默认高饱和蓝在大面积操作区里的压迫感。
  colorPrimary: '#4F70E7',
  colorInfo: '#4F70E7',
  colorLink: '#4F70E7',
  // 语义色与代码库现有用法完全一致（#52c41a / #FAAD14 / #FF4D4F），
  // 统一后所有状态色改由 token 派生，删除业务代码里的裸 hex。
  colorSuccess: '#52C41A',
  colorWarning: '#FAAD14',
  colorError: '#FF4D4F',
  // 企业墨色：比纯黑柔和，同时驱动 colorTextSecondary/Tertiary/Quaternary
  // 与 colorBorder 的自动派生。
  colorTextBase: '#1F2329',
  colorBgBase: '#FFFFFF',
};

/**
 * 深色模式种子：不写任何颜色，让 darkAlgorithm 从 colorPrimary 反算整条色阶。
 * 见文件顶部 ⚠️ 说明。
 */
const darkSeeds = {};

/**
 * 组件级覆盖。只覆盖确需调整的组件。
 */
const components: ThemeConfig['components'] = {
  // Layout：顶部栏与容器同色，靠边框分隔。侧栏底色由 ConsoleLayout/AdminLayout
  // 按模式显式设置（Sider 的 theme 属性会覆盖这里的 token）。
  Layout: {
    headerBg: 'token.colorBgContainer',
    headerHeight: 68,
    headerPadding: '0 28px',
    bodyBg: 'token.colorBgLayout',
  },
  // Menu：选中用主色浅底而非实底，贴合「品牌色只用于选中状态」。
  Menu: {
    itemHeight: 40,
    itemMarginInline: 8,
    itemPaddingInline: 12,
    itemBorderRadius: 9,
    itemColor: 'token.colorText',
    itemHoverBg: 'token.colorFillTertiary',
    itemSelectedBg: 'token.colorPrimaryBg',
    itemSelectedColor: 'token.colorPrimary',
    subMenuItemBg: 'transparent',
  },
  // Table：全项目 53 处，收益最大的一块。表头走最浅填充并压掉纵向分割线。
  Table: {
    headerBg: 'token.colorFillQuaternary',
    headerColor: 'token.colorTextHeading',
    headerSplitColor: 'transparent',
    borderColor: 'token.colorBorderSecondary',
    headerBorderRadius: 6,
    rowHoverBg: 'token.colorFillQuaternary',
    rowSelectedBg: 'token.colorPrimaryBg',
    rowSelectedHoverBg: 'token.colorPrimaryBgHover',
    cellPaddingBlock: 10,
    cellPaddingInline: 12,
  },
  // Card：现状 44 处多用 size="small"，整体收一档内边距。
  Card: {
    paddingLG: 16,
    borderRadiusLG: 12,
  },
  // Statistic：现状 24 处，其中大量 valueStyle 写死 hex。
  // 这里只统一字号，颜色由 MetricCard 用 token 显式传入。
  Statistic: {
    titleFontSize: 12,
    contentFontSize: 22,
  },
  // Tag：现状约 180 处。裸 Tag 与 color="default" 走这组 token；
  // 带预设色名（green/red/...）的 Tag 不受影响，这正好是 StatusBadge 的落点。
  Tag: {
    defaultBg: 'token.colorFillQuaternary',
    defaultColor: 'token.colorTextSecondary',
    borderRadiusSM: 4,
    fontSize: 12,
    lineHeight: 1.5,
  },
  // Typography：把原先散落的 #999 / #666 语义固化到 token。
  Typography: {
    colorTextHeading: 'token.colorTextBase',
    colorTextDescription: 'token.colorTextTertiary',
    titleMarginTop: 0,
    colorLinkHover: 'token.colorPrimaryHover',
  },
  // Modal：69 处，统一标题字号与底部背景。
  Modal: {
    borderRadiusLG: 8,
    titleFontSize: 16,
    footerBg: 'transparent',
  },
  // Alert：52 处。注意约 12 处是脱敏/权限说明，改样式不影响其语义。
  Alert: {
    defaultPadding: '8px 12px',
    borderRadiusLG: 6,
  },
  // Progress：2 处，原 strokeColor 写死 hex，改由 defaultColor 统一。
  Progress: {
    lineWidth: 6,
    defaultColor: 'token.colorPrimary',
  },
  // Descriptions：68 处，最密集的组件之一。
  Descriptions: {
    fontSize: 13,
    labelBg: 'transparent',
  },
  // Tabs：Phase B 会把报告页的多 Tab 结构拆掉，这里只统一间距。
  Tabs: {
    horizontalItemGutter: 16,
    itemSelectedColor: 'token.colorPrimary',
    itemHoverColor: 'token.colorPrimary',
    inkBarColor: 'token.colorPrimary',
  },
  // Button：统一小按钮高度，表格操作列密度对齐。
  Button: {
    borderRadius: 8,
    controlHeightSM: 26,
    fontSize: 14,
    paddingInline: 12,
  },
  // Form：筛选工具栏与表单统一间距。
  Form: {
    itemMarginBottom: 16,
    labelFontSize: 13,
  },
  // Select：筛选工具栏的控件密度。
  Select: {
    borderRadiusLG: 6,
    controlPaddingHorizontal: 8,
  },
};

/**
 * 构造主题配置。
 *
 * @param dark 是否使用深色算法。
 * @returns 可直接传给 ConfigProvider 的 ThemeConfig。
 */
export function buildTheme(dark = false): ThemeConfig {
  return {
    algorithm: dark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
    token: { ...sharedSeeds, ...(dark ? darkSeeds : lightSeeds) },
    components,
  };
}
