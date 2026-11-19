<template>
  <section class="page" data-module="alert">
    <header class="page-head">
      <div>
        <h2>智能告警管理</h2>
        <p class="page-desc">维护告警规则，围绕规则编号、告警名称、监控指标、阈值条件做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记告警规则</button>
        <button class="btn" type="button" @click="exportRows">导出智能告警清单</button>
      </div>
    </header>

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
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
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
          <td :colspan="columns.length + 1" class="empty-state">暂无智能告警数据，可先登记告警规则</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条智能告警记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <section class="panel">
      <h3 class="panel-title">告警判定记录</h3>
      <p class="panel-desc">按实际发布的指标结果快照判定；计算失败期间展示上次完整结果的判定依据，可对照每次触发时的输入批次。</p>
      <form class="filter-bar" @submit.prevent="loadEvaluations">
        <label class="filter-item">
          <span>规则编号</span>
          <input v-model="evalRuleFilter" placeholder="如 ALER-0003" />
        </label>
        <label class="filter-item">
          <span>统计月份</span>
          <input v-model="evalMonthFilter" placeholder="如 2026-10" />
        </label>
        <button class="btn" type="submit">查询判定</button>
        <button class="btn ghost" type="button" @click="resetEvalFilters">重置条件</button>
      </form>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in evalColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in evalRows" :key="String(row.id)">
            <td v-for="column in evalColumns" :key="column">
              <strong v-if="column === '判定结果' && row[column] === '已触发'" class="triggered-text">{{ row[column] }}</strong>
              <template v-else>{{ row[column] ?? '—' }}</template>
            </td>
          </tr>
          <tr v-if="!evalRows.length">
            <td :colspan="evalColumns.length" class="empty-state">暂无告警判定记录，发布月度快照后自动生成</td>
          </tr>
        </tbody>
      </table>
    </section>

    <Teleport to="body">
      <div v-if="showCreateModal" class="modal-overlay" @click.self="showCreateModal = false">
        <div class="modal-card">
          <header class="modal-head">
            <h3>登记告警规则</h3>
            <button class="btn ghost" type="button" @click="showCreateModal = false">&times;</button>
          </header>
          <form class="modal-body" @submit.prevent="submitCreate">
            <label v-for="field in columns.slice(0, 3)" :key="field" class="modal-field">
              <span>{{ field }}</span>
              <input v-model="createFields[field]" :placeholder="`请输入${field}`" required />
            </label>
            <footer class="modal-foot">
              <button class="btn" type="button" @click="showCreateModal = false">取消</button>
              <button class="btn primary" type="submit">提交登记</button>
            </footer>
          </form>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/alert'
const columns = ["规则编号", "告警名称", "监控指标", "阈值条件", "告警级别", "通知方式", "静默时段", "规则状态"]
const actions = ["保存配置", "启用规则", "停用规则"]
const statuses = ["草稿", "已配置", "生效中", "已停用"]
const stats = [{"label": "生效中规则", "value": 0}, {"label": "草稿规则", "value": 0}, {"label": "停用规则", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const showCreateModal = ref(false)
const createFields = ref<Record<string, string>>({})
const evalColumns = ["判定编号", "规则编号", "统计月份", "快照编号", "输入批次", "指标金额", "阈值条件", "判定结果", "变化说明", "判定时间"]
const evalRows = ref<Row[]>([])
const evalRuleFilter = ref('')
const evalMonthFilter = ref('')

function updateStats() {
  const data = rows.value
  stats.length > 0 && (stats[0].value = data.filter((r: Row) => r.status === statuses[1] || r.pending).length)
  stats.length > 1 && (stats[1].value = data.filter((r: Row) => r.status && !r.pending && !r.abnormal).length)
  stats.length > 2 && (stats[2].value = data.filter((r: Row) => r.abnormal).length)
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = ''
  createFields.value = {}
  showCreateModal.value = true
}

async function submitCreate() {
  errorMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: createFields.value }),
    })
    if (!response.ok) {
      const data = await response.json()
      throw new Error(data.message || '登记失败')
    }
    showCreateModal.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    if (!response.ok) {
      throw new Error('智能告警动作未生效，请稍后重试')
    }
    await reload()
    await loadEvaluations()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '智能告警操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('告警规则列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    updateStats()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '智能告警列表读取失败'
  }
}

async function loadEvaluations() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (evalRuleFilter.value.trim()) {
    params.set('rule', evalRuleFilter.value.trim())
  }
  if (evalMonthFilter.value.trim()) {
    params.set('month', evalMonthFilter.value.trim())
  }
  try {
    const response = await request(`${ENDPOINT}/evaluations?${params.toString()}`)
    if (!response.ok) {
      throw new Error('告警判定记录读取失败')
    }
    const payload = await response.json()
    evalRows.value = payload.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '告警判定记录读取失败'
  }
}

function resetEvalFilters() {
  evalRuleFilter.value = ''
  evalMonthFilter.value = ''
  void loadEvaluations()
}

onMounted(() => {
  void reload()
  void loadEvaluations()
})
</script>

<style scoped>
.panel {
  margin-top: 20px;
}
.panel-title {
  font-size: 15px;
  margin: 0 0 4px;
}
.panel-desc {
  color: var(--muted);
  font-size: 12px;
  margin: 0 0 10px;
}
.triggered-text {
  color: #b42318;
}
</style>

