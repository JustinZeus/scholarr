<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(
  defineProps<{
    size?: "sm" | "md" | "lg" | "xl";
  }>(),
  {
    size: "md",
  },
);

const sizeClass = computed(() => {
  if (props.size === "sm") {
    return "h-7 w-7";
  }
  if (props.size === "lg") {
    return "h-10 w-10";
  }
  if (props.size === "xl") {
    return "h-14 w-14";
  }
  return "h-7 w-7";
});

const logoMaskStyle: Record<string, string> = {
  "--brand-logo-mask": "url(/scholar_logo.png)",
};
</script>

<template>
  <span
    :class="['brand-logo-mark', sizeClass]"
    :style="logoMaskStyle"
    aria-hidden="true"
  />
</template>

<style scoped>
.brand-logo-mark {
  display: inline-block;
  flex-shrink: 0;
  background-color: rgb(var(--color-brand-700));
  -webkit-mask-image: var(--brand-logo-mask);
  mask-image: var(--brand-logo-mask);
  -webkit-mask-position: center;
  mask-position: center;
  -webkit-mask-repeat: no-repeat;
  mask-repeat: no-repeat;
  -webkit-mask-size: contain;
  mask-size: contain;
}
</style>
