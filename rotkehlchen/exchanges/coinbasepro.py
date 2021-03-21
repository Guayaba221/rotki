import binascii
import csv
import hashlib
import hmac
import json
import logging
import time
from base64 import b64decode, b64encode
from collections import defaultdict
from http import HTTPStatus
from json.decoder import JSONDecodeError
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any, DefaultDict, Dict, List, Optional, Tuple, Union
from urllib.parse import urlencode

import gevent
import requests
from typing_extensions import Literal

from rotkehlchen.accounting.structures import Balance
from rotkehlchen.assets.asset import Asset
from rotkehlchen.assets.converters import asset_from_coinbase
from rotkehlchen.constants.misc import ZERO
from rotkehlchen.constants.assets import A_ETH
from rotkehlchen.constants.timing import QUERY_RETRY_TIMES
from rotkehlchen.errors import (
    DeserializationError,
    RemoteError,
    UnknownAsset,
    UnprocessableTradePair,
    UnsupportedAsset,
)
from rotkehlchen.exchanges.data_structures import AssetMovement, MarginPosition, Trade
from rotkehlchen.exchanges.exchange import ExchangeInterface, ExchangeQueryBalances
from rotkehlchen.inquirer import Inquirer
from rotkehlchen.logging import RotkehlchenLogsAdapter
from rotkehlchen.serialization.deserialize import (
    deserialize_asset_amount,
    deserialize_asset_amount_force_positive,
    deserialize_asset_movement_category,
    deserialize_fee,
    deserialize_price,
    deserialize_timestamp_from_date,
    deserialize_trade_type,
)
from rotkehlchen.typing import (
    ApiKey,
    ApiSecret,
    AssetMovementCategory,
    Fee,
    Location,
    Timestamp,
    TradePair,
    AssetType,
)
from rotkehlchen.user_messages import MessagesAggregator
from rotkehlchen.utils.interfaces import cache_response_timewise, protect_with_lock
from rotkehlchen.utils.serialization import rlk_jsonloads_dict, rlk_jsonloads_list

if TYPE_CHECKING:
    from rotkehlchen.db.dbhandler import DBHandler

logger = logging.getLogger(__name__)
log = RotkehlchenLogsAdapter(logger)


COINBASEPRO_PAGINATION_LIMIT = 100  # default + max limit
SECS_TO_WAIT_FOR_REPORT = 300
MINS_TO_WAIT_FOR_REPORT = SECS_TO_WAIT_FOR_REPORT / 60


def coinbasepro_to_worldpair(product: str) -> TradePair:
    """Turns a coinbasepro product into our trade pair format

    - Can raise UnprocessableTradePair if product is in unexpected format
    - Case raise UnknownAsset if any of the pair assets are not known to Rotki
    """
    parts = product.split('-')
    if len(parts) != 2:
        raise UnprocessableTradePair(product)

    base_asset = Asset(parts[0])
    quote_asset = Asset(parts[1])

    return TradePair(f'{base_asset.identifier}_{quote_asset.identifier}')


class CoinbaseProPermissionError(Exception):
    pass


class Coinbasepro(ExchangeInterface):  # lgtm[py/missing-call-to-init]

    def __init__(
            self,
            api_key: ApiKey,
            secret: ApiSecret,
            database: 'DBHandler',
            msg_aggregator: MessagesAggregator,
            passphrase: str,
    ):
        super().__init__('coinbasepro', api_key, secret, database)
        self.base_uri = 'https://api.pro.coinbase.com'
        self.msg_aggregator = msg_aggregator
        self.account_to_currency: Optional[Dict[str, Asset]] = None

        self.session.headers.update({
            'Content-Type': 'Application/JSON',
            'CB-ACCESS-KEY': self.api_key,
            'CB-ACCESS-PASSPHRASE': passphrase,
        })

    def validate_api_key(self) -> Tuple[bool, str]:
        """Validates that the Coinbase Pro API key is good for usage in Rotki

        Makes sure that the following permissions are given to the key:
        - View
        """
        try:
            self._api_query('accounts')
        except CoinbaseProPermissionError:
            msg = (
                'Provided Coinbase Pro API key needs to have "View" permission activated. '
                'Please log into your coinbase account and create a key with '
                'the required permissions.'
            )
            return False, msg
        except RemoteError as e:
            error = str(e)
            if 'Invalid Passphrase' in error:
                msg = (
                    'The passphrase for the given API key does not match. Please '
                    'create a key with the preset passphrase "rotki"'
                )
                return False, msg

            return False, error

        return True, ''

    def _api_query(
            self,
            endpoint: str,
            request_method: Literal['GET', 'POST'] = 'GET',
            options: Optional[Dict[str, Any]] = None,
            query_options: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Any], Optional[str]]:
        """Performs a coinbase PRO API Query for endpoint

        You can optionally provide extra arguments to the endpoint via the options argument.

        Returns a tuple of the result and optional pagination cursor.

        Raises RemoteError if something went wrong with connecting or reading from the exchange
        Raises CoinbaseProPermissionError if the API Key does not have sufficient
        permissions for the endpoint
        """
        request_url = f'/{endpoint}'

        timestamp = str(int(time.time()))
        if options:
            stringified_options = json.dumps(options, separators=(',', ':'))
        else:
            stringified_options = ''
            options = {}

        if query_options:
            request_url += '?' + urlencode(query_options)

        message = timestamp + request_method + request_url + stringified_options
        log.debug(
            'Coinbase Pro API query',
            request_method=request_method,
            request_url=request_url,
            options=options,
        )

        if 'products' not in endpoint:
            try:
                signature = hmac.new(
                    b64decode(self.secret),
                    message.encode(),
                    hashlib.sha256,
                ).digest()
            except binascii.Error as e:
                raise RemoteError('Provided API Secret is invalid') from e

            self.session.headers.update({
                'CB-ACCESS-SIGN': b64encode(signature).decode('utf-8'),
                'CB-ACCESS-TIMESTAMP': timestamp,
            })

        retries_left = QUERY_RETRY_TIMES
        while retries_left > 0:
            full_url = self.base_uri + request_url
            try:
                response = self.session.request(
                    request_method.lower(),
                    full_url,
                    data=stringified_options,
                )
            except requests.exceptions.RequestException as e:
                raise RemoteError(
                    f'Coinbase Pro {request_method} query at '
                    f'{full_url} connection error: {str(e)}',
                ) from e

            if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
                # Backoff a bit by sleeping. Sleep more, the more retries have been made
                gevent.sleep(QUERY_RETRY_TIMES / retries_left)
                retries_left -= 1
            else:
                # get out of the retry loop, we did not get 429 complaint
                break

        json_ret: Union[List[Any], Dict[str, Any]]
        if response.status_code == HTTPStatus.BAD_REQUEST:
            json_ret = rlk_jsonloads_dict(response.text)
            if json_ret['message'] == 'invalid signature':
                raise CoinbaseProPermissionError(
                    f'While doing {request_method} at {endpoint} endpoint the API secret '
                    f'created an invalid signature.',
                )
            # else do nothing and a generic remote error will be thrown below

        elif response.status_code == HTTPStatus.FORBIDDEN:
            raise CoinbaseProPermissionError(
                f'API key does not have permission for {endpoint}',
            )

        if response.status_code != HTTPStatus.OK:
            raise RemoteError(
                f'Coinbase Pro {request_method} query at {full_url} responded with error '
                f'status code: {response.status_code} and text: {response.text}',
            )

        try:
            json_ret = rlk_jsonloads_list(response.text)
        except JSONDecodeError as e:
            raise RemoteError(
                f'Coinbase Pro {request_method} query at {full_url} '
                f'returned invalid JSON response: {response.text}',
            ) from e

        return json_ret, response.headers.get('cb-after', None)

    def create_or_return_account_to_currency_map(self) -> Dict[str, Asset]:
        if self.account_to_currency is not None:
            return self.account_to_currency

        accounts, _ = self._api_query('accounts')
        self.account_to_currency = {}
        for account in accounts:
            try:
                asset = asset_from_coinbase(account['currency'])
                self.account_to_currency[account['id']] = asset
            except UnsupportedAsset as e:
                self.msg_aggregator.add_warning(
                    f'Found coinbase pro account with unsupported asset '
                    f'{e.asset_name}. Ignoring it.',
                )
                continue
            except UnknownAsset as e:
                self.msg_aggregator.add_warning(
                    f'Found coinbase pro account result with unknown asset '
                    f'{e.asset_name}. Ignoring it.',
                )
                continue
            except KeyError as e:
                self.msg_aggregator.add_warning(
                    f'Found coinbase pro account entry with missing {str(e)} field. '
                    f'Ignoring it',
                )
                continue

        return self.account_to_currency

    @protect_with_lock()
    @cache_response_timewise()
    def query_balances(self) -> ExchangeQueryBalances:
        try:
            accounts, _ = self._api_query('accounts')
        except (CoinbaseProPermissionError, RemoteError) as e:
            msg = f'Coinbase Pro API request failed. {str(e)}'
            log.error(msg)
            return None, msg

        assets_balance: DefaultDict[Asset, Balance] = defaultdict(Balance)
        for account in accounts:
            try:
                amount = deserialize_asset_amount(account['balance'])
                # ignore empty balances. Coinbase returns zero balances for everything
                # a user does not own
                if amount == ZERO:
                    continue

                asset = asset_from_coinbase(account['currency'])
                try:
                    usd_price = Inquirer().find_usd_price(asset=asset)
                except RemoteError as e:
                    self.msg_aggregator.add_error(
                        f'Error processing coinbasepro balance result due to inability to '
                        f'query USD price: {str(e)}. Skipping balance entry',
                    )
                    continue

                assets_balance[asset] += Balance(
                    amount=amount,
                    usd_value=amount * usd_price,
                )
            except UnknownAsset as e:
                self.msg_aggregator.add_warning(
                    f'Found coinbase pro balance result with unknown asset '
                    f'{e.asset_name}. Ignoring it.',
                )
                continue
            except UnsupportedAsset as e:
                self.msg_aggregator.add_warning(
                    f'Found coinbase pro balance result with unsupported asset '
                    f'{e.asset_name}. Ignoring it.',
                )
                continue
            except (DeserializationError, KeyError) as e:
                msg = str(e)
                if isinstance(e, KeyError):
                    msg = f'Missing key entry for {msg}.'
                self.msg_aggregator.add_error(
                    'Error processing a coinbase pro account balance. Check logs '
                    'for details. Ignoring it.',
                )
                log.error(
                    'Error processing a coinbase pro account balance',
                    account_balance=account,
                    error=msg,
                )
                continue

        return dict(assets_balance), ''

    def _get_products_ids(self) -> List[str]:
        """Gets a list of all product ids (markets) offered by coinbase PRO

        - Raises the same exceptions as _api_query()
        - Can raise KeyError if the API does not return the expected response format.
        """
        products, _ = self._api_query('products', request_method='GET')
        return [product['id'] for product in products]

    def _get_account_ids(self) -> List[str]:
        """Gets a list of all account ids

        - Raises the same exceptions as _api_query()
        - Can raise KeyError if the API does not return the expected response format.
        """
        accounts, _ = self._api_query('accounts')
        return [account['id'] for account in accounts]

    def _read_trades(self, filepath: str) -> List[Trade]:
        """Reads a csv fill type report and extracts the Trades"""
        with open(filepath, newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            trades = []
            for row in reader:
                try:
                    timestamp = deserialize_timestamp_from_date(
                        row['created at'],
                        'iso8601',
                        'coinbasepro',
                    )
                    trades.append(Trade(
                        timestamp=timestamp,
                        location=Location.COINBASEPRO,
                        pair=coinbasepro_to_worldpair(row['product']),
                        trade_type=deserialize_trade_type(row['side']),
                        amount=deserialize_asset_amount(row['size']),
                        rate=deserialize_price(row['price']),
                        fee=deserialize_fee(row['fee']),
                        fee_currency=Asset(row['price/fee/total unit']),
                        link=row['trade id'],
                        notes='',
                    ))
                except UnprocessableTradePair as e:
                    self.msg_aggregator.add_warning(
                        f'Found unprocessable Coinbasepro pair {e.pair}. Ignoring the trade.',
                    )
                    continue
                except UnknownAsset as e:
                    self.msg_aggregator.add_warning(
                        f'Found unknown Coinbasepro asset {e.asset_name}. '
                        f'Ignoring the trade.',
                    )
                    continue
                except (DeserializationError, KeyError) as e:
                    msg = str(e)
                    if isinstance(e, KeyError):
                        msg = f'Missing key entry for {msg}.'
                    self.msg_aggregator.add_error(
                        'Failed to deserialize a coinbasepro trade. '
                        'Check logs for details. Ignoring it.',
                    )
                    log.error(
                        'Error processing a coinbasepro trade.',
                        raw_trade=row,
                        error=msg,
                    )
                    continue

        return trades

    def _paginated_query(
            self,
            endpoint: str,
            query_options: Dict[str, Any] = None,
            limit: int = COINBASEPRO_PAGINATION_LIMIT,
    ):
        if query_options is None:
            query_options = {}
        query_options['limit'] = limit
        while True:
            result, after_cursor = self._api_query(endpoint=endpoint, query_options=query_options)
            yield result
            if after_cursor is None or len(result) < limit:
                break

            query_options['after'] = after_cursor

    def query_online_deposits_withdrawals(
            self,
            start_ts: Timestamp,
            end_ts: Timestamp,
    ) -> List[AssetMovement]:
        """Queries coinbase pro for asset movements"""
        log.debug('Query coinbasepro asset movements', start_ts=start_ts, end_ts=end_ts)
        movements = []
        raw_movements = []
        for batch in self._paginated_query(
            endpoint='transfers',
            query_options={'type': 'withdraw'},
        ):
            raw_movements.extend(batch)
        for batch in self._paginated_query(
            endpoint='transfers',
            query_options={'type': 'deposit'},
        ):
            raw_movements.extend(batch)

        account_to_currency = self.create_or_return_account_to_currency_map()
        for entry in raw_movements:
            try:
                raw_time = entry['completed_at']
                if raw_time.endswith('+00'):  # proper iso8601 needs + 00:00 for timezone
                    raw_time = raw_time.replace('+00', '+00:00')
                timestamp = deserialize_timestamp_from_date(raw_time, 'iso8601', 'coinbasepro')
                if timestamp < start_ts or timestamp > end_ts:
                    continue

                category = deserialize_asset_movement_category(entry['type'])
                asset = account_to_currency.get(entry['account_id'], None)
                if asset is None:
                    log.warning(
                        f'Skipping coinbase pro asset_movement {entry} due to inability to '
                        f'match account id to an asset',
                    )
                    continue

                address = None
                transaction_id = None
                fee = Fee(ZERO)
                if category == AssetMovementCategory.DEPOSIT:
                    try:
                        address = entry['details']['crypto_address']
                        transaction_id = entry['details']['crypto_transaction_hash']
                    except KeyError:
                        pass
                else:  # withdrawal
                    try:
                        address = entry['details']['sent_to_address']
                        transaction_id = entry['details']['crypto_transaction_hash']
                        fee = deserialize_fee(entry['details']['fee'])
                    except KeyError:
                        pass

                if transaction_id and (asset == A_ETH or asset.asset_type == AssetType.ETHEREUM_TOKEN):  # noqa: E501
                    transaction_id = '0x' + transaction_id

                movements.append(AssetMovement(
                    location=Location.COINBASEPRO,
                    category=category,
                    address=address,
                    transaction_id=transaction_id,
                    timestamp=timestamp,
                    asset=asset,
                    amount=deserialize_asset_amount_force_positive(entry['amount']),
                    fee_asset=asset,
                    fee=fee,
                    link=str(entry['id']),
                ))
            except UnknownAsset as e:
                self.msg_aggregator.add_warning(
                    f'Found unknown Coinbasepro asset {e.asset_name}. '
                    f'Ignoring its deposit/withdrawal.',
                )
                continue
            except (DeserializationError, KeyError) as e:
                msg = str(e)
                if isinstance(e, KeyError):
                    msg = f'Missing key entry for {msg}.'
                self.msg_aggregator.add_error(
                    'Failed to deserialize a Coinbasepro deposit/withdrawal. '
                    'Check logs for details. Ignoring it.',
                )
                log.error(
                    'Error processing a coinbasepro  deposit/withdrawal.',
                    raw_asset_movement=entry,
                    error=msg,
                )
                continue

        return movements

    def query_online_trade_history(
            self,
            start_ts: Timestamp,
            end_ts: Timestamp,
    ) -> List[Trade]:
        """Queries coinbase pro for trades

        1. Generates relevant reports and writes them to a temporary directory
        2. Reads all files from that directory and extracts Trades
        3. Temporary directory is removed
        """
        log.debug('Query coinbasepro trade history', start_ts=start_ts, end_ts=end_ts)
        trades = []
        with TemporaryDirectory() as tempdir:
            try:
                filepaths = self._generate_reports(
                    start_ts=start_ts,
                    end_ts=end_ts,
                    report_type='fills',
                    tempdir=tempdir,
                )
            except CoinbaseProPermissionError as e:
                self.msg_aggregator.add_error(
                    f'Got permission error while querying Coinbasepro for trades: {str(e)}',
                )
                return []
            except RemoteError as e:
                self.msg_aggregator.add_error(
                    f'Got remote error while querying Coinbasepro for trades: {str(e)}',
                )
                return []

            for filepath in filepaths:
                trades.extend(self._read_trades(filepath))

        return trades

    def query_online_margin_history(
            self,  # pylint: disable=no-self-use
            start_ts: Timestamp,  # pylint: disable=unused-argument
            end_ts: Timestamp,  # pylint: disable=unused-argument
    ) -> List[MarginPosition]:
        return []  # noop for coinbasepro
