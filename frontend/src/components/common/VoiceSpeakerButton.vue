<template>
  <!-- 只有白名单内的 Agent 才渲染（白名单唯一真源在 store，别在这里再写一遍） -->
  <a-tooltip v-if="tts.supports(agentId)" :title="tooltip" placement="bottomRight">
    <button
      class="speaker-btn"
      :class="{ on: tts.enabled, playing: tts.phase === 'playing' }"
      :aria-label="tooltip"
      :aria-pressed="tts.enabled"
      @click="onClick"
    >
      <LoadingOutlined v-if="busy" spin />
      <PauseOutlined v-else-if="tts.phase === 'playing'" />
      <SoundOutlined v-else-if="tts.enabled" />

      <!--
        关闭态 = 「禁止喇叭」（喇叭 + 斜杠）。

        ★ 这里**不能**用 antd 的 `AudioMutedOutlined` —— 那个图标画的是「静音**麦克风**」
          （话筒 + 斜杠），跟本按钮的语义（喇叭播报）对不上。
        ★ 而 ant-design 图标库里**根本没有**「喇叭 + 斜杠」这个图标：7.0.1 实测 789 个图标中
          与声音相关的只有 AudioOutlined / AudioFilled / AudioMutedOutlined /
          SoundOutlined / SoundFilled / SoundTwoTone，没有 muted-sound。
        ⇒ 所以内联一个，两段几何都取自 antd 自己，保证与开启态同形、与图标库同风格：
          · 喇叭主体：逐字复用 `SoundOutlined` 的 path（形状与开启态完全一致）
          · 斜杠：复用 antd 自家 `EyeInvisibleOutlined` 的斜杠几何（同 viewBox、
            同粗细 76 个 viewBox 单位、同为直接叠加不挖空）
      -->
      <svg
        v-else
        class="speaker-off"
        viewBox="64 64 896 896"
        width="1em"
        height="1em"
        fill="currentColor"
        focusable="false"
        aria-hidden="true"
      >
        <path
          d="M625.9 115c-5.9 0-11.9 1.6-17.4 5.3L254 352H90c-8.8 0-16 7.2-16 16v288c0 8.8 7.2 16 16 16h164l354.5 231.7c5.5 3.6 11.6 5.3 17.4 5.3 16.7 0 32.1-13.3 32.1-32.1V147.1c0-18.8-15.4-32.1-32.1-32.1zM586 803L293.4 611.7l-18-11.7H146V424h129.4l17.9-11.7L586 221v582zm348-327H806c-8.8 0-16 7.2-16 16v40c0 8.8 7.2 16 16 16h128c8.8 0 16-7.2 16-16v-40c0-8.8-7.2-16-16-16zm-41.9 261.8l-110.3-63.7a15.9 15.9 0 00-21.7 5.9l-19.9 34.5c-4.4 7.6-1.8 17.4 5.8 21.8L856.3 800a15.9 15.9 0 0021.7-5.9l19.9-34.5c4.4-7.6 1.7-17.4-5.8-21.8zM760 344a15.9 15.9 0 0021.7 5.9L892 286.2c7.6-4.4 10.2-14.2 5.8-21.8L878 230a15.9 15.9 0 00-21.7-5.9L746 287.8a15.99 15.99 0 00-5.8 21.8L760 344z"
        />
        <line
          x1="139.5"
          y1="862"
          x2="851.6"
          y2="149.9"
          stroke="currentColor"
          stroke-width="76"
        />
      </svg>
    </button>
  </a-tooltip>
</template>

<script setup lang="ts">
/**
 * 语音播报开关（对话框右上角喇叭）。
 *
 * 交互（对齐豆包那类「读给我听」）：
 * - 关闭态点一下 → 先**体检当前店铺有没有可用音色**；没有就明确说原因并保持关闭，绝不用默认音色顶替
 * - 开启后 Agent 回复自动朗读；正在播时点一下 = **只停播**（开关仍开着）；再点一下才关
 *
 * 音色是 per-shop 的（`shop_voice` 按店铺存），所以切店铺时必须停播 + 重新体检。
 */
import { computed, onMounted, onUnmounted, watch } from 'vue'
import { LoadingOutlined, PauseOutlined, SoundOutlined } from '@ant-design/icons-vue'

import { useVoiceTtsStore } from '@/stores/voiceTts'
import { useShopStore } from '@/stores/shop'

const props = defineProps<{ agentId: string }>()

const tts = useVoiceTtsStore()
const shopStore = useShopStore()

const busy = computed(() => tts.phase === 'loading' || tts.phase === 'checking')

const tooltip = computed(() => {
  if (tts.phase === 'checking') return '正在确认当前店铺的音色…'
  if (tts.phase === 'loading') return '正在合成语音…（点击停止）'
  if (tts.phase === 'playing') return '正在朗读（点击停止播放）'
  if (tts.enabled) return '关闭语音播报'
  return '开启语音播报：店秘书的回复会自动朗读'
})

async function onClick() {
  await tts.toggle(props.agentId)
}

// 音色 per-shop：切店铺 → 停播 + 清缓存 + 重新体检
watch(
  () => shopStore.currentShopId,
  () => {
    void tts.handleShopChange()
  }
)

onMounted(() => {
  void tts.refreshAvailability()
})

// 组件消失（切到别的 Agent / 离开对话视图）时停掉播放，别让上一家的声音留在后台
onUnmounted(() => {
  tts.stop()
})
</script>

<style scoped>
.speaker-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  position: relative;
  width: 30px;
  height: 30px;
  margin-left: var(--space-12);
  padding: 0;
  font-size: var(--font-size-14);
  color: var(--text-secondary);
  background: transparent;
  border: 1px solid var(--border-base);
  border-radius: var(--radius-8);
  cursor: pointer;
  transition: all 0.18s ease;
}

.speaker-btn:hover {
  color: var(--primary);
  border-color: var(--primary);
  background: var(--bg-hover-light);
}

/* 内联的「禁止喇叭」图标：去掉 inline 基线间隙，尺寸交给 svg 的 1em */
.speaker-off {
  display: block;
}

/* 开启态：实心主色，与「未开启」一眼可分 */
.speaker-btn.on {
  color: #fff;
  background: var(--primary);
  border-color: var(--primary);
}

.speaker-btn.on:hover {
  color: #fff;
  background: var(--primary-hover);
  border-color: var(--primary-hover);
}

/* 播放态：外层呼吸圈 —— 区分「已开启」与「正在念」 */
.speaker-btn.playing::after {
  content: '';
  position: absolute;
  inset: -3px;
  border: 2px solid var(--primary);
  border-radius: var(--radius-10);
  animation: voice-speaker-pulse 1.3s ease-out infinite;
  pointer-events: none;
}

@keyframes voice-speaker-pulse {
  0% {
    opacity: 0.75;
    transform: scale(0.92);
  }
  100% {
    opacity: 0;
    transform: scale(1.3);
  }
}

/* 尊重系统「减少动效」设置：不做缩放动画，只留一个静态描边 */
@media (prefers-reduced-motion: reduce) {
  .speaker-btn.playing::after {
    animation: none;
    opacity: 0.5;
  }
}
</style>
