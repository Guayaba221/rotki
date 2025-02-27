<script setup lang="ts">
import { Section } from '@/types/status';
import { IgnoreActionType } from '@/types/history/ignored';
import { SavedFilterLocation } from '@/types/filtering';
import { useStatusStore } from '@/store/status';
import { useHistoryAutoRefresh } from '@/composables/history/auto-refresh';
import { useIgnore } from '@/composables/history';
import { usePaginationFilters } from '@/composables/use-pagination-filter';
import { useCommonTableProps } from '@/composables/use-common-table-props';
import { useAssetMovements } from '@/composables/history/asset-movements';
import { type Filters, type Matcher, useAssetMovementFilters } from '@/composables/filters/asset-movement';
import UpgradeRow from '@/components/history/UpgradeRow.vue';
import DepositWithdrawalDetails from '@/components/history/deposits-withdrawals/DepositWithdrawalDetails.vue';
import DateDisplay from '@/components/display/DateDisplay.vue';
import AmountDisplay from '@/components/display/amount/AmountDisplay.vue';
import AssetDetails from '@/components/helper/AssetDetails.vue';
import BadgeDisplay from '@/components/history/BadgeDisplay.vue';
import LocationDisplay from '@/components/history/LocationDisplay.vue';
import IgnoredInAcountingIcon from '@/components/history/IgnoredInAcountingIcon.vue';
import CollectionHandler from '@/components/helper/CollectionHandler.vue';
import IgnoreButtons from '@/components/history/IgnoreButtons.vue';
import TableFilter from '@/components/table-filter/TableFilter.vue';
import TableStatusFilter from '@/components/helper/TableStatusFilter.vue';
import HistoryTableActions from '@/components/history/HistoryTableActions.vue';
import NavigatorLink from '@/components/helper/NavigatorLink.vue';
import CardTitle from '@/components/typography/CardTitle.vue';
import TablePageLayout from '@/components/layout/TablePageLayout.vue';
import type { DataTableColumn } from '@rotki/ui-library';
import type { Writeable } from '@rotki/common';
import type { AssetMovementEntry, AssetMovementRequestPayload } from '@/types/history/asset-movements';

const props = withDefaults(
  defineProps<{
    locationOverview?: string;
  }>(),
  {
    locationOverview: '',
  },
);

const { t } = useI18n();

const { locationOverview } = toRefs(props);

const showIgnoredAssets = ref<boolean>(false);

const mainPage = computed(() => get(locationOverview) === '');

const tableHeaders = computed<DataTableColumn<AssetMovementEntry>[]>(() => {
  const overview = !get(mainPage);
  const headers: DataTableColumn<AssetMovementEntry>[] = [
    {
      cellClass: !overview ? '!p-0' : '!w-0 !max-w-[4rem]',
      class: !overview ? '!p-0' : '',
      key: 'ignoredInAccounting',
      label: '',
    },
    {
      align: 'center',
      cellClass: '!py-1',
      class: '!w-[7.5rem]',
      key: 'location',
      label: t('common.location'),
      sortable: true,
    },
    {
      align: overview ? 'start' : 'center',
      cellClass: overview ? '!pl-0' : 'py-1',
      class: `text-no-wrap${overview ? ' !pl-0' : ''}`,
      key: 'category',
      label: t('deposits_withdrawals.headers.action'),
      sortable: true,
    },
    {
      cellClass: '!py-1',
      key: 'asset',
      label: t('common.asset'),
    },
    {
      align: 'end',
      key: 'amount',
      label: t('common.amount'),
      sortable: true,
    },
    {
      align: 'end',
      key: 'fee',
      label: t('deposits_withdrawals.headers.fee'),
      sortable: true,
    },
    {
      key: 'timestamp',
      label: t('common.datetime'),
      sortable: true,
    },
  ];

  if (overview)
    headers.splice(1, 1);

  return headers;
});

const extraParams = computed(() => ({
  excludeIgnoredAssets: !get(showIgnoredAssets),
}));

const { fetchAssetMovements, refreshAssetMovements } = useAssetMovements();
const { expanded, selected } = useCommonTableProps<AssetMovementEntry>();

const {
  fetchData,
  filters,
  isLoading,
  matchers,
  pagination,
  setPage,
  sort,
  state: assetMovements,
} = usePaginationFilters<
  AssetMovementEntry,
  AssetMovementRequestPayload,
  Filters,
  Matcher
>(fetchAssetMovements, {
  extraParams,
  filterSchema: useAssetMovementFilters,
  history: get(mainPage) ? 'router' : false,
  locationOverview,
  onUpdateFilters(query) {
    set(showIgnoredAssets, query.excludeIgnoredAssets === 'false');
  },
  requestParams: computed<Partial<AssetMovementRequestPayload>>(() => {
    const params: Writeable<Partial<AssetMovementRequestPayload>> = {};
    const location = get(locationOverview);

    if (location)
      params.location = toSnakeCase(location);

    return params;
  }),
});

useHistoryAutoRefresh(fetchData);

const { ignore } = useIgnore({
  actionType: IgnoreActionType.MOVEMENTS,
  toData: (item: AssetMovementEntry) => item.identifier,
}, selected, () => fetchData());

const { isLoading: isSectionLoading } = useStatusStore();
const loading = isSectionLoading(Section.ASSET_MOVEMENT);

const value = computed({
  get: () => {
    if (!get(mainPage))
      return undefined;

    return get(selected).map(({ identifier }: AssetMovementEntry) => identifier);
  },
  set: (values) => {
    set(
      selected,
      get(assetMovements).data.filter(({ identifier }: AssetMovementEntry) => values?.includes(identifier)),
    );
  },
});

function getItemClass(item: AssetMovementEntry) {
  return item.ignoredInAccounting ? 'opacity-50' : '';
}

onMounted(async () => {
  await fetchData();
  await refreshAssetMovements();
});

watch(loading, async (isLoading, wasLoading) => {
  if (!isLoading && wasLoading)
    await fetchData();
});
</script>

<template>
  <TablePageLayout
    :hide-header="!mainPage"
    :child="!mainPage"
    :title="[t('navigation_menu.history'), t('deposits_withdrawals.title')]"
  >
    <template #buttons>
      <RuiTooltip :open-delay="400">
        <template #activator>
          <RuiButton
            variant="outlined"
            color="primary"
            :loading="loading"
            @click="refreshAssetMovements(true)"
          >
            <template #prepend>
              <RuiIcon name="refresh-line" />
            </template>
            {{ t('common.refresh') }}
          </RuiButton>
        </template>
        {{ t('deposits_withdrawals.refresh_tooltip') }}
      </RuiTooltip>
    </template>

    <RuiCard>
      <template
        v-if="!mainPage"
        #header
      >
        <CardTitle>
          <NavigatorLink :to="{ path: '/history/deposits-withdrawals' }">
            {{ t('deposits_withdrawals.title') }}
          </NavigatorLink>
        </CardTitle>
      </template>

      <HistoryTableActions v-if="mainPage">
        <template #filter>
          <TableStatusFilter>
            <div class="py-1 max-w-[16rem]">
              <RuiSwitch
                v-model="showIgnoredAssets"
                class="p-4"
                color="primary"
                hide-details
                :label="t('transactions.filter.show_ignored_assets')"
              />
            </div>
          </TableStatusFilter>
          <TableFilter
            v-model:matches="filters"
            class="min-w-full sm:min-w-[26rem]"
            :matchers="matchers"
            :location="SavedFilterLocation.HISTORY_DEPOSITS_WITHDRAWALS"
          />
        </template>
        <IgnoreButtons
          :disabled="selected.length === 0 || loading"
          @ignore="ignore($event)"
        />
        <div
          v-if="selected.length > 0"
          class="flex flex-row items-center gap-2"
        >
          {{ t('deposits_withdrawals.selected', { count: selected.length }) }}
          <RuiButton
            variant="text"
            size="sm"
            @click="selected = []"
          >
            {{ t('common.actions.clear_selection') }}
          </RuiButton>
        </div>
      </HistoryTableActions>

      <CollectionHandler
        :collection="assetMovements"
        @set-page="setPage($event)"
      >
        <template #default="{ data, limit, total, showUpgradeRow }">
          <RuiDataTable
            v-model="value"
            v-model:expanded="expanded"
            v-model:sort.external="sort"
            v-model:pagination.external="pagination"
            :cols="tableHeaders"
            :rows="data"
            :loading="isLoading || loading"
            :loading-text="t('deposits_withdrawals.loading')"
            class="asset-movements"
            outlined
            row-attr="identifier"
            single-expand
            sticky-header
            :item-class="getItemClass"
          >
            <template #item.ignoredInAccounting="{ row }">
              <IgnoredInAcountingIcon v-if="row.ignoredInAccounting" />
              <span v-else />
            </template>
            <template #item.location="{ row }">
              <LocationDisplay :identifier="row.location" />
            </template>
            <template #item.category="{ row }">
              <BadgeDisplay :color="row.category.toLowerCase() === 'withdrawal' ? 'grey' : 'green'">
                {{ row.category }}
              </BadgeDisplay>
            </template>
            <template #item.asset="{ row }">
              <AssetDetails
                opens-details
                :asset="row.asset"
              />
            </template>
            <template #item.amount="{ row }">
              <AmountDisplay
                class="deposits-withdrawals__movement__amount"
                :value="row.amount"
              />
            </template>
            <template #item.fee="{ row }">
              <AmountDisplay
                class="deposits-withdrawals__trade__fee"
                :asset="row.feeAsset"
                :value="row.fee"
              />
            </template>
            <template #item.timestamp="{ row }">
              <DateDisplay :timestamp="row.timestamp" />
            </template>
            <template #expanded-item="{ row }">
              <DepositWithdrawalDetails :item="row" />
            </template>
            <template
              v-if="showUpgradeRow"
              #body.prepend="{ colspan }"
            >
              <UpgradeRow
                :limit="limit"
                :total="total"
                :colspan="colspan"
                :label="t('deposits_withdrawals.label')"
              />
            </template>
          </RuiDataTable>
        </template>
      </CollectionHandler>
    </RuiCard>
  </TablePageLayout>
</template>
