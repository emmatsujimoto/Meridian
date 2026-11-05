"""The version flags."""

import pytest

from meridian import __version__
from meridian.cli import main


@pytest.mark.parametrize("flag", ["-V", "--version"])
def test_version_flags(flag, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main([flag])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip().endswith(__version__)
