from collections import (
    namedtuple,
)
from functools import (
    partial,
    wraps,
)
from typing import (  # noqa: F401
    Any,
    Dict,
    List,
)
from cytoolz import (
    assoc,
    assoc_in,
    curry,
    merge,
)
from eth_utils import (
    apply_formatters_to_dict,
    decode_hex,
    to_canonical_address,
)

from eth.tools.fixtures.helpers import (
    get_test_name,
)
from eth.tools.fixtures.normalization import (
    normalize_environment,
    normalize_execution,
    normalize_state,
    normalize_transaction,
    normalize_networks,
)
from eth.tools._utils.mappings import (
    deep_merge,
)
from eth.tools._utils.vyper import (
    compile_vyper_lll,
)

from ._utils import (
    add_transaction_to_group,
    wrap_in_list,
)


#
# Defaults
#

DEFAULT_MAIN_ENVIRONMENT = {
    "currentCoinbase": to_canonical_address("0x2adc25665018aa1fe0e6bc666dac8fc2697ff9ba"),
    "currentDifficulty": 131072,
    "currentGasLimit": 1000000,
    "currentNumber": 1,
    "currentTimestamp": 1000,
    "previousHash": decode_hex(
        "0x5e20a0453cecd065ea59c37ac63e079ee08998b6045136a8ce6635c7912ec0b6"
    ),
}


DEFAULT_MAIN_TRANSACTION = {
    "data": b"",
    "gasLimit": 100000,
    "gasPrice": 0,
    "nonce": 0,
    "secretKey": decode_hex("0x45a915e4d060149eb4365960e6a7a45f334393093061116b197e3240065ff2d8"),
    "to": to_canonical_address("0x0f572e5295c57f15886f9b263e2f6d2d6c7b5ec6"),
    "value": 0
}


def get_default_transaction(networks):
    return DEFAULT_MAIN_TRANSACTION


DEFAULT_EXECUTION = {
    "address": to_canonical_address("0x0f572e5295c57f15886f9b263e2f6d2d6c7b5ec6"),
    "origin": to_canonical_address("0xcd1722f2947def4cf144679da39c4c32bdc35681"),
    "caller": to_canonical_address("0xcd1722f2947def4cf144679da39c4c32bdc35681"),
    "value": 1000000000000000000,
    "data": b"",
    "gasPrice": 1,
    "gas": 100000
}


Test = namedtuple("Test", ["filler", "fill_kwargs"])
# make `None` default for fill_kwargs
Test.__new__.__defaults__ = (None,)  # type: ignore


#
# Filler Generation
#

def setup_filler(name, environment=None):
    environment = normalize_environment(environment or {})
    return {name: {
        "env": environment,
        "pre": {},
    }}


def setup_main_filler(name, environment=None):
    return setup_filler(name, merge(DEFAULT_MAIN_ENVIRONMENT, environment or {}))


def pre_state(*raw_state, filler):
    @wraps(pre_state)
    def _pre_state(filler):
        test_name = get_test_name(filler)

        old_pre_state = filler[test_name].get("pre_state", {})
        pre_state = normalize_state(raw_state)
        defaults = {address: {
            "balance": 0,
            "nonce": 0,
            "code": b"",
            "storage": {},
        } for address in pre_state}
        new_pre_state = deep_merge(defaults, old_pre_state, pre_state)

        return assoc_in(filler, [test_name, "pre"], new_pre_state)


def _expect(post_state, networks, transaction, filler):
    test_name = get_test_name(filler)
    test = filler[test_name]
    test_update = {test_name: {}}  # type: Dict[str, Dict[Any, Any]]

    pre_state = test.get("pre", {})
    post_state = normalize_state(post_state or {})
    defaults = {address: {
        "balance": 0,
        "nonce": 0,
        "code": b"",
        "storage": {},
    } for address in post_state}
    result = deep_merge(defaults, pre_state, normalize_state(post_state))
    new_expect = {"result": result}

    if transaction is not None:
        transaction = normalize_transaction(
            merge(get_default_transaction(networks), transaction)
        )
        if "transaction" not in test:
            transaction_group = apply_formatters_to_dict({
                "data": wrap_in_list,
                "gasLimit": wrap_in_list,
                "value": wrap_in_list,
            }, transaction)
            indexes = {
                index_key: 0
                for transaction_key, index_key in [
                    ("gasLimit", "gas"),
                    ("value", "value"),
                    ("data", "data"),
                ]
                if transaction_key in transaction_group
            }
        else:
            transaction_group, indexes = add_transaction_to_group(
                test["transaction"], transaction
            )
        new_expect = assoc(new_expect, "indexes", indexes)
        test_update = assoc_in(test_update, [test_name, "transaction"], transaction_group)

    if networks is not None:
        networks = normalize_networks(networks)
        new_expect = assoc(new_expect, "networks", networks)

    existing_expects = test.get("expect", [])
    expect = existing_expects + [new_expect]
    test_update = assoc_in(test_update, [test_name, "expect"], expect)

    return deep_merge(filler, test_update)


def expect(post_state=None, networks=None, transaction=None):
    return partial(_expect, post_state, networks, transaction)


@curry
def execution(execution, filler):
    execution = normalize_execution(execution or {})

    # user caller as origin if not explicitly given
    if "caller" in execution and "origin" not in execution:
        execution = assoc(execution, "origin", execution["caller"])

    if "vyperLLLCode" in execution:
        code = compile_vyper_lll(execution["vyperLLLCode"])
        if "code" in execution:
            if code != execution["code"]:
                raise ValueError("Compiled Vyper LLL code does not match")
        execution = assoc(execution, "code", code)

    execution = merge(DEFAULT_EXECUTION, execution)

    test_name = get_test_name(filler)
    return deep_merge(
        filler,
        {
            test_name: {
                "exec": execution,
            }
        }
    )
