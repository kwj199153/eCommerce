<template>
  <div class="pl-page">
    <!-- 左侧分组栏 -->
    <div class="pl-sidebar">
      <div class="pl-sidebar-header">
        <span class="pl-sidebar-title">产品分组</span>
        <a-button type="text" size="small" @click="openCreateGroup">
          <PlusOutlined />
        </a-button>
      </div>

      <!-- 「全部产品」入口 -->
      <div
        class="pl-group-item"
        :class="{ active: store.currentGroupId === null }"
        @click="store.selectGroup(null)"
      >
        <span class="pl-color-dot" style="background: var(--text-disabled)"></span>
        <span class="pl-group-name">全部产品</span>
        <span class="pl-group-count">{{ store.totalCount }}</span>
      </div>

      <!-- 分组列表 -->
      <div
        v-for="g in store.groups"
        :key="g.id"
        class="pl-group-item"
        :class="{ active: store.currentGroupId === g.id }"
        @click="store.selectGroup(g.id)"
      >
        <span class="pl-color-dot" :style="{ background: g.color }"></span>
        <span class="pl-group-name">{{ g.name }}</span>
        <span class="pl-group-count">{{ store.groupProductCount[g.id] || 0 }}</span>
        <a-dropdown :trigger="['click']" @click.stop>
          <a-button type="text" size="small" class="pl-group-more" @click.stop>
            <MoreOutlined />
          </a-button>
          <template #overlay>
            <a-menu @click="handleGroupMenuClick($event, g)">
              <a-menu-item key="rename">重命名</a-menu-item>
              <a-menu-item key="color">改颜色</a-menu-item>
              <a-menu-item key="up">上移</a-menu-item>
              <a-menu-item key="down">下移</a-menu-item>
              <a-menu-divider />
              <a-menu-item key="delete" style="color: var(--danger)">删除分组</a-menu-item>
            </a-menu>
          </template>
        </a-dropdown>
      </div>

      <div v-if="store.groups.length === 0" class="pl-group-empty">
        暂无分组，点击右上角 + 新建
      </div>

      <!-- 未分组（虚拟分组，始终置底，不支持改名/删除） -->
      <div
        v-if="store.ungroupedCount > 0"
        class="pl-group-item pl-group-item--ungrouped"
        :class="{ active: store.currentGroupId === '__ungrouped__' }"
        @click="store.selectGroup('__ungrouped__')"
      >
        <span class="pl-color-dot" style="background: var(--text-disabled)"></span>
        <span class="pl-group-name">未分组</span>
        <span class="pl-group-count">{{ store.ungroupedCount }}</span>
      </div>
    </div>

    <!-- 右侧内容区 -->
    <div class="pl-content">
    <!-- 统计卡片 -->
    <div class="stat-cards">
      <div class="stat-card">
        <div class="stat-value">{{ store.totalCount }}</div>
        <div class="stat-label">产品总数</div>
      </div>
      <div class="stat-card stat-draft">
        <div class="stat-value orange">{{ draftCount }}</div>
        <div class="stat-label">草稿待完善</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">${{ formatNumber(store.totalValue) }}</div>
        <div class="stat-label">库存总价值</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ store.avgMargin }}%</div>
        <div class="stat-label">平均利润率</div>
      </div>
      <div class="stat-card">
        <div class="stat-value green">{{ activeCount }}</div>
        <div class="stat-label">在售 Listing</div>
      </div>
    </div>

    <!-- 操作栏 -->
    <div class="toolbar">
      <div class="toolbar-left">
        <a-radio-group v-model:value="viewMode" size="small" button-style="solid" class="view-switch">
          <a-radio-button value="flat">
            <AppstoreOutlined /> 平铺
          </a-radio-button>
          <a-radio-button value="tree">
            <UnorderedListOutlined /> 树形
          </a-radio-button>
        </a-radio-group>
        <a-input-search
          v-model:value="store.searchQuery"
          placeholder="搜索标题、ASIN、SKU、品牌..."
          style="width: 280px"
          allow-clear
        >
          <template #prefix><SearchOutlined /></template>
        </a-input-search>
        <a-select
          v-model:value="store.filterCategory"
          style="width: 140px"
          placeholder="全部分类"
          allow-clear
        >
          <a-select-option v-for="cat in CATEGORIES" :key="cat.key" :value="cat.key">
            {{ cat.icon }} {{ cat.label }}
            <span v-if="store.categoryStats[cat.key]" class="cat-count">({{ store.categoryStats[cat.key] }})</span>
          </a-select-option>
        </a-select>
        <a-select
          v-model:value="store.filterStatus"
          style="width: 120px"
          placeholder="全部状态"
          allow-clear
        >
          <a-select-option value="draft">📝 草稿 ({{ draftCount }})</a-select-option>
          <a-select-option value="active">✅ 在售</a-select-option>
          <a-select-option value="archived">📦 归档</a-select-option>
        </a-select>
        <a-select
          v-model:value="store.sortBy"
          style="width: 140px"
        >
          <a-select-option value="updated_at">最近更新</a-select-option>
          <a-select-option value="price_asc">价格 ↑</a-select-option>
          <a-select-option value="price">价格 ↓</a-select-option>
          <a-select-option value="sales">日均销量</a-select-option>
          <a-select-option value="rating">评分</a-select-option>
          <a-select-option value="margin">利润率</a-select-option>
          <a-select-option value="bsr">BSR 排名</a-select-option>
        </a-select>
      </div>
      <div class="toolbar-right">
        <a-tooltip title="从 CSV/JSON 文件批量导入产品数据">
          <a-button @click="showImportModal = true">
            <UploadOutlined /> 导入
          </a-button>
        </a-tooltip>
        <a-button type="primary" @click="openAddModal">
          <PlusOutlined /> 新增产品
        </a-button>
      </div>
    </div>

    <!-- 产品列表表格（树形：SPU下挂SKU，SKU缩进） -->
    <a-table
      :columns="columns"
      :data-source="viewMode === 'flat' ? store.flatSpuRows : store.treeItems"
      :loading="store.isLoading"
      row-key="id"
      :pagination="{ pageSize: 12, size: 'small', showTotal: (t: number) => `共 ${t} 个产品` }"
      size="middle"
      :scroll="{ x: 1040, y: 'calc(100vh - 380px)' }"
      :default-expand-all-rows="true"
      :expand-row-by-click="false"
      :indent-size="20"
      :children-column-name="'children'"
      :row-class-name="rowClassName"
    >
      <template #bodyCell="{ column, record }">
        <!-- 产品信息 -->
        <template v-if="column.dataIndex === 'title'">
          <a-popover placement="rightTop" trigger="hover" :overlayStyle="{ width: '340px' }">
            <template #content>
              <div class="hp-preview">
                <img v-if="record.main_image" :src="record.main_image" alt="" class="hp-img" @error="(e: Event) => (e.target as HTMLImageElement).style.display = 'none'" />
                <div class="hp-body">
                  <div class="hp-title">{{ record.title }}</div>
                  <a-tag v-if="record.status === 'draft'" :color="productStatusColor(record.status)" size="small">草稿</a-tag>
                  <div class="hp-meta">
                    <code class="hp-asin">{{ record.asin || '（SPU 无 ASIN）' }}</code>
                    <span class="hp-sku">SKU: {{ record.sku }}</span>
                    <span v-if="record.brand" class="hp-brand">{{ record.brand }}</span>
                  </div>
                  <template v-if="record.is_spu">
                    <div class="hp-parent-note">
                      规格主题：{{ record.spu_theme || '未设置' }} · 共 {{ store.getChildren(record.id).length }} 个 SKU
                    </div>
                  </template>
                  <template v-else>
                  <div class="hp-stats">
                    <div class="hp-stat"><span class="hp-label">售价</span><strong>${{ record.price.toFixed(2) }}</strong></div>
                    <div class="hp-stat"><span class="hp-label">成本</span><strong>${{ record.cost.toFixed(2) }}</strong></div>
                    <div class="hp-stat"><span class="hp-label">利润率</span><strong :class="'margin-' + (record.margin >= 60 ? 'high' : record.margin >= 30 ? 'mid' : 'low')">{{ record.margin }}%</strong></div>
                  </div>
                  <div class="hp-row">
                    <span class="hp-label">评分</span>
                    <span class="stars">{{ '★'.repeat(Math.floor(record.rating)) }}{{ '☆'.repeat(5 - Math.floor(record.rating)) }}</span>
                    <strong>{{ record.rating }}</strong>
                    <span class="hp-sub">({{ formatNumber(record.review_count) }})</span>
                    <span v-if="record.bsr" class="hp-bsr">BSR #{{ record.bsr.toLocaleString() }}</span>
                  </div>
                  <div class="hp-row">
                    <span class="hp-label">库存</span>
                    <strong style="color: var(--primary);">FBA {{ record.fba_stock }}</strong>
                    <span v-if="record.fbm_stock > 0" style="color: var(--text-tertiary); margin-left: 8px;">FBM {{ record.fbm_stock }}</span>
                    <span class="hp-sub" style="margin-left: auto;">日销 <strong>{{ record.daily_sales_avg }}/天</strong></span>
                  </div>
                  <div v-if="record.selling_points" class="hp-points">
                    <div v-for="(sp, i) in record.selling_points.split(' | ').slice(0, 3)" :key="i" class="hp-point">{{ sp }}</div>
                  </div>
                  </template>
                </div>
              </div>
            </template>
            <div class="product-cell">
            <div class="product-cell-head">
              <div class="product-thumb">
                <img v-if="record.main_image" :src="record.main_image" alt="" loading="lazy" @error="onImgError" />
                <div v-else class="thumb-placeholder">🖼️</div>
              </div>
              <div class="product-cell-body">
                <div class="product-title">
                  {{ record.title }}
                  <a-tag v-if="record.status === 'draft'" :color="productStatusColor(record.status)" size="small">草稿</a-tag>
                  <span v-if="record.is_spu" class="var-parent-badge">👪 SPU · {{ store.getChildren(record.id).length }} SKU</span>
                  <span v-else-if="record.spu_id" class="var-child-badge">
                    {{ record.spec_value || 'SKU' }}
                  </span>
                </div>
                <div class="product-meta">
                  <span class="asin">{{ record.asin || '-' }}</span>
                  <a-divider type="vertical" :margin="4" />
                  <span class="sku">{{ record.sku }}</span>
                  <a-divider type="vertical" :margin="4" />
                  <span class="brand">{{ record.brand || '-' }}</span>
                </div>
                <div class="tags-row" v-if="record.tags.length || (record.groups && record.groups.length)">
                  <a-tag v-for="tag in record.tags" :key="tag" size="small" :color="productTagColor(tag)">{{ tag }}</a-tag>
                  <a-tag
                    v-for="gid in (record.groups || [])"
                    :key="'g-' + gid"
                    size="small"
                    :color="getGroupById(gid)?.color || 'default'"
                  >
                    📁 {{ getGroupById(gid)?.name || '未知分组' }}
                  </a-tag>
                </div>
              </div>
            </div>
          </div>
          </a-popover>
        </template>

        <!-- 价格/成本 -->
        <template v-else-if="column.dataIndex === 'price'">
          <!-- 单品：投影唯一 SKU 的售价/成本 -->
          <div v-if="isSingleSkuSpu(record)" class="price-cell price-cell-projected">
            <span class="price">${{ singleSkuOf(record)!.price.toFixed(2) }}</span>
            <span class="cost">成本 ${{ singleSkuOf(record)!.cost.toFixed(2) }}</span>
          </div>
          <!-- 多变体：价格区间 + SKU 数量 -->
          <div v-else-if="record.is_spu" class="spu-summary-cell">
            <span class="price">{{ spuPriceRange(record) }}</span>
            <span class="sku-count">× {{ spuSkus(record).length }} SKU</span>
          </div>
          <div v-else class="price-cell">
            <span class="price">${{ record.price.toFixed(2) }}</span>
            <span class="cost">成本 ${{ record.cost.toFixed(2) }}</span>
          </div>
        </template>

        <!-- 利润率 -->
        <template v-else-if="column.dataIndex === 'margin'">
          <span v-if="isSingleSkuSpu(record)" :class="['margin-badge', 'projected', singleSkuOf(record)!.margin >= 60 ? 'high' : singleSkuOf(record)!.margin >= 30 ? 'mid' : 'low']">
            {{ singleSkuOf(record)!.margin }}%
          </span>
          <span v-else-if="record.is_spu" class="cell-placeholder">—</span>
          <span v-else :class="['margin-badge', record.margin >= 60 ? 'high' : record.margin >= 30 ? 'mid' : 'low']">
            {{ record.margin }}%
          </span>
        </template>

        <!-- BSR -->
        <template v-else-if="column.dataIndex === 'bsr'">
          <span v-if="isSingleSkuSpu(record)" class="projected">
            <template v-if="singleSkuOf(record)!.bsr">#{{ singleSkuOf(record)!.bsr!.toLocaleString() }}</template>
            <template v-else>-</template>
          </span>
          <span v-else-if="record.is_spu" class="cell-placeholder">—</span>
          <span v-else-if="record.bsr">#{{ record.bsr.toLocaleString() }}</span>
          <span v-else class="text-muted">-</span>
        </template>

        <!-- 评分 -->
        <template v-else-if="column.dataIndex === 'rating'">
          <div v-if="isSingleSkuSpu(record)" class="rating-cell projected">
            <span class="stars">{{ '★'.repeat(Math.floor(singleSkuOf(record)!.rating)) }}{{ '☆'.repeat(5 - Math.floor(singleSkuOf(record)!.rating)) }}</span>
            <span class="rating-num">{{ singleSkuOf(record)!.rating }}</span>
            <span class="review-count">({{ formatNumber(singleSkuOf(record)!.review_count) }})</span>
          </div>
          <div v-else-if="record.is_spu" class="cell-placeholder">—</div>
          <div v-else class="rating-cell">
            <span class="stars">{{ '★'.repeat(Math.floor(record.rating)) }}{{ '☆'.repeat(5 - Math.floor(record.rating)) }}</span>
            <span class="rating-num">{{ record.rating }}</span>
            <span class="review-count">({{ formatNumber(record.review_count) }})</span>
          </div>
        </template>

        <!-- 库存 -->
        <template v-else-if="column.dataIndex === 'stock'">
          <!-- 单品：投影唯一 SKU 库存 -->
          <div v-if="isSingleSkuSpu(record)" class="stock-cell projected">
            <span class="fba-stock">FBA: {{ singleSkuOf(record)!.fba_stock }}</span>
            <span v-if="singleSkuOf(record)!.fbm_stock > 0" class="fbm-stock">FBM: {{ singleSkuOf(record)!.fbm_stock }}</span>
          </div>
          <!-- 多变体：总库存汇总 -->
          <div v-else-if="record.is_spu" class="spu-summary-cell">
            <span class="fba-stock">总库存 {{ spuTotalStock(record) }}</span>
            <span class="sku-count">× {{ spuSkus(record).length }} SKU</span>
          </div>
          <div v-else class="stock-cell">
            <span class="fba-stock">FBA: {{ record.fba_stock }}</span>
            <span v-if="record.fbm_stock > 0" class="fbm-stock">FBM: {{ record.fbm_stock }}</span>
          </div>
        </template>

        <!-- 日均销量 -->
        <template v-else-if="column.dataIndex === 'daily_sales_avg'">
          <template v-if="isSingleSkuSpu(record)"><strong class="projected">{{ singleSkuOf(record)!.daily_sales_avg }}</strong><span class="unit">/天</span></template>
          <span v-else-if="record.is_spu" class="cell-placeholder">—</span>
          <template v-else><strong>{{ record.daily_sales_avg }}</strong><span class="unit">/天</span></template>
        </template>

        <!-- Listing 状态 -->
        <template v-else-if="column.dataIndex === 'listing_status'">
          <a-tag v-if="record.is_spu" size="small" color="purple">SPU</a-tag>
          <a-badge
            v-else
            :status="listingStatusMap[record.listing_status]?.status || 'default'"
            :text="listingStatusMap[record.listing_status]?.text || record.listing_status"
          />
        </template>

        <!-- 操作 -->
        <template v-else-if="column.dataIndex === 'actions'">
          <a-space>
            <!-- SPU：新增SKU + AIGC + Listing 优化 + 详情 + 编辑 + 删除 -->
            <template v-if="record.is_spu">
              <a-tooltip title="新增SKU">
                <a-button type="text" size="small" class="aigc-btn" @click="openAddChild(record)">
                  <PlusOutlined />
                </a-button>
              </a-tooltip>
              <!-- AIGC 媒体生成：SPU也可触发，用SPU公共文案作为模板 -->
              <a-tooltip title="AIGC 媒体生成">
                <a-button type="text" size="small" class="aigc-btn" @click="handleAigcLaunch(record)">
                  <PictureOutlined />
                </a-button>
              </a-tooltip>
              <!-- Listing 优化：SPU可基于公共文案模板生成 Listing -->
              <a-tooltip title="Listing 优化">
                <a-button type="text" size="small" class="listing-opt-btn" @click="handleListingOptimize(record)">
                  <FileTextOutlined />
                </a-button>
              </a-tooltip>
              <a-tooltip title="查看详情">
                <a-button type="text" size="small" @click="openDetailDrawer(record)">
                  <EyeOutlined />
                </a-button>
              </a-tooltip>
              <a-tooltip title="编辑SPU">
                <a-button type="text" size="small" @click="openEditModal(record)">
                  <EditOutlined />
                </a-button>
              </a-tooltip>
              <a-popconfirm title="删除SPU将同时删除其全部SKU，确定？" @confirm="handleDeleteParent(record)">
                <a-tooltip title="删除">
                  <a-button type="text" size="small" danger>
                    <DeleteOutlined />
                  </a-button>
                </a-tooltip>
              </a-popconfirm>
            </template>
            <!-- 独立产品（非父非子）：自我组化 + AIGC + Listing 优化 + 详情 + 编辑 + 删除 -->
            <template v-else-if="!record.spu_id">
              <a-tooltip title="提升为SPU（本产品将成为第一个 SKU）">
                <a-button type="text" size="small" class="aigc-btn" @click="openPromoteToGroup(record)">
                  <PlusOutlined />
                </a-button>
              </a-tooltip>
              <a-tooltip title="AIGC 媒体生成">
                <a-button type="text" size="small" class="aigc-btn" @click="handleAigcLaunch(record)">
                  <PictureOutlined />
                </a-button>
              </a-tooltip>
              <a-tooltip :title="record.status === 'draft' ? 'Listing 优化（草稿）' : 'Listing 优化'">
                <a-button type="text" size="small" :class="['listing-opt-btn', { 'is-draft': record.status === 'draft' }]" @click="handleListingOptimize(record)">
                  <FileTextOutlined />
                </a-button>
              </a-tooltip>
              <a-tooltip title="查看详情">
                <a-button type="text" size="small" @click="openDetailDrawer(record)">
                  <EyeOutlined />
                </a-button>
              </a-tooltip>
              <a-tooltip title="编辑">
                <a-button type="text" size="small" @click="openEditModal(record)">
                  <EditOutlined />
                </a-button>
              </a-tooltip>
              <a-popconfirm title="确定删除此产品？" @confirm="handleDelete(record.id)">
                <a-tooltip title="删除">
                  <a-button type="text" size="small" danger>
                    <DeleteOutlined />
                  </a-button>
                </a-tooltip>
              </a-popconfirm>
            </template>
            <!-- SKU：图片 + 详情 + 编辑 + 删除（SKU 无文案，无 Listing） -->
            <template v-else>
              <a-tooltip title="AIGC 媒体生成">
                <a-button type="text" size="small" class="aigc-btn" @click="handleAigcLaunch(record)">
                  <PictureOutlined />
                </a-button>
              </a-tooltip>
              <a-tooltip title="查看详情">
                <a-button type="text" size="small" @click="openDetailDrawer(record)">
                  <EyeOutlined />
                </a-button>
              </a-tooltip>
              <a-tooltip title="编辑">
                <a-button type="text" size="small" @click="openEditModal(record)">
                  <EditOutlined />
                </a-button>
              </a-tooltip>
              <a-popconfirm title="确定删除此产品？" @confirm="handleDelete(record.id)">
                <a-tooltip title="删除">
                  <a-button type="text" size="small" danger>
                    <DeleteOutlined />
                  </a-button>
                </a-tooltip>
              </a-popconfirm>
            </template>
          </a-space>
        </template>
      </template>
    </a-table>

    <!-- 新增/编辑产品弹窗 -->
    <ProductFormModal v-model:open="modalVisible" :editing-id="editingId" @saved="onSaved" />

    <!-- SKU 增删弹窗 -->
    <SkuFormModal v-model:open="childModalVisible" :editing-id="childEditingId" :parent-id="childParentId" @saved="onSaved" />

    <!-- 提升为 SPU 弹窗 -->
    <PromoteSkuModal v-model:open="promoteModalVisible" :product-id="promoteTargetId" @saved="onSaved" />

    <!-- 详情抽屉 -->
    <a-drawer
      v-model:open="drawerVisible"
      :title="currentDetail?.title || '产品详情'"
      width="520"
      placement="right"
    >
      <template v-if="currentDetail">
        <!-- 主图 -->
        <div class="detail-main-image">
          <img v-if="currentDetail.main_image" :src="currentDetail.main_image" alt="主图" @error="onImgError" />
          <div v-else class="detail-image-placeholder">🖼️ 暂无主图</div>
          <div v-if="currentDetail.images?.length" class="detail-thumbs">
            <img
              v-for="(img, i) in currentDetail.images"
              :key="i"
              :src="img"
              alt="附图"
              loading="lazy"
              @error="onImgError"
            />
          </div>
        </div>

        <!-- 竞品管理入口（产品详情维护对标竞品；监控驱动统一在下方"关联竞品·定向监控"区） -->
        <div style="margin-bottom: 12px; display:flex; gap:8px; flex-wrap:wrap; align-items:center">
          <a-button type="primary" size="small" @click="openCompetitorManager">
            <TeamOutlined /> 对标竞品管理
          </a-button>
        </div>

        <a-descriptions :column="1" bordered size="small">
          <a-descriptions-item label="ASIN"><code>{{ detailDisplay.asin || '-' }}</code></a-descriptions-item>
          <a-descriptions-item label="SKU">{{ detailDisplay.sku }}</a-descriptions-item>
          <a-descriptions-item label="品牌">{{ detailDisplay.brand || '-' }}</a-descriptions-item>
          <a-descriptions-item label="售价">${{ detailDisplay.price.toFixed(2) }}</a-descriptions-item>
          <a-descriptions-item label="成本">${{ detailDisplay.cost.toFixed(2) }}</a-descriptions-item>
          <a-descriptions-item label="利润率">
            <span :class="['margin-badge', detailDisplay.margin >= 60 ? 'high' : detailDisplay.margin >= 30 ? 'mid' : 'low']">
              {{ detailDisplay.margin }}%
            </span>
          </a-descriptions-item>
          <a-descriptions-item label="ROI">{{ detailDisplay.roi }}%</a-descriptions-item>
          <a-descriptions-item label="BSR">#{{ detailDisplay.bsr?.toLocaleString() || '-' }}</a-descriptions-item>
          <a-descriptions-item label="评分">{{ detailDisplay.rating }} ({{ detailDisplay.review_count }} 评论)</a-descriptions-item>
          <a-descriptions-item label="FBA 库存">{{ detailDisplay.fba_stock }}</a-descriptions-item>
          <a-descriptions-item label="FBM 库存">{{ detailDisplay.fbm_stock }}</a-descriptions-item>
          <a-descriptions-item label="日均销量">{{ detailDisplay.daily_sales_avg }}/天</a-descriptions-item>
          <a-descriptions-item label="配送">{{ detailDisplay.fulfillment_type }}</a-descriptions-item>
          <a-descriptions-item label="标签">
            <a-tag v-for="t in detailDisplay.tags" :key="t">{{ t }}</a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="备注">{{ detailDisplay.notes || '-' }}</a-descriptions-item>
        </a-descriptions>

        <!-- Listing 信息 -->
        <div
          v-if="detailDisplay.generated_title || detailDisplay.generated_bullets?.length || detailDisplay.description || detailDisplay.seo_score"
          class="detail-section"
        >
          <h4>
            📝 Listing 信息
            <a-tag v-if="detailDisplay.seo_score" :color="getSeoScoreColor(detailDisplay.seo_score)" size="small">
              SEO {{ detailDisplay.seo_score }}
            </a-tag>
            <a-tag v-if="detailDisplay.listing_version" color="default" size="small">v{{ detailDisplay.listing_version }}</a-tag>
          </h4>

          <!-- 标题对比 -->
          <div v-if="detailDisplay.generated_title" class="listing-block">
            <div class="listing-label">产品标题</div>
            <div class="listing-title">{{ detailDisplay.generated_title }}</div>
          </div>

          <!-- 五点描述 -->
          <div v-if="detailDisplay.generated_bullets?.length" class="listing-block">
            <div class="listing-label">五点描述 (Bullet Points)</div>
            <div
              v-for="(b, i) in detailDisplay.generated_bullets"
              :key="i"
              class="bullet-item"
            >
              <div class="bullet-title">▸ {{ b.title }}</div>
              <div class="bullet-content">{{ b.content }}</div>
            </div>
          </div>

          <!-- 商品描述 -->
          <div v-if="detailDisplay.description" class="listing-block">
            <div class="listing-label">商品描述 (Description)</div>
            <div class="listing-desc">{{ detailDisplay.description }}</div>
          </div>

          <!-- 竞品 ASIN + 定向监控态（监控驱动统一在此：单行/批量） -->
          <div v-if="detailDisplay.competitor_asins?.length" class="listing-block">
            <div class="cm-section-head">
              <div class="listing-label">关联竞品 · 定向监控</div>
              <a-button
                size="small"
                type="link"
                class="cm-batch-btn"
                :loading="inheritingMonitor"
                :disabled="!unmonitoredCompetitorCount"
                @click="inheritMonitorFromCompetitors(currentDetail)"
              >
                <FundOutlined /> 全部开启监控{{ unmonitoredCompetitorCount ? `（${unmonitoredCompetitorCount}）` : '（已全监控）' }}
              </a-button>
            </div>
            <div class="competitor-mon-list">
              <div v-for="c in detailDisplay.competitor_asins" :key="c" class="competitor-mon-row">
                <img
                  v-if="productCompetitorMap[c]?.main_image"
                  class="cm-img"
                  :src="productCompetitorMap[c]?.main_image"
                  :alt="c"
                  loading="lazy"
                  @error="(e: Event) => { (e.target as HTMLImageElement).style.display = 'none'; const fb = (e.target as HTMLImageElement).nextElementSibling as HTMLElement | null; if (fb) fb.style.display = 'inline-flex'; }"
                />
                <span class="cm-img-fb" :style="{ display: productCompetitorMap[c]?.main_image ? 'none' : 'inline-flex' }">🏷️</span>
                <span class="cm-asin">{{ c }}</span>
                <a-button
                  v-if="mpStore.isAsinInPool(c)"
                  type="link"
                  size="small"
                  danger
                  class="cm-mon-act"
                  @click="removeMonitoredCompetitor(c)"
                >停止监控</a-button>
                <a-button
                  v-else
                  type="link"
                  size="small"
                  class="cm-mon-act"
                  @click="monitorOneCompetitor(c)"
                >开启监控</a-button>
              </div>
            </div>
          </div>
        </div>

        <!-- SKU 列表（SPU 详情） -->
        <div v-if="currentDetail.is_spu && detailSkus.length" style="margin-top: 16px">
          <h4>SKU ({{ currentDetail.spu_theme || '未设置规格主题' }})</h4>
          <a-table
            :columns="variationColumns"
            :data-source="detailSkus"
            :pagination="false"
            size="small"
            row-key="asin"
          />
        </div>
      </template>
    </a-drawer>

    <!-- 竞品管理（入口2：产品详情持久维护对标竞品） -->
    <CompetitorManager
      v-model:open="cmOpen"
      :owner="cmOwner"
      owner-type="product"
      @saved="onCmSaved"
    />

    <!-- 文件导入弹窗 -->
    <a-modal
      v-model:open="showImportModal"
      title="批量导入产品"
      width="540px"
      :footer="null"
    >
      <div class="import-area">
        <a-upload-dragger
          :file-list="importFileList"
          :before-upload="handleImportFile"
          :remove="() => { importFileList = []; return true }"
          accept=".json,.csv"
          :max-count="1"
        >
          <p class="ant-upload-drag-icon"><InboxOutlined /></p>
          <p class="ant-upload-text">点击或拖拽文件到此区域上传</p>
          <p class="ant-upload-hint">
            支持 JSON / CSV 格式<br/>
            CSV 列：asin, sku, title, brand, category, price, cost, fba_stock...
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
              </ul>
            </template>
          </a-alert>
        </div>
      </div>
    </a-modal>

    <!-- 新建分组弹窗 -->
    <a-modal
      v-model:open="createGroupVisible"
      title="新建产品分组"
      :footer="null"
      :width="400"
      centered
    >
      <a-form layout="vertical">
        <a-form-item label="分组名称">
          <a-input
            v-model:value="createGroupName"
            placeholder="如：高利润小家电、潜力赛道"
            @pressEnter="submitCreateGroup"
          />
        </a-form-item>
        <a-form-item label="标签颜色">
          <div class="pl-color-picker">
            <span
              v-for="c in GROUP_COLORS"
              :key="c"
              class="pl-color-swatch"
              :class="{ active: createGroupColor === c }"
              :style="{ background: c }"
              @click="createGroupColor = c"
            ></span>
          </div>
        </a-form-item>
      </a-form>
      <template #footer>
        <a-button @click="createGroupVisible = false">取消</a-button>
        <a-button type="primary" @click="submitCreateGroup">创建</a-button>
      </template>
    </a-modal>

    <!-- 重命名分组弹窗 -->
    <a-modal
      v-model:open="renameVisible"
      title="重命名分组"
      :footer="null"
      :width="400"
      centered
    >
      <a-input v-model:value="renameValue" placeholder="新分组名称" @pressEnter="submitRename" />
      <template #footer>
        <a-button @click="renameVisible = false">取消</a-button>
        <a-button type="primary" @click="submitRename">确定</a-button>
      </template>
    </a-modal>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import {
  PlusOutlined,
  UploadOutlined,
  SearchOutlined,
  EditOutlined,
  DeleteOutlined,
  EyeOutlined,
  InboxOutlined,
  MoreOutlined,
  TeamOutlined,
  FundOutlined,
  PictureOutlined,
  FileTextOutlined,
  AppstoreOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons-vue'
import { useProductLibraryStore, PRODUCT_CATEGORIES, GROUP_COLORS, type ProductItem, type ProductGroup } from '@/stores/productLibrary'
import CompetitorManager from '@/components/competitor/CompetitorManager.vue'
import ProductFormModal from './ProductLibrary/ProductFormModal.vue'
import SkuFormModal from './ProductLibrary/SkuFormModal.vue'
import PromoteSkuModal from './ProductLibrary/PromoteSkuModal.vue'
import { useCompetitorPoolStore } from '@/stores/competitorPool'
import { useMonitorPoolStore } from '@/stores/monitorPool'
import { productTagColor, productStatusColor } from '@/utils/colorSemantics'

const store = useProductLibraryStore()
const cpStore = useCompetitorPoolStore()
const mpStore = useMonitorPoolStore()
const CATEGORIES = PRODUCT_CATEGORIES

/** 视图模式：flat 平铺（仅 SPU 产品款）｜ tree 树形（SPU 父行 + SKU 缩进） */
const viewMode = ref<'flat' | 'tree'>('tree')

/** 表格行 class：SPU高亮 + 左侧色条；SKU加左侧竖线标记层级 */
function rowClassName(record: ProductItem) {
  if (record.is_spu) return 'pl-row-parent'
  if (record.spu_id) return 'pl-row-child'
  return ''
}

/**
 * SPU 行「只读投影」：仅页面展示，不写库。
 * - 单品（1 SPU + 仅 1 SKU）：把唯一 SKU 的售价/成本/利润率/BSR/评分/库存/日销 投影到 SPU 父行
 * - 多变体（SKU 数 > 1）：SPU 行显示汇总（价格区间 / 总库存 / SKU 数量）
 */
/** 取 SPU 行的 SKU 子行数组（优先 record.children，兜底 store.getChildren） */
function spuSkus(record: ProductItem): ProductItem[] {
  if (!record.is_spu) return []
  if (record.children && record.children.length) return record.children
  return store.getChildren(record.id)
}
/** 是否「单品」：SPU 且仅 1 个 SKU */
function isSingleSkuSpu(record: ProductItem): boolean {
  return record.is_spu && spuSkus(record).length === 1
}
/** 单 SKU 时返回唯一子行（否则 undefined） */
function singleSkuOf(record: ProductItem): ProductItem | undefined {
  const sks = spuSkus(record)
  return sks.length === 1 ? sks[0] : undefined
}
/** SPU 多变体：价格区间文本「$min - $max」 */
function spuPriceRange(record: ProductItem): string {
  const sks = spuSkus(record)
  if (!sks.length) return '—'
  const prices = sks.map(s => s.price)
  const min = Math.min(...prices)
  const max = Math.max(...prices)
  return min === max ? `$${min.toFixed(2)}` : `$${min.toFixed(2)} - $${max.toFixed(2)}`
}
/** SPU 多变体：总库存（FBA 求和） */
function spuTotalStock(record: ProductItem): number {
  return spuSkus(record).reduce((sum, s) => sum + s.fba_stock, 0)
}

// ====== 竞品管理（入口2）======
const cmOpen = ref(false)
const cmOwner = ref<{ asin: string; title?: string; brand?: string; category?: string; keywords?: string[]; main_image?: string } | null>(null)
/** 当前详情产品的对标竞品 asin → CompetitorRef 映射（含 main_image），渲染缩略图用 */
const productCompetitorMap = computed(() => {
  if (!currentDetail.value) return {} as Record<string, { main_image?: string }>
  const list = cpStore.poolCompetitors('product', currentDetail.value.asin)
  const m: Record<string, { main_image?: string }> = {}
  for (const c of list) m[c.asin] = { main_image: c.main_image }
  return m
})
function openCompetitorManager() {
  if (!currentDetail.value) return
  const p = currentDetail.value
  cmOwner.value = {
    asin: p.asin,
    title: p.title,
    brand: p.brand,
    category: p.category,
    keywords: p.keywords || [],
    main_image: p.main_image || '',
  }
  cmOpen.value = true
}
function onCmSaved() {
  // 竞品已写回该产品 competitor_asins（store.updateItem 已同步响应式）
}

// ====== 定向监控：批量继承对标竞品到监控池 ======
const inheritingMonitor = ref(false)
/** 详情产品的对标竞品中，尚未纳入监控池的数量（>0 时"全部开启监控"可用） */
const unmonitoredCompetitorCount = computed(() => {
  if (!currentDetail.value?.competitor_asins?.length) return 0
  return currentDetail.value.competitor_asins.filter(a => !mpStore.isAsinInPool(a)).length
})
/** 批量：把该产品 competitor_asins 里未监控的，纳入监控池并归属当前产品（定向监控） */
function inheritMonitorFromCompetitors(p: ProductItem) {
  // 拉取已配置的对标竞品（含 main_image / brand / category），入池时一并带上主图，便于监控页直接看图
  const allOwned = cpStore.poolCompetitors('product', p.asin)
  const ownedByAsin = new Map(allOwned.map(c => [c.asin, c]))
  const list = (p.competitor_asins || []).filter(a => !mpStore.isAsinInPool(a))
  if (!list.length) { message.info('对标竞品已全部在监控池'); return }
  inheritingMonitor.value = true
  try {
    const { added, existing } = mpStore.addManyFromCompetitors(list.map(asin => {
      const c = ownedByAsin.get(asin)
      return {
        asin,
        title: c?.title,
        brand: c?.brand,
        main_image: c?.main_image,
        category: p.category,
        ownedBy: { type: 'product' as const, asin: p.asin, title: p.title },
      }
    }))
    if (added) message.success(`已继承 ${added} 个对标竞品到监控池（归属「${p.title}」）`)
    if (existing) message.info(`${existing} 个已在监控池`)
  } finally { inheritingMonitor.value = false }
}

/** 单个对标竞品 → 定向监控（归属当前产品） */
function monitorOneCompetitor(asin: string) {
  const p = currentDetail.value
  if (!p) return
  // 同样带上 main_image / brand / category，避免监控池列表显示空图
  const c = cpStore.poolCompetitors('product', p.asin).find(x => x.asin === asin)
  mpStore.addFromCompetitor({
    asin,
    title: c?.title,
    brand: c?.brand,
    main_image: c?.main_image,
    category: p.category,
    ownedBy: { type: 'product', asin: p.asin, title: p.title },
  })
  message.success(`已开启 ${asin} 的监控（归属「${p.title}」）`)
}

/** 从监控池移除该竞品（停止定向监控，保留对标引用） */
function removeMonitoredCompetitor(asin: string) {
  mpStore.removeRecords([asin])
  message.success(`已停止监控 ${asin}（对标引用保留）`)
}

// ====== 计算属性 ======
const activeCount = computed(() =>
  store.items.filter(p => p.listing_status === 'active').length
)
const draftCount = computed(() =>
  store.items.filter(p => p.status === 'draft').length
)

// ====== 表格列 ======
const columns = [
  { title: '产品信息', dataIndex: 'title', width: 220, ellipsis: true },
  { title: '售价/成本', dataIndex: 'price', width: 105 },
  { title: '利润率', dataIndex: 'margin', width: 78, sorter: (a: ProductItem, b: ProductItem) => a.margin - b.margin },
  { title: 'BSR', dataIndex: 'bsr', width: 80 },
  { title: '评分', dataIndex: 'rating', width: 115 },
  { title: '库存', dataIndex: 'stock', width: 105 },
  { title: '日销', dataIndex: 'daily_sales_avg', width: 70 },
  { title: 'Listing', dataIndex: 'listing_status', width: 70 },
  { title: '操作', dataIndex: 'actions', width: 168, fixed: 'right' as const },
]

const variationColumns = [
  { title: 'ASIN', dataIndex: 'asin', width: 130 },
  { title: '规格值', dataIndex: 'spec_value', width: 100 },
  { title: '价格', dataIndex: 'price', width: 80 },
  { title: '库存', dataIndex: 'fba_stock', width: 80 },
]

const listingStatusMap: Record<string, { status: string; text: string }> = {
  active: { status: 'success', text: '在售' },
  inactive: { status: 'default', text: '停售' },
  suppressed: { status: 'warning', text: '被抑制' },
  pending: { status: 'processing', text: '待上架' },
}

// ====== 弹窗（子组件自治，主文件只持 open 状态与当前编辑对象 id）======
const modalVisible = ref(false)
const editingId = ref<string | null>(null)

function openAddModal() {
  editingId.value = null
  modalVisible.value = true
}

function openEditModal(record: ProductItem) {
  editingId.value = record.id
  modalVisible.value = true
}

/** 任一弹窗保存成功后回调（子组件已自行关弹窗 + 弹提示） */
function onSaved() {}

async function handleDelete(id: string) {
  await store.deleteItem(id)
  message.success('已删除')
}

/** 删除SPU：级联删除其全部SKU */
async function handleDeleteParent(parent: ProductItem) {
  const children = store.getChildren(parent.id)
  for (const child of children) {
    await store.deleteItem(child.id)
  }
  await store.deleteItem(parent.id)
  message.success(`已删除SPU及 ${children.length} 个 SKU`)
}

// ====== 分组操作 ======
const getGroupById = (id: string): ProductGroup | undefined =>
  store.groups.find(g => g.id === id)

// 新建分组
const createGroupVisible = ref(false)
const createGroupName = ref('')
const createGroupColor = ref(GROUP_COLORS[0])

function openCreateGroup() {
  createGroupName.value = ''
  createGroupColor.value = GROUP_COLORS[store.groups.length % GROUP_COLORS.length]
  createGroupVisible.value = true
}

async function submitCreateGroup() {
  const name = createGroupName.value.trim()
  if (!name) {
    message.warning('请输入分组名称')
    return
  }
  const group = await store.createGroup({ name, color: createGroupColor.value })
  store.selectGroup(group.id)
  message.success(`分组「${group.name}」已创建`)
  createGroupVisible.value = false
}

// 重命名
const renameVisible = ref(false)
const renameValue = ref('')
const renameTargetId = ref<string | null>(null)

function submitRename() {
  if (!renameTargetId.value || !renameValue.value.trim()) return
  store.renameGroup(renameTargetId.value, renameValue.value)
  message.success('已重命名')
  renameVisible.value = false
}

function handleGroupMenuClick(e: { key: string }, group: ProductGroup) {
  switch (e.key) {
    case 'rename':
      renameTargetId.value = group.id
      renameValue.value = group.name
      renameVisible.value = true
      break
    case 'color':
      const idx = GROUP_COLORS.indexOf(group.color)
      const next = GROUP_COLORS[(idx + 1) % GROUP_COLORS.length]
      store.setGroupColor(group.id, next)
      break
    case 'up':
      store.moveGroup(group.id, 'up')
      break
    case 'down':
      store.moveGroup(group.id, 'down')
      break
    case 'delete':
      store.deleteGroup(group.id)
      message.success('分组已删除')
      break
  }
}

// ====== Listing 优化（跳转到对话视图）======
function handleListingOptimize(record: ProductItem) {
  // 通过 CustomEvent 通知 Workspace 切换到对话视图并带入商品数据
  window.dispatchEvent(new CustomEvent('product-listing-optimize', {
    detail: record,
  }))
}

// ====== SPU 下 SKU 的增删维护（弹窗已下沉 SkuFormModal，主文件持 open 与当前对象）======
const childModalVisible = ref(false)
const childEditingId = ref<string | null>(null)
const childParentId = ref<string | null>(null)

function openAddChild(parent: ProductItem) {
  childEditingId.value = null
  childParentId.value = parent.id
  childModalVisible.value = true
}

function openEditChild(child: ProductItem) {
  childEditingId.value = child.id
  childParentId.value = child.spu_id || null
  childModalVisible.value = true
}

async function handleDeleteChild(child: ProductItem) {
  await store.deleteItem(child.id)
  message.success('SKU已删除')
}

// ====== 自我组化：独立产品 → SPU（弹窗已下沉 PromoteSkuModal）======
const promoteModalVisible = ref(false)
const promoteTargetId = ref<string | null>(null)

function openPromoteToGroup(product: ProductItem) {
  promoteTargetId.value = product.id
  promoteModalVisible.value = true
}

// ====== AIGC 媒体生成（跳转到 AIGC Agent + 载入产品）======
function handleAigcLaunch(record: ProductItem) {
  window.dispatchEvent(new CustomEvent('product-aigc-launch', {
    detail: record,
  }))
}

// ====== 详情抽屉 ======
const drawerVisible = ref(false)
const currentDetail = ref<ProductItem | null>(null)

function openDetailDrawer(record: ProductItem) {
  currentDetail.value = record
  drawerVisible.value = true
}

/** 详情抽屉里 SPU 的 SKU 列表：始终取真实 SKU（不受 treeItems 单品隐藏 children 影响） */
const detailSkus = computed<ProductItem[]>(() => {
  const p = currentDetail.value
  if (!p || !p.is_spu) return []
  return store.getChildren(p.id)
})

/**
 * 详情抽屉展示对象：单品 SPU 时，把唯一 SKU 的交易 + Listing 数据投影到 SPU 上（仅展示），
 * 避免详情里显示 $0.00 / #- / 0 库存 / 空 Listing 等空值。多变体 SPU 保持原样（交易/Listing 字段由各 SKU 行承载）。
 */
const detailDisplay = computed<ProductItem>(() => {
  const p = currentDetail.value
  if (!p) return p as unknown as ProductItem
  if (p.is_spu && detailSkus.value.length === 1) {
    const sku = detailSkus.value[0]
    return {
      ...p,
      price: sku.price,
      cost: sku.cost,
      margin: sku.margin,
      roi: sku.roi,
      bsr: sku.bsr,
      rating: sku.rating,
      review_count: sku.review_count,
      fba_stock: sku.fba_stock,
      fbm_stock: sku.fbm_stock,
      daily_sales_avg: sku.daily_sales_avg,
      fulfillment_type: sku.fulfillment_type,
      asin: sku.asin,
      sku: sku.sku,
      // Listing 字段（SKU 独立文案，单品场景投影到 SPU 详情展示）
      listing_status: sku.listing_status,
      generated_title: sku.generated_title,
      generated_bullets: sku.generated_bullets,
      generated_a_plus: sku.generated_a_plus,
      seo_score: sku.seo_score,
      generated_at: sku.generated_at,
      listing_version: sku.listing_version,
      listing_history: sku.listing_history,
      has_a_plus: sku.has_a_plus,
      has_video: sku.has_video,
      rating_breakdown: sku.rating_breakdown,
      competitor_asins: sku.competitor_asins ?? p.competitor_asins,
    }
  }
  return p
})

// ====== 文件导入 ======
const showImportModal = ref(false)
const importFileList = ref<any[]>([])
const importResult = ref<{ success: number; failed: number; errors: string[] } | null>(null)

async function handleImportFile(file: File) {
  importFileList.value = [file]
  importResult.value = await store.parseAndImport(file)
  if (importResult.value.success > 0) {
    message.success(`成功导入 ${importResult.value.success} 个产品`)
  }
  return false
}

// ====== 辅助 ======
function formatNumber(n: number): string {
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K'
  return n.toString()
}

/** SEO 评分颜色 */
function getSeoScoreColor(score: number): string {
  if (score >= 80) return 'green'
  if (score >= 60) return 'blue'
  if (score >= 40) return 'orange'
  return 'red'
}

/** 图片加载失败时隐藏破图，显示占位 */
function onImgError(e: Event) {
  const el = e.target as HTMLImageElement
  el.style.display = 'none'
  // 若存在相邻占位元素则显示它
  const parent = el.parentElement
  if (parent) {
    const ph = parent.querySelector('.thumb-placeholder, .detail-image-placeholder')
    if (ph) (ph as HTMLElement).style.display = 'flex'
  }
}

onMounted(() => {
  store.fetchItems()
})
</script>

<style scoped>
.pl-page {
  height: 100%;
  display: flex;
  overflow: hidden;
}

/* ===== 左侧分组栏 ===== */
.pl-sidebar {
  width: 220px;
  flex-shrink: 0;
  border-right: 1px solid var(--border-base);
  display: flex;
  flex-direction: column;
  background: var(--bg-sidebar);
  overflow-y: auto;
}

.pl-sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 16px 8px;
}

.pl-sidebar-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.pl-group-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 16px;
  cursor: pointer;
  transition: background 0.15s;
  font-size: 13px;
}

.pl-group-item:hover {
  background: var(--border-base);
}

.pl-group-item.active {
  background: var(--bg-active-light);
  border-right: 3px solid var(--primary);
}

.pl-color-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.pl-group-name {
  flex: 1;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pl-group-count {
  font-size: 11px;
  color: var(--text-tertiary);
  background: var(--border-base);
  border-radius: 10px;
  padding: 0 8px;
}

.pl-group-more {
  opacity: 0;
  transition: opacity 0.15s;
}

.pl-group-item:hover .pl-group-more {
  opacity: 1;
}

.pl-group-empty {
  padding: 16px;
  font-size: 12px;
  color: var(--text-disabled);
  line-height: 1.6;
}

.pl-group-item--ungrouped {
  margin-top: 8px;
  border-top: 1px dashed var(--border-strong);
  padding-top: 10px;
  opacity: 0.85;
}

.pl-group-item--ungrouped:hover {
  opacity: 1;
}

.pl-color-picker {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.pl-color-swatch {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  cursor: pointer;
  border: 2px solid transparent;
  transition: all 0.2s;
}

.pl-color-swatch.active {
  border-color: var(--text-primary);
  transform: scale(1.15);
}

/* ===== 右侧内容区 ===== */
.pl-content {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  padding: 16px 24px;
}

/* 统计卡片 */
.stat-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 14px;
  flex-shrink: 0;
}

.stat-card {
  background: var(--bg-sidebar);
  border-radius: 8px;
  padding: 12px 16px;
  border: 1px solid var(--border-base);
}

.stat-value {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
}

.stat-value.green {
  color: var(--success);
}

.stat-value.orange {
  color: var(--warning);
}

.stat-draft {
  background: var(--warning-bg);
}

.stat-label {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-top: 2px;
}

/* Listing 优化按钮 */
.listing-opt-btn {
  color: var(--purple) !important;
}
.listing-opt-btn:hover {
  background: var(--purple-bg) !important;
}
/* 草稿商品 - 更醒目 */
.listing-opt-btn.is-draft {
  color: var(--purple) !important;
  font-weight: bold;
}
.listing-opt-btn.is-draft:hover {
  background: var(--purple-border) !important;
}

/* AIGC 媒体生成按钮（跳转 AIGC Agent，图标同 Agent=PictureOutlined） */
.aigc-btn {
  color: var(--primary) !important;
}
.aigc-btn:hover {
  background: var(--info-bg) !important;
}

/* 工具栏 */
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  flex-shrink: 0;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.view-switch {
  flex-shrink: 0;
}

.toolbar-right {
  display: flex;
  gap: 8px;
}

.cat-count {
  color: var(--text-tertiary);
  font-size: 11px;
  margin-left: 4px;
}

/* 产品单元格 */
.product-cell {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.product-cell-head {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}

.product-thumb {
  width: 48px;
  height: 48px;
  flex-shrink: 0;
  border-radius: 6px;
  overflow: hidden;
  background: var(--bg-sidebar);
  border: 1px solid var(--border-base);
}

.product-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.thumb-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  color: var(--text-disabled);
}

.product-cell-body {
  flex: 1;
  min-width: 0;
}

.product-title {
  font-weight: 500;
  color: var(--text-primary);
  line-height: 1.3;
}

.product-meta {
  font-size: 12px;
  color: var(--text-tertiary);
  display: flex;
  align-items: center;
}

.asin {
  font-family: monospace;
  color: var(--text-secondary);
}

.tags-row {
  display: flex;
  gap: 3px;
  flex-wrap: wrap;
}

/* 价格 */
.price-cell {
  display: flex;
  flex-direction: column;
}

.price {
  font-weight: 600;
  color: var(--text-primary);
}

.cost {
  font-size: 11px;
  color: var(--text-tertiary);
}

/* 利润率 */
.margin-badge {
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 13px;
}
.margin-badge.high { background: var(--success-bg); color: var(--success); }
.margin-badge.mid { background: var(--warning-bg); color: var(--warning); }
.margin-badge.low { background: var(--danger-bg); color: var(--danger); }

/* 评分 */
.rating-cell {
  display: flex;
  align-items: center;
  gap: 4px;
}

.stars {
  color: var(--warning);
  letter-spacing: -1px;
  font-size: 13px;
}

.rating-num {
  font-weight: 600;
  font-size: 13px;
}

.review-count {
  font-size: 11px;
  color: var(--text-tertiary);
}

/* 库存 */
.stock-cell {
  display: flex;
  flex-direction: column;
  font-size: 12px;
}

.fba-stock { color: var(--primary); }
.fbm-stock { color: var(--text-tertiary); }

.unit {
  font-size: 11px;
  color: var(--text-tertiary);
}

.text-muted { color: var(--text-disabled); }

/* 导入区域 */
.import-area { padding: 8px 0; }
.import-result { margin-top: 16px; }
.error-list {
  margin: 4px 0 0; padding-left: 18px;
  color: var(--danger); font-size: 12px;
}

:deep(.ant-table) { flex: 1; overflow: hidden; }
:deep(.ant-table-container) { height: 100%; }
:deep(.ant-table-body) { overflow-y: auto !important; overflow-x: hidden !important; }
:deep(.ant-table-content) { overflow-x: hidden !important; }
/* 操作列 fixed:right 在滚动时与主体对齐 */
:deep(.ant-table-cell-fix-right) { background: var(--bg-elevated) !important; }
:deep(.ant-table-thead > tr > th) {
  background: var(--bg-sidebar) !important;
  font-weight: 600;
  border-right: 1px solid var(--border-base) !important;
  border-bottom: 1px solid var(--border-base) !important;
}
/* 表格所有 cell 边框跟随主题深浅（浅色=#f0f0f0 / 深色=#303030），覆盖 antd 默认 colorPrimary 衍生色 */
:deep(.ant-table-tbody > tr > td),
:deep(.ant-table-cell),
:deep(.ant-table-thead > tr > th) {
  border-right-color: var(--border-base) !important;
  border-bottom-color: var(--border-base) !important;
}
/* 表格内所有可能的边框容器（cell/row/group/fixed列）边框统一跟随主题，彻底消除彩色竖条纹 */
:deep(.ant-table-fixed-right),
:deep(.ant-table-fixed-right table),
:deep(.ant-table-cell-fix-right),
:deep(.ant-table-cell-fix-left) {
  background: var(--bg-elevated) !important;
  border-color: var(--border-base) !important;
}
/* 移除固定列与主表之间的默认阴影边框，避免「拼接缝」看着像竖条纹 */
:deep(.ant-table-fixed-right::before),
:deep(.ant-table-fixed-right::after),
:deep(.ant-table-cell-fix-right::before),
:deep(.ant-table-cell-fix-right::after) {
  display: none !important;
  box-shadow: none !important;
}
/* 最后一列不需要右边框，最后一行不需要下边框，避免与容器边框叠加 */
:deep(.ant-table-tbody > tr > td:last-child),
:deep(.ant-table-thead > tr > th:last-child) {
  border-right: none !important;
}
:deep(.ant-table-tbody > tr:last-child > td) {
  border-bottom: none !important;
}

/* SPU行：白底 + 左侧 1px 极细色条（与列分隔线同色，融入表格整体） */
:deep(.ant-table-tbody > tr.pl-row-parent > td) {
  background: var(--bg-elevated) !important;
  border-left: 1px solid var(--border-base);
}
/* SKU行：白底 + 左侧 1px 极细色条（与列分隔线同色） */
:deep(.ant-table-tbody > tr.pl-row-child > td) {
  background: var(--bg-elevated) !important;
  border-left: 1px solid var(--border-base);
}
/* SPU hover：浅灰底 */
:deep(.ant-table-tbody > tr.pl-row-parent:hover > td) {
  background: var(--bg-hover-light) !important;
}
/* SKU hover：浅灰底 */
:deep(.ant-table-tbody > tr.pl-row-child:hover > td) {
  background: var(--bg-hover-light) !important;
}

/* 详情抽屉主图 */
.detail-main-image {
  margin-bottom: 16px;
}

.detail-main-image > img {
  width: 100%;
  border-radius: 8px;
  border: 1px solid var(--border-base);
  display: block;
  object-fit: cover;
}

.detail-image-placeholder {
  width: 100%;
  height: 160px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-disabled);
  background: var(--bg-sidebar);
  border: 1px dashed var(--border-strong);
  border-radius: 8px;
}

.detail-thumbs {
  display: flex;
  gap: 8px;
  margin-top: 8px;
  flex-wrap: wrap;
}

.detail-thumbs img {
  width: 56px;
  height: 56px;
  object-fit: cover;
  border-radius: 6px;
  border: 1px solid var(--border-base);
}

/* 详情 section 通用 */
.detail-section {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px dashed var(--border-base);
}

.detail-section h4 {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 12px 0;
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 卖点关键词 */
.selling-points {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.selling-point-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 6px 10px;
  background: linear-gradient(135deg, var(--warning-bg) 0%, var(--warning-bg) 100%);
  border-left: 3px solid var(--warning);
  border-radius: 4px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--warning);
}

.sp-num {
  background: var(--warning);
  color: #fff;
  border-radius: 50%;
  width: 18px;
  height: 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  font-weight: 600;
  flex-shrink: 0;
}

.sp-text {
  flex: 1;
  word-break: break-word;
}

.keywords-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  font-size: 11px;
}

.kw-label {
  color: var(--text-tertiary);
  font-size: 11px;
  margin-right: 4px;
}

.kw-tag {
  font-size: 10px;
  margin: 2px !important;
}

/* Listing 信息 */
.listing-block {
  margin-bottom: 14px;
}

.listing-label {
  font-size: 10px;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 6px;
  font-weight: 600;
}

.listing-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  line-height: 1.5;
  padding: 8px 10px;
  background: var(--bg-sidebar);
  border-left: 3px solid var(--primary);
  border-radius: 4px;
}

.bullet-item {
  margin-bottom: 8px;
  padding: 8px 10px;
  background: var(--bg-sidebar);
  border-left: 3px solid var(--success);
  border-radius: 4px;
}

.bullet-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--success);
  margin-bottom: 4px;
  letter-spacing: 0.3px;
}

.bullet-content {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.6;
}

.listing-desc {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.6;
  padding: 8px 10px;
  background: var(--bg-sidebar);
  border-radius: 4px;
}

.competitor-mon-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
/* 定向监控区块标题行：左侧 label，右侧批量开启 */
.cm-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 4px;
}
.cm-section-head .cm-batch-btn {
  font-size: 12px;
  padding: 0 4px;
}
.cm-section-head .cm-batch-btn[disabled] {
  color: var(--text-tertiary) !important;
}
.competitor-mon-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 3px 6px;
  background: var(--bg-sidebar);
  border-radius: 4px;
}
.cm-img { width: 22px; height: 22px; border-radius: 3px; object-fit: cover; border: 1px solid var(--border-base); background: var(--bg-elevated); flex-shrink: 0; }
.cm-img-fb { width: 22px; height: 22px; border-radius: 3px; border: 1px solid var(--border-base); background: var(--bg-elevated); align-items: center; justify-content: center; font-size: 12px; flex-shrink: 0; }
.cm-asin {
  font-family: 'SF Mono', Monaco, monospace;
  font-size: 11px;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cm-mon-act {
  font-size: 11px;
  padding: 0 2px;
  flex-shrink: 0;
}

/* ====== 悬浮预览卡片 ====== */
.hp-preview {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.hp-img {
  width: 100%;
  height: 170px;
  object-fit: cover;
  border-radius: 8px;
  border: 1px solid var(--border-base);
  background: var(--bg-sidebar);
}

.hp-body {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.hp-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.hp-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.hp-asin { font-family: 'SF Mono', Monaco, monospace; font-size: 11px; color: var(--text-secondary); }
.hp-sku { font-size: 11px; color: var(--text-tertiary); }
.hp-brand { font-size: 12px; color: var(--text-secondary); }

.hp-stats {
  display: flex;
  gap: 16px;
  padding: 8px 10px;
  background: var(--bg-sidebar);
  border-radius: 6px;
}

.hp-stat {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.hp-label {
  font-size: 11px;
  color: var(--text-tertiary);
}

.hp-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.hp-sub { font-size: 11px; color: var(--text-tertiary); }
.hp-bsr { font-size: 11px; color: var(--text-tertiary); margin-left: auto; }

.stars { color: var(--warning); letter-spacing: -1px; font-size: 13px; }

.margin-high { color: var(--success) !important; }
.margin-mid { color: var(--warning) !important; }
.margin-low { color: var(--danger) !important; }

.hp-points {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.hp-point {
  font-size: 11px;
  color: var(--text-secondary);
  line-height: 1.4;
  padding: 4px 8px;
  background: linear-gradient(135deg, var(--warning-bg), var(--warning-bg));
  border-left: 3px solid var(--warning);
  border-radius: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ====== SPU：新增弹窗SKU行 ====== */
.var-child-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}

/* ====== SPU / SKU 徽标 ====== */
.var-parent-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
  color: var(--purple);
  background: var(--purple-bg);
  border: 1px solid var(--purple-border);
  white-space: nowrap;
}
.var-child-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
  color: var(--primary);
  background: var(--info-bg);
  border: 1px solid var(--info-border);
  white-space: nowrap;
}

/* ====== SPU行灰色占位 ====== */
.cell-placeholder {
  color: var(--text-disabled);
  font-size: 13px;
  user-select: none;
}

/* ====== SPU 行「只读投影」（单品投影唯一 SKU 数据）====== */
.projected {
  opacity: 0.82;
}
.price-cell-projected {
  /* 视觉提示：SPU 行投影自唯一 SKU，非原生存储 */
}
.margin-badge.projected {
  outline: 1px dashed var(--border-strong);
  outline-offset: 1px;
}

/* ====== SPU 多变体汇总视图 ====== */
.spu-summary-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.spu-summary-cell .price {
  font-weight: 600;
  color: var(--text-primary);
}
.spu-summary-cell .fba-stock {
  color: var(--primary);
}
.spu-summary-cell .sku-count {
  font-size: 11px;
  color: var(--purple);
}

/* ====== SPU hover 预览备注 ====== */
.hp-parent-note {
  font-size: 12px;
  color: var(--text-secondary);
  background: var(--purple-bg);
  border: 1px solid var(--purple-border);
  border-radius: 6px;
  padding: 6px 10px;
  margin-top: 8px;
}

/* ====== SPU 展开面板 ====== */
.var-children-panel {
  padding: 12px 16px;
  background: var(--bg-base);
  border-radius: 8px;
  margin: 4px 0 8px 40px;
}
.var-children-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.var-children-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

/* ====== SPU公共文案 ====== */
.parent-content-summary {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.pc-sp {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
}
.pc-bullets, .pc-aplus {
  font-size: 12px;
  color: var(--text-secondary);
}
.pc-empty {
  font-size: 12px;
  color: var(--text-disabled);
  padding: 8px;
  border: 1px dashed var(--border-base);
  border-radius: 6px;
}
.pc-bullet-row {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}
</style>
