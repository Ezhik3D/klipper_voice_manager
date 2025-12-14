from typing import List, Tuple
from number_words import number_to_words
from plural_utils import plural_form

def phrase_for_component(value: int, unit: str) -> List[str]:
    """Преобразует компонент в фразу со словом и единицей."""
    if value <= 0 or value > 999:
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

def split_mm_components(X_mm: int) -> Tuple[int, int, int, int]:
    """Разбивает миллиметры на компоненты: км, м, см, мм."""
    km = X_mm // 1_000_000
    rem_after_km = X_mm % 1_000_000


    m = rem_after_km // 1_000
    rem_after_m = rem_after_km % 1_000

    cm = rem_after_m // 10
    mm = rem_after_m % 10

    return km, m, cm, mm

def generate_all_phrase_variants(X_mm: int) -> List[Tuple[List[str], int, str, int]]:
    km_comp, m_comp, cm_comp, mm_comp = split_mm_components(X_mm)
    results = []

    # ВАРИАНТ 1: все раздельно (гарантированный минимум)
    phrase = []
    if km_comp > 0:
        phrase += phrase_for_component(km_comp, "km")
    if m_comp > 0:
        phrase += phrase_for_component(m_comp, "m")
    if cm_comp > 0:
        phrase += phrase_for_component(cm_comp, "cm")
    if mm_comp > 0:
        phrase += phrase_for_component(mm_comp, "mm")
    if phrase:
        results.append((phrase, len(phrase), "full", 0))

    # ВАРИАНТ 2: км + м + (см+мм в мм), если см+мм ≤ 999
    if km_comp > 0 and m_comp > 0:
        total_mm = cm_comp * 10 + mm_comp
        if 0 < total_mm <= 999:
            phrase = (
                phrase_for_component(km_comp, "km") +
                phrase_for_component(m_comp, "m") +
                phrase_for_component(total_mm, "mm")
            )
            results.append((phrase, len(phrase), "km_m_mm", 0))


    # ВАРИАНТ 3: если нет м, но есть км + см+мм в мм
    if km_comp > 0 and m_comp == 0:
        total_mm = cm_comp * 10 + mm_comp
        if 0 < total_mm <= 999:
            phrase = (
                phrase_for_component(km_comp, "km") +
                phrase_for_component(total_mm, "mm")
            )
            results.append((phrase, len(phrase), "km_mm", 0))


    return results

def get_compact_filament_phrase_mm(X_mm: int) -> List[str]:
    print(f"[MM_IN] {X_mm}")


    if X_mm <= 0:
        print(f"[MM_OUT] []")
        return []


    candidates = generate_all_phrase_variants(X_mm)
    if not candidates:
        print(f"[MM_OUT] []")
        return []

    # Сортировка: 1) ошибка (0), 2) длина фразы (меньше слов), 3) приоритет "total_m" / "total_mm"
    candidates.sort(key=lambda x: (x[3], x[1], x[2] not in ["total_m", "total_mm", "m+total_mm"]))


    best_phrase = candidates[0][0]
    best_text = " ".join(best_phrase)
    error = candidates[0][3]
    print(f"[MM_OUT] {best_text} (ошибка: {error}мм)")


    return best_phrase
