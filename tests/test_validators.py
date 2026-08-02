from monitor_jus.validators import (
    normalize_cnj,
    validate_cnpj,
    validate_cpf,
    validate_oab,
)


def _make_valid_cpf(base9: str = "123456789") -> str:
    def dig(nums: str, factors: range) -> str:
        total = sum(int(n) * f for n, f in zip(nums, factors))
        r = (total * 10) % 11
        return "0" if r == 10 else str(r)

    d1 = dig(base9, range(10, 1, -1))
    d2 = dig(base9 + d1, range(11, 1, -1))
    return base9 + d1 + d2


def test_validate_cpf_known_valid():
    assert validate_cpf(_make_valid_cpf()) is True


def test_validate_cpf_invalid():
    assert validate_cpf("11111111111") is False


def test_validate_cnpj():
    # gera CNPJ válido sintético
    base = "112223330001"
    w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    w2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]

    def calc(b: str, w: list[int]) -> int:
        t = sum(int(a) * x for a, x in zip(b, w))
        r = t % 11
        return 0 if r < 2 else 11 - r

    d1 = calc(base, w1)
    d2 = calc(base + str(d1), w2)
    assert validate_cnpj(base + f"{d1}{d2}") is True


def test_validate_oab():
    assert validate_oab("123456", "SP") is True
    assert validate_oab("12", "SP") is False


def test_normalize_cnj():
    parts = normalize_cnj("0000832-35.2018.4.01.3202")
    assert parts is not None
    assert parts.segmento == "4"
    assert parts.tribunal == "01"
    assert len(parts.numero_digits) == 20
