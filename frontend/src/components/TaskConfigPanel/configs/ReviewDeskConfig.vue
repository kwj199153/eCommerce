<template>
  <div class="rd-root">
    <!-- 视图切换：本店近期差评 / 关联不上产品的孤儿差评 -->
    <div class="rd-tabs">
      <button
        v-for="t in VIEWS"
        :key="t.key"
        class="rd-tab"
        :class="{ active: view === t.key }"
        :title="t.hint"
        @click="switchView(t.key)"
      >
        <span class="rd-tab-icon">{{ t.icon }}</span>
        <span>{{ t.label }}</span>
        <span v-if="counts[t.key] !== null" class="rd-tab-count">{{ counts[t.key] }}</span>
      </button>
      <a-button
        size="small"
        type="text"
        :loading="loading"
        title="只读：重新拉取列表，不写任何数据、不生成草稿"
        @click="reload"
      >
        <ReloadOutlined /> 刷新（只读）
      </a-button>
    </div>

    <!-- ===== 读 / 写 分界（第 292 轮立、第 304 轮改载体）=====
         ★ 老板指令：「这种常驻提示取消，悬停按钮提示即可」。
           原先这里挂一排常驻 chip，占掉首屏三行、且**每个视图都重复一遍**。
           同一份口径改挂到**按钮的 title** 上（谁要写，谁身上写清楚）：
             · 刷新             → title「只读…不写库」
             · 生成待处置        → title「写操作（批量）…」
             · 批准 / 核准 / 登记 → title「只能人点…」
           判据形态不变（信息没丢，载体从「常驻」变「悬停」），
           `cdp-review-desk-ui-probe.mjs` 的 B2 已同步改成查按钮 title。 -->

    <!-- 差评列表：时间窗 + 星级 -->
    <div v-if="view !== 'ledger'" class="rd-filter">
      <span class="rd-filter-label">时间窗</span>
      <a-select v-model:value="days" size="small" class="rd-days" @change="reload">
        <a-select-option :value="7">近 7 天</a-select-option>
        <a-select-option :value="30">近 30 天</a-select-option>
        <a-select-option :value="90">近 90 天</a-select-option>
        <a-select-option :value="3650">全部</a-select-option>
      </a-select>
      <span class="rd-filter-label">星级</span>
      <a-select v-model:value="maxRating" size="small" class="rd-days" @change="reload">
        <a-select-option :value="3">≤3 星（中差评）</a-select-option>
        <a-select-option :value="5">全部星级</a-select-option>
      </a-select>
    </div>

    <!-- ===== 风险话术识别（第 299 轮 P1；第 302 轮改口径）=====
         ★★★ 文案里**不得写死类别中文名**（「加码要挟 / 索赔要钱 / …」）——
           后端 `/reviews/risk` 已经下发了 `categories` + `category_labels`，
           界面上有名字的地方一律从那里取（卡片标签走 `hits[].label`）。
           手写一份就是同一个词表的第二份实现：第 302 轮把「威胁差评」改成
           「加码要挟」（原定义自相矛盾：这条文本本身已经是那条公开的差评），
           而这里还挂着旧名 —— 没人报错，只是界面在说一套、后端在判另一套。
           静态门禁 `check-review-risk-view.cjs` 的 R19 钉住这件事。
         ★ 只读、**按需触发**：语义判定每条一次模型调用（贵），必须由人按按钮，
           不能挂在列表加载里自动跑。
         ★ 只在这个视图显示：扫描口径与「近期差评」同源（`/reviews` 那一批），
           孤儿差评是**另一批**数据，给它们标风险会张冠李戴。
         ★ 排序在**后端**（风险 → 未定论 → 干净）；前端只按后端给的顺序渲染。 -->
    <div v-if="view === 'recent'" class="rd-risk-bar">
      <a-button
        size="small"
        :loading="riskLoading"
        title="只读：逐条判定评价正文是否含对抗性话术（升级要挟 / 索要赔偿 / 平台投诉），命中的标红置顶"
        @click="runRiskScan"
      >
        <SafetyCertificateOutlined /> 风险识别
      </a-button>
      <template v-if="riskMeta">
        <span class="rd-risk-chip rd-risk-chip-risk">风险 {{ riskMeta.risk_count }}</span>
        <span class="rd-risk-chip rd-risk-chip-unknown">未定论 {{ riskMeta.unknown_count }}</span>
        <span class="rd-risk-chip">干净 {{ riskMeta.clean_count }}</span>
        <span class="rd-risk-tip">
          已按「风险 → 未定论 → 干净」置顶（顺序来自后端）；
          本页扫描 {{ riskMeta.scanned }} / 共 {{ riskMeta.total }} 条
          <template v-if="riskMeta.capped">（已达单次上限）</template>
          <template v-if="riskMeta.llm_used">
            ；分层：规则已判定 {{ riskMeta.semantic_skipped }} 条未重复送语义，
            语义打包 {{ riskMeta.llm_calls }} 次（共送 {{ riskMeta.semantic_sent }} 条）
          </template>
        </span>
        <a-button size="small" type="text" @click="clearRisk">清除标记</a-button>
      </template>
      <span v-else class="rd-risk-tip">
        逐条判定评价正文里的对抗性话术（以进一步升级相要挟、索要退款赔偿、
        预告平台介入或投诉 —— 类别名由后端下发），命中的标红并置顶。
        ★ 判定对象是**已公开发布的买家评价**，不是买家私信 / 客服会话：
          评价里的施压常以「旁白」口气出现（说给别人听，其实是对卖家要价），照样要判。
        只读：不写库、不发券、不改处置状态。
        分层：先跑零成本的规则通道，规则已判出四类的**不再送语义**，其余打包成一次语义调用。
      </span>
    </div>

    <!-- ★ 降级必须如实上屏：语义通道不可用时每条都是「未定论」，
         显示成「全部清白」等于把一次**没扫成**的扫描伪装成一次**通过**的扫描。 -->
    <a-alert
      v-if="view === 'recent' && riskMeta?.degraded"
      type="warning"
      show-icon
      class="rd-alert"
      message="语义判定通道不可用（服务端未配置 LLM 凭据）"
      description="本次只跑了规则通道：命中规则的照实标红，其余一律记为「未定论」，需人工判 —— 不等于没有风险。"
    />
    <a-alert
      v-if="view === 'recent' && riskError"
      type="error"
      show-icon
      class="rd-alert"
      :message="riskError"
    />

    <!-- 处置台账：状态筛选 + 批量生成（★「生成待处置」全仓只此一处） -->
    <div v-else class="rd-filter">
      <span class="rd-filter-label">状态</span>
      <a-select
        v-model:value="dispStatusFilter"
        size="small"
        class="rd-days"
        allow-clear
        placeholder="全部状态"
        :options="DISPOSITION_STATUS_OPTIONS"
        @change="reload"
      />
      <a-button
        size="small"
        type="primary"
        :loading="backfilling"
        title="写操作（批量，全仓只此一处）：按「有归因但还没处置」的中差评生成待批准草稿；已有处置的一律跳过，不覆盖"
        @click="runBackfill"
      >
        <ThunderboltOutlined /> 生成待处置
      </a-button>
      <span class="rd-filter-tip">按「有归因但还没处置」的中差评批量生成草稿（已有则跳过）</span>
    </div>

    <!-- ★ 失败原因**必须留在界面上**（第 304 轮）：后端 `failed[]` 里每条都带
         `reason`，一句 toast 装不下 4 条不同的原因，且会一闪而过。
         老板实际遇到的正是这个：提示猜「多半是缺归因或没配规则」，
         而真因是那 4 类的**补偿规则没配** —— 猜错方向 ⇒ 人跑去重跑归因，
         永远跑不出结果。 -->
    <a-alert
      v-if="backfillNote"
      type="warning"
      show-icon
      closable
      class="rd-alert"
      message="生成待处置：有条目给不出方案"
      :description="backfillNote"
      @close="backfillNote = ''"
    />

    <!-- ★ 失败必须落到界面上：500 / 400（没选店铺）都是这一块，
         不能让它变成「列表空空的随机失败」。 -->
    <a-alert v-if="error" type="error" show-icon :message="error" class="rd-alert" />

    <div v-else-if="loading && !hasRows" class="rd-hint">
      <a-spin size="small" /> 正在读取{{ viewLabel }}…
    </div>

    <div v-else-if="!hasRows" class="rd-hint">
      <div class="rd-hint-icon">{{ emptyIcon }}</div>
      <div class="rd-hint-title">{{ emptyTitle }}</div>
      <div class="rd-hint-desc">{{ emptyDesc }}</div>
      <div v-if="isFilteredEmpty" class="rd-hint-acts">
        <a-button size="small" @click="resetFilters">清空筛选</a-button>
      </div>
      <div v-else-if="view === 'ledger'" class="rd-hint-acts">
        <a-button size="small" type="primary" :loading="backfilling" @click="runBackfill">
          生成待处置
        </a-button>
      </div>
    </div>

    <!-- ===== 处置台账：以处置为主语 ===== -->
    <div v-else-if="view === 'ledger'" class="rd-ledger">
      <table class="rd-table">
        <thead>
          <tr>
            <!-- ★ ASIN 必须在台账里看得见：差评列表显示 `B0CXXXX009`、
                 台账只显示 `SKU-KC-002`，两边看着像两份互不相通的数据 ——
                 其实是同一批（23 条评价的 asin / sku 完全一致），
                 缺的只是这一列。 -->
            <th>ASIN</th>
            <th>SKU</th>
            <th class="num">评分</th>
            <th>差评标题</th>
            <th>通道</th>
            <th class="num">补偿</th>
            <th>状态</th>
            <th class="num">更新</th>
            <th class="rd-table-act"></th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="d in dispositions"
            :key="d.id"
            class="rd-row-clickable"
            :title="rowHint(d)"
            @click="openDispositionDetail(d)"
          >
            <td><code>{{ d.review?.asin || '—' }}</code></td>
            <td><code>{{ d.review?.sku || '—' }}</code></td>
            <td class="num">{{ d.review?.rating ?? '—' }} 星</td>
            <td class="rd-table-title" :title="d.review?.title || ''">
              {{ d.review?.title || '—' }}
            </td>
            <td>
              <!-- 通道逐个可悬停查看作用（不可逆的两类会明确标出来） -->
              <a-tooltip v-for="c in d.channels" :key="c" :title="channelEffect(c)">
                <a-tag>{{ channelLabel(c) }}</a-tag>
              </a-tooltip>
            </td>
            <td class="num">{{ compensationText(d.compensation) }}</td>
            <td>
              <a-tag :color="DISPOSITION_STATUS_COLORS[d.status]">
                {{ DISPOSITION_STATUS_LABELS[d.status] }}
              </a-tag>
            </td>
            <td class="num">{{ shortTime(d.updated_at) }}</td>
            <td class="rd-table-act">
              <!-- ★ 第 292 轮：这里从前一律写「查看」，用户找不到去哪编辑。
                   待批准 / 已驳回的行点进去就是**可编辑**的，文案必须如实。 -->
              <a-button type="link" size="small" class="rd-act-open">{{ rowActionLabel(d) }}</a-button>
              <!-- ★ 第 298 轮：列表行也要能直达对话 —— 此前这个出口只长在**抽屉**里，
                   老板在【处置台账】列表上找不到它（原话：列表没有按钮）。
                   `@click.stop` 必须留：行本身点了是开抽屉，不拦会两个动作一起触发。 -->
              <a-tooltip title="把这条差评带进对话，按「差评应对」的完整流程走">
                <a-button type="link" size="small" class="rd-act-chat"
                  :disabled="!d.review_id" @click.stop="sendRowToChat(d)">💬</a-button>
              </a-tooltip>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-if="dispTotal > dispositions.length" class="rd-more">
        共 {{ dispTotal }} 条，当前显示 {{ dispositions.length }} 条
      </div>
    </div>

    <!-- ===== 补偿规则配置（第 304 轮后半）=====
         ★ 这就是此前「要调金额请去改规则表」那句话**缺失的落点**：
           金额由规则唯一算出，这里是人配规则的地方。 -->
    <div v-else-if="view === 'rules'" class="rd-rules">
      <div class="rd-rules-bar">
        <span class="rd-filter-tip">
          金额由这里唯一算出 —— 处置草稿按「归因 + 命中规则」现算；<b>改金额不在这里改，改这里</b>。
        </span>
        <a-button size="small" type="primary" @click="openRuleCreate">
          <SettingOutlined /> 新建规则
        </a-button>
      </div>
      <a-alert v-if="rulesError" type="error" show-icon :message="rulesError" class="rd-alert" />
      <ReviewDeskRulesTable
        :rules="rules"
        @edit="openRuleEdit"
        @toggle="toggleRule"
        @remove="removeRule"
      />
    </div>

    <!-- ===== 差评列表：以差评为主语 ===== -->
    <div v-else class="rd-list">
      <div
        v-for="r in displayItems"
        :key="r.id"
        class="rd-item"
        :class="[riskClass(r.id), { active: detailReviewId === r.id }]"
        @click="openDetail(r)"
      >
        <div class="rd-item-top">
          <span class="rd-stars">{{ '★'.repeat(Math.max(0, r.rating)) }}<span class="rd-stars-dim">{{ '★'.repeat(Math.max(0, 5 - (r.rating || 0))) }}</span></span>
          <span class="rd-date">{{ (r.review_at || '').slice(0, 10) || '-' }}</span>
          <a-tag v-if="r.source === 'mock_seed'" color="orange" size="small">演示数据</a-tag>
          <!-- ★ 风险标记：类别中文名与等级中文名**都取自后端**
               （`label` / `level_label`），前端不写第二份映射。
               未定论走琥珀色 —— 它与「干净」方向相反，不可同色。 -->
          <a-tag
            v-if="riskMap[r.id]?.is_risk"
            color="red"
            size="small"
            :title="riskMap[r.id].suggested_action"
          >
            🛡 {{ riskTagText(riskMap[r.id]) }}
          </a-tag>
          <a-tag
            v-else-if="riskMap[r.id]?.decision === 'unknown'"
            color="orange"
            size="small"
            :title="riskMap[r.id].note"
          >
            🛡 未定论
          </a-tag>
          <!-- ★ 第 298 轮：与台账行同款 —— 差评卡片上也给一个直达对话的出口
               （此前非要点开抽屉才看得见那个按钮）。`@click.stop` 同上。 -->
          <a-tooltip title="把这条差评带进对话，按「差评应对」的完整流程走">
            <a-button type="link" size="small" class="rd-item-chat"
              @click.stop="sendItemToChat(r)">💬</a-button>
          </a-tooltip>
        </div>
        <div class="rd-title">{{ r.title || '（无标题）' }}</div>
        <div class="rd-body">{{ r.body || '—' }}</div>
        <!-- ★ 证据是**原文片段**（后端保证），界面只显示：不改写、不拼接 ——
             改了老板拿它去原文里搜就搜不到，等于伪造证据。 -->
        <div v-if="showRiskEvidence(riskMap[r.id])" class="rd-risk-ev">
          <div v-for="h in riskMap[r.id].hits" :key="h.category" class="rd-risk-hit">
            <span class="rd-risk-hit-cat">{{ h.label }}</span>
            <span class="rd-risk-hit-lv">· {{ levelLabel(h.level) }}</span>
            <span v-for="(ev, i) in h.evidence" :key="i" class="rd-risk-quote">「{{ ev }}」</span>
            <span v-if="!h.evidence.length && h.note" class="rd-risk-note">{{ h.note }}</span>
          </div>
        </div>
        <div class="rd-meta">
          <template v-if="r.asin"><span>ASIN <code>{{ r.asin }}</code></span></template>
          <template v-else-if="r.sku"><span>SKU <code>{{ r.sku }}</code></span></template>
          <template v-else><span class="rd-meta-miss">无 ASIN / SKU</span></template>
          <span>·</span>
          <span>{{ REVIEW_STATUS_LABELS[r.status] || r.status || '未处理' }}</span>
          <span v-if="dispositionStatus[r.id]" class="rd-disp">
            · <span :class="'rd-disp-' + dispositionStatus[r.id]">
              {{ DISPOSITION_STATUS_LABELS[dispositionStatus[r.id]] }}
            </span>
          </span>
          <!-- ★ 补归因入口（第 304 轮后半）：判不出归因（unknown）的差评永远进不了
               处置链 —— 这里给出唯一的手工出口。`@click.stop` 防止触发行点击开抽屉。 -->
          <span class="rd-attr-entry">
            <a-button
              type="link"
              size="small"
              class="rd-item-attr"
              title="这条差评判不出归因 / 还没归因 ⇒ 进不了处置链。点此手工指定成因（落 manual，自动同步不覆盖）"
              @click.stop="openAttribution(r)"
            >补归因</a-button>
          </span>
        </div>
      </div>
      <div v-if="total > items.length" class="rd-more">
        共 {{ total }} 条，当前显示 {{ items.length }} 条
      </div>
    </div>

    <!-- ============================ 处置抽屉 ============================ -->
    <!-- ★ 第 296 轮（老板指令）：「宽度 480 → 720」+「单列 → **左右两栏**」
         （老板：「设置部分放左、生成部分放右」）。
         ★ 第 298 轮（老板指令·术语统一）：抽屉标题定为「差评处置」——
           全仓业务面只留**处置**一个词（写路径本来就叫 `review_dispositions`、
           面板第三个视图也叫「处置台账」），「处理」只在**泛动词**处保留
           （差评状态「待处理」、通道「人工处理 / 升级处理」）。
           分工不变：台账看列表、处置做单条（与功能栏「差评台账」区分）。
         ★ 分栏依据**不是**「左上下文、右操作」：判定结论虽然只读，但它是
           「该不该处置」的判据，与通道、补偿同属**设置侧** ⇒ 左栏；
           券码是核准的产物、草稿是生成的产物，与提交动作同属**产出侧** ⇒ 右栏。
         ★ 720 = `WINDOW_W.xxl`（第 297 轮起窗口宽度一律走 `src/config/layout.ts`
           的 6 档阶梯）；与「资料库 · 差评库」抽屉（`ReviewLibrary.vue`）同为 xxl 档。
         ★ 为什么两栏各自复制一份 `<template v-if="detailView">`，而不是让一个
           template 跨栏：template 的起止标签必须落在同一栏内 —— 否则渲染后
           `</div><div>` 会把两栏的 DOM 配对搞乱（左栏多一个闭合、右栏少一个）。
         ★ 两栏用 flex + `min-width: 0`：少了后者，差评长正文会把列撑破。 -->
    <a-drawer
      v-model:open="detailOpen"
      :title="detailView ? `差评处置 · ${detailView.title || detailView.id}` : '差评处置'"
      :width="WINDOW_W.xxl"
      placement="right"
    >
      <!-- ★ 第 298 轮：把「这条差评」送进对话链路的结构化出口。
           此前界面在左栏写着「在对话里直接问」（见下方那段 rd-tip），
           但**没有任何路径把这条差评带过去** —— 前端只发 `{message, skill}`，
           模型只能从**会话历史**里挑一条顶上（第 250 轮那个洞的同一形状）。
           ★ 放 `#extra` 而不是某个区块里：它是「这条差评」的整体动作，
             一打开抽屉就能看到，不依赖滚动到某个区块。 -->
      <template #extra>
        <a-button v-if="detailView" size="small" :disabled="!detailView.id" @click="sendToChat">
          💬 在对话里处置这条
        </a-button>
      </template>
      <div class="rd-detail-grid">
        <!-- ==================== 左栏：事实 + 设置 ==================== -->
        <div class="rd-detail-col">
          <template v-if="detailView">
            <a-descriptions :column="1" bordered size="small">
              <a-descriptions-item label="星级">{{ detailView.rating ?? '-' }} 星</a-descriptions-item>
              <a-descriptions-item label="ASIN"><code>{{ detailView.asin || '-' }}</code></a-descriptions-item>
              <a-descriptions-item label="SKU"><code>{{ detailView.sku || '-' }}</code></a-descriptions-item>
              <a-descriptions-item label="时间">{{ detailView.review_at || '-' }}</a-descriptions-item>
              <a-descriptions-item label="买家">{{ detailView.buyer_name || '匿名' }}</a-descriptions-item>
              <a-descriptions-item label="来源">
                {{ detailView.source === 'mock_seed' ? '演示数据' : detailView.source || '-' }}
              </a-descriptions-item>
            </a-descriptions>

            <div class="rd-section">
              <h4>📝 评价正文</h4>
              <div class="rd-body-full">{{ detailView.body || '（无正文）' }}</div>
            </div>

            <!-- ===== 个案 / 系统性判定（第 294 轮 B 档）=====
                 ★ 为什么这一块必须存在：这个判定此前**只有对话通道**算得出来
                   （面板 11 个端点一个都没有）⇒ 用户走完「草稿 → 批准 → 核准」
                   也看不到「这是不是系统性问题」，于是自然会问「技能卡还用得上吗」。
                   不是用不上，是面板静默漏了这一步、且漏得毫无提示。
                 ★ 结论**由后端算**（`systemic-check`）：组合规则本身就是判据，
                   放界面等于同一可见性两份实现。这里只显示 label 与 reason。 -->
            <div class="rd-section">
              <h4>
                🔎 个案 / 系统性判定
                <a-tag v-if="systemic" :color="SYSTEMIC_COLORS[systemic.verdict]">
                  {{ systemic.verdict_label }}
                </a-tag>
              </h4>

              <div v-if="systemicLoading" class="rd-hint-inline">
                <a-spin size="small" /> 判定中…
              </div>
              <div v-else-if="systemicError" class="rd-hint-inline">
                判定失败：{{ systemicError }}
              </div>

              <template v-else-if="systemic">
                <div v-if="systemic.ready" class="rd-kv">
                  <span class="rd-k">同因历史</span>
                  <span class="rd-v">
                    {{ systemic.historical_count }} 次
                    <span class="rd-block-hint">
                      （阈值 ≥{{ systemic.threshold }} 次算重复问题）
                    </span>
                  </span>
                </div>
                <div class="rd-kv">
                  <span class="rd-k">SKU 健康分</span>
                  <span class="rd-v">
                    <template v-if="skuHealth && skuHealth.found">
                      {{ skuHealth.health_score }}
                      <span class="rd-block-hint">
                        环比 {{ (skuHealth.delta ?? 0) > 0 ? '+' : '' }}{{ skuHealth.delta }}
                        · 中差评占比 {{ skuHealth.negative_rate }}
                      </span>
                    </template>
                    <template v-else>还没算过（需先有一期归因数据）</template>
                  </span>
                </div>
                <div class="rd-tip">{{ systemic.reason }}</div>

                <div v-if="systemic.recommend_escalate" class="rd-warn">
                  ⚠️ 判为「{{ systemic.verdict_label }}」：差评只是症状，建议升级到根因环节。
                  <a-button
                    v-if="editable"
                    size="small"
                    :disabled="editChannels.includes('escalate')"
                    @click="adoptEscalate"
                  >
                    {{ editChannels.includes('escalate')
                      ? '已勾选「升级」通道' : '采纳：勾选「升级」通道' }}
                  </a-button>
                  <span v-else class="rd-block-hint">
                    先「生成处置草稿」（或等它加载完），才能把「升级」加进通道
                  </span>
                </div>
                <div class="rd-tip">
                  只读：判定由后端算（<code>systemic-check</code>），界面不自己推算 ——
                  否则同一结论会有两份实现，改了后端忘改界面就出分歧。
                </div>
                <!-- ★ 第 295 轮 A 档：撤下「差评应对」快捷卡片后，必须在这里给出
                     **能力仍在**的出口 —— 否则用户会以为"卡片没了 = 这个能力没了"。
                     措辞三条缺一不可（少一条就变成"字面为真、暗示为假"）：
                       ① 说清这里**没有多轮**（是面板的结构性上限，不是遗漏）；
                       ② 给出**具体动作**与它的位置（大屏模式下对话是左侧那个窄栏）；
                       ③ 点明定位（面板是辅助入口 / 对话是主通道）—— 老板第 295 轮原话。 -->
                <div class="rd-tip">
                  💬 本块只有一句结论、<b>没有多轮</b>。要它解释「凭什么算重复」、
                  或跟买家继续拉锯，点右上角 <b>💬 在对话里处置这条</b> 把这条差评带进
                  <b>对话</b>直接问 —— 那里会按「差评应对」的完整流程走
                  （大屏模式下是左侧那个窄栏，切「对话模式」更宽）。
                </div>
              </template>
              <!-- ★ 兜底：loading / error / 有数据 之外的第四态。
                   少了它，一旦状态机出现空档（请求被取消、组件重挂），这一块就是
                   一片**没有解释的空白** —— 用户只会以为「功能没做」。
                   本仓铁律：失败与空态都必须能归因。 -->
              <div v-else class="rd-hint-inline">判定未开始 —— 打开一条差评后会自动请求。</div>
            </div>

            <div class="rd-section">
              <h4>
                🛠 处置
                <a-tag v-if="disposition" :color="DISPOSITION_STATUS_COLORS[disposition.status]">
                  {{ DISPOSITION_STATUS_LABELS[disposition.status] }}
                </a-tag>
              </h4>

              <div v-if="detailLoading" class="rd-hint-inline">
                <a-spin size="small" /> 读取处置中…
              </div>

              <!-- 尚无处置：此处只说明状态，生成动作在右栏「📤 生成」。
                   ★ 不在左栏再放一个「生成处置草稿」按钮 —— 同一个不可逆流程两个
                     入口，正是第 291 轮删掉资料库入口的理由（HITL 唯一把关点被架空）。 -->
              <div v-else-if="!disposition" class="rd-hint-inline">
                这条差评还没有处置记录 —— 去右栏「📤 生成」点【生成处置草稿】。
              </div>

              <template v-else>
                <div class="rd-steps">
                  <span class="rd-step done">① 生成草稿<em>可写 · 幂等</em></span>
                  <span class="rd-step" :class="{ done: disposition.status === 'approved' || disposition.status === 'issued' || disposition.status === 'executed' }">
                    ② 人批准<em>只能人点</em>
                  </span>
                  <span class="rd-step" :class="{ done: disposition.status === 'issued' || disposition.status === 'executed' }">
                    ③ 人核准<em>不可逆 · 只生成券码</em>
                  </span>
                  <!-- ★ ④ 是本轮补的那一步：③ 只做本地核准，**平台侧没动**。
                       少了这一步，流程到 `issued` 就「结束」了，而钱其实没退。 -->
                  <span class="rd-step" :class="{ done: disposition.status === 'executed' }">
                    ④ 平台执行<em>人工做完后登记回执</em>
                  </span>
                </div>

                <!-- ① 通道：5 类逐个可点，点一项看它的实际作用与可逆性 -->
                <div class="rd-block">
                  <div class="rd-block-head">
                    <span>处置通道</span>
                    <span class="rd-block-hint">{{ editable ? '可分别点选' : '已锁定：' + lockReason }}</span>
                  </div>
                  <div class="rd-chips">
                    <button
                      v-for="c in ALL_CHANNELS"
                      :key="c"
                      type="button"
                      class="rd-chip"
                      :class="{ on: editChannels.includes(c), locked: !editable }"
                      :disabled="!editable"
                      @click="toggleChannel(c)"
                      @mouseenter="channelHint = c"
                    >
                      {{ CHANNEL_META[c].label
                      }}<span v-if="CHANNEL_META[c].irreversible" class="rd-chip-mark">✱</span>
                    </button>
                  </div>
                  <div class="rd-chip-desc">
                    <b>{{ CHANNEL_META[focusChannel].label }}</b>：{{ CHANNEL_META[focusChannel].effect }}
                  </div>
                  <div v-if="irreversiblePicked.length" class="rd-warn">
                    ⚠️ 已选不可逆通道：{{ irreversiblePicked.map(channelLabel).join(' / ') }}
                    —— ③ 核准之后不能改，只能另开一笔。✱ 标记的就是这类。
                  </div>
                </div>

                <!-- ② 补偿方案：只读，且必须说清**为什么**只读 -->
                <div class="rd-block">
                  <div class="rd-block-head">
                    <span>补偿方案</span>
                    <span class="rd-block-hint">只读</span>
                  </div>
                  <!-- ★ 依据：后端 `/draft` 一直返回 `primary_cause_label` 与
                       `rule_name`，界面此前**一次都没渲染** ⇒ 用户看得到「补偿 ¥8」，
                       看不到「为什么是 ¥8」。金额不改（规则唯一算），但理由必须看得见。 -->
                  <div v-if="draftInfo" class="rd-kv">
                    <span class="rd-k">依据</span>
                    <span class="rd-v">
                      归因 {{ draftInfo.primary_cause_label || '—' }}
                      · 命中规则 {{ draftInfo.rule_name || '—' }}
                      <code v-if="draftInfo.rule_code">{{ draftInfo.rule_code }}</code>
                    </span>
                  </div>
                  <div class="rd-kv">
                    <span class="rd-k">{{ compensationText(disposition.compensation) }}</span>
                  </div>
                  <div class="rd-tip">
                    <b>金额不在这里改</b>：它由「补偿规则」唯一算出 —— 手改等于绕过预算上限
                    （超限时后端直接报错，不会静默按上限赔）。要调金额，去顶部
                    <b>「补偿规则」标签</b>改对应的规则（改了下次生成才生效）。
                  </div>
                </div>
              </template>
            </div>
          </template>
        </div>

        <!-- ==================== 右栏：生成 ==================== -->
        <div class="rd-detail-col">
          <template v-if="detailView">
            <div class="rd-section">
              <h4>📤 生成</h4>

              <div v-if="detailLoading" class="rd-hint-inline">
                <a-spin size="small" /> 读取处置中…
              </div>

              <template v-else-if="!disposition">
                <div class="rd-hint-inline">这条差评还没有处置记录。</div>
                <a-button type="primary" size="small" :loading="acting" @click="proposeDraft">
                  生成处置草稿
                </a-button>
                <div class="rd-tip">
                  草稿会按「归因 + 补偿规则」现算，落在 <code>proposed</code>；
                  <b>批准与核准必须由人点</b>（不可逆，不在 Agent 工具里）；平台侧执行需人工去后台完成后登记回执。
                </div>
              </template>

              <template v-else>
                <!-- ③ 券码：核准才生成，且会自动写进回复草稿 -->
                <div class="rd-block">
                  <div class="rd-block-head">
                    <span>券码</span>
                    <span class="rd-block-hint">只读</span>
                  </div>
                  <div v-if="disposition.coupon_code" class="rd-kv">
                    <span class="rd-v"><code>{{ disposition.coupon_code }}</code></span>
                  </div>
                  <div v-else class="rd-tip">
                    还没核准 ⇒ 尚无券码。③ 核准时自动生成，并<b>写进下面的回复草稿</b>；
                    若草稿已被人工改过则保留人工措辞，同时在处置备注里记账。
                    ★ 券码是**本地生成的待执行凭据**，不是「已发放」的凭证 ——
                    平台侧动作仍需人工去后台做完。
                  </div>
                </div>

                <!-- ④ 回复草稿：可编辑（改措辞不改钱），或按状态锁定 -->
                <div class="rd-block">
                  <div class="rd-block-head">
                    <span>回复草稿</span>
                    <span class="rd-block-hint">
                      {{ editable ? (editDirty ? '有未保存的修改' : '可编辑') : '已锁定：' + lockReason }}
                    </span>
                  </div>
                  <div class="rd-draft-label">中文</div>
                  <a-textarea v-model:value="editZh" :rows="4" :disabled="!editable" />
                  <div class="rd-draft-label">English</div>
                  <a-textarea v-model:value="editEn" :rows="4" :disabled="!editable" />
                  <div class="rd-tip">
                    措辞可以改（对买家说话吃语境）；<b>补偿金额不在文中改</b>。
                    草稿在批准之前一律用「拟 / 正在办理」的口径，不写成既成事实。
                  </div>
                </div>

                <div class="rd-actions">
                  <a-button v-if="editable" size="small" :loading="acting" @click="saveEdits">
                    保存修改
                  </a-button>
                  <a-button v-if="editable" size="small" :disabled="acting" @click="restoreSystemDraft">
                    填入系统草稿
                  </a-button>
                  <a-button
                    v-if="disposition.status === 'proposed'"
                    type="primary"
                    size="small"
                    :loading="acting"
                    title="写操作（单条）：批准这条草稿；只能人点 —— 发券退款不可逆，不在 Agent 工具里"
                    @click="confirmAct('approve')"
                  >批准</a-button>
                  <a-button
                    v-if="disposition.status === 'proposed' || disposition.status === 'approved'"
                    size="small"
                    :loading="acting"
                    title="写操作（单条）：驳回这条草稿；只能人点"
                    @click="confirmAct('reject')"
                  >驳回</a-button>
                  <a-button
                    v-if="disposition.status === 'approved'"
                    danger
                    size="small"
                    :loading="acting"
                    title="写操作（单条·不可逆）：本地核准 —— 生成券码并写进回复。本系统不会调用平台接口，平台侧动作仍需人工去后台执行"
                    @click="confirmAct('issue')"
                  >核准（不可逆）</a-button>
                  <!-- ★ ④ 登记回执：本系统不调平台写接口，这一步是「人去平台做完了，
                       回来登记」。没有它，`executed` 就没有来源 —— 界面也就
                       没资格说「已执行」。 -->
                  <a-button
                    v-if="disposition.status === 'issued'"
                    type="primary"
                    size="small"
                    :loading="acting"
                    title="写操作（单条·终态）：登记「平台上已经执行完」的回执 —— 只有真做完了才登记"
                    @click="confirmAct('receipt')"
                  >登记平台回执</a-button>
                </div>
                <div v-if="disposition.status === 'issued'" class="rd-tip">
                  <b>已核准 · 待平台执行</b>：券码已生成并写进回复，历史不可改
                  （要调整只能另开一笔）。
                  ★ 本系统<b>不会调用平台接口</b> —— 请人工去平台后台发券 / 退款，
                  做完回来点【登记平台回执】。
                </div>
                <div v-if="disposition.status === 'executed'" class="rd-tip">
                  <b>平台已执行</b>：{{ disposition.execution_mode === 'manual' ? '人工在平台执行' : '系统执行' }}
                  <template v-if="disposition.platform_ref"> · 凭证 <code>{{ disposition.platform_ref }}</code></template>
                  <template v-if="disposition.executed_by"> · 登记人 {{ disposition.executed_by }}</template>
                  <template v-if="disposition.executed_at"> · {{ disposition.executed_at }}</template>
                  <template v-if="disposition.receipt_note"><br />{{ disposition.receipt_note }}</template>
                </div>
                <div v-if="disposition.status === 'rejected'" class="rd-tip">
                  已驳回 —— 改完通道 / 措辞后点「保存修改」会重新回到待批准。
                </div>
              </template>
            </div>
          </template>
        </div>
      </div>
    </a-drawer>

    <!-- ================== 弹窗层（第 347 轮第五刀外移）================== -->
    <!-- ★ 三个弹窗（确认 / 规则编辑器 / 补归因）已外移到 `reviewDesk/ReviewDeskModals.vue`。
         写动作 runAct / saveRule / submitAttribution **仍住在本文件** —— 写门禁
         `check-disposition-write-exit.cjs` C1/C2 要求写 API 的 `.vue` 出口唯一且在本面板。 -->
    <ReviewDeskModals
      v-model:confirm-open="confirmOpen"
      v-model:reject-notes="rejectNotes"
      v-model:receipt-ref="receiptRef"
      v-model:receipt-note="receiptNote"
      v-model:rule-editor-open="ruleEditorOpen"
      v-model:rule-form="ruleForm"
      v-model:attr-open="attrOpen"
      v-model:attr-cause="attrCause"
      v-model:attr-notes="attrNotes"
      :confirm-title="confirmTitle"
      :confirm-text="confirmText"
      :pending-act="pendingAct"
      :acting="acting"
      :rule-editor-loading="ruleEditorLoading"
      :editing-rule="editingRule"
      :attr-loading="attrLoading"
      :attr-target="attrTarget"
      @act="runAct"
      @rule-ok="saveRule"
      @attr-ok="submitAttribution"
    />
  </div>
</template>

<script setup lang="ts">
/**
 * 差评工作台（第 289 轮 P1）—— 客服 Agent 功能栏「差评台账」的右栏面板。
 *
 * ★ 三个视图不是三个功能，是**同一件事的三个切面**（第 291 轮收敛）
 * ------------------------------------------------------------------------
 *   · 近期差评 / 未关联产品 —— 以**差评**为主语：本店发生了什么、哪条还没管；
 *   · 处置台账 —— 以**处置**为主语：已经发起过的草稿，现在处于什么状态。
 *   两者不能互相顶替：台账天然看不到「还没处置过的差评」，而差评列表也看不到
 *   「差评本身已不在时间窗内、但历史上发放过」的那批处置。
 *
 * ★★ 为什么台账必须并到这里，而不是留在资料库独立成页
 * ------------------------------------------------------------------------
 *   原先资料库里的 `DispositionLibrary`（资料库 → 差评处置）与本面板
 *   **各有一套** approve / reject / issue 按钮 —— 同一个「人审不可逆动作」
 *   存在两个 UI 出口，HITL 的唯一把关点就被架空了。
 *   合并后这三个写动作全仓只在本文件被调用；那个入口连同侧边栏项一并删除。
 *
 * ★ 为什么「孤儿」要和主列表并列
 * ------------------------------------------------------------------------
 * 差评与产品是**软关联**（`customer_reviews.asin` 没有外键指到 `skus`）：
 * 关联不上的那批差评**不会出现在任何产品的差评 tab 里**，只会静默消失。
 * 没有这张表，「产品详情写着 0 条差评」这句话永远无法被证伪。
 */
import { WINDOW_W } from '@/config/layout'
import { ref, computed } from 'vue'
import { message } from 'ant-design-vue'
import {
  ReloadOutlined, SafetyCertificateOutlined, ThunderboltOutlined,
  SettingOutlined,
} from '@ant-design/icons-vue'
import {
  listShopReviews,
  listOrphanReviews,
  listDispositions,
  getDisposition,
  draftDisposition,
  proposeDisposition,
  backfillDispositions,
  approveDisposition,
  rejectDisposition,
  issueDisposition,
  recordExecutionReceipt,
  getReviewSystemicCheck,
  getSkuHealth,
  scanReviewsRisk,
  listCompensationRules,
  createCompensationRule,
  updateCompensationRule,
  deleteCompensationRule,
  setReviewAttribution,
  DISPOSITION_STATUS_LABELS,
  DISPOSITION_STATUS_COLORS,
  type ProductReview,
  type Disposition,
  type DispositionReview,
  type DispositionStatus,
  type DispositionDraft,
  type SkuHealth,
  type SystemicCheck,
  type ReviewRiskBlock,
  type ReviewRiskScanResult,
  type CompensationRule,
  type CreateRuleParam,
  type UpdateRuleParam,
  type AttributionCause,
  type RuleCondition,
  type RuleAction,
} from '@/api/trade'
import {
  REVIEW_STATUS_LABELS, COMPENSATION_TYPE_LABELS, DISPOSITION_STATUS_OPTIONS,
  VIEWS, type ViewKey, SYSTEMIC_COLORS, CONFIRM_TITLES, CONFIRM_TEXTS,
  type RuleForm,
  compensationText, rowActionLabel, rowHint, shortTime,
} from './reviewDesk/reviewDeskVocabulary'
import { useReviewDeskViews } from './reviewDesk/useReviewDeskViews'
import { useReviewDeskEdits } from './reviewDesk/useReviewDeskEdits'
import ReviewDeskRulesTable from './reviewDesk/ReviewDeskRulesTable.vue'
import ReviewDeskModals from './reviewDesk/ReviewDeskModals.vue'

/**
 * 处置通道的**含义与可逆性** —— 唯一真源（与后端 `service.DISPOSITION_CHANNELS`
 * 逐字对齐，5 个取值）。
 *
 * ★ 为什么每个通道都要能点开看：从前界面上它们只是一排**不可点的** `a-tag`，
 *   用户看不出「点了会怎样、能不能反悔」。而它们恰恰是**可逆性不同**的动作 ——
 *   发券 / 退款一旦 `issued` 就不可逆（要调整只能另开一笔），回复 / 升级则不然。
 *   `CHANNEL_LABELS` 由本表派生，不手写第二份。
 */
const CHANNEL_META: Record<string, { label: string; effect: string; irreversible: boolean }> = {
  reply: { label: '回复', effect: '只给买家发一段回复，不动钱。', irreversible: false },
  coupon: {
    label: '补偿券',
    effect: '发一张有面额的券；核准时生成券码并写进回复，之后不可逆。'
      + '★ 本系统不调用平台接口：核准之后仍需人工去平台后台把券发出去。',
    irreversible: true,
  },
  refund: {
    label: '退款',
    effect: '退回部分或全部货款（可按百分比）；核准之后不可逆。'
      + '★ 本系统不调用平台接口：核准之后仍需人工去平台后台把款退掉。',
    irreversible: true,
  },
  reship: { label: '补发', effect: '重新发货，需买家回复确认收货地址。', irreversible: false },
  escalate: { label: '升级', effect: '转上级 / 人工处理，不带金额。', irreversible: false },
}

/** 通道中文名（从 `CHANNEL_META` 派生） */
const CHANNEL_LABELS: Record<string, string> = Object.fromEntries(
  Object.entries(CHANNEL_META).map(([k, v]) => [k, v.label]),
)

/** 全部通道，顺序与后端 `DISPOSITION_CHANNELS` 一致 */
const ALL_CHANNELS = Object.keys(CHANNEL_META)

// ★ 视图状态与派生已外移到 `reviewDesk/useReviewDeskViews.ts`（第 341 轮）：
//   它们全是纯 ref / computed，**取数仍留在下面 `reload()` 里** ——
//   门禁 `check-review-risk-view.cjs` R14 要求 `reload` 的函数体（含末尾那个
//   「指纹变了才清风险标记」的条件）留在本文件。
const {
  view, days, maxRating, loading, error, items, total, counts,
  dispositions, dispTotal, dispStatusFilter, backfilling,
  dispositionStatus, rules, rulesError,
  viewLabel, hasRows, emptyTitle, emptyDesc, emptyIcon, isFilteredEmpty,
} = useReviewDeskViews()

const detailOpen = ref(false)
const detailLoading = ref(false)
const detailReviewId = ref('')
const disposition = ref<Disposition | null>(null)
const acting = ref(false)

/**
 * 抽屉里那条差评的展示形状。
 *
 * ★ 为什么多这一层：抽屉有三个入口 —— 近期差评 / 孤儿差评给的是 `ProductReview`
 *   （字段最全），台账给的是 `DispositionReview` 摘要（**没有** asin / source /
 *   status）。不归一就会变成「同一个抽屉按入口不同走两套取值」，这正是本仓
 *   反复踩的「同一判定两份实现」。
 */
interface DetailView {
  id: string
  sku: string
  asin: string
  rating: number | null
  title: string
  body: string
  review_at: string
  buyer_name: string
  source: string
}

const detailView = ref<DetailView | null>(null)

function toDetailView(
  r: ProductReview | DispositionReview | null | undefined,
  id: string,
): DetailView {
  return {
    id,
    sku: r?.sku || '',
    asin: (r as ProductReview | undefined)?.asin || '',
    rating: r?.rating ?? null,
    title: r?.title || '',
    body: r?.body || '',
    review_at: r?.review_at || '',
    buyer_name: r?.buyer_name || '',
    source: (r as ProductReview | undefined)?.source || '',
  }
}

/**
 * 「这条差评 → 对话」的**唯一出口**（第 298 轮）。
 *
 * ★ 为什么走 CustomEvent 而不是直接改 provide / store：
 *   「切 Agent + 载对象 + 切回对话视图」这套时序在本仓有一处唯一实现
 *   （`Workspace.vue::launchProductToAgent` 那一族 handler）。本组件再写一份
 *   就是「同一动作两份实现」—— 加第三个跳转来源时必然漏一处。
 * ★ 传的是 `DetailView`（三个入口的**唯一归一形状**）：它的 `id` 就是
 *   `review_id` —— 后端差评应对技能第 0 步 `get_customer_review_context(review_id)`
 *   靠它取上下文。此前那个 id 只能从用户消息文本或**会话历史**里来。
 * ★ 三个界面入口（抽屉 `#extra` / 台账行 / 差评列表行）**都调它**，
 *   不各自 `dispatchEvent` —— 否则「谁在生产这个事件」就有三份实现，
 *   加第四个入口时必然漏一处。静态门禁 `check-review-chat-entries.cjs`
 *   钉的正是「本文件里 `dispatchEvent` 恰好 1 处」。
 */
function emitReviewToChat(rh: DetailView) {
  if (!rh?.id) return
  window.dispatchEvent(new CustomEvent('review-send-to-chat', { detail: { ...rh } }))
}

/**
 * 抽屉右上角【💬 在对话里处置这条】：出口同上，另外**关掉抽屉** ——
 * 马上要切到对话视图，留着一个覆盖全屏的抽屉会挡住它。
 */
function sendToChat() {
  const r = detailView.value
  if (!r) return
  emitReviewToChat(r)
  detailOpen.value = false
}

/**
 * 台账行 → 对话（第 298 轮补的缺口：老板「【处置台账】列表没有按钮」）。
 *
 * ★ 送的是 `review_id`（`d.review_id`），**不是**处置 id（`d.id`）——
 *   两者是不同实体：`d.id` 是处置记录的 id，拿它当 `review_id` 会把 Agent
 *   的结论**静默**打到另一条差评上（`Disposition` 两个字段都在，取错不报错）。
 * ★ 摘要 `d.review` 可能为 null（列表接口没带）⇒ 仍走 `toDetailView` 归一：
 *   它至少把 `id` 撑住，而后端只认这个 id，其余字段缺了不影响链路。
 */
function sendRowToChat(d: Disposition) {
  emitReviewToChat(toDetailView(d.review, d.review_id))
}

/** 差评列表行 → 对话（与台账行同一个出口，只是直接拿整条差评） */
function sendItemToChat(r: ProductReview) {
  emitReviewToChat(toDetailView(r, r.id))
}

// ==================================================================
// 风险话术识别（第 299 轮 P1）
//
// ★ 判定结果不进 `items`，单独放 `riskMap`：`items` 是「差评清单」这个事实，
//   判定是**针对某一份清单**的另一层快照。两者生命周期不同 —— 刷新列表（便宜）
//   不该顺手把判定（贵）丢掉，但清单一旦变了，旧判定必须作废，否则会把
//   A 清单的标记画到 B 清单的行上（行 id 还在、结论已过期）。
//   ⇒ 清空**不是**「只要 reload 就清」，而是「**这份清单的指纹变了**才清」：
//     判据的唯一写入点在 `reload()` 末尾
//     （`listKeyOf(items.value) !== riskListKey.value`），只有一处决定有效性。
//   ★★ 第 300 轮修正（老板实测报的缺陷）：原实现在 `reload()` **开头无条件**
//     清空，而 `switchView()` 每次都会 reload ⇒ 点一下「处置台账」就把刚跑出来的
//     判定全作废。那两份视图与「近期差评清单」无关，作废毫无道理 —— 用户要么
//     重跑一次 43s 深扫，要么被误导成「没识别过」。
//
// ★ 顺序由**后端**定：`riskOrder` 存的是后端返回的 id 序列，`displayItems`
//   只做「按这个序列重排」，**不判断谁风险高**。在界面再算一次就是
//   同一判定两份实现（本仓铁律）。静态门禁 `check-review-risk-view.cjs`
//   钉住本文件不得出现 `.sort(`。
// ==================================================================

/** review_id → 风险块（只有点过【风险识别】才有值） */
const riskMap = ref<Record<string, ReviewRiskBlock>>({})
/** 后端返回的**顺序**（风险 → 未定论 → 干净，同组内新→旧） */
const riskOrder = ref<string[]>([])
/** 本次判定的元信息（计数 / 降级 / 截断 + 后端中文名表） */
const riskMeta = ref<ReviewRiskScanResult | null>(null)
const riskLoading = ref(false)
const riskError = ref('')
/**
 * 当前这批标记**是针对哪一份清单**算出来的（指纹）。
 *
 * ★ 为什么需要它：判定（贵，43s）与清单（便宜）生命周期不同 ——
 *   清单没换就不该丢掉判定；清单换了就必须丢掉（否则把 A 清单的结论画到
 *   B 清单的行上：行 id 还在、结论已过期）。区分这两件事的唯一依据就是这个指纹。
 * ★ 空串 = 当前没有有效判定。
 */
const riskListKey = ref('')

const riskApplied = computed(() => riskOrder.value.length > 0)

/**
 * 「这份清单」的指纹 —— 风险判定**只对这一份**有效。
 *
 * ★ 为什么是「两个入参 + 行 id 序列」：
 *   · 少了 `days` / `max_rating`：改了时间窗、而恰好 id 没变（小店很常见）
 *     会被误判成同一份清单；
 *   · 少了 id 序列：期间新来了差评、或某条被处置后从列表消失，同样会被误判成
 *     同一份 —— 界面就用一份**缺行的旧结论**冒充当前清单。
 * ★ 用**后端返回的行**算，不在前端另立一套口径（本仓铁律：同一判定只有一份实现）。
 */
function listKeyOf(rows: ProductReview[]): string {
  return `${days.value}|${maxRating.value}|${rows.map((r) => r.id).join(',')}`
}

/**
 * 列表的**渲染顺序**。
 *
 * ★ 没有判定 ⇒ 原样；有判定 ⇒ 按后端给的 id 序列重排，后端没覆盖到的
 *   （例如单次上限截断）跟在后面 —— 一行都不丢。
 * ★ 这里**没有排序判断**，只有一次查表 + 拼接：「谁该置顶」是后端的结论。
 */
const displayItems = computed<ProductReview[]>(() => {
  if (!riskApplied.value) return items.value
  const left = new Map(items.value.map((r) => [r.id, r]))
  const out: ProductReview[] = []
  for (const id of riskOrder.value) {
    const r = left.get(id)
    if (r) {
      out.push(r)
      left.delete(id)
    }
  }
  for (const r of items.value) if (left.has(r.id)) out.push(r)
  return out
})

/** 卡片的风险皮肤类名（取值与后端 `DECISION_*` 对齐） */
function riskClass(id: string): string {
  const d = riskMap.value[id]?.decision
  return d ? `rd-risk-${d}` : ''
}

/** 等级中文名 —— ★ 取后端下发的 `level_labels`，不在前端写第二份映射 */
function levelLabel(level: string): string {
  return riskMeta.value?.level_labels?.[level] || level
}

/**
 * 证据块该不该出现。
 *
 * ★ 不能只判 `hits.length`：规则通道**只命中 r5（高情绪）**时定论是 `clean`，
 *   那时的 hits 是「候选池」线索，不是风险证据。若照样渲染，块里的类别名
 *   （`.rd-risk-hit-cat` 用 `--danger-strong`）就是**红字**，而卡片本身没有任何
 *   风险标记 —— 字面为真、暗示为假（读起来像「被标红了，但结论是干净」）。
 *   第 299 轮真机实测就撞到了这个：第一条差评 decision=clean 却挂着红字
 *   「高情绪差评」。
 * ⇒ 只有「有可执行的定论」才配上这个块：**命中四类**，或**未定论**（要人补判）。
 */
function showRiskEvidence(b?: ReviewRiskBlock): boolean {
  return !!b && b.hits.length > 0 && (b.is_risk || b.decision === 'unknown')
}

/** 风险标签文案：类别名 + 等级名**都来自后端** */
function riskTagText(b: ReviewRiskBlock): string {
  const names = b.risk_categories.map(
    (c) => b.hits.find((h) => h.category === c)?.label || c,
  )
  return `${names.join(' / ') || '风险'} · ${b.level_label}`
}

/** 清掉风险标记（**只清标记**，列表本身不动） */
function clearRisk() {
  riskMap.value = {}
  riskOrder.value = []
  riskMeta.value = null
  riskError.value = ''
  // ★ 指纹必须一起清：它代表「这批标记针对哪份清单」，标记没了它就不该留着
  //   （否则下一份**恰好同构**的清单会继承这批已经不存在的标记，把
  //   `listKeyOf(...) !== riskListKey` 这条判据骗过去）。
  riskListKey.value = ''
}

async function runRiskScan() {
  riskLoading.value = true
  riskError.value = ''
  try {
    // `deep=true` ⇒ 走语义通道。★ 这里**显式**写出来，不依赖后端默认值
    //   （默认档是浅层；依赖默认值 ⇒ 哪天默认值改了，会静默地开始花钱）。
    //   这个动作**只在用户按按钮时**发生，不挂在列表加载里。
    const res = await scanReviewsRisk({
      max_rating: maxRating.value, days: days.value, limit: 100, deep: true,
    })
    const map: Record<string, ReviewRiskBlock> = {}
    const order: string[] = []
    for (const it of res.items) {
      map[it.id] = it.risk
      order.push(it.id)
    }
    riskMap.value = map
    riskOrder.value = order
    riskMeta.value = res
    // ★ 记下「判定针对的是哪份清单」：`items.value` 此刻正是 `listShopReviews`
    //   用同一组 `max_rating` / `days` 载入的那一份（扫描与列表同源）。
    riskListKey.value = listKeyOf(items.value)
  } catch (e: any) {
    // ★ 失败必须落到界面上，不能变成「按钮点了没反应」；
    //   同时**清掉旧标记** —— 留着会让用户以为那是这次的结果。
    //   走 `clearRisk()`（而不是逐字段赋值）⇒ 指纹也一起清，不留半截状态。
    clearRisk()
    riskError.value = e?.response?.data?.detail || e?.message || '风险识别失败'
  } finally {
    riskLoading.value = false
  }
}

const confirmOpen = ref(false)
const pendingAct = ref<'approve' | 'reject' | 'issue' | 'receipt' | ''>('')
const rejectNotes = ref('')
/** 平台执行回执的输入（登记人由服务端注入，这里只有凭证号与备注） */
const receiptRef = ref('')
const receiptNote = ref('')
/** ★ 批量生成失败的原因**留在界面上**（一句 toast 装不下多条不同原因） */
const backfillNote = ref('')

// ==================================================================
// 补偿规则配置（第 304 轮后半）
//
// ★ 为什么这里要有独立的配置入口：此前「补偿方案」只读块写着
//   「要调金额请去改规则表」，但**没有任何路径到得了规则表**——
//   `compensation_rules` 连端点都没有，那句话是负指令。这个视图
//   就是那个缺失的入口：列表 / 新建 / 启停 / 删除，金额由这里唯一算出。
// ==================================================================

// ★ `rules` / `rulesError` 已随视图状态外移到 `useReviewDeskViews()`；
//   原 `const rulesLoading` 是**死代码**（全文件零消费点），一并删除。
/** 新建 / 编辑规则用的抽屉 */
const ruleEditorOpen = ref(false)
const ruleEditorLoading = ref(false)
/** null = 新建；有值 = 编辑那条（编辑时 `code` 只读） */
const editingRule = ref<CompensationRule | null>(null)
/** 表单态（新建与编辑共用一份） */
const ruleForm = ref<RuleForm>({
  code: '',
  name: '',
  cause: 'logistics_delay',
  priority: 100,
  max_rating: null,
  min_delay_days: null,
  verified_purchase: false,
  action_type: 'none',
  amount: null,
  currency: 'USD',
  budget_cap: 0,
  enabled: true,
  notes: '',
})

/** 补归因入口（差评列表行上的动作） */
const attrOpen = ref(false)
const attrLoading = ref(false)
const attrTarget = ref<ProductReview | null>(null)
const attrCause = ref<AttributionCause>('logistics_delay')
const attrNotes = ref('')

/** 打开新建规则 —— 重置表单到默认值 */
function openRuleCreate() {
  editingRule.value = null
  ruleForm.value = {
    code: '',
    name: '',
    cause: 'logistics_delay',
    priority: 100,
    max_rating: null,
    min_delay_days: null,
    verified_purchase: false,
    action_type: 'none',
    amount: null,
    currency: 'USD',
    budget_cap: 0,
    enabled: true,
    notes: '',
  }
  ruleEditorOpen.value = true
}

/** 打开编辑 —— 把后端值回填进表单（code 只读） */
function openRuleEdit(r: CompensationRule) {
  editingRule.value = r
  const c = r.conditions || {}
  const a = r.action || {}
  ruleForm.value = {
    code: r.code,
    name: r.name || '',
    cause: r.cause,
    priority: r.priority,
    max_rating: typeof c.max_rating === 'number' ? c.max_rating : null,
    min_delay_days: typeof c.min_delay_days === 'number' ? c.min_delay_days : null,
    verified_purchase: !!c.verified_purchase,
    action_type: (a.type === 'coupon' || a.type === 'refund') ? a.type : 'none',
    amount: typeof a.amount === 'number' ? a.amount : null,
    currency: a.currency || 'USD',
    budget_cap: r.budget_cap || 0,
    enabled: r.enabled,
    notes: r.notes || '',
  }
  ruleEditorOpen.value = true
}

/** 表单 → 后端请求体（条件 / 补偿只带非空项，避免传空键被后端拒） */
function buildRuleParam(): { create: CreateRuleParam; update: UpdateRuleParam } {
  const f = ruleForm.value
  const conditions: RuleCondition = {}
  if (typeof f.max_rating === 'number') conditions.max_rating = f.max_rating
  if (typeof f.min_delay_days === 'number') conditions.min_delay_days = f.min_delay_days
  if (f.verified_purchase) conditions.verified_purchase = true

  const action: RuleAction = { type: f.action_type }
  if (f.action_type !== 'none' && typeof f.amount === 'number') {
    action.amount = f.amount
    action.currency = f.currency
  }

  const common = {
    name: f.name,
    cause: f.cause,
    priority: f.priority,
    conditions: Object.keys(conditions).length ? conditions : undefined,
    action,
    budget_cap: f.budget_cap,
    enabled: f.enabled,
    notes: f.notes,
  }
  return {
    create: { code: f.code, ...common },
    update: common,
  }
}

/** 保存规则（新建 or 编辑） */
async function saveRule() {
  const f = ruleForm.value
  const isEdit = !!editingRule.value
  if (!isEdit && !f.code.trim()) {
    message.warning('请填规则代号（code）')
    return
  }
  ruleEditorLoading.value = true
  try {
    const { create, update } = buildRuleParam()
    if (isEdit) {
      await updateCompensationRule(editingRule.value!.id, update)
      message.success('规则已更新')
    } else {
      await createCompensationRule(create)
      message.success('规则已新建')
    }
    ruleEditorOpen.value = false
    if (view.value === 'rules') void reload()
  } catch (e: any) {
    // ★ 失败必须上屏：409 同 code 冲突、400 形状非法，都要让用户看见
    message.error(e?.response?.data?.detail || e?.message || '保存规则失败')
  } finally {
    ruleEditorLoading.value = false
  }
}

/** 启停一条规则（`enabled` 翻转，走 PATCH 部分更新） */
async function toggleRule(r: CompensationRule) {
  try {
    await updateCompensationRule(r.id, { enabled: !r.enabled })
    if (view.value === 'rules') void reload()
  } catch (e: any) {
    message.error(e?.response?.data?.detail || e?.message || '切换启用状态失败')
  }
}

/** 删除一条规则（硬删；确认交给 UI 的 Popconfirm） */
async function removeRule(r: CompensationRule) {
  try {
    await deleteCompensationRule(r.id)
    message.success('规则已删除')
    if (view.value === 'rules') void reload()
  } catch (e: any) {
    message.error(e?.response?.data?.detail || e?.message || '删除规则失败')
  }
}

/** 差评列表行 → 补归因抽屉 */
function openAttribution(r: ProductReview) {
  attrTarget.value = r
  attrCause.value = 'logistics_delay'
  attrNotes.value = ''
  attrOpen.value = true
}

/** 提交补归因 */
async function submitAttribution() {
  const r = attrTarget.value
  if (!r) return
  attrLoading.value = true
  try {
    await setReviewAttribution(r.id, {
      primary_cause: attrCause.value,
      notes: attrNotes.value,
    })
    message.success('已补归因 —— 这条差评现在会进入处置链')
    attrOpen.value = false
    if (view.value === 'recent') void reload()
  } catch (e: any) {
    message.error(e?.response?.data?.detail || e?.message || '补归因失败')
  } finally {
    attrLoading.value = false
  }
}

const confirmTitle = computed(() => CONFIRM_TITLES[pendingAct.value] || '确认操作')
const confirmText = computed(() => CONFIRM_TEXTS[pendingAct.value] || '')

async function reload() {
  loading.value = true
  error.value = ''
  try {
    if (view.value === 'ledger') {
      const res = await listDispositions({
        status: dispStatusFilter.value, limit: 200,
      })
      dispositions.value = res.items
      dispTotal.value = res.total
      counts.value.ledger = res.total
    } else if (view.value === 'rules') {
      const rows = await listCompensationRules({ include_disabled: true })
      rules.value = rows
      counts.value.rules = rows.length
    } else if (view.value === 'orphan') {
      const res = await listOrphanReviews({
        max_rating: maxRating.value, limit: 100,
      })
      items.value = res.items
      total.value = res.total
      counts.value.orphan = res.total
      await loadDispositionStates()
    } else {
      const res = await listShopReviews({
        max_rating: maxRating.value, days: days.value, limit: 100,
      })
      items.value = res.items
      total.value = res.total
      counts.value.recent = res.total
      await loadDispositionStates()
    }
  } catch (e: any) {
    // ★ 失败必须回写界面：否则所有失败都表现为「列表是空的，但又说不清为什么」
    error.value = e?.response?.data?.detail || e?.message || '加载失败'
    items.value = []
    total.value = 0
    dispositions.value = []
    dispTotal.value = 0
  } finally {
    loading.value = false
  }
  // ★★ 有效性判据的**唯一写入点**（第 300 轮）。放在 try/catch 之后、
  //   且只在「近期差评」视图里判，理由有两条：
  //     ① 判定只挂在 `view === 'recent'` 的那份清单上；切到处置台账 /
  //        未关联差评**并不改变**那份清单（`items` 也没被这两支改写），
  //        所以那时的 reload 与判定无关，不该顺手作废它；
  //     ② 放在 try/catch **之后** ⇒ 加载失败把 `items` 清空时，指纹同样对不上
  //        （变成 `days|rating|`），判定随之作废 —— 否则界面会一边报错、
  //        一边挂着「已识别 N 条」的旧计数（字面为真、暗示为假）。
  if (view.value === 'recent' && listKeyOf(items.value) !== riskListKey.value) {
    clearRisk()
  }
}

/**
 * 批量取「这批差评各自有没有处置」。
 * ★ 一条一条查 ⇒ 100 条就是 100 次往返。这里用一次性拉全店处置列表做映射，
 *   因为处置量级（人的动作产物）远小于差评量级。
 */
async function loadDispositionStates() {
  try {
    const res = await listDispositions({ limit: 200 })
    const map: Record<string, DispositionStatus> = {}
    for (const d of res.items) map[d.review_id] = d.status
    dispositionStatus.value = map
  } catch {
    // ★ 处置状态拿不到 ≠ 处置为空：宁可留着旧值，也不把「还没处置」伪装给用户看
    //   （沿用 preset的方向：拿不到权威清单时保留旧值）
  }
}

function switchView(k: ViewKey) {
  view.value = k
  void reload()
}

/** 清空台账状态筛选 —— 筛选造成的空态唯一的逃生口 */
function resetFilters() {
  dispStatusFilter.value = undefined
  void reload()
}

/** 差评列表行 → 抽屉 */
function openDetail(r: ProductReview) {
  void openDispositionDrawer(r.id, toDetailView(r, r.id))
}

/** 台账行 → 抽屉（`review` 摘要可能没带 ⇒ 允许先只认 review_id） */
function openDispositionDetail(d: Disposition) {
  void openDispositionDrawer(d.review_id, d.review ? toDetailView(d.review, d.review_id) : null)
}

// ==================================================================
// 个案 / 系统性判定（第 294 轮 B 档）
//
// ★ 判定与健康分是**两个独立事实**，所以走两个端点：
//     · `systemic-check` —— 这条差评是个案还是系统性（后端唯一口径）；
//     · `skus/{sku}/health` —— 这个 SKU 的健康分（与判定同源，同一个 service 函数）。
//   界面**不自己组合**判定结论：组合规则就是判据，放界面等于第二份实现。
// ==================================================================

/** 判定（后端唯一口径：verdict / verdict_label / recommend_escalate 全部取自它） */
const systemic = ref<SystemicCheck | null>(null)
const systemicLoading = ref(false)
const systemicError = ref('')
/** 该 SKU 的买家反馈健康分（独立端点；拿不到就不显示，不编 0 分） */
const skuHealth = ref<SkuHealth | null>(null)
/** 补偿依据（归因 + 命中规则）—— 来自**只读**的 `/draft`（明确不落库） */
const draftInfo = ref<DispositionDraft | null>(null)

async function loadSystemic(reviewId: string) {
  systemicLoading.value = true
  systemicError.value = ''
  systemic.value = null
  try {
    systemic.value = await getReviewSystemicCheck(reviewId)
  } catch (e: any) {
    // ★ 失败必须落到界面上，不能变成「判定区块空白的随机失败」
    systemicError.value = e?.response?.data?.detail || e?.message || '判定失败'
  } finally {
    systemicLoading.value = false
  }
}

async function loadSkuHealth(sku: string) {
  skuHealth.value = null
  if (!sku) return          // 没有 SKU（关联不上产品）⇒ 这一行不显示，不猜
  try {
    skuHealth.value = await getSkuHealth(sku)
  } catch {
    // ★ 拿不到健康分 ≠ 健康分为 0：宁可这一行空着
    skuHealth.value = null
  }
}

async function loadDraftInfo(reviewId: string) {
  try {
    const d = await draftDisposition(reviewId)
    draftInfo.value = d.ready ? d : null
  } catch {
    draftInfo.value = null
  }
}

/** 采纳判定 → 把「升级」勾进通道（**不直接保存**：仍要人点「保存修改」） */
function adoptEscalate() {
  if (!editable.value) return
  if (!editChannels.value.includes('escalate')) editChannels.value.push('escalate')
  channelHint.value = 'escalate'
  message.info('已勾选「升级」通道 —— 点「保存修改」后生效')
}

async function openDispositionDrawer(reviewId: string, seedView: DetailView | null) {
  detailView.value = seedView
  detailReviewId.value = reviewId
  disposition.value = null
  detailOpen.value = true
  detailLoading.value = true
  // ★ 判定 / 健康分 / 依据**不等处置拉完**：它们取的是差评与 SKU 维度的事实，
  //   与「这条差评有没有处置」无关 ⇒ 并行发出去，抽屉开得更快。
  void loadSystemic(reviewId)
  void loadSkuHealth(seedView?.sku || '')
  void loadDraftInfo(reviewId)
  try {
    disposition.value = await getDisposition(reviewId)
    // ★ 详情接口带的评价摘要才是权威的：台账行的摘要字段不全 ⇒ 拿到就覆盖
    if (disposition.value?.review) {
      detailView.value = toDetailView(disposition.value.review, reviewId)
      // ★ 详情接口带的 SKU 才是权威的：与预置值不同 ⇒ 用权威值重取健康分
      const sku = detailView.value.sku || ''
      if (sku && sku !== (seedView?.sku || '')) void loadSkuHealth(sku)
    }
  } catch {
    disposition.value = null    // 404：尚无处置，属正常状态
  } finally {
    // 兜底：seed 与详情都没有 ⇒ 至少把 id 撑住，别让抽屉整个空白
    if (!detailView.value) detailView.value = toDetailView(null, reviewId)
    detailLoading.value = false
  }
}

/**
 * 批量给「有归因但还没处置」的差评补生成草稿（幂等，已有则跳过）。
 *
 * ★★ 全仓只有这一处按钮：这个能力是从被删掉的资料库页搬过来的。
 *   若不搬，「批量生成」这条**写入路径就彻底消失** —— 而它是
 *   `review_dispositions` 唯一的批量写入口（单条走上面 proposeDraft）。
 */
async function runBackfill() {
  backfilling.value = true
  backfillNote.value = ''
  try {
    const out = await backfillDispositions()
    if (out.created > 0) {
      message.success(`已生成 ${out.created} 条待批准处置`)
    } else if (out.failed?.length) {
      // ★★ 用后端给的**真实**原因，不许自己猜。理由见 backfillFailureText。
      backfillNote.value = backfillFailureText(out.failed)
      message.warning(`没有生成新草稿：${out.failed.length} 条给不出方案（原因已展开在面板上）`)
    } else {
      message.info(
        `没有需要生成的差评（扫到 ${out.scanned ?? 0} 条：都已处置，或还没有归因）`,
      )
    }
    await reload()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '生成处置失败'
  } finally {
    backfilling.value = false
  }
}

/**
 * 把后端 `failed[]` 聚成人能读的一段话。
 *
 * ★★ 第 304 轮**两次**修正，教训是同一条：不许猜，也不许把两件事说成一件
 * ----------------------------------------------------------------
 * ① 面板原来写「多半是缺归因或没配规则」。实测那 4 条**全都有归因**
 *    ⇒ 猜的代价不是「说得不够准」，而是把人引到错方向：他跑去重跑归因，
 *      而重跑归因永远跑不出结果（缺的不是归因）。
 * ② 改成「这几类没有启用补偿规则」后**又错了**：4 条里 `logistics_delay`
 *    明明有启用规则（`logistics-delay-minor`，条件 `min_delay_days=3`），
 *    只是这条差评不满足条件 ⇒ 报「没有规则」是**假陈述**。
 *    ⇒ 一律以**后端 `reason_code`** 为准分流，前端不再从文案正则猜形状。
 *
 * ★ 两种成因**分开说**，因为下一步动作相反：
 *   `no_rule`（这一类真没有 ⇒ 补一条就能出方案）
 *   `rule_conditions_unmet`（有，但这条不满足 ⇒ 再配一条也命中不了）
 * ★ 同成因按归因归并计数（避免同一句话重复 N 遍），不同成因并列。
 * ★ 后端没给 `reason_code` 时退回按原文归并，如实说 —— 不补一个像是原因的句子。
 */
function backfillFailureText(failed: any[]): string {
  const items = (failed || []).filter((f) => f)
  const n = items.length
  if (!n) return ''

  const noRule = new Map<string, number>()
  const condUnmet = new Map<string, number>()
  let coded = 0
  for (const f of items) {
    const code = String(f?.reason_code || '')
    if (code !== 'no_rule' && code !== 'rule_conditions_unmet') continue
    const label = String(f?.primary_cause_label || f?.primary_cause || '未知归因').trim()
    const bucket = code === 'no_rule' ? noRule : condUnmet
    bucket.set(label, (bucket.get(label) || 0) + 1)
    coded++
  }
  const fmt = (m: Map<string, number>) =>
    [...m.entries()].map(([c, k]) => `${c} ${k} 条`).join(' / ')

  if (coded === n && (noRule.size || condUnmet.size)) {
    const segs: string[] = []
    if (noRule.size) {
      segs.push(
        `${fmt(noRule)}：这一类还没有补偿规则 —— 点顶部「补偿规则」标签补一条就能出方案`,
      )
    }
    if (condUnmet.size) {
      segs.push(
        `${fmt(condUnmet)}：已有规则，但这条不满足它的条件 —— 再配一条也命中不了，请看事实或改条件`,
      )
    }
    return `${n} 条给不出方案 —— ${segs.join('；')}。`
  }

  // 兜底：后端没分类（或混了别的成因）时按原文归并计数，最多列 3 种。
  // ★ 刻意**不用** `.sort()`：面板里出现排序就是「顺序的第二份实现」
  //   （门禁 `check-review-risk-view.cjs` R3）。Map 的插入顺序就是后端 `failed[]` 的顺序。
  const raw = items.map((f) => String(f?.reason || '').trim()).filter(Boolean)
  if (!raw.length) {
    return `${n} 条给不出方案，且后端没有返回原因 —— 不猜，请把这条差评 id 报给开发。`
  }
  const tally = new Map<string, number>()
  for (const r of raw) tally.set(r, (tally.get(r) || 0) + 1)
  const parts = [...tally.entries()].map(([r, c]) => (c > 1 ? `${r}（${c} 条）` : r))
  const shown = parts.length > 3 ? [...parts.slice(0, 3), `等 ${parts.length} 种原因`] : parts
  return `${n} 条给不出方案：${shown.join('；')}`
}

/** 生成草稿 —— 幂等，Agent 也能调这一步；后面的批准 / 核准 / 登记回执只能人点 */
async function proposeDraft() {
  const reviewId = detailView.value?.id
  if (!reviewId) return
  acting.value = true
  try {
    disposition.value = await proposeDisposition({ review_id: reviewId })
    message.success('处置草稿已生成（待批准）')
    void loadDraftInfo(reviewId)   // 依据（归因 / 命中规则）随之刷新
    void reload()
  } catch (e: any) {
    message.error(e?.response?.data?.detail || e?.message || '生成草稿失败')
  } finally {
    acting.value = false
  }
}

function confirmAct(kind: 'approve' | 'reject' | 'issue' | 'receipt') {
  pendingAct.value = kind
  rejectNotes.value = ''
  receiptRef.value = ''
  receiptNote.value = ''
  confirmOpen.value = true
}

async function runAct() {
  const reviewId = detailView.value?.id
  const kind = pendingAct.value
  if (!reviewId || !kind) return
  acting.value = true
  try {
    if (kind === 'approve') disposition.value = await approveDisposition(reviewId)
    else if (kind === 'reject') disposition.value = await rejectDisposition(reviewId, rejectNotes.value)
    else if (kind === 'receipt') {
      disposition.value = await recordExecutionReceipt(reviewId, {
        execution_mode: 'manual',
        platform_ref: receiptRef.value,
        receipt_note: receiptNote.value,
      })
    } else disposition.value = await issueDisposition(reviewId)
    message.success(
      kind === 'issue'
        // ★ 不许说「已发放」：那一步只做本地核准，平台侧还没动
        ? '已核准，券码已生成并写进回复 —— 平台侧还没执行，请人工去平台后台完成后登记回执'
        : kind === 'receipt'
          ? '回执已登记：平台已执行（终态，不可再改）'
          : '操作完成',
    )
    confirmOpen.value = false
    void reload()
  } catch (e: any) {
    // ★ 每个失败都要能看到原因（例如「未批准就想发放」会被后端挡掉）
    message.error(e?.response?.data?.detail || e?.message || '操作失败')
  } finally {
    acting.value = false
  }
}

/** 通道中文名（与后端值域对齐；认不出的取值原样吐出来，不静默吞掉） */
function channelLabel(c: string): string {
  return CHANNEL_LABELS[c] || c
}

/** 通道作用说明 —— 台账列表悬停用；认不出的取值如实说「尚无说明」 */
function channelEffect(c: string): string {
  return CHANNEL_META[c]?.effect || `${c}（后端新加的通道，界面还没有说明）`
}

// ==================================================================
// 抽屉里的编辑区（第 292 轮）
//
// ★ 为什么这里要有编辑：从前面板把四块内容（补偿方案 / 通道 / 券码 / 回复草稿）
//   全做成 `<span>` 只读，用户「找不到去哪里编辑」。但**不是四块都能改**：
//     · 补偿金额 —— 不能改。改了绕过预算上限（Rule 是唯一真源）；
//     · 券码     —— 不能改，它只在核准那一步生成；
//     · 通道     —— 可改，且必须讲清每类的可逆性；
//     · 回复措辞 —— 可改（对买家说话吃语境），改措辞不涉及钱，无安全风险。
//
// ★ 状态与动作已外移到 `reviewDesk/useReviewDeskEdits.ts`（第 341 轮第二刀）。
//   这里只留口径说明。通道语义表 `CHANNEL_META` / 通道全集 `ALL_CHANNELS` 仍住在
//   本文件（门禁 `check-disposition-execution-honesty.cjs` H8 钉住），按**引用**
//   注入 composable —— 不复制第二份，避免「同一判定两份实现」。
// ==================================================================
const {
  editChannels, editZh, editEn, channelHint,
  editable, lockReason, editDirty, focusChannel, irreversiblePicked,
  toggleChannel, saveEdits, restoreSystemDraft,
} = useReviewDeskEdits({
  disposition, detailView, acting, reload,
  allChannels: ALL_CHANNELS,
  channelMeta: CHANNEL_META,
})

void reload()
</script>

<style scoped src="./reviewDesk/reviewDesk.css"></style>
<style scoped src="./reviewDesk/rdTable.css"></style>
