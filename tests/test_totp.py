import pytest
from app.totp import generate_code, seconds_remaining, TOTPError


@pytest.mark.parametrize(
    "instant,expected",
    [
        (59, "94287082"),
        (1111111109, "07081804"),
        (1111111111, "14050471"),
        (1234567890, "89005924"),
        (2000000000, "69279037"),
    ],
)
def test_rfc6238(instant, expected):
    assert (
        generate_code("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", instant, digits=8) == expected
    )


def test_invalid_secret_safe():
    with pytest.raises(TOTPError, match="^Invalid TOTP secret$"):
        generate_code("synthetic-secret-not-valid!")
    assert seconds_remaining(59) == 1
