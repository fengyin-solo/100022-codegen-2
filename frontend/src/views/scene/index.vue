<template>
  <section class="page" data-module="scene">
    <header class="page-head">
      <div>
        <h2>分场大纲管理</h2>
        <p class="page-desc">
          维护分场表，拍摄难度按场次、场景地点、日戏夜戏与预计时长统一评估；
          列表与导出同一套标准，已审核场次锁定历史结果。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记分场表</button>
        <button class="btn" type="button" :disabled="recalculating" @click="recalculate(false)">重算全部难度</button>
        <button class="btn" type="button" :disabled="recalculating" @click="recalculate(true)">只重试失败场次</button>
        <button class="btn" type="button" @click="exportRows">导出分场大纲清单</button>
      </div>
    </header>

    <div v-if="rules" class="rule-bar">
      <span>当前规则版本：<strong>{{ rules.rule_version }}</strong></span>
      <span>单场时长上限：<strong>{{ rules.duration_limit_minutes }} 分钟</strong>（超过即判争议）</span>
      <span>争议项口径：{{ rules.dispute_criteria.join('；') }}</span>
    </div>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>难度状态 / 争议</th>
          <th>规则版本</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :class="{ 'row-locked': row.难度锁定 }">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>
            <span v-if="row.难度锁定" class="tag tag-locked">已锁定</span>
            <span v-else-if="row.难度状态 === '评估失败'" class="tag tag-failed" :title="row.评估原因 ?? undefined">
              评估失败
            </span>
            <span v-else-if="row.难度状态 === '争议待复核'" class="tag tag-dispute">争议待复核</span>
            <span v-else class="tag tag-ok">{{ row.难度状态 }}</span>
            <ul v-if="hasDisputes(row)" class="dispute-list">
              <li v-for="reason in (row.争议说明 ?? [])" :key="reason">{{ reason }}</li>
            </ul>
            <p v-if="row.难度状态 === '评估失败'" class="fail-reason">{{ row.评估原因 }}</p>
          </td>
          <td>
            {{ row.规则版本 ?? '—' }}
            <span v-if="row.难度锁定" title="审核时冻结的规则快照，阈值变更不会改写">🔒</span>
          </td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 3" class="empty-state">暂无分场大纲数据，可先登记分场表</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条分场大纲记录（导出与列表采用同一评估标准）</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
    </footer>

    <div v-if="creating" class="modal-mask" @click.self="closeCreate">
      <form class="modal-card" @submit.prevent="submitCreate">
        <h3>登记分场表</h3>
        <p class="modal-tip">
          场景地点、日戏夜戏、预计时长为难度评估必填项；地点或时长缺失/无法解析时
          不允许保存。预计时长支持「120」「120分钟」「2小时」等写法，
          超过 {{ rules?.duration_limit_minutes ?? 240 }} 分钟将标记为争议项。
        </p>
        <label v-for="field in formFields" :key="field.key" class="modal-field">
          <span>{{ field.label }}<em v-if="field.required">*</em></span>
          <select v-if="field.key === '日戏夜戏'" v-model="form[field.key]">
            <option value="" disabled>请选择日戏 / 夜戏</option>
            <option v-for="opt in ['日戏', '夜戏']" :key="opt" :value="opt">{{ opt }}</option>
          </select>
          <input v-else v-model="form[field.key]" :placeholder="field.placeholder ?? ''" />
        </label>
        <p v-if="createError" class="error-text">{{ createError }}</p>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="closeCreate">取消</button>
          <button class="btn primary" type="submit" :disabled="submitting">保存并评估难度</button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type SceneRow = {
  id: number
  拍摄难度?: string | null
  难度总分?: number | null
  难度争议?: boolean
  争议说明?: string[]
  难度状态?: string
  评估原因?: string
  规则版本?: string
  难度锁定?: boolean
  [key: string]: string | number | boolean | string[] | null | undefined
}
type Rules = {
  rule_version: string
  duration_limit_minutes: number
  dispute_criteria: string[]
}

const ENDPOINT = '/api/scene'
const columns = ["场次编号", "所属剧本", "场景地点", "日戏夜戏", "出场人物", "预计时长", "拍摄难度"]
const actions = ["提交分场", "审核分场", "调整场次"]

const rows = ref<SceneRow[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = ["场次编号", "所属剧本", "场景地点"]
const rules = ref<Rules | null>(null)
const recalculating = ref(false)

const creating = ref(false)
const submitting = ref(false)
const createError = ref('')
const form = reactive<Record<string, string>>({
  场次编号: '',
  所属剧本: '',
  场景地点: '',
  日戏夜戏: '',
  预计时长: '',
  出场人物: '',
})
const formFields = [
  { key: '场次编号', label: '场次编号', required: true, placeholder: '如 SCEN-0010' },
  { key: '所属剧本', label: '所属剧本', required: true },
  { key: '场景地点', label: '场景地点', required: true, placeholder: '棚拍 / 常规实景 / 特殊外景按名称自动归类' },
  { key: '日戏夜戏', label: '日戏夜戏', required: true },
  { key: '预计时长', label: '预计时长（分钟）', required: true, placeholder: '如 120分钟 / 2小时' },
  { key: '出场人物', label: '出场人物', required: false },
]

function hasDisputes(row: SceneRow): boolean {
  return row.难度争议 === true && Array.isArray(row.争议说明) && row.争议说明.length > 0
}

const stats = computed(() => [  { label: '总场次数', value: rows.value.length },
  {
    label: '高难度场次',
    value: rows.value.filter((row) => row.拍摄难度 === '高').length,
  },
  {
    label: '争议待复核',
    value: rows.value.filter((row) => row.难度争议 === true).length,
  },
  {
    label: '评估失败',
    value: rows.value.filter((row) => row.难度状态 === '评估失败').length,
  },
])

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  createError.value = ''
  Object.keys(form).forEach((key) => {
    form[key] = ''
  })
  creating.value = true
}

function closeCreate() {
  creating.value = false
}

async function submitCreate() {
  createError.value = ''
  submitting.value = true
  try {
    const values: Record<string, string> = {}
    Object.entries(form).forEach(([key, value]) => {
      if (value.trim()) values[key] = value.trim()
    })
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      // 地点/时长缺失等不允许保存的原因由后端明确给出，原样展示，不静默吞掉。
      createError.value = payload.message || '分场表未保存，请检查必填项'
      return
    }
    creating.value = false
    noticeMessage.value = '分场表已保存，拍摄难度已按现行规则评估'
    await reload()
  } catch (error) {
    createError.value = error instanceof Error ? error.message : '分场表保存失败'
  } finally {
    submitting.value = false
  }
}

async function recalculate(onlyFailed: boolean) {
  errorMessage.value = ''
  noticeMessage.value = ''
  recalculating.value = true
  try {
    const response = await request(`${ENDPOINT}/recalculate`, {
      method: 'POST',
      body: JSON.stringify({ only_failed: onlyFailed }),
    })
    const payload = await response.json()
    if (!response.ok) {
      throw new Error(payload.detail || '重算未生效')
    }
    const parts = [
      `成功 ${payload.succeeded.length} 场`,
      `失败 ${payload.failed.length} 场`,
      `已锁定跳过 ${payload.skipped.length} 场`,
    ]
    noticeMessage.value = `重算完成（规则 ${payload.rule_version}）：${parts.join('，')}` +
      (payload.failed.length ? '；失败场次可在补全地点或时长后点「只重试失败场次」。' : '')
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '拍摄难度重算失败'
  } finally {
    recalculating.value = false
  }
}

async function runAction(action: string, row: SceneRow) {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || '分场大纲动作未生效')
    }
    if (action === '审核分场') {
      noticeMessage.value = '分场已审核，难度结果与规则版本已冻结，后续阈值变更不会改写本场。'
    } else if (action === '调整场次') {
      noticeMessage.value = '分场已解冻并按现行规则重新评估难度。'
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '分场大纲操作失败'
  }
}

async function loadRules() {
  try {
    const response = await request(`${ENDPOINT}/difficulty-rules`)
    if (response.ok) {
      rules.value = await response.json()
    }
  } catch {
    // 规则口径加载失败不阻塞列表
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('分场表列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '分场大纲列表读取失败'
  }
}

onMounted(() => {
  void loadRules()
  void reload()
})
</script>

<style scoped>
.page-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.rule-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  background: #f8fafc;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 12px;
  margin-bottom: 12px;
  font-size: 12px;
  color: var(--muted);
}

.tag {
  display: inline-block;
  border-radius: 10px;
  padding: 1px 8px;
  font-size: 12px;
  white-space: nowrap;
}

.tag-ok { background: #ecfdf3; color: #027a48; }
.tag-dispute { background: #fffaeb; color: #b54708; }
.tag-failed { background: #fef3f2; color: #b42318; }
.tag-locked { background: #eef2f6; color: #475467; }

.row-locked {
  background: #fafafa;
}

.dispute-list {
  margin: 4px 0 0;
  padding-left: 16px;
  font-size: 12px;
  color: #b54708;
}

.fail-reason {
  margin: 4px 0 0;
  font-size: 12px;
  color: #b42318;
}

.notice-text {
  color: #027a48;
}

.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(16, 24, 40, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}

.modal-card {
  width: 460px;
  max-width: calc(100vw - 32px);
  background: #fff;
  border-radius: 10px;
  padding: 18px 20px;
}

.modal-card h3 {
  margin: 0 0 8px;
}

.modal-tip {
  font-size: 12px;
  color: var(--muted);
  margin: 0 0 12px;
}

.modal-field {
  display: block;
  margin-bottom: 10px;
}

.modal-field span {
  display: block;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 4px;
}

.modal-field em {
  color: #b42318;
  font-style: normal;
  margin-left: 2px;
}

.modal-field input,
.modal-field select {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 13px;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 14px;
}
</style>
