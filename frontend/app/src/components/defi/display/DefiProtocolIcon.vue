<script setup lang="ts">
import { DefiProtocol } from '@/types/modules';
import AppImage from '@/components/common/AppImage.vue';

const props = withDefaults(
  defineProps<{
    protocol: DefiProtocol;
    mode?: 'icon' | 'label' | 'both';
  }>(),
  { mode: 'both' },
);
const protocol = toRef(props, 'protocol');

const icon = computed(() => {
  const defiProtocol = get(protocol);
  if (defiProtocol.endsWith('_v2'))
    return defiProtocol.replace('_v2', '');

  if (defiProtocol.startsWith('makerdao'))
    return 'makerdao';

  return defiProtocol;
});

const name = computed(() => {
  const defiProtocol = get(protocol);
  if (defiProtocol === DefiProtocol.MAKERDAO_DSR)
    return 'MakerDAO DSR';
  else if (defiProtocol === DefiProtocol.MAKERDAO_VAULTS)
    return 'MakerDAO Vaults';
  else if (defiProtocol === DefiProtocol.YEARN_VAULTS)
    return 'yearn.finance Vaults';
  else if (defiProtocol === DefiProtocol.YEARN_VAULTS_V2)
    return 'yearn.finance Vaults v2';

  return defiProtocol;
});
</script>

<template>
  <div
    class="flex flex-row items-center"
    :class="mode === 'icon' ? 'justify-center' : null"
  >
    <RuiTooltip
      :popper="{ placement: 'top' }"
      :disabled="mode !== 'icon'"
      :open-delay="400"
    >
      <template #activator>
        <AppImage
          v-if="mode === 'icon' || mode === 'both'"
          contain
          max-width="32px"
          max-height="32px"
          :class="{
            'mr-2': mode !== 'icon',
            [$style.icon]: true,
          }"
          :src="`./assets/images/protocols/${icon}.svg`"
        />
        <span
          v-if="mode === 'label' || mode === 'both'"
          class="text-rui-text-secondary"
          :class="$style.label"
        >
          {{ toSentenceCase(name) }}
        </span>
      </template>
      <span>
        {{ toSentenceCase(name) }}
      </span>
    </RuiTooltip>
  </div>
</template>

<style lang="scss" module>
.icon {
  max-width: 30px;
}

.label {
  font-size: 12px;
}
</style>
