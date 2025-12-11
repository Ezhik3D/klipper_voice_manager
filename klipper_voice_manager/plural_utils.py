# plural_utils.py
def plural_form(number: int, forms: tuple) -> str:
    """
    Возвращает правильную форму слова в зависимости от числа.
    forms должен быть кортежем из трёх строк: (форма1, форма2, форма3)
    """
    if not isinstance(number, (int, float)):
        raise TypeError("Аргумент number должен быть числом")

    if not isinstance(forms, tuple) or len(forms) != 3:
        raise ValueError("Аргумент forms должен быть кортежем из трёх строк")

    n = int(abs(number)) % 100
    if 11 <= n <= 19:
        return forms[2]

    last_digit = n % 10
    if last_digit == 1:
        return forms[0]
    elif 2 <= last_digit <= 4:
        return forms[1]
    else:
        return forms[2]


def plural_degree(number: int) -> str:
    """
    Возвращает алиас слова «градус» в правильной форме.
    """
    return plural_form(number, ("градус", "градуса", "градусов"))
