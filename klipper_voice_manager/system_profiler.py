import platform
import os

try:
    import psutil
except ImportError:
    psutil = None



class SystemProfiler:
    _cached_profile = None  # Кэшируем результат для повторного использования

    def __init__(self):
        if SystemProfiler._cached_profile is None:
            SystemProfiler._cached_profile = self._detect_profile()
        self.profile_name = SystemProfiler._cached_profile
        self.audio_params = self._get_audio_params()

    def _is_arm(self):
        """Определяем, является ли платформа ARM-based."""
        machine = platform.machine().lower()
        return 'arm' in machine or 'aarch' in machine

    def _get_cpu_freq_mhz(self):
        """Получаем частоту CPU (в МГц) из /proc/cpuinfo для Linux."""
        try:
            with open('/proc/cpuinfo', 'r') as f:
                for line in f:
                    if line.startswith('cpu MHz'):
                        return float(line.split(':')[1].strip())
        except (OSError, ValueError):
            pass
        return 1000  # Условное значение по умолчанию (1 ГГц)

    def _get_memory_mb(self):
        """Получаем объём RAM в МБ (с fallback-механизмами)."""
        if psutil:
            return psutil.virtual_memory().total // (1024 * 1024)

        # Для Linux без psutil — читаем /proc/meminfo
        try:
            with open('/proc/meminfo', 'r') as f:
                for line in f:
                    if line.startswith('MemTotal:'):
                        kb = int(line.split()[1])
                        return kb // 1024
        except (OSError, ValueError):
            pass

        return 512  # Условное значение для fallback

    def _detect_profile(self):
        system = platform.system()
        is_arm = self._is_arm()
        cpu_freq = self._get_cpu_freq_mhz()
        mem_mb = self._get_memory_mb()

        if system == "Windows":
            if mem_mb < 2048:  # <2 ГБ
                return 'ULTRA_WEAK'
            elif mem_mb < 8192:  # <8 ГБ
                return 'WEAK'
            else:
                return 'STRONG'

        elif system == "Linux":
            # Для ARM-устройств (Raspberry Pi, OrangePi)
            if is_arm:
                if cpu_freq < 800 or mem_mb < 256:
                    return 'ULTRA_WEAK'
                elif cpu_freq < 1000 or mem_mb < 512:
                    return 'WEAK'
                elif mem_mb < 2048:
                    return 'MEDIUM'
                else:
                    return 'STRONG'
            # Для x86_64 Linux
            else:
                if mem_mb < 512:
                    return 'ULTRA_WEAK'
                elif mem_mb < 2048:
                    return 'WEAK'
                elif mem_mb < 8192:
                    return 'MEDIUM'
                else:
                    return 'STRONG'

        else:  # Другие ОС (macOS и др.)
            if mem_mb < 1024:
                return 'ULTRA_WEAK'
            elif mem_mb < 4096:
                return 'WEAK'
            else:
                return 'MEDIUM'  # По умолчанию для неизвестных систем

    def _get_audio_params(self):
        """Возвращает параметры аудио в зависимости от профиля."""
        if self.profile_name == 'ULTRA_WEAK':
            return {
                'frequency': 22050,
                'channels': 1,
                'silence_ms': 100,  # Увеличено для разборчивости на слабых ЦАПах
            }
        elif self.profile_name == 'WEAK':
            return {
                'frequency': 44100,
                'channels': 1,
                'silence_ms': 50,   # Больше тишины для компенсации артефактов
            }
        elif self.profile_name == 'MEDIUM':
            return {
                'frequency': 44100,
                'channels': 1,
                'silence_ms': 30,
            }
        else:  # STRONG
            return {
                'frequency': 48000,
                'channels': 1,
                'silence_ms': 20,
            }
