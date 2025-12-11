# number_to_words.py


def number_to_words(number: int, gender: str = "m") -> list:
    """
    Преобразует число в список слов (на русском языке).
    Поддерживает числа от 0 до 999.
    Род влияет на 1 и 2: 'один'/'одна'/'одно', 'два'/'две'.
    gender: 'm' - мужской, 'f' - женский, 'n' - средний
    """
    if not isinstance(number, int):
        raise ValueError("Аргумент должен быть целым числом")

    if number < 0 or number > 999:
        raise ValueError("Поддерживаются только числа от 0 до 999")

    units_m = [
        "ноль",
        "один",
        "два",
        "три",
        "четыре",
        "пять",
        "шесть",
        "семь",
        "восемь",
        "девять",
    ]
    units_f = [
        "ноль",
        "одна",
        "две",
        "три",
        "четыре",
        "пять",
        "шесть",
        "семь",
        "восемь",
        "девять",
    ]
    units_n = [
        "ноль",
        "одно",
        "два",
        "три",
        "четыре",
        "пять",
        "шесть",
        "семь",
        "восемь",
        "девять",
    ]

    teens = [
        "десять",
        "одиннадцать",
        "двенадцать",
        "тринадцать",
        "четырнадцать",
        "пятнадцать",
        "шестнадцать",
        "семнадцать",
        "восемнадцать",
        "девятнадцать",
    ]
    tens = [
        "",
        "",
        "двадцать",
        "тридцать",
        "сорок",
        "пятьдесят",
        "шестьдесят",
        "семьдесят",
        "восемьдесят",
        "девяносто",
    ]
    hundreds = [
        "",
        "сто",
        "двести",
        "триста",
        "четыреста",
        "пятьсот",
        "шестьсот",
        "семьсот",
        "восемьсот",
        "девятьсот",
    ]

    words = []

    if number >= 100:
        h = number // 100
        words.append(hundreds[h])
        number %= 100

    if 10 <= number < 20:
        words.append(teens[number - 10])
        return words

    if number >= 20:
        t = number // 10
        words.append(tens[t])
        number %= 10

    if 0 < number < 10:
        if gender == "f":
            words.append(units_f[number])
        elif gender == "n":
            words.append(units_n[number])
        else:
            words.append(units_m[number])

    elif number == 0 and not words:
        words.append(units_m[0])

    return words
