import pytest

from polymarket.auth import BuilderApiKey, RelayerApiKey
from polymarket.errors import UserInputError


def test_relayer_api_key_normalizes_address() -> None:
    from eth_utils.address import to_checksum_address

    raw = "0xddeeaa11220000000000000000000000000000aa"
    auth = RelayerApiKey(key="k", address=raw)
    assert auth.address == to_checksum_address(raw)
    assert auth.address != raw


def test_relayer_api_key_rejects_invalid_address() -> None:
    with pytest.raises(UserInputError, match="Invalid relayer address"):
        RelayerApiKey(key="k", address="not-an-address")


def test_builder_api_key_repr_does_not_leak_secrets() -> None:
    auth = BuilderApiKey(key="super-secret-key", secret="dGVzdA==", passphrase="super-pass")
    r = repr(auth)
    s = str(auth)
    assert "super-secret-key" not in r and "super-secret-key" not in s
    assert "dGVzdA==" not in r and "dGVzdA==" not in s
    assert "super-pass" not in r and "super-pass" not in s
    assert "BuilderApiKey" in r and "redacted" in r


def test_relayer_api_key_repr_does_not_leak_key() -> None:
    addr = "0x0000000000000000000000000000000000000001"
    auth = RelayerApiKey(key="super-secret-relayer-key", address=addr)
    r = repr(auth)
    s = str(auth)
    assert "super-secret-relayer-key" not in r and "super-secret-relayer-key" not in s
    assert "RelayerApiKey" in r and "redacted" in r
    assert addr in r
