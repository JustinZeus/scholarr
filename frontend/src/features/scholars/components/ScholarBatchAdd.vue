<script setup lang="ts">
import { computed, ref } from "vue";
import AppButton from "@/components/ui/AppButton.vue";
import AppCard from "@/components/ui/AppCard.vue";
import AppHelpHint from "@/components/ui/AppHelpHint.vue";
import { parseScholarTokens } from "./scholar-batch-parsing";

defineProps<{
  saving: boolean;
  loading: boolean;
}>();

const emit = defineEmits<{
  (e: "add-scholars", ids: string[]): void;
}>();

const scholarBatchInput = ref("");

const parsedTokens = computed(() => parseScholarTokens(scholarBatchInput.value));
const validIds = computed(() => parsedTokens.value.filter((t) => t.id !== null));
const invalidTokens = computed(() => parsedTokens.value.filter((t) => t.id === null));
const parsedBatchCount = computed(() => validIds.value.length);

function onSubmit(): void {
  const ids = validIds.value.map((t) => t.id!);
  if (ids.length > 0) {
    emit("add-scholars", ids);
    scholarBatchInput.value = "";
  }
}
</script>

<template>
  <AppCard class="space-y-4 xl:flex xl:min-h-0 xl:flex-col">
    <div class="space-y-1">
      <div class="flex items-center gap-1">
        <h2 class="text-lg font-semibold text-ink-primary">Add Scholar Profiles</h2>
        <AppHelpHint text="A scholar profile is a Google Scholar author page that Scholarr will monitor for publication changes." />
      </div>
      <p class="text-sm text-secondary">Paste one or more Scholar IDs or profile URLs and add them in one action.</p>
    </div>

    <form class="grid gap-3" @submit.prevent="onSubmit">
      <label class="grid gap-2 text-sm font-medium text-ink-secondary" for="scholar-batch-input">
        <span>Scholar IDs or profile URLs</span>
        <textarea
          id="scholar-batch-input"
          v-model="scholarBatchInput"
          rows="5"
          placeholder="A-UbBTPM15wL&#10;https://scholar.google.com/citations?hl=en&user=A-UbBTPM15wL"
          class="w-full rounded-lg border border-stroke-interactive bg-surface-input px-3 py-2 text-sm text-ink-primary outline-none ring-focus-ring transition placeholder:text-ink-muted focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-focus-offset disabled:cursor-not-allowed disabled:opacity-60"
        />
      </label>

      <div v-if="parsedTokens.length > 0" class="space-y-1">
        <p class="text-xs text-secondary">
          <strong class="text-ink-primary">{{ parsedBatchCount }}</strong> valid ID{{ parsedBatchCount === 1 ? "" : "s" }}
          <template v-if="invalidTokens.length > 0">
            · <span class="text-state-warning-text">{{ invalidTokens.length }} skipped</span>
          </template>
        </p>
        <ul v-if="invalidTokens.length > 0" class="space-y-0.5" data-testid="validation-errors">
          <li
            v-for="item in invalidTokens.slice(0, 5)"
            :key="item.index"
            class="text-xs text-state-warning-text"
          >
            #{{ item.index }}: {{ item.error }}
            <code class="ml-1 break-all text-ink-muted">{{ item.raw.length > 60 ? item.raw.slice(0, 57) + "..." : item.raw }}</code>
          </li>
          <li v-if="invalidTokens.length > 5" class="text-xs text-state-warning-text">
            +{{ invalidTokens.length - 5 }} more skipped
          </li>
        </ul>
      </div>
      <div v-else class="text-xs text-secondary">
        Parsed IDs: <strong class="text-ink-primary">0</strong>
      </div>

      <div class="flex flex-wrap items-center justify-end gap-2">
        <AppButton type="submit" :disabled="saving || loading || parsedBatchCount === 0">
          {{ saving ? "Adding..." : "Add scholars" }}
        </AppButton>
      </div>
    </form>
  </AppCard>
</template>
