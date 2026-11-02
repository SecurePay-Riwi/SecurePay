"""The cache keys of contract C5 (HU-67 reads and writes them)."""

import uuid

from services.decision_engine import reference_data


def test_account_and_merchant_keys():
    account, merchant = uuid.uuid4(), uuid.uuid4()
    assert reference_data.account_key(account) == f"acct:{account}"
    assert reference_data.merchant_key(merchant) == f"merch:{merchant}"


def test_the_restricted_list_keys_share_a_hash_tag():
    # RENAME between two keys is only valid in cluster mode with the same slot.
    for key in (reference_data.RESTRICTED_DOCS, reference_data.RESTRICTED_DOCS_NEXT,
                reference_data.RESTRICTED_LOADED_AT):
        assert key.startswith("{restricted}:")

