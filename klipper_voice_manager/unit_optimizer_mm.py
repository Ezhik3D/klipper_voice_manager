from typing import List, Tuple
from number_words import number_to_words
from plural_utils import plural_form


def split_mm_components(X_mm: int) -> Tuple[int, int, int, int]:
    km = X_mm // 1_000_000
    rem = X_mm % 1_000_000
    m = rem // 1_000
    rem %= 1_000
    cm = rem // 10
    mm = rem % 10
    return km, m, cm, mm


def phrase_for_component(value: int, unit: str) -> List[str]:
    if value <= 0:
        return []
    words = number_to_words(value)
    if unit == "km":
        unit_name = plural_form(value, ("километр", "километра", "километров"))
    elif unit == "m":
        unit_name = plural_form(value, ("метр", "метра", "метров"))
    elif unit == "cm":
        unit_name = plural_form(value, ("сантиметр", "сантиметра", "сантиметров"))
    elif unit == "mm":
        unit_name = plural_form(value, ("миллиметр", "миллиметра", "миллиметров"))
    else:
        unit_name = unit
    words.append(unit_name)
    return words


def generate_phrases(X_mm: int) -> List[Tuple[List[str], int]]:
    km, m, cm, mm = split_mm_components(X_mm)
    results = []

    if 1 <= km <= 999 and 1 <= m <= 999:
        phrase = phrase_for_component(km, "km") + phrase_for_component(m, "m")
        results.append((phrase, len(phrase)))

    if 1 <= m <= 999 and 1 <= cm <= 999:
        phrase = phrase_for_component(m, "m") + phrase_for_component(cm, "cm")
        results.append((phrase, len(phrase)))

    if 1 <= cm <= 999 and 1 <= mm <= 999:
        phrase = phrase_for_component(cm, "cm") + phrase_for_component(mm, "mm")
        results.append((phrase, len(phrase)))

    for val, unit in [(km, "km"), (m, "m"), (cm, "cm"), (mm, "mm")]:
        if 1 <= val <= 999:
            phrase = phrase_for_component(val, unit)
            results.append((phrase, len(phrase)))

    return results


def select_best_phrase(phrases: List[Tuple[List[str], int]]) -> List[str]:
    if not phrases:
        return []
    min_word_count = min(count for _, count in phrases)
    candidates = [p for p in phrases if p[1] == min_word_count]

    unit_priority = {"км": 0, "м": 1, "см": 2, "мм": 3}

    def priority_score(phrase_tuple):
        phrase, _ = phrase_tuple
        for word in phrase:
            for unit_name, priority in unit_priority.items():
                if unit_name in word:
                    return priority
        return 999

    candidates.sort(key=priority_score)
    return candidates[0][0]


def get_compact_filament_phrase_mm(X_mm: int) -> List[str]:
    if X_mm <= 0:
        return []

    candidates = generate_phrases(X_mm)

    if not candidates:
        km = X_mm // 1_000_000
        if 1 <= km <= 999:
            return phrase_for_component(km, "km")

        m = X_mm // 1_000
        if 1 <= m <= 999:
            return phrase_for_component(m, "m")

        cm = X_mm // 10
        if 1 <= cm <= 999:
            return phrase_for_component(cm, "cm")

        if 1 <= X_mm <= 999:
            return phrase_for_component(X_mm, "mm")

        return []

    best_phrase = select_best_phrase(candidates)
    return best_phrase
