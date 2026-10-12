#!/bin/bash

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🤖 Запуск бота Конференции МБ 2026${NC}"

if [ ! -f .env ]; then
    echo -e "${RED}❌ Файл .env не найден!${NC}"
    echo -e "${YELLOW}Скопируйте .env.example в .env и заполните необходимые переменные.${NC}"
    exit 1
fi

echo -e "${BLUE}📦 Проверка и установка зависимостей через Poetry...${NC}"
if ! command -v poetry &> /dev/null; then
    echo -e "${RED}❌ Poetry не установлен! Установите Poetry: https://python-poetry.org/docs/#installation${NC}"
    exit 1
fi

poetry install --no-root

echo -e "${BLUE}🗄️ Применение миграций базы данных...${NC}"
poetry run alembic upgrade head || exit 1

echo -e "${GREEN}🚀 Запуск бота...${NC}"
poetry run python main.py
