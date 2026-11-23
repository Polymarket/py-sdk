"""The test suite never prints secrets, even when a test using them fails."""

from __future__ import annotations

import secrets
import textwrap
from pathlib import Path

import pytest

_SUITE_CONFTEST = Path(__file__).parents[1] / "conftest.py"


def test_failing_tests_do_not_print_private_keys(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_key = "0x" + secrets.token_hex(32)
    monkeypatch.setenv("REDACTION_CHECK_PRIVATE_KEY", env_key)
    pytester.makeconftest(_SUITE_CONFTEST.read_text())
    (pytester.path / "test_leaky.py").write_text(
        textwrap.dedent(
            """
        import os
        from pathlib import Path

        import pytest
        from eth_account import Account


        @pytest.fixture
        def wallet_private_key():
            return os.environ["REDACTION_CHECK_PRIVATE_KEY"]


        def sign(private_key):
            raise ValueError(f"cannot sign with {private_key}")


        def test_fixture_key(wallet_private_key):
            print(wallet_private_key)
            sign(wallet_private_key)


        def test_created_key():
            key = Account.create().key.hex()
            Path("created_key.txt").write_text(key)
            print(key)
            assert key == "0x00"
            """
        )
    )

    result = pytester.runpytest_subprocess("-rfEs", "--showlocals", "-p", "no:cacheprovider")

    result.assert_outcomes(failed=2)
    output = result.stdout.str() + result.stderr.str()
    created_key = (pytester.path / "created_key.txt").read_text()
    for key in (env_key, created_key):
        assert key.removeprefix("0x") not in output
    assert "[REDACTED]" in output
