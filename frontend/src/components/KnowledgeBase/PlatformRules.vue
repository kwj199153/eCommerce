<template>
  <div class="pr-page">
    <!-- 顶部标题栏 -->
    <div class="pr-header">
      <div>
        <h2 class="pr-title">平台规则库</h2>
        <p class="pr-subtitle">聚合各跨境电商平台的运营规则、政策条款与合规要求</p>
      </div>
      <div class="header-actions">
        <a-tooltip title="管理规则文档（PDF / MD / Excel）">
          <a-button @click="showDocPanel = !showDocPanel">
            <FileTextOutlined /> 文档 {{ showDocPanel ? '收起' : '管理' }}
            <a-badge v-if="store.docs.length" :count="store.docs.length" :offset="[-4, 0]" />
          </a-button>
        </a-tooltip>
        <a-tooltip title="导出全部规则，支持 JSON / Excel / CSV / TXT，可选择保存位置">
          <a-button @click="exportRules">
            <ExportOutlined /> 导出
          </a-button>
        </a-tooltip>
        <a-tooltip title="从文件批量导入规则（支持 JSON / CSV / TXT）">
          <a-button @click="showImportModal = true">
            <UploadOutlined /> 导入规则
          </a-button>
        </a-tooltip>
        <a-button type="primary" @click="openAddModal">
          <PlusOutlined /> 新增规则
        </a-button>
      </div>
    </div>

    <!-- 规则文档面板（可折叠，RAG 补充资料） -->
    <div v-show="showDocPanel" class="doc-panel">
      <div class="doc-panel-header">
        <span class="doc-panel-title"><FileTextOutlined /> 规则原文文档（RAG 补充资料）</span>
        <a-space>
          <a-upload
            :show-file-list="false"
            accept=".pdf,.md,.txt,.xlsx,.xls,.csv"
            :before-upload="handleDocUpload"
          >
            <a-button size="small" type="primary"><UploadOutlined /> 上传文档</a-button>
          </a-upload>
        </a-space>
      </div>
      <div v-if="store.docs.length" class="doc-list">
        <div v-for="doc in store.docs" :key="doc.id" class="doc-item">
          <div class="doc-info">
            <span class="doc-icon">{{ getDocIcon(doc.file_type) }}</span>
            <span class="doc-name">{{ doc.filename }}</span>
            <span class="doc-size">{{ formatSize(doc.size) }}</span>
            <a-tag size="small" :color="platformMeta(doc.platform).color">
              {{ platformMeta(doc.platform).label }}
            </a-tag>
            <span v-if="doc.description" class="doc-desc">— {{ doc.description }}</span>
          </div>
          <a-space :size="4">
            <a-tooltip title="AI 拆分：自动从文档中提取结构化规则">
              <a-button
                type="text"
                size="small"
                :loading="aiSplittingDocId === doc.id"
                @click="handleAiSplit(doc)"
              >
                <RobotOutlined /> AI 拆分
              </a-button>
            </a-tooltip>
            <a-popconfirm title="删除此文档？" @confirm="store.deleteDoc(doc.id)">
              <a-button type="text" size="small" danger><DeleteOutlined /></a-button>
            </a-popconfirm>
          </a-space>
        </div>
      </div>
      <a-empty v-else description="暂无规则原文文档，上传 PDF/MD/Excel 作为规则检索素材" :image-style="{ height: '40px' }" />
    </div>

    <!-- 统计卡片 -->
    <div class="stat-cards">
      <div class="stat-card">
        <div class="stat-value">{{ store.totalCount }}</div>
        <div class="stat-label">规则总数</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ store.platformCount }}</div>
        <div class="stat-label">覆盖平台</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ activeCount }}</div>
        <div class="stat-label">生效中</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ upcomingCount }}</div>
        <div class="stat-label">即将生效</div>
      </div>
    </div>

    <!-- 筛选栏 -->
    <div class="toolbar">
      <div class="toolbar-left">
        <a-input-search
          v-model:value="store.searchQuery"
          placeholder="搜索规则标题、内容、标签..."
          style="width: 260px"
          allow-clear
        >
          <template #prefix><SearchOutlined /></template>
        </a-input-search>
        <a-select
          v-model:value="store.filterPlatform"
          style="width: 140px"
          placeholder="全部平台"
          allow-clear
        >
          <a-select-option v-for="p in PLATFORMS" :key="p.key" :value="p.key">
            {{ p.icon }} {{ p.label }}
          </a-select-option>
        </a-select>
        <a-select
          v-model:value="store.filterCategory"
          style="width: 140px"
          placeholder="全部分类"
          allow-clear
        >
          <a-select-option v-for="c in RULE_CATEGORIES" :key="c.key" :value="c.key">
            {{ c.icon }} {{ c.label }}
          </a-select-option>
        </a-select>
        <a-select
          v-model:value="store.filterStatus"
          style="width: 120px"
          placeholder="全部状态"
          allow-clear
        >
          <a-select-option value="active">🟢 生效中</a-select-option>
          <a-select-option value="upcoming">🟡 即将生效</a-select-option>
          <a-select-option value="expired">⚪ 已失效</a-select-option>
        </a-select>
      </div>
    </div>

    <!-- 已启用的过滤条件（chip 行） -->
    <div v-if="store.hasActiveFilters" class="active-filters">
      <span class="af-label">
        <FilterOutlined /> 已启用过滤 ({{ store.activeFilterCount }})
      </span>

      <a-tag
        v-if="store.filterPlatform && store.filterPlatform !== 'all'"
        closable
        @close="store.filterPlatform = undefined"
        :color="COLOR_PLATFORM"
        class="af-chip"
      >
        平台：{{ platformLabel(store.filterPlatform) }}
      </a-tag>

      <a-tag
        v-if="store.filterCategory && store.filterCategory !== 'all'"
        closable
        @close="store.filterCategory = undefined"
        :color="COLOR_INFO"
        class="af-chip"
      >
        分类：{{ categoryLabel(store.filterCategory) }}
      </a-tag>

      <a-tag
        v-if="store.filterStatus && store.filterStatus !== 'all'"
        closable
        @close="store.filterStatus = undefined"
        :color="COLOR_INFO"
        class="af-chip"
      >
        状态：{{ statusLabel(store.filterStatus) }}
      </a-tag>

      <a-tag
        v-if="store.searchQuery.trim()"
        closable
        @close="store.searchQuery = ''"
        :color="COLOR_INFO"
        class="af-chip"
      >
        搜索："{{ store.searchQuery }}"
      </a-tag>

      <a-button type="link" size="small" danger @click="store.clearAllFilters()">
        <ClearOutlined /> 清空全部
      </a-button>
    </div>

    <!-- 规则列表 -->
    <a-table
      :columns="columns"
      :data-source="store.filteredItems"
      :loading="store.isLoading"
      row-key="id"
      :pagination="{ pageSize: 12, size: 'small', showTotal: (t: number) => `共 ${t} 条规则` }"
      size="middle"
      :scroll="{ y: 'calc(100vh - 360px)' }"
    >
      <template #bodyCell="{ column, record }">
        <!-- 标题列 -->
        <template v-if="column.key === 'title'">
          <div class="title-cell">
            <div class="title-text-wrap">
              <span class="title-text">{{ record.title }}</span>
              <div class="title-sub">
                <a-tag :color="platformMeta(record.platform).color" size="small">
                  {{ platformMeta(record.platform).icon }} {{ platformMeta(record.platform).label }}
                </a-tag>
                <a-tag color="default" size="small">{{ categoryLabel(record.category) }}</a-tag>
              </div>
            </div>
          </div>
        </template>

        <!-- 内容预览列 -->
        <template v-else-if="column.key === 'content'">
          <a-tooltip :title="record.content">
            <span class="content-preview">{{ record.content.slice(0, 60) }}...</span>
          </a-tooltip>
        </template>

        <!-- 生效日期列 -->
        <template v-else-if="column.key === 'effective_date'">
          <span>{{ record.effective_date }}</span>
        </template>

        <!-- 状态列 -->
        <template v-else-if="column.key === 'status'">
          <a-tag :color="statusColor(getResolvedStatus(record))">
            {{ statusLabel(getResolvedStatus(record)) }}
          </a-tag>
          <a-tooltip v-if="record.status !== 'auto'" title="手动覆盖状态（不受日期自动计算影响）">
            <span class="manual-override-badge">✋</span>
          </a-tooltip>
        </template>

        <!-- 操作列 -->
        <template v-else-if="column.key === 'action'">
          <a-space :size="4">
            <a-tooltip title="查看详情">
              <a-button type="text" size="small" @click="openDetail(record)">
                <EyeOutlined />
              </a-button>
            </a-tooltip>
            <a-tooltip title="编辑">
              <a-button type="text" size="small" @click="openEditModal(record)">
                <EditOutlined />
              </a-button>
            </a-tooltip>
            <a-popconfirm title="确认删除该规则？" @confirm="handleDelete(record)">
              <a-button type="text" size="small" danger>
                <DeleteOutlined />
              </a-button>
            </a-popconfirm>
          </a-space>
        </template>
      </template>
    </a-table>

    <!-- 批量导入规则弹窗 -->
    <a-modal
      v-model:open="showImportModal"
      title="批量导入规则"
      width="520px"
      :footer="null"
    >
      <div class="import-area">
        <a-upload-dragger
          :file-list="importFileList"
          :before-upload="handleImportFile"
          :remove="() => { importFileList = []; return true }"
          accept=".json,.csv,.txt"
          :max-count="1"
        >
          <p class="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p class="ant-upload-text">点击或拖拽文件到此区域上传</p>
          <p class="ant-upload-hint">
            支持 JSON / CSV / TXT 格式<br/>
            JSON：数组，每项含 platform / category / title / content<br/>
            CSV：platform, category, title, content<br/>
            TXT：每行 "标题 /// 内容"
          </p>
        </a-upload-dragger>

        <div v-if="importResult" class="import-result" :class="{ error: importResult.failed > 0 }">
          <a-alert
            :type="importResult.failed > 0 ? 'warning' : 'success'"
            :message="`导入完成：成功 ${importResult.success} 条${importResult.failed > 0 ? `，失败 ${importResult.failed} 条` : ''}`"
          >
            <template v-if="importResult.errors.length" #description>
              <ul class="error-list">
                <li v-for="(err, i) in importResult.errors.slice(0, 5)" :key="i">{{ err }}</li>
                <li v-if="importResult.errors.length > 5">... 还有 {{ importResult.errors.length - 5 }} 条错误</li>
              </ul>
            </template>
          </a-alert>
        </div>
      </div>
    </a-modal>

    <!-- 上传文档弹窗（选择平台+描述） -->
    <a-modal
      v-model:open="docUploadModalVisible"
      title="上传规则文档"
      width="440px"
      ok-text="确认上传"
      @ok="confirmDocUpload"
    >
      <div v-if="docUploadForm.pendingFile" class="doc-upload-preview">
        <div class="doc-upload-file">
          <span class="doc-upload-icon">{{ getDocIcon((docUploadForm.pendingFile.name.split('.').pop() || '') as PlatformRuleDoc['file_type']) }}</span>
          <span class="doc-upload-name">{{ docUploadForm.pendingFile.name }}</span>
          <span class="doc-upload-size">{{ formatSize(docUploadForm.pendingFile.size) }}</span>
        </div>
      </div>
      <a-form layout="vertical">
        <a-form-item label="所属平台" required>
          <a-select v-model:value="docUploadForm.platform" placeholder="选择文档所属平台">
            <a-select-option v-for="p in PLATFORMS" :key="p.key" :value="p.key">
              {{ p.icon }} {{ p.label }}
            </a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="描述（可选）">
          <a-input v-model:value="docUploadForm.description" placeholder="如：Amazon 2026 Listing 完整规范" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- AI 拆分确认弹窗（人工审核 + 去重标记 + 版本管理） -->
    <a-modal
      v-model:open="aiConfirmVisible"
      :title="aiConfirmDoc ? `🤖 AI 拆分结果 — ${aiConfirmDoc.filename}` : 'AI 拆分确认'"
      width="720px"
      ok-text="确认添加选中项"
      cancel-text="取消"
      :confirm-loading="aiConfirmLoading"
      @ok="confirmAiSplit"
      @cancel="cancelAiSplit"
    >
      <!-- 统计摘要 -->
      <div class="ai-confirm-summary">
        <span class="ai-stat ai-stat-new">✅ 全新 {{ dupCount.new }}</span>
        <span class="ai-stat ai-stat-dup">🟡 重复 {{ dupCount.duplicate }}</span>
        <span class="ai-stat ai-stat-update">🔵 更新 {{ dupCount.update }}</span>
      </div>

      <a-alert
        type="info"
        show-icon
        message="请审核以下 AI 提取的规则。重复项默认不勾选，更新项建议覆盖旧版。可编辑内容或调整分类。"
        style="margin-bottom: 12px"
      />

      <!-- 统一设置：日期对所有规则一次生效（同一文档拆出的规则生效日一致） -->
      <div class="ai-batch-date">
        <span class="ai-batch-title">📅 统一设置日期</span>
        <span class="ai-batch-label">生效日期</span>
        <a-date-picker
          v-model:value="aiBatchEffectiveDate"
          value-format="YYYY-MM-DD"
          size="small"
          style="width: 140px"
        />
        <span class="ai-batch-label">失效日期</span>
        <a-date-picker
          v-model:value="aiBatchExpiryDate"
          value-format="YYYY-MM-DD"
          size="small"
          style="width: 140px"
          placeholder="留空=永久"
        />
        <span class="ai-batch-label">有效期</span>
        <a-button size="small" :type="!aiBatchExpiryDate ? 'primary' : 'default'" @click="setAiBatchExpiry(null)">永久</a-button>
        <a-button size="small" :type="aiBatchIsExpiry(3) ? 'primary' : 'default'" @click="setAiBatchExpiry(3)">3月</a-button>
        <a-button size="small" :type="aiBatchIsExpiry(6) ? 'primary' : 'default'" @click="setAiBatchExpiry(6)">6月</a-button>
        <a-button size="small" :type="aiBatchIsExpiry(12) ? 'primary' : 'default'" @click="setAiBatchExpiry(12)">1年</a-button>
        <a-button size="small" :type="aiBatchIsExpiry(24) ? 'primary' : 'default'" @click="setAiBatchExpiry(24)">2年</a-button>
        <span class="ai-batch-sync">此处的日期会同步应用到下方全部规则</span>
      </div>

      <div class="ai-confirm-actions">
        <span class="ai-confirm-count">
          已选 {{ aiPendingRules.filter(r => r._checked).length }} / {{ aiPendingRules.length }} 条
        </span>
        <a-button size="small" @click="selectAllNew">全选全新</a-button>
        <a-button size="small" @click="aiPendingRules.forEach(r => r._checked = true)">全选</a-button>
        <a-button size="small" danger @click="aiPendingRules.forEach(r => r._checked = false)">全不选</a-button>
      </div>

      <div class="ai-confirm-list">
        <div
          v-for="(rule, idx) in aiPendingRules"
          :key="idx"
          class="ai-confirm-item"
          :class="{
            'ai-confirm-item-unchecked': !rule._checked,
            'ai-confirm-item-dup': rule._dupStatus === 'duplicate',
            'ai-confirm-item-update': rule._dupStatus === 'update',
            'ai-confirm-item-new': rule._dupStatus === 'new',
          }"
        >
          <!-- 左侧：勾选 + 状态标签 -->
          <div class="ai-confirm-left">
            <div class="ai-confirm-check">
              <a-checkbox v-model:checked="rule._checked" />
            </div>
            <a-tooltip placement="left" :overlayStyle="{ maxWidth: '320px' }">
              <template #title>
                <div v-if="rule._dupStatus === 'duplicate'" class="ai-dup-tooltip">
                  <p><strong>⚠ 与已有规则相似</strong></p>
                  <p>相似度：{{ ((rule._similarityScore || 0) * 100).toFixed(0) }}%</p>
                  <p>匹配规则：{{ getMatchedRuleTitle(rule._matchedRuleId) }}</p>
                  <p style="margin-top:6px">
                    <a-button type="link" size="small" @click="viewMatchedRule(rule._matchedRuleId!)">查看原规则 →</a-button>
                  </p>
                </div>
                <div v-else-if="rule._dupStatus === 'update'" class="ai-dup-tooltip">
                  <p><strong>🔄 检测到版本更新</strong></p>
                  <p>{{ rule._diffSummary }}</p>
                  <p>旧规则：{{ getMatchedRuleTitle(rule._matchedRuleId) }}</p>
                  <p style="margin-top:6px">
                    <a-button type="link" size="small" @click="replaceThisRule(rule)">覆盖旧版 →</a-button>
                  </p>
                </div>
                <div v-else>
                  <p><strong>✅ 全新规则</strong></p>
                  <p>与现有规则库无匹配项</p>
                </div>
              </template>
              <span
                class="ai-dup-badge"
                :class="`ai-dup-${rule._dupStatus}`"
              >
                {{ dupStatusLabel(rule._dupStatus) }}
                <span v-if="rule._similarityScore !== undefined" class="ai-dup-score">
                  {{ (rule._similarityScore * 100).toFixed(0) }}%
                </span>
              </span>
            </a-tooltip>
          </div>

          <!-- 右侧：编辑区 -->
          <div class="ai-confirm-body">
            <div class="ai-confirm-row">
              <a-input
                v-model:value="rule.title"
                size="small"
                :disabled="!rule._checked"
                style="flex: 1; margin-right: 8px"
              />
              <a-select
                v-model:value="rule.category"
                size="small"
                style="width: 110px"
                :disabled="!rule._checked"
              >
                <a-select-option v-for="c in RULE_CATEGORIES" :key="c.key" :value="c.key">{{ c.label }}</a-select-option>
              </a-select>
            </div>
            <a-textarea
              v-model:value="rule.content"
              :auto-size="{ minRows: 2, maxRows: 4 }"
              :disabled="!rule._checked"
              placeholder="规则正文..."
              style="margin-top: 6px"
            />
            <div class="ai-confirm-meta">
              <a-tag size="small" color="blue">AI 提取</a-tag>
              <a-tag size="small" :color="platformMeta(rule.platform).color">
                {{ platformMeta(rule.platform).label }}
              </a-tag>
              <span v-if="rule._diffSummary" class="ai-diff-hint">{{ rule._diffSummary }}</span>
              <!-- 操作按钮 -->
              <a-button
                v-if="rule._matchedRuleId && rule._dupStatus !== 'new'"
                type="link"
                size="small"
                @click="viewMatchedRule(rule._matchedRuleId!)"
              >查看原规则</a-button>
              <a-button
                v-if="rule._dupStatus === 'update'"
                type="link"
                size="small"
                style="color: var(--primary)"
                @click="replaceThisRule(rule)"
              >覆盖旧版</a-button>
              <!-- 高级设置开关 -->
              <a-button
                type="link"
                size="small"
                @click="toggleAiAdvance(rule)"
                :disabled="!rule._checked"
              >
                {{ aiAdvanceOpen.has(rule) ? '收起设置' : '⚙️ 高级设置' }}
              </a-button>
            </div>

            <!-- 高级设置：状态 / 标签 / 来源（日期已由顶部统一设置，同一文档生效日一致） -->
            <div
              v-if="aiAdvanceOpen.has(rule)"
              class="ai-confirm-advance"
              @click.stop
            >
              <a-row :gutter="8">
                <a-col :span="24">
                  <span class="ai-adv-label">状态（日期已统一，仅需在此覆盖特殊情况）</span>
                  <a-select v-model:value="rule.status" size="small" style="width: 100%" :disabled="!rule._checked">
                    <a-select-option value="auto">🤖 自动（按统一日期计算，推荐）</a-select-option>
                    <a-select-option value="active">🟢 强制生效中</a-select-option>
                    <a-select-option value="upcoming">🟡 强制即将生效</a-select-option>
                    <a-select-option value="expired">⚪ 强制已失效</a-select-option>
                  </a-select>
                </a-col>
              </a-row>
              <a-row :gutter="8" style="margin-top: 4px">
                <a-col :span="12">
                  <span class="ai-adv-label">标签（逗号分隔）</span>
                  <a-input
                    v-model:value="rule.tagsText"
                    size="small"
                    style="width: 100%"
                    :disabled="!rule._checked"
                    placeholder="如：标题, 字符限制"
                  />
                </a-col>
                <a-col :span="12">
                  <span class="ai-adv-label">来源链接</span>
                  <a-input
                    v-model:value="rule.source"
                    size="small"
                    style="width: 100%"
                    :disabled="!rule._checked"
                    placeholder="https://..."
                  />
                </a-col>
              </a-row>
            </div>
          </div>
        </div>
      </div>
    </a-modal>

    <!-- Layer 3：强制添加重复规则的二次确认弹窗 -->
    <a-modal
      v-model:open="aiForceAddVisible"
      title="⚠ 检测到高度重复规则"
      width="480px"
      ok-text="仍要添加"
      cancel-text="返回修改"
      :confirm-loading="aiConfirmLoading"
      @ok="forceConfirmAiSplit"
      @cancel="aiForceAddVisible = false"
    >
      <a-alert
        type="warning"
        show-icon
        message="以下勾选的规则与现有规则高度相似，确定要重复入库吗？"
        style="margin-bottom: 16px"
      />
      <div class="ai-force-list">
        <div v-for="(w, i) in aiForceWarnings" :key="i" class="ai-force-item">
          <WarningOutlined style="color: var(--warning); margin-right: 8px" />
          <span>{{ w }}</span>
        </div>
      </div>
      <p class="ai-force-note">提示：极少数业务场景确实需要保留多条版本对比（如新旧政策并行期）。如为误判请返回取消勾选。</p>
    </a-modal>

    <!-- 新增/编辑规则弹窗 -->
    <a-modal
      v-model:open="editModalVisible"
      :title="editingId ? '编辑规则' : '新增规则'"
      width="600px"
      :confirm-loading="saving"
      @ok="handleSubmit"
    >
      <a-form layout="vertical">
        <a-row :gutter="12">
          <a-col :span="12">
            <a-form-item label="平台" required>
              <a-select v-model:value="editForm.platform" placeholder="选择平台">
                <a-select-option v-for="p in PLATFORMS" :key="p.key" :value="p.key">
                  {{ p.icon }} {{ p.label }}
                </a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="规则分类" required>
              <a-select v-model:value="editForm.category" placeholder="选择分类">
                <a-select-option v-for="c in RULE_CATEGORIES" :key="c.key" :value="c.key">
                  {{ c.icon }} {{ c.label }}
                </a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
        </a-row>
        <a-form-item label="规则标题" required>
          <a-input v-model:value="editForm.title" placeholder="如：商品标题字符数限制" />
        </a-form-item>
        <a-form-item label="规则内容" required>
          <a-textarea
            v-model:value="editForm.content"
            :rows="5"
            placeholder="输入规则正文..."
          />
        </a-form-item>
        <a-row :gutter="12">
          <a-col :span="12">
            <a-form-item label="生效日期" required>
              <a-date-picker
                v-model:value="editForm.effective_date"
                value-format="YYYY-MM-DD"
                style="width: 100%"
              />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="失效日期">
              <a-date-picker
                v-model:value="editForm.expiry_date"
                value-format="YYYY-MM-DD"
                style="width: 100%"
                placeholder="留空=永不过期"
              />
            </a-form-item>
          </a-col>
        </a-row>

        <!-- 有效期快捷选择 -->
        <div class="validity-quick-select">
          <span class="vqs-label">快捷设置有效期：</span>
          <a-space :size="6" wrap>
            <a-button
              size="small"
              :type="!expDateStr ? 'primary' : 'default'"
              @click="setExpiryDate(null)"
            >♾️ 永久</a-button>
            <a-button
              size="small"
              :type="isExpiryMatch(3) ? 'primary' : 'default'"
              @click="setExpiryDate(3)"
            >3 个月</a-button>
            <a-button
              size="small"
              :type="isExpiryMatch(6) ? 'primary' : 'default'"
              @click="setExpiryDate(6)"
            >6 个月</a-button>
            <a-button
              size="small"
              :type="isExpiryMatch(12) ? 'primary' : 'default'"
              @click="setExpiryDate(12)"
            >1 年</a-button>
            <a-button
              size="small"
              :type="isExpiryMatch(24) ? 'primary' : 'default'"
              @click="setExpiryDate(24)"
            >2 年</a-button>
          </a-space>
          <span v-if="expDateStr && effDateStr" class="vqs-preview">
            （有效期 {{ calcDurationDays }} 天）
          </span>
        </div>
        <a-form-item label="状态">
          <a-select v-model:value="editForm.status">
            <a-select-option value="auto">🤖 自动（根据日期计算，推荐）</a-select-option>
            <a-select-option value="active">🟢 强制生效中</a-select-option>
            <a-select-option value="upcoming">🟡 强制即将生效</a-select-option>
            <a-select-option value="expired">⚪ 强制已失效</a-select-option>
          </a-select>
          <div class="form-hint">选择「自动」时，系统根据生效/失效日期实时判定状态；手动选项用于特殊场景覆盖（如提前失效）</div>
        </a-form-item>
        <a-form-item label="标签（逗号分隔）">
          <a-input v-model:value="editForm.tagsText" placeholder="如：标题, 字符限制, Listing" />
        </a-form-item>
        <a-form-item label="来源链接">
          <a-input v-model:value="editForm.source" placeholder="https://..." />
        </a-form-item>
        <a-form-item label="来源文档">
          <a-select
            v-model:value="editForm.source_doc_id"
            placeholder="关联到已上传的规则原文文档"
            allow-clear
            style="width: 100%"
          >
            <a-select-option v-for="doc in store.docs" :key="doc.id" :value="doc.id">
              {{ getDocIcon(doc.file_type) }} {{ doc.filename }}
              <span class="select-doc-platform">({{ platformMeta(doc.platform).label }})</span>
            </a-select-option>
          </a-select>
          <div class="form-hint">选择后可在规则详情中一键跳转到完整原文</div>
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 详情弹窗 -->
    <a-modal
      v-model:open="detailVisible"
      :title="detailItem?.title"
      :footer="null"
      width="680px"
    >
      <div v-if="detailItem" class="detail-body">
        <div class="detail-meta">
          <a-tag :color="platformMeta(detailItem.platform).color">
            {{ platformMeta(detailItem.platform).icon }} {{ platformMeta(detailItem.platform).label }}
          </a-tag>
          <a-tag color="default">{{ categoryLabel(detailItem.category) }}</a-tag>
          <a-tag :color="statusColor(getResolvedStatus(detailItem))">
            {{ statusLabel(getResolvedStatus(detailItem)) }}
          </a-tag>
          <span v-if="detailItem.status !== 'auto'" class="manual-override-badge" title="手动覆盖状态">✋</span>
          <span class="detail-date">生效：{{ detailItem.effective_date }}</span>
          <span v-if="detailItem.expiry_date" class="detail-date" style="color: var(--danger)">
            失效：{{ detailItem.expiry_date }}
            <span style="font-size: 11px; color: var(--text-tertiary); font-weight: normal">
              （{{ calcDetailDuration(detailItem) }}）
            </span>
          </span>
          <span v-else class="detail-date" style="color: var(--success)">永不过期</span>
        </div>

        <!-- 来源文档关联 -->
        <div v-if="detailItem.source_doc_id" class="detail-source-doc">
          <span class="detail-source-doc-label"><FileTextOutlined /> 来源文档</span>
          <a-button
            type="link"
            size="small"
            @click="openSourceDoc(detailItem.source_doc_id!)"
          >
            <LinkOutlined /> {{ store.getDocById(detailItem.source_doc_id!)?.filename || '查看原文' }}
            <ExportOutlined style="margin-left: 4px" />
          </a-button>
        </div>

        <div class="detail-content">{{ detailItem.content }}</div>
        <div v-if="detailItem.tags.length" class="detail-tags">
          <a-tag v-for="t in detailItem.tags" :key="t" color="blue">{{ t }}</a-tag>
        </div>
        <a v-if="detailItem.source" :href="detailItem.source" target="_blank" class="detail-source">
          外部来源链接 →
        </a>
      </div>
    </a-modal>

    <!-- 来源文档预览弹窗 -->
    <a-modal
      v-model:open="sourceDocVisible"
      :title="sourceDocItem ? `📄 ${sourceDocItem.filename}` : '来源文档'"
      :footer="null"
      width="720px"
      :body-style="{ maxHeight: '70vh', overflow: 'auto', padding: '0' }"
    >
      <div v-if="sourceDocItem" class="source-doc-body">
        <!-- 文档元数据条 -->
        <div class="source-doc-meta-bar">
          <a-tag :color="platformMeta(sourceDocItem.platform).color">
            {{ platformMeta(sourceDocItem.platform).label }}
          </a-tag>
          <a-tag size="small">{{ getDocIcon(sourceDocItem.file_type) }} {{ sourceDocItem.file_type.toUpperCase() }}</a-tag>
          <span class="source-doc-size">{{ formatSize(sourceDocItem.size) }}</span>
          <span class="source-doc-date">上传于 {{ sourceDocItem.uploaded_at.slice(0, 10) }}</span>
        </div>

        <!-- 文档描述 -->
        <p v-if="sourceDocItem.description" class="source-doc-desc">{{ sourceDocItem.description }}</p>

        <!-- ====== 原文内容区（核心） ====== -->
        <div class="source-doc-content-section">
          <div class="source-doc-section-header" @click="toggleContentExpanded">
            <span class="source-doc-section-title"><FileTextOutlined /> 原文内容</span>
            <span class="source-doc-toggle">{{ contentExpanded ? '收起 ▲' : '展开全文 ▼' }}</span>
          </div>
          <div v-show="contentExpanded" class="source-doc-content-body">
            <pre v-if="sourceDocItem.content" class="source-doc-text">{{ sourceDocItem.content }}</pre>
            <a-empty v-else description="暂无原文内容（上传时未提取文本）" :image-style="{ height: '60px' }" />
          </div>
        </div>

        <!-- 分割线 -->
        <a-divider style="margin: 12px 0" />

        <!-- 关联到此文档的规则列表 -->
        <div class="source-doc-rules">
          <h4 class="source-doc-rules-title">从此文档提取的规则（{{ linkedRules.length }} 条）</h4>
          <div v-if="linkedRules.length" class="source-doc-rules-list">
            <div v-for="rule in linkedRules" :key="rule.id" class="source-doc-rule-item" @click="viewLinkedRule(rule)">
              <a-tag :color="statusColor(rule.status)" size="small">{{ statusLabel(rule.status) }}</a-tag>
              <span class="source-doc-rule-title">{{ rule.title }}</span>
              <span class="source-doc-rule-cat">{{ categoryLabel(rule.category) }}</span>
              <ExportOutlined class="source-doc-arrow" />
            </div>
          </div>
          <a-empty v-else description="暂无规则关联此文档，可点击「AI 拆分」自动提取" :image-style="{ height: '36px' }" />
        </div>
      </div>
    </a-modal>

    <!-- 导出弹窗（多格式 + 可选目标文件夹） -->
    <ExportModal
      v-model:open="exportVisible"
      title="导出平台规则库"
      unit="规则"
      :count="exportCount"
      :base-name="`平台规则库_${todayStamp()}`"
      :json-data="exportRulesJson"
      :columns="exportColumns"
      :rows="exportRows"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { message } from 'ant-design-vue'
import {
  SearchOutlined,
  PlusOutlined,
  DeleteOutlined,
  EditOutlined,
  EyeOutlined,
  FilterOutlined,
  ClearOutlined,
  FileTextOutlined,
  UploadOutlined,
  InboxOutlined,
  LinkOutlined,
  ExportOutlined,
  RobotOutlined,
  WarningOutlined,
} from '@ant-design/icons-vue'
import { usePlatformRulesStore, PLATFORMS, RULE_CATEGORIES, type PlatformRule, type PlatformRuleDoc, type PendingRuleWithDup, type DupStatus, getResolvedStatus } from '@/stores/platformRules'
import { todayStamp } from '@/utils/download'
import ExportModal from '@/components/common/ExportModal.vue'
import { COLOR_INFO, COLOR_PLATFORM } from '@/utils/colorSemantics'

const store = usePlatformRulesStore()

// ====== 文档面板 ======
const showDocPanel = ref(false)
const docUploadModalVisible = ref(false)
const docUploadForm = reactive({
  platform: 'amazon' as string,
  description: '',
  pendingFile: null as File | null,
})

function getDocIcon(type: PlatformRuleDoc['file_type']): string {
  switch (type) {
    case 'pdf': return '📄'
    case 'md': return '📝'
    case 'excel': return '📊'
    case 'txt': return '📃'
    default: return '📎'
  }
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function handleDocUpload(file: File) {
  docUploadForm.pendingFile = file
  docUploadForm.platform = 'amazon'
  docUploadForm.description = ''
  docUploadModalVisible.value = true
  return false
}

async function confirmDocUpload() {
  if (!docUploadForm.pendingFile) return
  const f = docUploadForm.pendingFile
  await store.uploadDoc(f, docUploadForm.platform, docUploadForm.description)
  message.success(`文档「${f.name}」已上传（${platformMeta(docUploadForm.platform).label}）`)
  docUploadModalVisible.value = false
  docUploadForm.pendingFile = null
}

// ====== AI 拆分（带人工确认 + 三层去重） ======
const aiSplittingDocId = ref<string | null>(null)

/** AI 拆分待确认弹窗 */
const aiConfirmVisible = ref(false)
const aiConfirmDoc = ref<PlatformRuleDoc | null>(null)
// 扩展：tagsText 用于高级设置里逗号字符串编辑
type AiPendingRule = PendingRuleWithDup & {
  _checked: boolean
  tagsText: string
}
const aiPendingRules = ref<AiPendingRule[]>([])
const aiConfirmLoading = ref(false)
// 每条规则「高级设置」折叠开关（存对象引用，key 用 Set<object>）
const aiAdvanceOpen = ref<Set<PendingRuleWithDup>>(new Set())

/** 切换某条规则的高级设置展开/收起 */
function toggleAiAdvance(rule: PendingRuleWithDup) {
  const s = new Set(aiAdvanceOpen.value)
  if (s.has(rule)) s.delete(rule)
  else s.add(rule)
  aiAdvanceOpen.value = s
}

/** 提取生效日期字符串（兼容 Dayjs/string） */
function ruleDateStr(v: any): string {
  if (!v) return ''
  if (typeof v === 'object' && v.format) return v.format('YYYY-MM-DD')
  if (typeof v === 'string') return v
  return ''
}

/** 批量日期状态：同一文档拆出的规则生效日/失效日一致，此处一次设置同步全部 */
const aiBatchEffectiveDate = ref<string | undefined>(undefined)
const aiBatchExpiryDate = ref<string | undefined>(undefined)

/** 顶部统一生效日期变化 → 同步到全部勾选规则 */
watch(aiBatchEffectiveDate, (val) => {
  if (val === undefined) return
  for (const r of aiPendingRules.value) {
    if (r._checked) r.effective_date = val
  }
})

/** 顶部统一失效日期变化 → 同步到全部勾选规则 */
watch(aiBatchExpiryDate, (val) => {
  for (const r of aiPendingRules.value) {
    if (r._checked) r.expiry_date = val || undefined
  }
})

/** 顶部快捷有效期（months=null 清空为永久），基于统一生效日计算 */
function setAiBatchExpiry(months: number | null) {
  if (months === null) {
    aiBatchExpiryDate.value = undefined
    return
  }
  const effRaw = ruleDateStr(aiBatchEffectiveDate.value) || new Date().toISOString().slice(0, 10)
  const eff = new Date(effRaw + 'T00:00:00')
  eff.setMonth(eff.getMonth() + months)
  aiBatchExpiryDate.value = eff.toISOString().slice(0, 10)
}

/** 顶部失效日期是否匹配某月数（快捷按钮高亮） */
function aiBatchIsExpiry(months: number): boolean {
  const eff = ruleDateStr(aiBatchEffectiveDate.value)
  const exp = ruleDateStr(aiBatchExpiryDate.value)
  if (!eff || !exp) return false
  const base = new Date(eff + 'T00:00:00')
  base.setMonth(base.getMonth() + months)
  return exp === base.toISOString().slice(0, 10)
}

/** Layer 3：强制添加重复规则的二次确认弹窗 */
const aiForceAddVisible = ref(false)
const aiForceWarnings = ref<string[]>([])
const aiForceRulesToAdd = ref<PendingRuleWithDup[]>([])

/** 去重统计 */
const dupCount = computed(() => {
  const counts = { new: 0, duplicate: 0, update: 0 }
  for (const r of aiPendingRules.value) { counts[r._dupStatus]++ }
  return counts
})

/** 去重状态中文标签 */
function dupStatusLabel(status: DupStatus): string {
  switch (status) {
    case 'new': return '全新'
    case 'duplicate': return '重复'
    case 'update': return '更新'
    default: return status
  }
}

/** 获取匹配到的原规则标题 */
function getMatchedRuleTitle(ruleId?: string): string {
  if (!ruleId) return ''
  const rule = store.items.find(r => r.id === ruleId)
  return rule?.title || '未知规则'
}

/** 全选全新规则（跳过重复项） */
function selectAllNew() {
  for (const r of aiPendingRules.value) {
    r._checked = r._dupStatus === 'new' || r._dupStatus === 'update'
  }
}

/** 查看匹配到的原规则（在规则详情中打开） */
function viewMatchedRule(ruleId: string) {
  const rule = store.items.find(r => r.id === ruleId)
  if (rule) openDetail(rule)
}

/** 覆盖旧版本（版本管理：旧标记 expired + 新入库 active） */
async function replaceThisRule(rule: AiPendingRule) {
  if (!rule._matchedRuleId) return
  try {
    // 组装干净的 payload（去 UI 辅助字段，解析日期与标签）
    const payload = {
      platform: rule.platform,
      category: rule.category,
      title: rule.title,
      content: rule.content,
      effective_date: ruleDateStr(rule.effective_date) || new Date().toISOString().slice(0, 10),
      expiry_date: rule.expiry_date ? ruleDateStr(rule.expiry_date) : undefined,
      status: rule.status,
      tags: (rule.tagsText || '').split(',').map((t: string) => t.trim()).filter(Boolean),
      source: rule.source,
      source_doc_id: rule.source_doc_id,
    }
    await store.replaceOldVersion(rule._matchedRuleId, payload)
    // 从待确认列表移除该条（已处理）
    const idx = aiPendingRules.value.indexOf(rule)
    if (idx >= 0) aiPendingRules.value.splice(idx, 1)
    message.success('已覆盖旧版，新规则已入库')
  } catch (e) {
    message.error(`覆盖失败：${e instanceof Error ? e.message : '未知错误'}`)
  }
}

async function handleAiSplit(doc: PlatformRuleDoc) {
  aiSplittingDocId.value = doc.id
  try {
    const result = await store.aiSplitFromDoc(doc.id, {
      onProgress: (msg) => message.loading(msg, 0),
    })
    message.destroy()

    // 弹出确认列表（带去重标注）
    aiConfirmDoc.value = doc
    // 默认行为：全新/更新 → 勾选；重复 → 不勾选
    // 每条补 tagsText（供高级设置编辑），并默认展开高级设置方便补日期
    const enriched: AiPendingRule[] = result.rules.map(r => {
      const base: AiPendingRule = {
        ...r,
        _checked: r._dupStatus !== 'duplicate', // 重复项默认不勾选
        tagsText: (r.tags || []).join(', '),
      }
      return base
    })
    aiPendingRules.value = enriched
    aiAdvanceOpen.value = new Set(enriched)

    // 顶部统一日期：默认取第一条规则的生效日（store 拆分时全部=今天），并同步给全部规则
    const sharedEff = ruleDateStr(enriched[0]?.effective_date)
    aiBatchEffectiveDate.value = sharedEff || new Date().toISOString().slice(0, 10)
    aiBatchExpiryDate.value = undefined
    aiConfirmVisible.value = true
  } catch (e) {
    message.destroy()
    message.error(`AI 拆分失败：${e instanceof Error ? e.message : '未知错误'}`)
  } finally {
    aiSplittingDocId.value = null
  }
}

/** Layer 3：确认添加前执行最终防重校验 */
async function confirmAiSplit() {
  const toAdd = aiPendingRules.value.filter(r => r._checked)
  if (toAdd.length === 0) {
    message.warning('请至少选择一条规则')
    return
  }

  // 去掉 _checked 后传给 store Layer 3 预检
  const toCheck: PendingRuleWithDup[] = toAdd.map(({ _checked, ...rest }) => rest)
  const checkResult = store.prePersistCheck(toCheck)

  if (checkResult.warnings.length > 0) {
    // 有高度重复项 → 弹出二次确认
    aiForceWarnings.value = checkResult.warnings
    aiForceRulesToAdd.value = checkResult.safeRules
    aiForceAddVisible.value = true
    return
  }

  // 无警告 → 直接入库
  await doAddRules(checkResult.safeRules)
}

/** 用户确认强制添加重复规则后执行 */
async function forceConfirmAiSplit() {
  await doAddRules(aiForceRulesToAdd.value)
  aiForceAddVisible.value = false
}

/** 实际执行入库 */
async function doAddRules(rules: PendingRuleWithDup[]) {
  aiConfirmLoading.value = true
  try {
    let addedCount = 0
    for (const rule of rules) {
      // 去掉去重标记 / UI 辅助字段，并解析日期为字符串
      const { _dupStatus, _matchedRuleId, _similarityScore, _diffSummary, ...rest } = rule as AiPendingRule
      const { tagsText, ...payloadRaw } = rest
      const payload = {
        ...payloadRaw,
        effective_date: ruleDateStr(payloadRaw.effective_date) || new Date().toISOString().slice(0, 10),
        expiry_date: payloadRaw.expiry_date ? ruleDateStr(payloadRaw.expiry_date) : undefined,
        tags: (tagsText || '').split(',').map((t: string) => t.trim()).filter(Boolean),
      }

      // 更新型规则：自动覆盖旧版
      if (_dupStatus === 'update' && _matchedRuleId) {
        await store.replaceOldVersion(_matchedRuleId, payload)
      } else {
        await store.addItem(payload)
      }
      addedCount++
    }
    message.success(`已添加 ${addedCount} 条规则`)
    aiConfirmVisible.value = false
    aiPendingRules.value = []
    aiBatchEffectiveDate.value = undefined
    aiBatchExpiryDate.value = undefined
  } catch (e) {
    message.error(`添加失败：${e instanceof Error ? e.message : '未知错误'}`)
  } finally {
    aiConfirmLoading.value = false
  }
}

/** 取消拆分确认 */
function cancelAiSplit() {
  aiConfirmVisible.value = false
  aiPendingRules.value = []
  aiAdvanceOpen.value = new Set()
  aiBatchEffectiveDate.value = undefined
  aiBatchExpiryDate.value = undefined
}

// ====== 文件导入（批量规则） ======
const showImportModal = ref(false)
const importFileList = ref<any[]>([])
const importResult = ref<{ success: number; failed: number; errors: string[] } | null>(null)

async function handleImportFile(file: File) {
  importFileList.value = [file]
  importResult.value = await store.parseAndImport(file)
  if (importResult.value.success > 0) {
    message.success(`成功导入 ${importResult.value.success} 条规则`)
  }
  return false
}

// ====== 导出（多格式，可选目标文件夹） ======
const exportVisible = ref(false)
const exportRows = ref<(string | number)[][]>([])
const exportRulesJson = ref<unknown>([])
const exportCount = ref(0)

/** 规则导出表格列头 */
const exportColumns = [
  '平台',
  '分类',
  '规则标题',
  '内容',
  '生效日期',
  '失效日期',
  '状态',
  '标签',
  '来源链接',
]

/** 打开导出弹窗：准备 JSON + 表格数据 */
function exportRules() {
  const data = store.items.map(({ id, created_at, updated_at, ...rule }) => rule)
  exportRulesJson.value = data
  exportCount.value = data.length

  exportRows.value = store.items.map(r => {
    const rs = getResolvedStatus(r)
    return [
      platformLabel(r.platform),
      categoryLabel(r.category),
      r.title,
      r.content,
      r.effective_date || '',
      r.expiry_date || '永不过期',
      statusLabel(rs) + (r.status !== 'auto' ? '（手动）' : ''),
      r.tags.join(', '),
      r.source || '',
    ]
  })
  exportVisible.value = true
}

// ====== 表格列 ======
const columns = [
  { title: '规则标题', dataIndex: 'title', key: 'title', width: 280 },
  { title: '内容预览', dataIndex: 'content', key: 'content' },
  { title: '生效日期', dataIndex: 'effective_date', key: 'effective_date', width: 110 },
  { title: '状态', dataIndex: 'status', key: 'status', width: 100 },
  { title: '操作', key: 'action', width: 130, fixed: 'right' },
]

// ====== 统计 ======
const activeCount = computed(() => store.statusCounts.active)
const upcomingCount = computed(() => store.statusCounts.upcoming)

// ====== 辅助函数 ======
function platformMeta(key: string) {
  return PLATFORMS.find(p => p.key === key) || { key, label: key, icon: '🌐', color: 'var(--text-tertiary)' }
}
function platformLabel(key: string) {
  return platformMeta(key).label
}
function categoryLabel(key: string) {
  return RULE_CATEGORIES.find(c => c.key === key)?.label || key
}
function statusLabel(s: string) {
  return s === 'active' ? '生效中' : s === 'upcoming' ? '即将生效' : '已失效'
}
function statusColor(s: string) {
  return s === 'active' ? 'green' : s === 'upcoming' ? 'orange' : 'default'
}

/** 计算规则的有效期时长（用于详情弹窗显示） */
function calcDetailDuration(rule: PlatformRule): string {
  if (!rule.effective_date || !rule.expiry_date) return ''
  const eff = new Date(rule.effective_date + 'T00:00:00')
  const exp = new Date(rule.expiry_date + 'T00:00:00')
  const days = Math.ceil((exp.getTime() - eff.getTime()) / (1000 * 60 * 60 * 24))
  if (days <= 0) return '已过期'
  if (days < 30) return `剩余 ${days} 天`
  if (days < 365) {
    const m = Math.round(days / 30)
    return `有效期 ${m} 个月`
  }
  const y = (days / 365).toFixed(1)
  return `有效期 ${y} 年`
}

// ====== 新增/编辑 ======
const editModalVisible = ref(false)
const saving = ref(false)
const editingId = ref<string | null>(null)
const editForm = reactive({
  platform: 'amazon',
  category: 'listing',
  title: '',
  content: '',
  effective_date: '',
  expiry_date: undefined as string | undefined,
  status: 'auto' as PlatformRule['status'],
  tagsText: '',
  source: '',
  source_doc_id: undefined as string | undefined,
})

// ====== 有效期快捷选择 ======

/**
 * 统一日期值提取：兼容 Dayjs 对象（a-date-picker 返回）和字符串
 * a-date-picker v-model 绑定的值在用户选择后是 Dayjs，不是 string
 */
function toDateStr(val: any): string {
  if (!val) return ''
  // Dayjs 对象
  if (typeof val === 'object' && val.format && typeof val.format === 'function') {
    return val.format('YYYY-MM-DD')
  }
  // 已经是字符串
  if (typeof val === 'string') return val
  return ''
}

/** 获取生效日期的字符串形式 */
const effDateStr = computed(() => toDateStr(editForm.effective_date))

/** 获取失效日期的字符串形式 */
const expDateStr = computed(() => toDateStr(editForm.expiry_date))

/** 根据生效日期 + 月数计算失效日期 */
function calcExpiryDate(months: number): string {
  const effRaw = effDateStr.value || new Date().toISOString().slice(0, 10)
  const eff = new Date(effRaw + 'T00:00:00')
  eff.setMonth(eff.getMonth() + months)
  return eff.toISOString().slice(0, 10)
}

/** 设置失效日期（null=永久/清除） */
function setExpiryDate(months: number | null) {
  if (months === null) {
    editForm.expiry_date = undefined as any
  } else {
    // 如果还没填生效日期，默认用今天
    if (!effDateStr.value) {
      editForm.effective_date = new Date().toISOString().slice(0, 10) as any
    }
    editForm.expiry_date = calcExpiryDate(months) as any
  }
}

/** 判断当前 expiry_date 是否匹配指定月数（用于高亮按钮） */
function isExpiryMatch(months: number): boolean {
  const exp = expDateStr.value
  if (!exp || !effDateStr.value) return false
  const expected = calcExpiryDate(months)
  return exp === expected
}

/** 计算当前设置的有效期天数 */
const calcDurationDays = computed(() => {
  const eff = effDateStr.value
  const exp = expDateStr.value
  if (!eff || !exp) return 0
  const effDt = new Date(eff + 'T00:00:00')
  const expDt = new Date(exp + 'T00:00:00')
  return Math.ceil((expDt.getTime() - effDt.getTime()) / (1000 * 60 * 60 * 24))
})

function openAddModal() {
  editingId.value = null
  Object.assign(editForm, {
    platform: 'amazon',
    category: 'listing',
    title: '',
    content: '',
    effective_date: '',
    expiry_date: undefined,
    status: 'auto',
    tagsText: '',
    source: '',
    source_doc_id: undefined,
  })
  editModalVisible.value = true
}

function openEditModal(record: PlatformRule) {
  editingId.value = record.id
  Object.assign(editForm, {
    platform: record.platform,
    category: record.category,
    title: record.title,
    content: record.content,
    effective_date: record.effective_date,
    expiry_date: record.expiry_date,
    status: record.status,
    tagsText: record.tags.join(', '),
    source: record.source || '',
    source_doc_id: record.source_doc_id,
  })
  editModalVisible.value = true
}

async function handleSubmit() {
  if (!editForm.title.trim() || !editForm.content.trim()) {
    message.warning('请填写规则标题和内容')
    return
  }
  saving.value = true
  try {
    const payload = {
      platform: editForm.platform,
      category: editForm.category,
      title: editForm.title.trim(),
      content: editForm.content.trim(),
      effective_date: effDateStr.value || new Date().toISOString().slice(0, 10),
      expiry_date: expDateStr.value || undefined,
      status: editForm.status,
      tags: editForm.tagsText.split(',').map(t => t.trim()).filter(Boolean),
      source: editForm.source.trim(),
      source_doc_id: editForm.source_doc_id || undefined,
    }
    if (editingId.value) {
      await store.updateItem(editingId.value, payload)
      message.success('规则已更新')
    } else {
      await store.addItem(payload)
      message.success('规则已新增')
    }
    editModalVisible.value = false
  } finally {
    saving.value = false
  }
}

function handleDelete(record: PlatformRule) {
  store.deleteItem(record.id)
  message.success('规则已删除')
}

// ====== 详情 ======
const detailVisible = ref(false)
const detailItem = ref<PlatformRule | null>(null)
function openDetail(record: PlatformRule) {
  detailItem.value = record
  detailVisible.value = true
}

// ====== 来源文档预览 ======
const sourceDocVisible = ref(false)
const sourceDocItem = ref<PlatformRuleDoc | null>(null)
const contentExpanded = ref(true)

/** 打开某条规则关联的来源文档预览 */
function openSourceDoc(docId: string) {
  const doc = store.getDocById(docId)
  if (doc) {
    sourceDocItem.value = doc
    contentExpanded.value = true
    sourceDocVisible.value = true
  }
}

function toggleContentExpanded() {
  contentExpanded.value = !contentExpanded.value
}

/** 关联到当前预览文档的所有规则 */
const linkedRules = computed(() => {
  if (!sourceDocItem.value) return []
  return store.items.filter(r => r.source_doc_id === sourceDocItem.value!.id)
})

/** 从文档预览中点击跳转到某条规则详情 */
function viewLinkedRule(rule: PlatformRule) {
  sourceDocVisible.value = false
  detailItem.value = rule
  detailVisible.value = true
}

onMounted(() => {
  store.fetchItems()
})
</script>

<style scoped>
.pr-page {
  padding: 20px;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.pr-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 16px;
  flex-shrink: 0;
}

.pr-title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
}

.pr-subtitle {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--text-tertiary);
}

.header-actions {
  flex-shrink: 0;
}

/* 统计卡片 */
.stat-cards {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
  flex-shrink: 0;
}

.stat-card {
  flex: 1;
  padding: 14px 16px;
  background: var(--bg-sidebar);
  border-radius: 8px;
  border: 1px solid var(--border-base);
}

.stat-value {
  font-size: 22px;
  font-weight: 600;
  color: var(--text-primary);
}

.stat-label {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-top: 2px;
}

/* 工具栏 */
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  flex-shrink: 0;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 过滤 chip 行 */
.active-filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin: -8px 0 16px 0;
  padding: 10px 12px;
  background: var(--bg-sidebar);
  border-radius: 6px;
  border: 1px dashed var(--border-strong);
}

.af-label {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-right: 4px;
}

.af-chip {
  font-size: 12px;
}

/* 表格单元格 */
.title-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.title-text-wrap {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.title-text {
  font-weight: 500;
  color: var(--text-primary);
  line-height: 1.4;
}

.title-sub {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.content-preview {
  color: var(--text-tertiary);
  font-size: 13px;
}

/* 手动覆盖状态徽标 */
.manual-override-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  font-size: 11px;
  margin-left: 4px;
  cursor: default;
}

/* 有效期快捷选择 */
.validity-quick-select {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--bg-sidebar);
  border-radius: 6px;
  border: 1px solid var(--border-base);
  margin-top: -8px;
  margin-bottom: 4px;
  flex-wrap: wrap;
}
.vqs-label {
  font-size: 12px;
  color: var(--text-tertiary);
  white-space: nowrap;
}
.vqs-preview {
  font-size: 12px;
  color: var(--primary);
  white-space: nowrap;
}

/* 详情弹窗 */
.detail-body {
  padding: 4px 0;
}

.detail-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.detail-date {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-left: 4px;
}

.detail-content {
  font-size: 14px;
  line-height: 1.7;
  color: var(--text-primary);
  white-space: pre-wrap;
  margin-bottom: 14px;
}

.detail-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.detail-source {
  color: var(--primary);
  font-size: 13px;
}

/* ====== 文档面板 ====== */
.doc-panel {
  margin-bottom: 16px;
  padding: 12px 16px;
  background: var(--bg-sidebar);
  border: 1px solid var(--border-base);
  border-radius: 8px;
  flex-shrink: 0;
}

.doc-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.doc-panel-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
}

.doc-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.doc-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 8px;
  background: var(--bg-elevated);
  border-radius: 4px;
  border: 1px solid var(--border-base);
}

.doc-info {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.doc-icon {
  font-size: 16px;
}

.doc-name {
  font-size: 13px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.doc-size {
  font-size: 12px;
  color: var(--text-tertiary);
  flex-shrink: 0;
}

.doc-desc {
  font-size: 12px;
  color: var(--text-tertiary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ====== 导入弹窗 ====== */
.import-area {
  padding: 4px 0;
}

.import-result {
  margin-top: 16px;
}

.error-list {
  margin: 4px 0 0;
  padding-left: 18px;
  color: var(--text-secondary);
  font-size: 12px;
}

/* 来源文档关联 */
.detail-source-doc {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  margin-bottom: 14px;
  background: var(--bg-hover-light);
  border-radius: 6px;
  border-left: 3px solid var(--primary);
}

.detail-source-doc-label {
  font-size: 12px;
  color: var(--text-tertiary);
  font-weight: 500;
}

/* 表单提示 */
.form-hint {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-top: 2px;
}

/* 下拉选项中文档平台标签 */
.select-doc-platform {
  color: var(--text-tertiary);
  font-size: 11px;
  margin-left: 4px;
}

/* ====== 来源文档预览弹窗 ====== */
.source-doc-body {
  padding: 0;
}

.source-doc-meta-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 12px 16px;
  background: var(--bg-sidebar);
  border-bottom: 1px solid var(--border-base);
}

.source-doc-size {
  font-size: 12px;
  color: var(--text-tertiary);
}

.source-doc-date {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-left: auto;
}

.source-doc-desc {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.6;
  margin: 0;
  padding: 10px 16px;
  background: var(--bg-elevated);
}

/* ====== 原文内容区 ====== */
.source-doc-content-section {
  border-bottom: 1px solid var(--border-base);
}

.source-doc-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  cursor: pointer;
  user-select: none;
  background: var(--bg-sidebar);
  transition: background 0.15s;
}

.source-doc-section-header:hover {
  background: var(--border-base);
}

.source-doc-section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.source-doc-toggle {
  font-size: 12px;
  color: var(--primary);
  cursor: pointer;
}

.source-doc-content-body {
  padding: 12px 16px;
  max-height: 400px;
  overflow-y: auto;
  background: var(--bg-elevated);
}

.source-doc-text {
  margin: 0;
  font-family: 'SF Mono', Monaco, 'Cascadia Code', 'Consolas', monospace;
  font-size: 12.5px;
  line-height: 1.75;
  color: var(--text-primary);
  white-space: pre-wrap;
  word-wrap: break-word;
  tab-size: 2;
}

.source-doc-desc {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.6;
  margin: 0;
  padding: 10px 16px;
  background: var(--bg-elevated);
}

/* 关联规则列表 */

.source-doc-rules-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 8px 0;
}

.source-doc-rules-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.source-doc-rule-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.15s;
}

.source-doc-rule-item:hover {
  background: var(--info-bg);
}

.source-doc-rule-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-doc-rule-cat {
  font-size: 11px;
  color: var(--text-tertiary);
}

.source-doc-arrow {
  font-size: 11px;
  color: var(--text-tertiary);
  margin-left: auto;
}

/* ====== 文档上传弹窗 ====== */
.doc-upload-preview {
  margin-bottom: 12px;
}

.doc-upload-file {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--bg-sidebar);
  border-radius: 6px;
  border: 1px solid var(--border-base);
}

.doc-upload-icon {
  font-size: 20px;
}

.doc-upload-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
}

.doc-upload-size {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-left: auto;
}

/* ====== AI 拆分确认弹窗 ====== */
.ai-confirm-header {
  margin-bottom: 12px;
}

.ai-confirm-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 8px;
}

.ai-confirm-count {
  font-size: 13px;
  color: var(--text-secondary);
  margin-right: auto;
}

.ai-confirm-list {
  max-height: 45vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.ai-confirm-item {
  display: flex;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  background: var(--bg-sidebar);
  transition: all 0.2s;
}

.ai-confirm-item:hover {
  border-color: var(--info-border);
  background: var(--info-bg);
}

.ai-confirm-item-unchecked {
  opacity: 0.5;
  background: var(--bg-hover-light);
}

.ai-confirm-check {
  padding-top: 4px;
}

.ai-confirm-body {
  flex: 1;
  min-width: 0;
}

.ai-confirm-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.ai-confirm-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
  flex-wrap: wrap;
}

/* AI 拆分——高级设置面板 */
.ai-confirm-advance {
  margin-top: 8px;
  padding: 8px 10px;
  background: var(--bg-sidebar);
  border: 1px solid var(--border-strong);
  border-radius: 6px;
}
.ai-adv-label {
  display: block;
  font-size: 12px;
  color: var(--text-tertiary);
  margin-bottom: 2px;
}
.ai-adv-quick {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 6px;
  flex-wrap: wrap;
  padding: 4px 0;
}

/* AI 拆分——顶部统一设置日期栏 */
.ai-batch-date {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 8px 12px;
  margin-bottom: 12px;
  background: var(--info-bg);
  border: 1px solid var(--info-border);
  border-radius: 6px;
}
.ai-batch-title {
  font-weight: 600;
  font-size: 13px;
  color: var(--primary);
  margin-right: 4px;
  white-space: nowrap;
}
.ai-batch-label {
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
}
.ai-batch-sync {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-left: 4px;
}

/* ====== 去重状态样式 ====== */

/* 统计摘要 */
.ai-confirm-summary {
  display: flex;
  gap: 16px;
  margin-bottom: 12px;
  padding: 8px 12px;
  background: var(--bg-sidebar);
  border-radius: 6px;
}

.ai-stat {
  font-size: 13px;
  font-weight: 500;
}

/* 左侧栏（勾选 + 状态标签） */
.ai-confirm-left {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

/* 去重状态徽标 */
.ai-dup-badge {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
  cursor: default;
  white-space: nowrap;
  user-select: none;
}

.ai-dup-new {
  background: var(--success-bg);
  color: var(--success);
  border: 1px solid var(--success-border);
}

.ai-dup-duplicate {
  background: var(--warning-bg);
  color: var(--warning);
  border: 1px solid var(--warning-border);
}

.ai-dup-update {
  background: var(--info-bg);
  color: var(--primary);
  border: 1px solid var(--info-border);
}

.ai-dup-score {
  opacity: 0.7;
  font-weight: 400;
}

/* 行级状态着色 */
.ai-confirm-item-new {
  border-left: 3px solid var(--success);
}

.ai-confirm-item-dup {
  border-left: 3px solid var(--warning);
  background: linear-gradient(90deg, var(--warning-bg) 0%, var(--bg-sidebar) 100%);
}

.ai-confirm-item-update {
  border-left: 3px solid var(--primary);
  background: linear-gradient(90deg, var(--info-bg) 0%, var(--bg-sidebar) 100%);
}

/* 悬浮提示 */
.ai-dup-tooltip {
  margin: 0;
  line-height: 1.6;
}

.ai-diff-hint {
  font-size: 11px;
  color: var(--primary);
  background: var(--info-bg);
  padding: 1px 6px;
  border-radius: 4px;
}

/* Layer 3 强制确认弹窗 */
.ai-force-list {
  max-height: 200px;
  overflow-y: auto;
  margin-bottom: 12px;
}

.ai-force-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 10px;
  margin-bottom: 6px;
  background: var(--warning-bg);
  border: 1px solid var(--warning-border);
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.5;
}

.ai-force-note {
  font-size: 12px;
  color: var(--text-tertiary);
  margin: 0;
}
</style>
