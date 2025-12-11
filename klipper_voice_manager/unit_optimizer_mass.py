from typing import List, Tuple
from number_words import number_to_words
from plural_utils import plural_form


def phrase_for_mass_component(value: int, unit: str) -> List[str]:
    if value <= 0 or value > 999:
        return []
    words = number_to_words(value)
    if unit == "kg":
        unit_name = plural_form(value, ("килограмм", "килограмма", "килограммов"))
    elif unit == "g":
        unit_name = plural_form(value, ("грамм", "грамма", "граммов"))
    else:
        unit_name = unit
    words.append(unit_name)
    return words


def generate_mass_phrases(X_g: int) -> List[Tuple[List[str], int]]:
    results = []
    if X_g <= 0:
        return results
    kg = X_g // 1000
    g = X_g % 1000
    if 1 <= kg <= 999 and 1 <= g <= 999:
        phrase = phrase_for_mass_component(kg, "kg") + phrase_for_mass_component(g, "g")
        results.append((phrase, len(phrase)))
    if 1 <= kg <= 999 and g == 0:
        phrase = phrase_for_mass_component(kg, "kg")
        results.append((phrase, len(phrase)))
    if kg == 0 and 1 <= g <= 999:
        phrase = phrase_for_mass_component(g, "g")
        results.append((phrase, len(phrase)))
    return results


def select_best_mass_phrase(phrases: List[Tuple[List[str], int]]) -> List[str]:
    if not phrases:
        return []
    min_len = min(count for _, count in phrases)
    candidates = [p for p in phrases if p[1] == min_len]

    def priority_key(item):
        phrase, _ = item
        has_kg = any("килограмм" in word for word in phrase)
        return 0 if has_kg else 1

    candidates.sort(key=priority_key)
    return candidates[0][0]


def get_compact_filament_phrase_grams(X_g: int) -> List[str]:
    if X_g <= 0:
        return []
    phrases = generate_mass_phrases(X_g)
    if not phrases:
        g = X_g % 1000
        if 1 <= g <= 999:
            return phrase_for_mass_component(g, "g")
        return []
    best_phrase = select_best_mass_phrase(phrases)
    return best_phrase
