import pytest

from polymarket._internal.environment import get_environment_config
from polymarket._internal.wallet import (
    classify_wallet_type,
    derive_beacon_deposit_wallet_address,
    derive_proxy_wallet_address,
    derive_safe_wallet_address,
    derive_uups_deposit_wallet_address,
    signature_type_for,
)
from polymarket.environments import PRODUCTION
from polymarket.errors import UserInputError

SIGNER = "0x0000000000000000000000000000000000000001"

EXPECTED_UUPS_DEPOSIT = "0x57ffbc34de23124faeb8387fcd689d314e57accd"
EXPECTED_BEACON_DEPOSIT = "0x94bf330955a0b957662feaf878de77bf25f76cd9"
EXPECTED_PROXY = "0x7754536ecd85c00b2e0cf9c1aa679340d8550756"
EXPECTED_SAFE = "0x766b6851a199bf91ae3fa13b1cfac5187355118f"


def test_derive_uups_deposit_wallet_address_matches_ts_golden_vector() -> None:
    derived = derive_uups_deposit_wallet_address(
        SIGNER, get_environment_config(PRODUCTION).wallet_derivation
    )
    assert derived.lower() == EXPECTED_UUPS_DEPOSIT


def test_derive_beacon_deposit_wallet_address_matches_ts_golden_vector() -> None:
    derived = derive_beacon_deposit_wallet_address(
        SIGNER, get_environment_config(PRODUCTION).wallet_derivation
    )
    assert derived.lower() == EXPECTED_BEACON_DEPOSIT


def test_derive_proxy_wallet_address_matches_ts_golden_vector() -> None:
    derived = derive_proxy_wallet_address(
        SIGNER, get_environment_config(PRODUCTION).wallet_derivation
    )
    assert derived.lower() == EXPECTED_PROXY


def test_derive_safe_wallet_address_matches_ts_golden_vector() -> None:
    derived = derive_safe_wallet_address(
        SIGNER, get_environment_config(PRODUCTION).wallet_derivation
    )
    assert derived.lower() == EXPECTED_SAFE


def test_signature_type_for_each_wallet_type() -> None:
    assert signature_type_for("EOA") == 0
    assert signature_type_for("POLY_PROXY") == 1
    assert signature_type_for("GNOSIS_SAFE") == 2
    assert signature_type_for("DEPOSIT_WALLET") == 3


def test_classify_wallet_type_returns_eoa_when_wallet_equals_signer() -> None:
    result = classify_wallet_type(
        signer=SIGNER, wallet=SIGNER, config=get_environment_config(PRODUCTION).wallet_derivation
    )
    assert result == "EOA"


def test_classify_wallet_type_returns_deposit_wallet_for_uups_address() -> None:
    result = classify_wallet_type(
        signer=SIGNER,
        wallet=EXPECTED_UUPS_DEPOSIT,
        config=get_environment_config(PRODUCTION).wallet_derivation,
    )
    assert result == "DEPOSIT_WALLET"


def test_classify_wallet_type_returns_deposit_wallet_for_beacon_address() -> None:
    result = classify_wallet_type(
        signer=SIGNER,
        wallet=EXPECTED_BEACON_DEPOSIT,
        config=get_environment_config(PRODUCTION).wallet_derivation,
    )
    assert result == "DEPOSIT_WALLET"


def test_classify_wallet_type_returns_poly_proxy_for_derived_address() -> None:
    result = classify_wallet_type(
        signer=SIGNER,
        wallet=EXPECTED_PROXY,
        config=get_environment_config(PRODUCTION).wallet_derivation,
    )
    assert result == "POLY_PROXY"


def test_classify_wallet_type_returns_gnosis_safe_for_derived_address() -> None:
    result = classify_wallet_type(
        signer=SIGNER,
        wallet=EXPECTED_SAFE,
        config=get_environment_config(PRODUCTION).wallet_derivation,
    )
    assert result == "GNOSIS_SAFE"


def test_classify_wallet_type_is_case_insensitive() -> None:
    upper = EXPECTED_UUPS_DEPOSIT.upper().replace("0X", "0x")
    result = classify_wallet_type(
        signer=SIGNER, wallet=upper, config=get_environment_config(PRODUCTION).wallet_derivation
    )
    assert result == "DEPOSIT_WALLET"


def test_classify_wallet_type_rejects_unrelated_wallet() -> None:
    with pytest.raises(UserInputError, match="does not match the signer"):
        classify_wallet_type(
            signer=SIGNER,
            wallet="0x0000000000000000000000000000000000000002",
            config=get_environment_config(PRODUCTION).wallet_derivation,
        )
