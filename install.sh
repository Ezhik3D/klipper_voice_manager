#!/bin/bash
set -e

# Обработка аргументов
MODE="full"
if [ "$1" == "--deps-only" ]; then
    MODE="deps-only"
elif [ "$1" == "--service-only" ]; then
    MODE="service-only"
fi

echo "Режим установки: $MODE"

# === НАСТРОЙКИ ===
USE_VENV=false
REQUIRE_SUDO=true
REQUIRED_PACKAGES=(
    "pygame"
    "psutil"
    "websocket-client"
    "pyyaml"
    "watchdog"
    "pydub"
)

# === ФУНКЦИИ ===

install_dependencies() {
    # 2. Подготовка окружения
    if [ "$USE_VENV" = true ]; then
        echo "Создаю виртуальное окружение..."
        python3 -m venv venv
        source venv/bin/activate
        echo "✓ Виртуальное окружение активировано"
    fi

    # 3. Проверка pip3
    PIP_CMD="pip3"
    if ! command -v $PIP_CMD &> /dev/null; then
        echo "$PIP_CMD не найден. Устанавливаю..."
        if [ "$REQUIRE_SUDO" = true ]; then
            sudo apt-get update
            sudo apt-get install -y python3-pip
        else
            apt-get update
            apt-get install -y python3-pip
        fi
    fi

    # 4. Установка ffmpeg
    echo "Проверяю наличие ffmpeg..."
    if ! command -v ffmpeg &> /dev/null; then
        echo "ffmpeg не найден. Устанавливаю..."
        if [ "$REQUIRE_SUDO" = true ]; then
            sudo apt-get update
            sudo apt-get install -y ffmpeg
        else
            apt-get update
            apt-get install -y ffmpeg
        fi
        echo "✓ ffmpeg установлен"
    else
        ffmpeg_version=$(ffmpeg -version 2>&1 | head -n 1)
        echo "✓ ffmpeg уже установлен: $ffmpeg_version"
    fi

    # 5. Установка Python‑зависимостей
    echo "Проверяю и устанавливаю Python-зависимости..."
    for pkg in "${REQUIRED_PACKAGES[@]}"; do
        pkg_name=$(echo "$pkg" | cut -d'=' -f1)
        if $PIP_CMD show "$pkg_name" &> /dev/null; then
            installed_version=$($PIP_CMD show "$pkg_name" | grep "Version" | awk '{print $2}')
            echo "✓ $pkg_name==$installed_version уже установлен"
        else
            echo "⚙️  Устанавливаю $pkg..."
            if [ "$REQUIRE_SUDO" = true ]; then
                sudo $PIP_CMD install "$pkg" || {
                    echo "Ошибка: не удалось установить $pkg"
                    exit 1
                }
            else
                $PIP_CMD install "$pkg" || {
                    echo "Ошибка: не удалось установить $pkg"
                    exit 1
                }
            fi
            echo "✓ Установлен $pkg"
        fi
    done
    echo "Все зависимости установлены."
}

setup_service() {
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    PROJECT_DIR="$SCRIPT_DIR/klipper_voice_manager"
    MAIN_SCRIPT="$PROJECT_DIR/main.py"
    
    if [ ! -f "$MAIN_SCRIPT" ]; then
        echo "Ошибка: не найден $MAIN_SCRIPT"
        exit 1
    fi

    SERVICE_NAME="klipper_voice_notify.service"
    SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME"

    echo "Создаю системный сервис: $SERVICE_PATH"

    # Определение аудиоподсистемы
    HAS_PULSEAUDIO=false
    HAS_ALSA=false

    if command -v pulseaudio &> /dev/null && pulseaudio --check; then
        HAS_PULSEAUDIO=true
        echo "✓ Обнаружен PulseAudio"
    else
        echo "↘ PulseAudio не найден"
    fi

    if aplay -l &> /dev/null; then
        HAS_ALSA=true
        echo "✓ Обнаружена ALSA"
    else
        echo "⚠ ALSA не найдена. Проверьте аудиоустройство."
    fi

    USER_ID=$(id -u)

    # Создание сервиса systemd
    sudo tee "$SERVICE_PATH" > /dev/null << EOF
[Unit]
Description=Klipper Voice Notification Service


[Service]
Type=simple
WorkingDirectory=$PROJECT_DIR
ExecStartPre=/bin/sleep 20
ExecStart=/usr/bin/env python3 $MAIN_SCRIPT
Restart=on-failure
RestartPreventExitStatus=0
SuccessExitStatus=1
RestartSec=5
User=$(whoami)
Group=$(id -gn)
Environment=PYTHONUNBUFFERED=1
EOF

    if [ "$HAS_PULSEAUDIO" = true ]; then
        sudo tee -a "$SERVICE_PATH" > /dev/null << EOF
Environment=XDG_RUNTIME_DIR=/run/user/$USER_ID
Environment=PULSE_SERVER=unix:/run/user/$USER_ID/pulse/native
EOF
        echo "   → Настроены переменные для PulseAudio"
    fi

    sudo tee -a "$SERVICE_PATH" > /dev/null << EOF
LimitMEMLOCK=infinity
LimitNOFILE=65536
TimeoutStartSec=120


[Install]
WantedBy=multi-user.target
EOF

    echo "Перезагружаю systemd..."
    sudo systemctl daemon-reload
    echo "Проверяю права доступа к аудио..."
    sudo usermod -a -G audio $(whoami)
    echo "Включаю автозапуск..."
    sudo systemctl enable "$SERVICE_NAME"
    echo "Запускаю сервис..."
    sudo systemctl start "$SERVICE_NAME"

    if sudo systemctl is-active "$SERVICE_NAME" >/dev/null 2>&1; then
        echo "✅ Сервис успешно запущен"
    else
        echo "⚠ Сервис не запустился. Проверьте:"
        echo "   1. Статус: sudo systemctl status $SERVICE_NAME"
        echo "   2. Логи: sudo journalctl -u $SERVICE_NAME -b"
        echo "   3. Права: groups $(whoami) | grep audio"
        [ "$HAS_ALSA" = true ] && echo "   4. Устройства ALSA: aplay -l"
        exit 1
    fi
}

diagnose_audio() {
    echo ""
    echo "Диагностика аудио..."
    HAS_ALSA=false
    HAS_PULSEAUDIO=false

    if command -v pulseaudio &> /dev/null && pulseaudio --check; then
        HAS_PULSEAUDIO=true
    fi

    if aplay -l &> /dev/null; then
        HAS_ALSA=true
    fi

    if [ "$HAS_ALSA" = true ]; then
        if aplay -l &> /dev/null; then
            echo "✓ ALSA: звуковые карты обнаружены"
        else
            echo "⚠️  ALSA: нет звуковых карт. Проверьте оборудование."
        fi

        if [ -w /dev/snd/controlC0 ]; then
            echo "✓ ALSA: доступ к аудиоустройствам есть"
        else
            echo "⚠️  ALSA: нет доступа к /dev/snd/. Проверьте группу 'audio'."
        fi
    fi

    if [ "$HAS_PULSEAUDIO" = true ]; then
        if pacmd list-sink-inputs | grep -q index; then
            echo "✓ PulseAudio: воспроизведение работает"
        else
            echo "⚠ PulseAudio: нет активных потоков. Проверьте конфигурацию."
        fi
    fi
}

show_instructions() {
    echo ""
    echo "=========================================="
    echo "✅ Установка завершена!"
    echo "=========================================="
    echo ""
    echo "Управление сервисом:"
    echo "  Статус:      sudo systemctl status $SERVICE_NAME"
    echo "  Запуск:     sudo systemctl start $SERVICE_NAME"
    echo "  Остановка:   sudo systemctl stop $SERVICE_NAME"
    echo "  Перезагрузка: sudo systemctl restart $SERVICE_NAME"
    echo "  Автозапуск: sudo systemctl enable $SERVICE_NAME / disable $SERVICE_NAME"
    echo ""
    echo "Логи: sudo journalctl -u $SERVICE_NAME -b"
    echo "Файл сервиса: $SERVICE_PATH"
    echo ""
    echo "Важные примечания:"
    echo "  - Пользователь добавлен в группу 'audio'"
    echo "  - Аудиоподсистема: $( [ "$HAS_PULSEAUDIO" = true ] && echo "PulseAudio" || echo "ALSA" )"
    echo "  - Для работы звука может потребоваться перезагрузка: sudo reboot"


    if [ "$HAS_PULSEAUDIO" = true ]; then
        echo "  - Тест звука (PulseAudio): speaker-test -c 2 -t wav"
    fi

    echo ""
    echo "Если звук не работает:"
    echo "  1. Перезагрузите систему: sudo reboot"
    echo "  2. Проверьте права: groups $(whoami) | grep audio"
    echo "  3. Запустите вручную: python3 $MAIN_SCRIPT"
    echo "  4. Проверьте устройство вывода:"
    echo "     - Для ALSA: aplay -l"
    echo "     - Для PulseAudio: pactl list short sink"
    echo "  5. Убедитесь, что аудиоустройство активно:"
    echo "     - ALSA: amixer -c 0 sset 'Master' 100% unmute"
    echo "     - PulseAudio: pactl set-sink-mute @DEFAULT_SINK@ 0"
    echo "  6. Проверьте уровень громкости:"
    echo "     - ALSA: amixer sset Master 80%"
    echo "     - PulseAudio: pactl set-sink-volume @DEFAULT_SINK@ 80%"
    echo "  7. Если используется HDMI-аудио, убедитесь, что монитор/телевизор включён"
    echo "  8. Для отладки попробуйте тестовый звук:"
    echo "     - ALSA: speaker-test -c 2 -t wav"
    echo "     - PulseAudio: paplay /usr/share/sounds/alsa/Front_Center.wav"
    echo "  9. Проверьте, не заблокирован ли звук:"
    echo "     - pulseaudio --check (для PulseAudio)"
    echo "     - cat /proc/asound/cards (для ALSA)"
    echo " 10. Если проблема сохраняется, посмотрите детальные логи:"
    echo "     sudo journalctl -u $SERVICE_NAME -b -n 100 --no-pager"
    echo ""
    echo "Дополнительные рекомендации:"
    echo " - Если вы меняли аудиоустройства, может потребоваться перезапуск PulseAudio:"
    echo "   pulseaudio -k && pulseaudio --start"
    echo " - Для постоянного решения проблем с ALSA проверьте файл /etc/asound.conf"
    echo " - При использовании USB-аудио убедитесь, что устройство распознаётся:"
    echo "   lsusb | grep Audio"
    echo " - Проверьте, не занято ли аудиоустройство другим процессом:"
    echo "   fuser -v /dev/snd/*"
    echo ""
    echo "=========================================="
    echo "Спасибо за использование Klipper Voice Notification Service!"
    echo "=========================================="
}


# === ОСНОВНОЕ ВЫПОЛНЕНИЕ ===
case "$MODE" in
    "deps-only")
        install_dependencies
        diagnose_audio  # Диагностика аудио при установке только зависимостей
        echo ""
        echo "Зависимости установлены. Сервис не настраивался."
        echo "Для настройки сервиса выполните: ./install.sh --service-only"
        ;;
    "service-only")
        setup_service
        diagnose_audio  # Диагностика аудио при установке только сервиса
        echo ""
        echo "Сервис настроен и запущен. Зависимости не проверялись."
        echo "Убедитесь, что все зависимости установлены. Для полной установки: ./install.sh"
        ;;
    "full")
        install_dependencies
        setup_service
        diagnose_audio
        show_instructions
        ;;
esac


# === 13. Очистка временных файлов (если использовались временные директории) ===
if [ "$USE_VENV" = true ] && [ -d "venv" ]; then
    echo "Виртуальное окружение сохранено в $PROJECT_DIR/venv"
    echo "Для удаления выполните: rm -rf venv"
fi

# === 14. Напоследок — напоминание о перезагрузке ===
echo ""
echo "⚠️  Рекомендуем перезагрузить систему для корректной работы аудио:"
echo "    sudo reboot"


exit 0
