<template>
  <section class="page" data-module="metric_run">
    <header class="page-head">
      <div>
        <h2>月度取数管理</h2>
        <p class="page-desc">从已接入数据集读取交易，按自然月聚合并发布指标结果快照，供月末核账与智能告警判定使用。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openFetch">月度取数</button>
        <button class="btn" type="button" @click="openCorrection">交易更正</button>
        <button class="btn" type="button" @click="exportRows">导出快照清单</button>
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
          <td :colspan="columns.length + 1" class="empty-state">暂无指标结果快照，可先执行月度取数</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条指标结果快照</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      <span v-if="noticeMessage" class="success-text">{{ noticeMessage }}</span>
    </footer>

    <section class="panel">
      <h3 class="panel-title">核账双月汇总</h3>
      <p class="panel-desc">提交更正前先对齐两个受影响月份的已发布金额；同一交易在一份结果中只归入一个月份。</p>
      <form class="filter-bar" @submit.prevent="loadSummary">
        <label class="filter-item">
          <span>指标编号</span>
          <input v-model="summaryMetric" placeholder="如 METR-0003" />
        </label>
        <label class="filter-item">
          <span>月份一</span>
          <input v-model="summaryMonthA" placeholder="如 2026-09" />
        </label>
        <label class="filter-item">
          <span>月份二</span>
          <input v-model="summaryMonthB" placeholder="如 2026-10" />
        </label>
        <button class="btn" type="submit">查询汇总</button>
      </form>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in summaryColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in summaryRows" :key="String(row['统计月份'])">
            <td v-for="column in summaryColumns" :key="column">{{ row[column] ?? '—' }}</td>
          </tr>
          <tr v-if="!summaryRows.length">
            <td :colspan="summaryColumns.length" class="empty-state">输入指标编号与两个月份后查询</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="panel">
      <h3 class="panel-title">交易源记录</h3>
      <p class="panel-desc">核对一笔交易当前归入哪个月份、属于哪个输入批次；被更正的旧记录会标记为已更正。</p>
      <form class="filter-bar" @submit.prevent="loadTransactions">
        <label class="filter-item">
          <span>交易编号</span>
          <input v-model="txnFilter" placeholder="如 TXN-1004" />
        </label>
        <button class="btn" type="submit">查询交易</button>
        <button class="btn ghost" type="button" @click="resetTxnFilter">显示全部</button>
      </form>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in txnColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in txnRows" :key="String(row.id)">
            <td v-for="column in txnColumns" :key="column">{{ row[column] ?? '—' }}</td>
          </tr>
          <tr v-if="!txnRows.length">
            <td :colspan="txnColumns.length" class="empty-state">暂无交易源记录</td>
          </tr>
        </tbody>
      </table>
    </section>

    <Teleport to="body">
      <div v-if="showFetchModal" class="modal-overlay" @click.self="showFetchModal = false">
        <div class="modal-card">
          <header class="modal-head">
            <h3>月度取数</h3>
            <button class="btn ghost" type="button" @click="showFetchModal = false">&times;</button>
          </header>
          <form class="modal-body" @submit.prevent="submitFetch">
            <label class="modal-field">
              <span>指标编号</span>
              <input v-model="fetchFields['指标编号']" placeholder="如 METR-0003" required />
            </label>
            <label class="modal-field">
              <span>统计月份</span>
              <input v-model="fetchFields['统计月份']" placeholder="如 2026-10" required />
            </label>
            <label class="modal-field">
              <span>数据集编号（留空则取第一个已接入数据集）</span>
              <input v-model="fetchFields['数据集编号']" placeholder="如 DATA-0002" />
            </label>
            <footer class="modal-foot">
              <button class="btn" type="button" @click="showFetchModal = false">取消</button>
              <button class="btn primary" type="submit">执行取数</button>
            </footer>
          </form>
        </div>
      </div>
    </Teleport>

    <Teleport to="body">
      <div v-if="showCorrectionModal" class="modal-overlay" @click.self="showCorrectionModal = false">
        <div class="modal-card">
          <header class="modal-head">
            <h3>交易更正</h3>
            <button class="btn ghost" type="button" @click="showCorrectionModal = false">&times;</button>
          </header>
          <form class="modal-body" @submit.prevent="submitCorrection">
            <label class="modal-field">
              <span>交易编号</span>
              <input v-model="correctionFields['交易编号']" placeholder="如 TXN-1004" required />
            </label>
            <label class="modal-field">
              <span>新业务日期</span>
              <input v-model="correctionFields['新业务日期']" placeholder="如 2026-09-03" required />
            </label>
            <label class="modal-field">
              <span>实付金额（留空则沿用原金额）</span>
              <input v-model="correctionFields['实付金额']" placeholder="如 4500" />
            </label>
            <footer class="modal-foot">
              <button class="btn" type="button" @click="showCorrectionModal = false">取消</button>
              <button class="btn primary" type="submit">提交更正</button>
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

const ENDPOINT = '/api/metric_run'
const columns = ["快照编号", "指标编号", "统计月份", "口径版本", "输入批次", "指标金额", "交易笔数", "快照状态"]
const actions = ["重新取数"]
const stats = [{ label: "已发布快照", value: 0 }, { label: "计算失败", value: 0 }, { label: "已取代快照", value: 0 }]
const summaryColumns = ["统计月份", "快照编号", "指标金额", "交易笔数", "输入批次", "口径版本", "快照状态"]
const txnColumns = ["交易编号", "业务日期", "实付金额", "数据集编号", "输入批次", "记录状态"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = ["指标编号", "统计月份", "输入批次"]
const showFetchModal = ref(false)
const showCorrectionModal = ref(false)
const fetchFields = ref<Record<string, string>>({})
const correctionFields = ref<Record<string, string>>({})
const summaryMetric = ref('METR-0003')
const summaryMonthA = ref('2026-09')
const summaryMonthB = ref('2026-10')
const summaryRows = ref<Row[]>([])
const txnFilter = ref('')
const txnRows = ref<Row[]>([])

function updateStats() {
  const data = rows.value
  stats[0].value = data.filter((r: Row) => r.status === '已发布').length
  stats[1].value = data.filter((r: Row) => r.status === '计算失败').length
  stats[2].value = data.filter((r: Row) => r.status === '已取代').length
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openFetch() {
  errorMessage.value = ''
  noticeMessage.value = ''
  fetchFields.value = {}
  showFetchModal.value = true
}

function openCorrection() {
  errorMessage.value = ''
  noticeMessage.value = ''
  correctionFields.value = {}
  showCorrectionModal.value = true
}

async function readResult(response: Response, fallback: string) {
  const data = await response.json()
  if (!response.ok) {
    throw new Error(data.detail || data.message || fallback)
  }
  return data
}

async function submitFetch() {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: fetchFields.value }),
    })
    const data = await readResult(response, '月度取数失败')
    showFetchModal.value = false
    if (data.ok) {
      noticeMessage.value = data.message
    } else {
      errorMessage.value = data.message
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '月度取数失败'
  }
}

async function submitCorrection() {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/corrections`, {
      method: 'POST',
      body: JSON.stringify({ values: correctionFields.value }),
    })
    const data = await readResult(response, '交易更正失败')
    showCorrectionModal.value = false
    if (data.ok) {
      noticeMessage.value = data.message
    } else {
      errorMessage.value = data.message
    }
    await Promise.all([reload(), loadSummary(), loadTransactions()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '交易更正失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const data = await readResult(response, '月度取数动作未生效，请稍后重试')
    if (data.ok) {
      noticeMessage.value = data.message
    } else {
      errorMessage.value = data.message
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '月度取数操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('快照列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    updateStats()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '指标结果快照列表读取失败'
  }
}

async function loadSummary() {
  errorMessage.value = ''
  const months = [summaryMonthA.value, summaryMonthB.value].filter((item) => item.trim()).join(',')
  try {
    const response = await request(`${ENDPOINT}/summary?metric=${encodeURIComponent(summaryMetric.value)}&months=${encodeURIComponent(months)}`)
    const data = await readResult(response, '双月汇总读取失败')
    summaryRows.value = data.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '双月汇总读取失败'
  }
}

async function loadTransactions() {
  errorMessage.value = ''
  const query = txnFilter.value.trim() ? `?txn=${encodeURIComponent(txnFilter.value.trim())}` : ''
  try {
    const response = await request(`${ENDPOINT}/transactions${query}`)
    const data = await readResult(response, '交易源记录读取失败')
    txnRows.value = data.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '交易源记录读取失败'
  }
}

function resetTxnFilter() {
  txnFilter.value = ''
  void loadTransactions()
}

onMounted(() => {
  void reload()
  void loadSummary()
  void loadTransactions()
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
.success-text {
  color: #067647;
}
</style>
