<script setup lang="ts">
import SuccessDisplay from '@/components/display/SuccessDisplay.vue';
import EventDecodingStatusDetails from '@/components/history/events/EventDecodingStatusDetails.vue';
import TransactionQueryStatusSteps from '@/components/history/events/tx/query-status/TransactionQueryStatusSteps.vue';
import TransactionQueryStatusDetails
  from '@/components/history/events/tx/query-status/TransactionQueryStatusDetails.vue';
import TransactionQueryStatusCurrent
  from '@/components/history/events/tx/query-status/TransactionQueryStatusCurrent.vue';
import HistoryEventsQueryStatusDetails
  from '@/components/history/events/query-status/HistoryEventsQueryStatusDetails.vue';
import HistoryEventsQueryStatusCurrent
  from '@/components/history/events/query-status/HistoryEventsQueryStatusCurrent.vue';
import type { Blockchain } from '@rotki/common';
import type {
  EvmTransactionQueryData,
  EvmUnDecodedTransactionsData,
  HistoryEventsQueryData,
} from '@/types/websocket-messages';

withDefaults(
  defineProps<{
    onlyChains?: Blockchain[];
    locations?: string[];
    transactions?: EvmTransactionQueryData[];
    decodingStatus: EvmUnDecodedTransactionsData[];
    events?: HistoryEventsQueryData[];
    getKey: (item: EvmTransactionQueryData | HistoryEventsQueryData) => string;
  }>(),
  {
    events: () => [],
    locations: () => [],
    onlyChains: () => [],
    transactions: () => [],
  },
);

const { t } = useI18n();
</script>

<template>
  <RuiDialog max-width="1200">
    <template #activator="{ attrs }">
      <RuiTooltip
        :popper="{ placement: 'top' }"
        :open-delay="400"
        class="ml-4"
      >
        <template #activator>
          <RuiButton
            variant="text"
            icon
            class="mt-1"
            size="sm"
            v-bind="attrs"
          >
            <RuiIcon name="information-line" />
          </RuiButton>
        </template>
        {{ t('common.details') }}
      </RuiTooltip>
    </template>
    <template #default="{ close }">
      <RuiCard>
        <template #custom-header>
          <div class="flex justify-between gap-4 px-4 py-2 items-center border-b border-default">
            <h5 class="text-h6 text-rui-text">
              {{ t('transactions.query_all.modal_title') }}
            </h5>
            <RuiButton
              icon
              variant="text"
              @click="close()"
            >
              <RuiIcon name="close-line" />
            </RuiButton>
          </div>
        </template>

        <div :class="$style.content">
          <div>
            <h6 class="text-body-1 font-medium">
              {{ t('transactions.query_status_events.title') }}
            </h6>
            <HistoryEventsQueryStatusCurrent
              :locations="locations"
              class="text-subtitle-2 text-rui-text-secondary mt-2"
            />
            <div
              v-for="item in events"
              :key="getKey(item)"
              class="py-1"
            >
              <HistoryEventsQueryStatusDetails :item="item" />
            </div>
          </div>

          <div>
            <h6 class="text-body-1 font-medium">
              {{ t('transactions.query_status.title') }}
            </h6>
            <TransactionQueryStatusCurrent
              :only-chains="onlyChains"
              class="text-subtitle-2 text-rui-text-secondary my-2"
            />
            <div
              v-for="item in transactions"
              :key="getKey(item)"
              class="py-1"
            >
              <TransactionQueryStatusDetails :item="item" />
              <TransactionQueryStatusSteps
                :item="item"
                :class="$style.stepper"
              />
            </div>
          </div>

          <div>
            <h6 class="text-body-1 font-medium mb-2">
              {{ t('transactions.events_decoding.title') }}
            </h6>
            <template v-if="decodingStatus.length > 0">
              <EventDecodingStatusDetails
                v-for="item in decodingStatus"
                :key="item.chain"
                class="py-1"
                :item="item"
              />
            </template>
            <template v-else>
              <div class="flex gap-2">
                <SuccessDisplay
                  success
                  size="22"
                />
                {{ t('transactions.events_decoding.decoded.true') }}
              </div>
            </template>
          </div>
        </div>
        <template #footer>
          <div class="w-full" />
          <RuiButton
            color="primary"
            @click="close()"
          >
            {{ t('common.actions.close') }}
          </RuiButton>
        </template>
      </RuiCard>
    </template>
  </RuiDialog>
</template>

<style module lang="scss">
.content {
  @apply overflow-y-auto -mx-4 px-4 pb-4 flex flex-col gap-8;
  max-height: calc(90vh - 11.875rem);
  min-height: 50vh;

  .stepper {
    @apply overflow-hidden #{!important};
  }
}
</style>
