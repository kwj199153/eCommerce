<template>
  <a-config-provider :locale="zhCN" :theme="themeStore.antdTheme">
    <router-view />
  </a-config-provider>
</template>

<script setup lang="ts">
import zhCN from 'ant-design-vue/es/locale/zh_CN'
import { useThemeStore } from '@/stores/theme'

const themeStore = useThemeStore()
</script>

<style>
/* 全局样式 */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html, body, #app {
  width: 100%;
  height: 100%;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
    'Helvetica Neue', Arial, 'Noto Sans', sans-serif, 'Apple Color Emoji',
    'Segoe UI Emoji', 'Segoe UI Symbol', 'Noto Color Emoji';
  background-color: #f5f7fa;
  color: #1a1a1a;
  transition: background-color 0.2s, color 0.2s;
}

/* ====== 全局 CSS 变量（亮色基线）。所有页面不要再写死 #fff / #f0f0f0 / #262626 等，改用 var(--xxx) ====== */
:root {
  --bg-base: #f5f7fa;
  --bg-elevated: #ffffff;       /* 主面板/卡片背景 */
  --bg-toolbar: #ffffff;        /* header / 顶部栏 */
  --bg-hover-light: #f5f5f5;    /* light 模式 hover */
  --bg-hover-dark: rgba(255, 255, 255, 0.06);
  --bg-active-light: #e6f7ff;
  --bg-active-dark: rgba(22, 119, 255, 0.18);
  --bg-sidebar: #fafafa;
  --bg-card-pill: #f0f0f0;      /* 小徽标/标签 */

  --border-base: #f0f0f0;
  --border-strong: #d9d9d9;

  --text-primary: #262626;
  --text-secondary: #595959;
  --text-tertiary: #8c8c8c;
  --text-disabled: #bfbfbf;
  --text-inverse: #ffffff;

  --primary: #1890ff;
  --primary-hover: #40a9ff;
  --danger: #ff4d4f;
  --success: #389e0d;
  --warning: #ad6800;
  --purple: #722ed1;

  /* 浅色状态底色（载入、选中 chip 等用） */
  --success-bg: #f6ffed;
  --success-border: #b7eb8f;
  --info-bg: #e6f7ff;
  --info-border: #91d5ff;
  --purple-bg: #f9f0ff;
  --purple-border: #efdbff;
  --warning-bg: #fffbe6;
  --warning-border: #ffe58f;
}

/* dark 模式覆盖变量 —— watch(effective) 自动同步 */
html.dark {
  --bg-base: #141414;
  --bg-elevated: #1f1f1f;
  --bg-toolbar: #141414;
  --bg-hover-light: rgba(255, 255, 255, 0.06);
  --bg-hover-dark: rgba(255, 255, 255, 0.06);
  --bg-active-light: rgba(22, 119, 255, 0.18);
  --bg-active-dark: rgba(22, 119, 255, 0.18);
  --bg-sidebar: #141414;
  --bg-card-pill: #262626;

  --border-base: #303030;
  --border-strong: #434343;

  --text-primary: rgba(255, 255, 255, 0.92);
  --text-secondary: rgba(255, 255, 255, 0.65);
  --text-tertiary: rgba(255, 255, 255, 0.45);
  --text-disabled: rgba(255, 255, 255, 0.25);
  --text-inverse: #1f1f1f;

  --primary: #177ddc;
  --primary-hover: #3d9be6;
  --danger: #ff7875;
  --success: #73d13d;
  --warning: #ffc53d;
  --purple: #b37feb;

  /* 深色状态底色（半透明品牌色，深底自然融合） */
  --success-bg: rgba(82, 196, 26, 0.12);
  --success-border: rgba(82, 196, 26, 0.4);
  --info-bg: rgba(24, 144, 255, 0.12);
  --info-border: rgba(24, 144, 255, 0.4);
  --purple-bg: rgba(114, 46, 209, 0.12);
  --purple-border: rgba(114, 46, 209, 0.4);
  --warning-bg: rgba(250, 173, 20, 0.12);
  --warning-border: rgba(250, 173, 20, 0.4);
}
html.dark, html.dark body, html.dark #app {
  background-color: var(--bg-base);
  color: var(--text-primary);
}

/* ====== 暗色模式派生：硬编码白色背景的常见 antd 组件 ====== */
html.dark .ant-layout,
html.dark .ant-layout-content,
html.dark .ant-layout-header,
html.dark .ant-layout-sider,
html.dark .ant-table,
html.dark .ant-card,
html.dark .ant-modal-content,
html.dark .ant-popover-inner,
html.dark .ant-dropdown-menu {
  background-color: var(--bg-elevated) !important;
  color: var(--text-primary) !important;
}
html.dark .ant-table-thead > tr > th,
html.dark .ant-table-tbody > tr > td {
  background-color: var(--bg-elevated) !important;
  border-bottom-color: var(--border-base) !important;
}
html.dark .ant-divider {
  border-color: var(--border-base) !important;
}
html.dark .ant-empty-description,
html.dark .ant-typography {
  color: var(--text-secondary) !important;
}
html.dark .ant-tag {
  border-color: var(--border-base);
}
html.dark input.ant-input,
html.dark textarea.ant-input,
html.dark .ant-input-affix-wrapper {
  background-color: #262626 !important;
  color: var(--text-primary) !important;
  border-color: var(--border-base) !important;
}

/* ====== Dropdown / Menu / SubMenu ====== */
html.dark .ant-dropdown .ant-dropdown-menu,
html.dark .ant-dropdown .ant-dropdown-menu .ant-menu-sub {
  background-color: var(--bg-elevated) !important;
}
html.dark .ant-dropdown .ant-dropdown-menu .ant-menu-item,
html.dark .ant-dropdown .ant-dropdown-menu .ant-menu-submenu-title {
  background-color: transparent !important;
  color: var(--text-primary) !important;
}
html.dark .ant-dropdown .ant-dropdown-menu .ant-menu-item:hover,
html.dark .ant-dropdown .ant-dropdown-menu .ant-menu-submenu-title:hover {
  background-color: var(--bg-hover-dark) !important;
  color: var(--text-primary) !important;
}
html.dark .ant-dropdown .ant-dropdown-menu .ant-menu-item-selected,
html.dark .ant-dropdown .ant-dropdown-menu .ant-menu-submenu-selected {
  background-color: var(--bg-active-dark) !important;
  color: var(--primary) !important;
}
html.dark .ant-dropdown .ant-dropdown-menu .ant-menu-item-divider,
html.dark .ant-dropdown .ant-dropdown-menu .ant-menu-divider {
  background-color: var(--border-base) !important;
}
html.dark .ant-dropdown .ant-dropdown-menu .ant-menu-item .anticon,
html.dark .ant-dropdown .ant-dropdown-menu .ant-menu-submenu-title .anticon {
  color: var(--text-secondary) !important;
}
html.dark .ant-dropdown .ant-dropdown-menu .ant-menu-submenu-arrow::before,
html.dark .ant-dropdown .ant-dropdown-menu .ant-menu-submenu-arrow::after {
  background: linear-gradient(
    135deg,
    transparent 0%,
    transparent 50%,
    rgba(255, 255, 255, 0.45) 50%,
    rgba(255, 255, 255, 0.45)
  ) !important;
}

/* ====== Popover 内嵌内容 ====== */
html.dark .ant-popover-inner-content {
  background-color: var(--bg-elevated) !important;
  color: var(--text-primary) !important;
}
html.dark .ant-popover-arrow::before,
html.dark .ant-popover-arrow::after {
  background: var(--bg-elevated) !important;
}

/* ====== Tabs / Drawer / Select / Radio ====== */
html.dark .ant-tabs-tab,
html.dark .ant-tabs-tab-active,
html.dark .ant-drawer-content,
html.dark .ant-drawer-header,
html.dark .ant-select-selector,
html.dark .ant-radio-button-wrapper {
  background-color: var(--bg-elevated) !important;
  color: var(--text-primary) !important;
  border-color: var(--border-base) !important;
}
html.dark .ant-radio-button-wrapper-checked:not(.ant-radio-button-wrapper-disabled) {
  background: var(--primary) !important;
  border-color: var(--primary) !important;
  color: #fff !important;
}
html.dark .ant-radio-button-wrapper:hover {
  color: var(--primary) !important;
}
html.dark .ant-select-dropdown {
  background-color: var(--bg-elevated) !important;
  border-color: var(--border-base) !important;
}
html.dark .ant-select-item-option-content,
html.dark .ant-select-item {
  color: var(--text-primary) !important;
}
html.dark .ant-select-item-option:hover:not(.ant-select-item-option-disabled) {
  background-color: var(--bg-hover-dark) !important;
}

/* ====== Message（顶部提示） ====== */
html.dark .ant-message-notice-content {
  background: var(--bg-elevated) !important;
  color: var(--text-primary) !important;
  border: 1px solid var(--border-base);
}
html.dark .ant-message-notice-content .anticon {
  color: var(--text-secondary);
}

/* ====== Modal / Drawer 遮罩 ====== */
html.dark .ant-modal-mask,
html.dark .ant-drawer-mask {
  background: rgba(0, 0, 0, 0.65) !important;
}

/* ====== Layout 硬编码背景（workspace container 这些 scoped 不被全局接管的地方靠这里强制） ====== */
html.dark .workspace-container,
html.dark .workspace-container .ant-layout-sider,
html.dark .workspace-container .main-content,
html.dark .workspace-container .header,
html.dark .workspace-container .chat-area,
html.dark .workspace-container .right-panel,
html.dark .workspace-container .sidebar,
html.dark .workspace-container .logo-row {
  background-color: var(--bg-elevated) !important;
  color: var(--text-primary) !important;
  border-color: var(--border-base) !important;
}
html.dark .workspace-container .right-panel,
html.dark .workspace-container .sidebar {
  border-color: var(--border-base) !important;
}
html.dark .workspace-container .header,
html.dark .workspace-container .logo-row {
  border-color: var(--border-base) !important;
}

/* ====== 滚动条样式 ====== */
::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

::-webkit-scrollbar-thumb {
  background-color: var(--border-strong);
  border-radius: 3px;
}

::-webkit-scrollbar-track {
  background-color: transparent;
}

html.dark ::-webkit-scrollbar-thumb {
  background-color: var(--border-strong);
}

/* ====== 全局深色补丁：覆盖工具/结果组件中常见的硬编码亮色（scoped 样式无法被变量接管，需 !important 强制） ====== */

/* 结果卡片容器背景 */
html.dark [class*="-result"],
html.dark [class*="-result"] .ant-card,
html.dark .result-panel, html.dark .price-summary,
html.dark .profit-highlight, html.dark .overview-card,
html.dark .preview-card, html.dark .competitor-card,
html.dark .position-chart, html.dark .insight-card,
html.dark .review-item, html.dark .metric-card,
html.dark .budget-card, html.dark .imp-item,
html.dark .risk-low, html.dark .risk-medium, html.dark .risk-high,
html.dark .anomaly-card, html.dark .detect-overview,
html.dark .issue-item, html.dark .change, html.dark .m-deviation,
html.dark .swot-box, html.dark .swot-item,
html.dark .helper-hint, html.dark .form-actions,
html.dark .filter-group, html.dark .results-bar,
html.dark .title-thumb, html.dark .title-thumb-ph,
html.dark .compact-toolbar, html.dark .rationale-box,
html.dark .improvement-grid, html.dark .section-header,
html.dark .action-bar, html.dark .group-title,
html.dark .analyzer-header, html.dark .compare-header,
html.dark .buybox-card, html.dark .practices-box,
html.dark .dimensions-section, html.dark .value-ranking,
html.dark .diff-section, html.dark .cost-row,
html.dark .drow, html.dark .dkpi-row,
html.dark .hc-row, html.dark .sov-card,
html.dark .insights-box, html.dark .intruder-result,
html.dark .ad-diagnosis-result, html.dark .bid-optimize-result,
html.dark .budget-alloc-result, html.dark .compare-grid-result,
html.dark .blue-ocean-result, html.dark .buybox-analysis-result,
html.dark .competitor-ad-result, html.dark .competitor-intel-evidence,
html.dark .ab-test-generator, html.dark .aigc-media-result,
html.dark .bullet-generator, html.dark .description-generator,
html.dark .keyword-miner-result, html.dark .profit-calculator,
html.dark .store-context-bar {
  background-color: var(--bg-elevated) !important;
  border-color: var(--border-base) !important;
}

/* 主文字色 #262626 / #333 / #444 / #434343 / #555 */
html.dark .tool-btn, html.dark .action-text, html.dark .analyzing-state h3,
html.dark .anomaly-type, html.dark .budget-card .value, html.dark .card-brand,
html.dark .change-down, html.dark .change-up, html.dark .comp-name,
html.dark .conclusion-header, html.dark .conclusion-summary, html.dark .cost-row b,
html.dark .dimension-card h5, html.dark .dkpi-val, html.dark .drow b,
html.dark .ds-value, html.dark .group-title, html.dark .hc-value,
html.dark .imp-value, html.dark .initial-empty-state h3, html.dark .insight-header,
html.dark .insights-box h4, html.dark .insights-box ul, html.dark .intruder-result h3,
html.dark .issue-title, html.dark .m-value, html.dark .metric-value,
html.dark .mini-value, html.dark .no-anomaly, html.dark .overview-text h3,
html.dark .preview-title, html.dark .price-final .label, html.dark .price-main .label,
html.dark .product-brand, html.dark .rank-row, html.dark .rec-list,
html.dark .recommendation-text, html.dark .review-title, html.dark .risk-high h4,
html.dark .risk-low h4, html.dark .risk-medium h4, html.dark .score-info h3,
html.dark .score-value, html.dark .section-header, html.dark .section-subtitle,
html.dark .section-title, html.dark .sov-card .value, html.dark .stat-value,
html.dark .store-context-bar .store-name, html.dark .strategy-name, html.dark .tool-title,
html.dark .toolbar-label, html.dark .value-primary, html.dark .value-warning,
html.dark .value.primary, html.dark .value.warning, html.dark [class*=" group-title"],
html.dark [class*=" section-header"], html.dark [class*=" section-title"], html.dark [class*=" tool-title"],
html.dark [class*="-result"], html.dark [class*="-result"] h1, html.dark [class*="-result"] h2,
html.dark [class*="-result"] h3, html.dark [class*="-result"] h4, html.dark [class*="-result"] h5,
html.dark [class*="-result"] h6 {
  color: var(--text-primary) !important;
}

/* 次要文字色 #595959 / #666 / #888 / #999 */
html.dark .improvement-grid h4, html.dark .rationale-box h4 {
  color: var(--text-secondary) !important;
}

/* 三级文字色 #8c8c8c / #bfbfbf / #bbb */
html.dark .action-row .label, html.dark .asin-text, html.dark .bar-label,
html.dark .benchmark, html.dark .budget-card .label, html.dark .campaign-name,
html.dark .card-title, html.dark .cause-row .label, html.dark .detect-time,
html.dark .ds-label, html.dark .factor-name, html.dark .factors-section h5,
html.dark .field-hint, html.dark .form-hint, html.dark .helper-hint,
html.dark .imp-label, html.dark .initial-empty-state, html.dark .issue-desc,
html.dark .item-value, html.dark .loading-hint, html.dark .m-current,
html.dark .m-expected, html.dark .m-label, html.dark .metric .label,
html.dark .metric-name, html.dark .mini-label, html.dark .option-desc,
html.dark .overview-stats, html.dark .overview-stats .stat, html.dark .preview-meta,
html.dark .product-title-text, html.dark .rank-num, html.dark .rationale-box p,
html.dark .review-author, html.dark .review-body, html.dark .review-date,
html.dark .review-meta, html.dark .score-info .summary, html.dark .section-desc,
html.dark .sellers-section h5, html.dark .sov-card .label, html.dark .stat-label,
html.dark .store-context-bar .currency, html.dark .strategy-label, html.dark .swot-box li,
html.dark .swot-col ul, html.dark .swot-label, html.dark .tip-text {
  color: var(--text-tertiary) !important;
}

/* 边框色 */
html.dark [class*="-result"],
html.dark .result-panel, html.dark .profit-highlight,
html.dark .overview-card, html.dark .preview-card,
html.dark .competitor-card, html.dark .position-chart,
html.dark .insight-card, html.dark .review-item,
html.dark .metric-card, html.dark .budget-card,
html.dark .imp-item, html.dark .anomaly-card,
html.dark .detect-overview, html.dark .issue-item,
html.dark .change, html.dark .m-deviation,
html.dark .swot-box, html.dark .helper-hint,
html.dark .filter-group, html.dark .results-bar,
html.dark .title-thumb, html.dark .title-thumb-ph,
html.dark .compact-toolbar, html.dark .rationale-box,
html.dark .improvement-grid, html.dark .section-header,
html.dark .action-bar, html.dark .group-title,
html.dark .analyzer-header, html.dark .compare-header,
html.dark .buybox-card, html.dark .practices-box,
html.dark .dimensions-section, html.dark .value-ranking,
html.dark .diff-section, html.dark .cost-row,
html.dark .drow, html.dark .dkpi-row,
html.dark .hc-row, html.dark .sov-card,
html.dark .insights-box, html.dark .intruder-result,
html.dark .ad-diagnosis-result, html.dark .bid-optimize-result,
html.dark .budget-alloc-result, html.dark .compare-grid-result,
html.dark .blue-ocean-result, html.dark .buybox-analysis-result,
html.dark .competitor-ad-result, html.dark .competitor-intel-evidence,
html.dark .ab-test-generator, html.dark .aigc-media-result,
html.dark .bullet-generator, html.dark .description-generator,
html.dark .keyword-miner-result, html.dark .profit-calculator,
html.dark .store-context-bar {
  border-color: var(--border-base) !important;
}

/* 分隔线 */
html.dark [class*="-result"] .ant-divider,
html.dark .ant-divider {
  border-color: var(--border-base) !important;
}

/* ====== Ant Design 表单组件深色补丁（Select/Input/TextArea/Picker 等） ====== */

/* --- Select 选择器 --- */
html.dark .ant-select-selector {
  background-color: var(--bg-elevated) !important;
  border-color: var(--border-base) !important;
  color: var(--text-primary) !important;
}
html.dark .ant-select-selection-item {
  color: var(--text-primary) !important;
}
html.dark .ant-select-selection-placeholder {
  color: var(--text-tertiary) !important;
}
html.dark .ant-select-arrow {
  color: var(--text-tertiary) !important;
}
html.dark .ant-select-clear {
  color: var(--text-tertiary) !important;
}
html.dark .ant-select-clear:hover {
  color: var(--text-secondary) !important;
}
/* Select 下拉菜单（增强已有规则） */
html.dark .ant-select-dropdown {
  background-color: var(--bg-elevated) !important;
  border-color: var(--border-base) !important;
}
html.dark .ant-select-item-option-content {
  color: var(--text-primary) !important;
}
html.dark .ant-select-item-option-active:not(.ant-select-item-option-disabled) {
  background-color: var(--bg-hover-dark) !important;
}
html.dark .ant-select-item-option-selected:not(.ant-select-item-option-disabled) {
  background-color: rgba(24, 144, 255, 0.15) !important;
}

/* --- Input 输入框 --- */
html.dark .ant-input,
html.dark .ant-input-affix-wrapper {
  background-color: var(--bg-elevated) !important;
  border-color: var(--border-base) !important;
  color: var(--text-primary) !important;
}
html.dark .ant-input input,
html.dark .ant-input-affix-wrapper input,
html.dark .ant-input,
html.dark .ant-input-affix-wrapper .ant-input {
  color: var(--text-primary) !important;
  -webkit-text-fill-color: var(--text-primary) !important;
}
html.dark .ant-input::placeholder,
html.dark .ant-input-affix-wrapper .ant-input::placeholder,
html.dark .ant-input input::placeholder {
  color: var(--text-tertiary) !important;
  -webkit-text-fill-color: var(--text-tertiary) !important;
}
html.dark .ant-input-prefix,
html.dark .ant-input-suffix {
  color: var(--text-tertiary) !important;
}
html.dark .ant-input-affix-wrapper-focused,
html.dark .ant-input:focus {
  border-color: var(--primary) !important;
  box-shadow: 0 0 0 2px rgba(24, 144, 255, 0.15) !important;
}

/* --- InputNumber 数字输入框 --- */
html.dark .ant-input-number {
  background-color: var(--bg-elevated) !important;
  border-color: var(--border-base) !important;
}
html.dark .ant-input-number input,
html.dark .ant-input-number .ant-input-number-input {
  color: var(--text-primary) !important;
  background-color: transparent !important;
  -webkit-text-fill-color: var(--text-primary) !important;
}
html.dark .ant-input-number input::placeholder,
html.dark .ant-input-number .ant-input-number-input::placeholder {
  color: var(--text-tertiary) !important;
  -webkit-text-fill-color: var(--text-tertiary) !important;
}
html.dark .ant-input-number-handler {
  background-color: var(--bg-hover-light) !important;
  border-color: var(--border-base) !important;
  color: var(--text-secondary) !important;
}
html.dark .ant-input-number-handler:hover {
  color: var(--primary) !important;
}
html.dark .ant-input-number-handler-down {
  border-top-color: var(--border-base) !important;
}

/* --- TextArea 文本域 --- */
html.dark .ant-input[data-type="textarea"] {
  background-color: var(--bg-elevated) !important;
  color: var(--text-primary) !important;
}

/* --- DatePicker / RangePicker 日期选择器 --- */
html.dark .ant-picker {
  background-color: var(--bg-elevated) !important;
  border-color: var(--border-base) !important;
  color: var(--text-primary) !important;
}
html.dark .ant-picker-input > input {
  color: var(--text-primary) !important;
}
html.dark .ant-picker-input > input::placeholder {
  color: var(--text-tertiary) !important;
}
html.dark .ant-picker-suffix {
  color: var(--text-tertiary) !important;
}
html.dark .ant-picker-panel {
  background-color: var(--bg-elevated) !important;
  border-color: var(--border-base) !important;
}
html.dark .ant-picker-cell-inner {
  color: var(--text-primary) !important;
}
html.dark .ant-picker-header {
  color: var(--text-secondary) !important;
  border-bottom-color: var(--border-base) !important;
}
html.dark .ant-picker-footer {
  border-top-color: var(--border-base) !important;
}

/* --- Radio / Checkbox 单选复选 --- */
html.dark .ant-radio-wrapper {
  color: var(--text-primary) !important;
}
html.dark .ant-checkbox-wrapper {
  color: var(--text-primary) !important;
}

/* --- Button disabled（深色下原生 disabled 字几乎不可见，提亮） --- */
html.dark .ant-btn:disabled,
html.dark .ant-btn.ant-btn-primary:disabled,
html.dark .ant-btn-default:disabled {
  background-color: var(--bg-hover-light) !important;
  border-color: var(--border-base) !important;
  color: var(--text-secondary) !important;
  opacity: 1 !important;
}
html.dark .ant-btn:disabled span,
html.dark .ant-btn.ant-btn-primary:disabled span {
  color: var(--text-secondary) !important;
}

/* --- Switch 开关 --- */
/* Switch 在 darkAlgorithm 下通常正常，仅保底 */

/* --- Form 表单标签 --- */
html.dark .ant-form-item-label > label {
  color: var(--text-primary) !important;
}
html.dark .ant-form-item-explain,
html.dark .ant-form-item-explain-error {
  color: var(--danger) !important;
}

/* --- Table 表格（工具组件内嵌套表格） --- */
html.dark .ant-table {
  background: transparent !important;
}
html.dark .ant-table-thead > tr > th {
  background-color: var(--bg-hover-light) !important;
  color: var(--text-primary) !important;
  border-bottom-color: var(--border-base) !important;
}
html.dark .ant-table-tbody > tr > td {
  background: transparent !important;
  color: var(--text-primary) !important;
  border-bottom-color: var(--border-base) !important;
}
html.dark .ant-table-tbody > tr:hover > td {
  background-color: var(--bg-hover-dark) !important;
}
html.dark .ant-table-placeholder {
  color: var(--text-tertiary) !important;
}

/* --- Tag 标签 --- */
html.dark .ant-tag {
  border-color: var(--border-base) !important;
}

/* --- Tooltip 提示 --- */
html.dark .ant-tooltip-inner {
  color: var(--text-primary) !important;
}

/* ====== TaskConfigPanel 子配置组件通用深色补丁 ====== */
/* 所有 configs/ 下的 .section-card / .card-title / .dim-card 等通用类 */
html.dark .section-card {
  background-color: var(--bg-elevated) !important;
  border-color: var(--border-base) !important;
}
html.dark .card-title {
  color: var(--text-primary) !important;
}
html.dark .tool-badge {
  background: rgba(24, 144, 255, 0.1) !important;
  color: var(--primary) !important;
}
html.dark .dim-card {
  background: var(--bg-elevated) !important;
  border-color: var(--border-base) !important;
  color: var(--text-primary) !important;
}
html.dark .dim-card.active {
  background: rgba(24, 144, 255, 0.1) !important;
  border-color: var(--primary) !important;
  color: var(--primary) !important;
}
html.dark .action-plan-hint,
html.dark .config-hint,
html-dark .form-hint {
  color: var(--text-secondary) !important;
}
</style>
