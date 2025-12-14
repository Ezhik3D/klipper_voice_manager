from typing import List, Tuple
from number_words import number_to_words
from plural_utils import plural_form

def phrase_for_mass_component(value: int, unit: str) -> List[str]:
    """Преобразует компонент массы в фразу со словом и единицей."""
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

def split_grams_components(X_g: int) -> Tuple[int, int]:
    """Разбивает граммы на компоненты: кг, г."""
    kg = X_g // 1000
    g = X_g % 1000
    return kg, g

def generate_all_mass_phrase_variants(X_g: int) -> List[Tuple[List[str], int, str]]:
    kg_comp, g_comp = split_grams_components(X_g)
    results = []

    # ВАРИАНТ 1: кг + г (если оба > 0 и ≤ 999)
    if kg_comp > 0 and kg_comp <= 999 and g_comp > 0 and g_comp <= 999:
        phrase = (phrase_for_mass_component(kg_comp, "kg") +
                 phrase_for_mass_component(g_comp, "g"))
        results.append((phrase, len(phrase), "kg_g"))

    # ВАРИАНТ 2: только кг (если > 0 и ≤ 999)
    if kg_comp > 0 and kg_comp <= 999:
        phrase = phrase_for_mass_component(kg_comp, "kg")
        results.append((phrase, len(phrase), "kg"))


    # ВАРИАНТ 3: только г (если > 0 и ≤ 999)
    if g_comp > 0 and g_comp <= 999:
        phrase = phrase_for_mass_component(g_comp, "g")
        results.append((phrase, len(phrase), "g"))

    return results

def get_compact_filament_phrase_grams(X_g: int) -> List[str]:
    print(f"[G_IN] {X_g}")


    if X_g <= 0:
        print(f"[G_OUT] []")
        return []

    candidates = generate_all_mass_phrase_variants(X_g)

    if not candidates:
        print(f"[G_OUT] []")
        return []

    # Сортировка:
    # 1) сначала варианты, где есть кг (если исходный X_g >= 1000)
    # 2) затем по длине фразы (меньше слов — лучше)
    # 3) если длины равны, предпочитаем "кг + г" вместо просто "кг"
    has_kg_in_input = (X_g >= 1000)  # если было хотя бы 1000г = 1кг


    def sort_key(item):
        phrase_type = item[2]
        # Приоритет: если были кг в исходных данных, то варианты с кг идут первыми
        prefers_kg = (has_kg_in_input and phrase_type in ["kg", "kg_g"])
        # Чем выше приоритет, тем раньше в списке (поэтому not prefers_kg)
        priority_kg = not prefers_kg
        # Длина фразы (меньше — лучше)
        length = item[1]
        # Если длины равны, "кг + г" лучше, чем просто "кг"
        subpriority = (phrase_type != "kg_g")
        return (priority_kg, length, subpriority)


    candidates.sort(key=sort_key)

    best_phrase = candidates[0][0]
    best_text = " ".join(best_phrase)
    print(f"[G_OUT] {best_text}")


    return best_phrase
