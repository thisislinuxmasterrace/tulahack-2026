<script setup lang="ts">
import type { RedactionStat } from '../../mocks/demoSession'

defineProps<{
  rows: RedactionStat[]
}>()
</script>

<template>
  <div class="report">
    <table class="report__table">
      <thead>
        <tr>
          <th scope="col">Тип данных</th>
          <th scope="col" class="report__num">Найдено</th>
          <th scope="col">Примеры (маскирование)</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.category">
          <td>{{ row.label }}</td>
          <td class="report__num">{{ row.count }}</td>
          <td class="report__ex">
            <span v-for="(ex, i) in row.examples" :key="i" class="report__pill">{{ ex }}</span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.report {
  overflow-x: auto;
}

.report__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.88rem;
}

th,
td {
  text-align: left;
  padding: 0.55rem 0.65rem;
  border-bottom: 1px solid var(--border);
  vertical-align: top;
}

th {
  color: var(--text-muted);
  font-weight: 600;
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

tbody tr:last-child td {
  border-bottom: none;
}

.report__num {
  width: 5rem;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}

.report__ex {
  color: var(--text-muted);
}

.report__pill {
  display: inline-block;
  margin: 0 0.35rem 0.25rem 0;
  padding: 0.15rem 0.45rem;
  border-radius: 6px;
  background: var(--bg-muted);
  font-family: var(--font-mono);
  font-size: 0.82rem;
}
</style>
