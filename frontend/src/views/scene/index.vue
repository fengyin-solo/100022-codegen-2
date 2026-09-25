<template>
  <section class="page" data-module="scene">
    <header class="page-head">
      <div>
        <h2>分场大纲管理</h2>
        <p class="page-desc">维护分场表，围绕场次编号、所属剧本、场景地点、日戏夜戏做登记、筛选与状态流转；拍摄难度按统一规则评估。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记分场表</button>
        <button class="btn" type="button" :disabled="recalculating" @click="recalculate()">
          {{ recalculating ? '重算中…' : '重算难度' }}
        </button>
        <button class="btn" type="button" @click="exportRows">导出分场大纲清单</button>
      </div>
    </header>

    <details v-if="rules" class="rule-panel">
      <summary>难度评估规则（当前版本 {{ rules.rule_version }}，单场时长上限 {{ rules.duration_max_minutes }} 分钟）</summary>
      <div class="rule-body">
        <div>
          <h3>计分口径</h3>
          <ul>
            <li v-for="item in rules.score_rules" :key="item">{{ item }}</li>
          </ul>
        </div>
        <div>
          <h3>争议项判定</h3>
          <ul>
            <li v-for="item in rules.dispute_rules" :key="item">{{ item }}</li>
          </ul>
          <p class="rule-note">{{ rules.frozen_policy }}</p>
        </div>
      </div>
    </details>

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
      <label class="filter-item">
        <span>分场状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="item in statuses" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <div v-if="recalcResult" class="recalc-panel">
      <p>
        重算完成（规则版本 {{ recalcResult.rule_version }}）：共 {{ recalcResult.summary.total }} 场，
        已重算 {{ recalcResult.summary.recalculated }}，已跳过 {{ recalcResult.summary.skipped }}，
        失败 {{ recalcResult.summary.failed }}。
        <button
          v-if="failedIds.length"
          class="link"
          type="button"
          :disabled="recalculating"
          @click="recalculate(failedIds)"
        >
          只重试失败场次（{{ failedIds.length }}）
        </button>
      </p>
      <ul v-if="failedItems.length" class="recalc-failures">
        <li v-for="item in failedItems" :key="item.id">
          {{ item.场次编号 || `ID ${item.id}` }}：{{ item.reason }}
        </li>
      </ul>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <template v-if="column === '预计时长'">
              {{ row[column] == null ? '—' : `${row[column]} 分钟` }}
            </template>
            <template v-else-if="column === '拍摄难度'">
              <span :title="row.难度规则版本 ? `评估规则版本 ${row.难度规则版本}` : '尚未评估'">
                {{ row[column] ?? '—' }}
              </span>
            </template>
            <template v-else-if="column === '难度争议'">
              <span v-if="row[column] === true" class="dispute-text" :title="String(row.争议原因 ?? '')">是</span>
              <span v-else-if="row[column] === false">否</span>
              <span v-else>—</span>
            </template>
            <template v-else>{{ row[column] || '—' }}</template>
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
          <td :colspan="columns.length + 1" class="empty-state">暂无分场大纲数据，可先登记分场表</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条分场大纲记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="showCreate" class="modal-mask" @click.self="closeCreate">
      <form class="modal-card" @submit.prevent="submitCreate">
        <h3>登记分场表</h3>
        <label v-for="field in createFields" :key="field.name" class="filter-item">
          <span>{{ field.label }}{{ field.required ? '（必填）' : '' }}</span>
          <select v-if="field.options" v-model="createForm[field.name]">
            <option value="">请选择</option>
            <option v-for="option in field.options" :key="option" :value="option">{{ option }}</option>
          </select>
          <input
            v-else
            v-model="createForm[field.name]"
            :type="field.type ?? 'text'"
            :placeholder="field.placeholder ?? ''"
          />
        </label>
        <p class="modal-hint">场景地点与预计时长为难度评估依据，缺失时不允许保存。</p>
        <p v-if="createError" class="error-text">{{ createError }}</p>
        <div class="modal-actions">
          <button class="btn primary" type="submit" :disabled="creating">{{ creating ? '保存中…' : '保存' }}</button>
          <button class="btn ghost" type="button" @click="closeCreate">取消</button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>

interface RuleInfo {
  rule_version: string
  duration_max_minutes: number
  score_rules: string[]
  dispute_rules: string[]
  frozen_policy: string
}

interface RecalcItem {
  id: number
  场次编号: string
  result: string
  reason: string
}

interface RecalcResult {
  rule_version: string
  summary: { total: number; recalculated: number; skipped: number; failed: number }
  results: RecalcItem[]
}

const ENDPOINT = '/api/scene'
const columns = ["场次编号", "所属剧本", "场景地点", "日戏夜戏", "出场人物", "预计时长", "拍摄难度", "难度争议", "分场状态"]
const actions = ["提交分场", "审核分场", "调整场次"]
const statuses = ["待编写", "已编写", "已审核", "已调整"]
interface CreateField {
  name: string
  label: string
  required: boolean
  type?: string
  placeholder?: string
  options?: string[]
}

const createFields: CreateField[] = [
  { name: '场次编号', label: '场次编号', required: true, placeholder: '如 SCEN-0006' },
  { name: '所属剧本', label: '所属剧本', required: true, placeholder: '如 SCRI-0001' },
  { name: '场景地点', label: '场景地点', required: true, placeholder: '如 咖啡馆内景 / 山顶公路外景' },
  { name: '日戏夜戏', label: '日戏夜戏', required: false, options: ['日戏', '夜戏', '黄昏', '清晨'] },
  { name: '出场人物', label: '出场人物', required: false, placeholder: '多个角色用顿号分隔' },
  { name: '预计时长', label: '预计时长（分钟）', required: true, type: 'number', placeholder: '如 30' },
]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const stats = ref([
  { label: '总场次数', value: 0 },
  { label: '待编写场次', value: 0 },
  { label: '夜戏场次', value: 0 },
  { label: '争议场次', value: 0 },
])

const rules = ref<RuleInfo | null>(null)
const recalcResult = ref<RecalcResult | null>(null)
const recalculating = ref(false)
const failedIds = ref<number[]>([])
const failedItems = ref<RecalcItem[]>([])

const showCreate = ref(false)
const creating = ref(false)
const createError = ref('')
const createForm = reactive<Record<string, string>>({})

function buildQuery() {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters.value)) {
    if (value) params.set(key === '场次编号' ? 'keyword' : key, value)
  }
  return params.toString()
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  // 导出与列表走同一组过滤条件、同一份评估结果，口径保持一致。
  const query = buildQuery()
  window.open(`${ENDPOINT}/export${query ? `?${query}` : ''}`, '_blank')
}

function openCreate() {
  createError.value = ''
  for (const field of createFields) createForm[field.name] = ''
  showCreate.value = true
}

function closeCreate() {
  showCreate.value = false
}

async function submitCreate() {
  creating.value = true
  createError.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: { ...createForm } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      createError.value = payload.message ?? '分场表保存被拒绝，请检查必填项'
      return
    }
    showCreate.value = false
    await reload()
  } catch (error) {
    createError.value = error instanceof Error ? error.message : '分场表保存失败'
  } finally {
    creating.value = false
  }
}

async function recalculate(entryIds?: number[]) {
  recalculating.value = true
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/recalculate`, {
      method: 'POST',
      body: JSON.stringify(entryIds?.length ? { entry_ids: entryIds } : {}),
    })
    if (!response.ok) {
      throw new Error('难度重算请求被拒绝，请稍后重试')
    }
    const payload = (await response.json()) as RecalcResult
    recalcResult.value = payload
    failedItems.value = payload.results.filter((item) => item.result === '失败')
    failedIds.value = failedItems.value.map((item) => item.id)
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '难度重算失败'
  } finally {
    recalculating.value = false
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? '分场大纲动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '分场大纲操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = buildQuery()
  try {
    const response = await request(`${ENDPOINT}${query ? `?${query}` : ''}`)
    if (!response.ok) {
      throw new Error('分场表列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    await refreshStats()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '分场大纲列表读取失败'
  }
}

async function refreshStats() {
  // 统计卡片需要全量口径，单独拉一次未过滤列表（演示数据量级在分页上限内）。
  const response = await request(`${ENDPOINT}?size=200`)
  if (!response.ok) return
  const payload = await response.json()
  const all: Row[] = payload.items ?? []
  stats.value = [
    { label: '总场次数', value: all.length },
    { label: '待编写场次', value: all.filter((row) => row.分场状态 === '待编写').length },
    { label: '夜戏场次', value: all.filter((row) => row.日戏夜戏 === '夜戏').length },
    { label: '争议场次', value: all.filter((row) => row.难度争议 === true).length },
  ]
}

async function loadRules() {
  try {
    const response = await request(`${ENDPOINT}/difficulty-rules`)
    if (response.ok) {
      rules.value = (await response.json()) as RuleInfo
    }
  } catch {
    rules.value = null
  }
}

onMounted(() => {
  void loadRules()
  void reload()
})
</script>

<style scoped>
.page-actions { display: flex; gap: 8px; }
.rule-panel { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 8px 12px; margin-bottom: 12px; font-size: 13px; }
.rule-panel summary { cursor: pointer; color: var(--brand); }
.rule-body { display: flex; gap: 24px; flex-wrap: wrap; margin-top: 8px; }
.rule-body h3 { font-size: 13px; margin: 0 0 4px; }
.rule-body ul { margin: 0; padding-left: 18px; color: var(--muted); }
.rule-note { color: #b42318; margin: 8px 0 0; }
.recalc-panel { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 8px 12px; margin-bottom: 12px; font-size: 13px; }
.recalc-panel p { margin: 0; }
.recalc-failures { margin: 6px 0 0; padding-left: 18px; color: #b42318; }
.dispute-text { color: #b42318; font-weight: 600; }
.modal-mask { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.4); display: flex; align-items: center; justify-content: center; z-index: 10; }
.modal-card { background: #fff; border-radius: 10px; padding: 20px; width: 420px; max-width: 90vw; display: flex; flex-direction: column; gap: 10px; }
.modal-card h3 { margin: 0; }
.modal-card input, .modal-card select { width: 100%; padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; }
.modal-hint { font-size: 12px; color: var(--muted); margin: 0; }
.modal-actions { display: flex; gap: 8px; justify-content: flex-end; }
.filter-item select { padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; }
</style>
