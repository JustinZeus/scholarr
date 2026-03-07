<script setup lang="ts">
defineProps<{
  baselineCompleted: boolean;
  lastRunStatus: string | null;
}>();
</script>

<template>
  <span
    v-if="!baselineCompleted"
    class="ml-1.5 inline-flex items-center rounded-full bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 ring-1 ring-inset ring-amber-600/20 dark:bg-amber-950 dark:text-amber-400 dark:ring-amber-400/20"
    title="This scholar hasn't been scraped yet. Publications will appear after the next run."
  >Pending</span>
  <span
    v-if="lastRunStatus === 'failed'"
    class="ml-1.5 inline-flex items-center rounded-full bg-red-50 px-1.5 py-0.5 text-[10px] font-medium text-red-700 ring-1 ring-inset ring-red-600/20 dark:bg-red-950 dark:text-red-400 dark:ring-red-400/20"
    title="The last scrape run for this scholar failed."
  >Failed</span>
  <span
    v-else-if="lastRunStatus === 'partial'"
    class="ml-1.5 inline-flex items-center rounded-full bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 ring-1 ring-inset ring-amber-600/20 dark:bg-amber-950 dark:text-amber-400 dark:ring-amber-400/20"
    title="The last scrape run for this scholar completed with partial results."
  >Partial</span>
  <span
    v-else-if="lastRunStatus === 'success'"
    class="ml-1.5 inline-flex items-center rounded-full bg-green-50 px-1.5 py-0.5 text-[10px] font-medium text-green-700 ring-1 ring-inset ring-green-600/20 dark:bg-green-950 dark:text-green-400 dark:ring-green-400/20"
    title="The last scrape run for this scholar completed successfully."
  >OK</span>
</template>
