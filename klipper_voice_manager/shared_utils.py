import os
import threading


class PhraseCache:
    """Кеш для быстрого поиска звуковых фраз."""
    
    def __init__(self):
        self._cache = {}
        self._lock = threading.Lock()
        self._version = 0
    
    def build_cache(self, sounds_dict):
        """Строит кеш из словаря звуков для быстрого поиска."""
        with self._lock:
            # Сортируем ключи по длине (убывание) для приоритета длинных фраз
            self._cache = {}
            for key in sorted(sounds_dict.keys(), key=lambda x: len(str(x).split()), reverse=True):
                # Парсим строку как список слов для быстрого поиска
                if isinstance(key, str) and key.startswith('[') and key.endswith(']'):
                    try:
                        # Кешируем уже распарсенный список
                        import ast
                        words = ast.literal_eval(key)
                        if isinstance(words, list):
                            self._cache[tuple(words)] = key
                    except:
                        pass
            self._version += 1
    
    def find_phrases(self, words_list):
        """Возвращает кешированные составные фразы из списка слов."""
        with self._lock:
            cache = self._cache.copy()
            version = self._version
        return cache, version


def enqueue_phrase(words_list, sound_manager, config_manager):
    """
    Энкодирует фразу в список путей к файлам и отправляет на воспроизведение.
    
    Оптимизирована версия с более эффективным поиском составных фраз.
    """
    result_files = []
    processed_words = []
    unmatched_words = words_list.copy()

    sounds = config_manager.get_config_section("sounds")
    if not sounds:
        # Если нет звуков в конфиге - переходим к одиночным словам
        pass
    else:
        # ОПТИМИЗАЦИЯ: Используем более эффективный алгоритм поиска
        # Вместо вложенных циклов O(n²), используем greedy поиск слева направо
        words_remaining = list(words_list)
        
        while words_remaining:
            found = False
            
            # Ищем самую длинную совпадающую фразу, начиная с текущей позиции
            for length in range(len(words_remaining), 0, -1):
                sublist = words_remaining[:length]
                composite_key = str(sublist)
                
                if composite_key in sounds:
                    # Нашли совпадение!
                    path = config_manager.find_sound_file(composite_key)
                    if path:
                        result_files.append(path)
                        processed_words.extend(sublist)
                        # Удаляем обработанные слова
                        words_remaining = words_remaining[length:]
                        # Удаляем из unmatched
                        for word in sublist:
                            if word in unmatched_words:
                                unmatched_words.remove(word)
                        print(f"[ФРАЗА] Найдена составная: {composite_key}")
                        found = True
                        break
            
            if not found:
                # Если не нашли совпадение, берём первое слово как одиночное
                word = words_remaining.pop(0)
                f = config_manager.find_sound_file(word)
                if f and os.path.isfile(f):
                    result_files.append(f)
                    processed_words.append(word)
                    if word in unmatched_words:
                        unmatched_words.remove(word)

    # Логирование результатов
    if processed_words:
        print(f"[ФРАЗА] Обработаны: {', '.join(processed_words)}")
    if unmatched_words:
        print(f"[ФРАЗА ПРЕДУПРЕЖДЕНИЕ] Не найдены: {', '.join(unmatched_words)}")

    # Воспроизведение
    if result_files:
        sound_manager.enqueue_sentence(result_files)
    else:
        print("[ФРАЗА ПРЕДУПРЕЖДЕНИЕ] Нет файлов для воспроизведения")
