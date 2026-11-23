"""Keep secrets out of everything pytest reports.

Failure output shows the arguments of every frame in the traceback, assertion
values and captured output, so a private key or API secret passed to a test or
to the SDK would otherwise be printed. Each report is rewritten before pytest
shows it, replacing secret values with ``[REDACTED]``.

Secrets are the values of credential environment variables and the keys of any
account a test creates with ``Account.create``.
"""

from __future__ import annotations

import os
import re
from collections.abc import Generator, Iterable
from typing import Any

import pytest
from eth_account import Account

REDACTED = "[REDACTED]"

_SECRET_ENV_NAME = re.compile(r"PRIVATE_KEY|SECRET|PASSPHRASE|API_KEY|TOKEN|PASSWORD")
# Shorter values are too likely to match ordinary text to be secrets.
_MIN_SECRET_LENGTH = 8


class _Redactor:
    def __init__(self) -> None:
        self._secrets: set[str] = set()

    def add(self, value: str) -> None:
        value = value.strip()
        if len(value) < _MIN_SECRET_LENGTH:
            return
        bare = value.removeprefix("0x").removeprefix("0X")
        for form in (value, value.lower(), value.upper(), bare, bare.lower(), bare.upper()):
            if len(form) >= _MIN_SECRET_LENGTH:
                self._secrets.add(form)

    def add_environment(self, environ: Iterable[tuple[str, str]]) -> None:
        for name, value in environ:
            if _SECRET_ENV_NAME.search(name.upper()):
                self.add(value)

    def redact(self, text: str) -> str:
        # Longest first, so a secret is never left partly visible by a shorter form.
        for secret in sorted(self._secrets, key=len, reverse=True):
            if secret in text:
                text = text.replace(secret, REDACTED)
        return text

    def redact_report(self, report: pytest.CollectReport | pytest.TestReport) -> None:
        longrepr = report.longrepr
        if isinstance(longrepr, tuple):
            path, lineno, message = longrepr
            report.longrepr = (path, lineno, self.redact(str(message)))
        elif longrepr is not None:
            text = str(longrepr)
            redacted = self.redact(text)
            if redacted != text:
                report.longrepr = redacted
        report.sections = [(title, self.redact(content)) for title, content in report.sections]


pytest_plugins = ["pytester"]

_redactor = _Redactor()


def pytest_configure(config: pytest.Config) -> None:
    _redactor.add_environment(os.environ.items())


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, Any, None]:
    outcome = yield
    _redactor.redact_report(outcome.get_result())


@pytest.hookimpl(hookwrapper=True)
def pytest_make_collect_report(collector: pytest.Collector) -> Generator[None, Any, None]:
    outcome = yield
    _redactor.redact_report(outcome.get_result())


@pytest.fixture(scope="session", autouse=True)
def redact_created_account_keys() -> Generator[None, None, None]:
    """Treat the key of every account a test creates as a secret."""
    create = Account.create

    def create_and_redact(*args: Any, **kwargs: Any) -> Any:
        account = create(*args, **kwargs)
        _redactor.add(account.key.hex())
        return account

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Account, "create", staticmethod(create_and_redact))
        yield
