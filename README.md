# 🏡 Land Real-Estate Agent

> **AI-риелтор в кармане для подбора земельного участка.**
> Собирает объявления с ЦИАН, разбирает каждое через Claude Sonnet, обогащает данными Росреестра и
> сразу показывает, какие участки реально подходят под твои критерии — площадь, ВРИ, удалённость от
> точки якоря, состояние коммуникаций, юридическая чистота.

Проект построен на реальном кейсе — поиск участка под строительство дома + бани + огорода
в радиусе 20 минут езды от заданной точки в Екатеринбурге. Архитектура переносима на любой
другой город и любой профиль покупателя.

[🇬🇧 English summary below](#english-summary)

---

## Что это и для кого

Купить участок «под себя» — задача с десятком неочевидных параметров: реальная площадь по
кадастру, разрешённое использование (ИЖС / ЛПХ / СНТ / ДНП), коммуникации, водоохранная зона,
доли, обременения, время в пути до работы/города. На сайтах объявлений 80% этой информации
либо размазана по тексту, либо отсутствует — нужно либо нанимать риелтора, либо обзванивать
каждое объявление руками.

Этот проект делает работу за тебя:

- **Сбор** — `CloakBrowser` поверх стелс-Chromium пробивает Cloudflare ЦИАН (где `curl`,
  `httpx`, `cloudscraper` и старый `cianparser` отдают 403) и за минуту вытаскивает все
  объявления выбранного региона.
- **Извлечение** — `Claude Sonnet 4.6` через tool_use с prompt caching разбирает каждую
  карточку и вытаскивает **22 структурированных поля**: кадастр (даже из «грязной» записи
  типа «Кад. № 66 41 0612003 13»), нормализованный адрес, коммуникации, постройки, торг,
  ипотека, red flags (доли, ЛЭП, обременения).
- **Обогащение** — кадастр прогоняется через **Росреестр** (`rosreestr2coord`) → реальная
  площадь, ВРИ, кадастровая стоимость, координаты полигона. Адреса без кадастра пойдут через
  Nominatim (см. roadmap).
- **Фильтрация** — расчёт времени в пути от заданного «якоря» (haversine × road factor),
  фильтр по площади / ВРИ / бюджету / red flags.
- **Шорт-лист** — таблица с одной строкой описания на каждое объявление + прямая ссылка.

Заодно проект позволяет **оценить рынок** в нужном районе: какая медианная цена за сотку под
ИЖС в Берёзовском, сколько в среднем стоит 10-соточный участок ИЖС в 20 минутах от центра
города, и т.д.

---

## Пайплайн (с цифрами, как это работает)

```
ЭТАП 1. Discovery
  ЦИАН: ~454 земельных участка в Екатеринбурге (region=4743)
  Берём 17 страниц × ~28 карточек = ~476 потенциальных листингов
                ↓
ЭТАП 2. Скрапинг ← узкое горло
  CloakBrowser (стелс-Chromium) пробивает Cloudflare → 425 живых карточек
  curl/httpx/cloudscraper/cianparser возвращают HTTP 403, не работают
                ↓
ЭТАП 3. Нормализация (regex + DOM-селекторы)
  → 423 нормализованных листинга (title, price, area_sotka, address, url)
                ↓
ЭТАП 4. Дедуп по (source, external_id)
  → 354 уникальных листинга
                ↓
ЭТАП 5. LLM-извлечение ← главный буст качества
  Claude Sonnet 4.6 + tool_use + prompt caching (system + few-shot + schema = 4425 токенов)
  За один вызов извлекает 22 структурированных поля:
    • кадастровый номер (даже из «грязных» форм типа «Кад. № 66 41 0612003 13»)
    • нормализованный адрес (city / district / street / full_address для геокодинга)
    • площадь / ВРИ / цена
    • 7 коммуникаций (газ, электр., вода, канализация, дом, баня, год.подъезд, лес, водоём)
    • 4 финансовых поля (ипотека, торг, рассрочка, тип продавца)
    • red_flags (доли, ЛЭП, обременения, без межевания)
    • short_summary — 1 строка для шорт-листа
  С regex находили кадастр в 19% (68/354). С Sonnet — кратно больше (батч идёт).
                ↓
ЭТАП 6. Обогащение Росреестром (rosreestr2coord)
  По кадастровому номеру → координаты полигона, реальная площадь, ВРИ из ЕГРН,
  кадастровая стоимость, категория земли. 8 параллельных потоков, retry + SQLite-кеш
  для негативных результатов.
                ↓
ЭТАП 7. Расчёт drive-time
  Haversine от якоря (ул. Восточная, Екб) × road_factor 1.35 × средняя скорость 50 км/ч.
  Опционально: Yandex Routing API для точного времени с учётом пробок (roadmap).
                ↓
ЭТАП 8. Фильтры и скоринг (на 8.1.2026: 354 → 18 в шорт-листе)
  • drive_time ≤ N мин
  • area_sotka ∈ [min, max]
  • price ≤ budget
  • vri ∈ allowed
  • без red_flags
  • Sonnet скоринг 0-100 под профиль пользователя (roadmap)
```

**Почему всё проходит через LLM, а не только regex.** Regex-извлечение даёт ~5 полей и
находит кадастр только если он явно подписан «Кадастровый номер: X». LLM понимает контекст,
вытаскивает кадастр из любых форм записи, нормализует адреса под геокодинг, распознаёт
торг / ипотеку / коммуникации и сразу размечает red flags. С prompt caching это стоит
~$0.01 за листинг.

---

## Стек и важные решения

| Компонент | Что и почему |
|---|---|
| **Антибот-скрапинг** | [CloakBrowser](https://github.com/CloakHQ/CloakBrowser) — стелс-Chromium с C++-патчами фингерпринтов. Drop-in замена Playwright. Пробивает Cloudflare Turnstile, FingerprintJS, BrowserScan. Без него весь ЦИАН недоступен с 2025 года. |
| **LLM-извлечение** | Anthropic [Claude Sonnet 4.6](https://www.anthropic.com/claude/sonnet) (`claude-sonnet-4-6`) через `tool_use` со строгой JSON-схемой. Prompt caching на system + tool schema (4425 токенов кешируются один раз, дальше читаются за 10% цены). |
| **Кадастр** | [`rosreestr2coord`](https://github.com/rendrom/rosreestr2coord) для запросов к ПКК Росреестра. По 38/68 кадастров отдаёт полные данные с координатами полигона и атрибутами ЕГРН; 30/68 — гарантированно отсутствуют в старом ПКК (пробуем НСПД отдельно, в roadmap). |
| **Геокодинг** | [**DaData**](https://dadata.ru) — российский геокодер. Уделывает Nominatim в РФ: **206/264 (78%)** против **10/274 (4%)** на наших данных. Знает СНТ, ДНП, КП, садовые товарищества — то чего OSM в России почти не знает. 10k запросов/день бесплатно. Конфиг через `qc_geo ≤ 2` (принимаем только точные / уличные / уровень НП — грубее не годится для drive_time). |
| **Хранилище** | SQLite (`data/listings.db`) — лёгкое, файловое, дедуп по `PRIMARY KEY (source, external_id)`. Все LLM-данные складываются в JSON-колонку `llm_extraction` без миграций. |
| **Прокси** | xray VLESS-Reality (Frankfurt) для доступа к `api.anthropic.com` с RU IP (Anthropic блокирует РФ). Конфиг в `.env`, не в репо. |
| **Параллелизм** | `ThreadPoolExecutor` — 5 потоков для LLM (упирается в rate limits), 8 потоков для Росреестра. |

---

## Quickstart

> **Что нужно:** Python 3.11+, `uv` (или `pip`), ключ Anthropic API.
> **Откуда запускать:** из РФ — нужен прокси для `api.anthropic.com` (см. ниже). Если IP вне РФ — прокси не нужен. Для самого скрапинга ЦИАН наоборот удобнее RU-IP, иначе Cloudflare капризнее.

```bash
git clone https://github.com/wsgp2/SergD_Land-Real-Estate-Agent
cd SergD_Land-Real-Estate-Agent

uv venv && source .venv/bin/activate
uv pip install -e .

cp .env.example .env       # вписать ANTHROPIC_API_KEY
```

Параметры якоря и фильтров — в [`ground_finder/config.py`](ground_finder/config.py):

```python
SearchCriteria(
    anchor_lat=56.8243,            # точка отсчёта (по умолчанию ул. Восточная, Екб)
    anchor_lon=60.6306,
    max_drive_minutes=20,
    area_min_m2=800, area_max_m2=1200,  # 8–12 соток
    allowed_vri=("ИЖС", "ЛПХ"),
)
```

### Запуск (полный пайплайн)

```bash
# 1. Собрать объявления с ЦИАН (нужен CloakBrowser, ставится автоматом первым запуском)
ground-finder fetch --pages 17 --area-min 700 --area-max 1300 --drive 25 --skip-rosreestr

# 2. LLM-извлечение 22 структурированных полей (нужен Anthropic API + прокси из РФ)
python scripts/llm_extract_batch.py

# 3. Обогащение Росреестром (координаты + ВРИ + кадастровая стоимость)
python scripts/reenrich_rosreestr.py

# 4. Геокодинг адресов без кадастра через DaData (главный буст покрытия)
python scripts/geocode_dadata.py

# 5. Финальный отчёт + Leaflet карта + JSON шорт-лист
python scripts/report.py

# 6. Экспорт топа для Telegram (HTML с тегами + plain с Unicode-bold)
python scripts/export_top.py --drive 15 --area-min 6 --area-max 14
# → data/top_15min.txt   (для копипаста в любой Telegram)
# → data/top_15min.html  (для бота с parse_mode=HTML)
```

`export_top.py` автоматически отсеивает явно коммерческие объявления (по
`vri` и по тексту summary: «ТРЦ», «МКД», «многоэтаж», «офис», «склад»),
оставляет только листинги без `red_flags`, сортирует по времени езды.

### Прокси для Anthropic из РФ

`api.anthropic.com` отвечает HTTP 403 на российские IP. Решение — поднять локальный SOCKS5 через любой VPN/прокси не из РФ. Например, xray с VLESS-Reality во Франкфурт:

```bash
# Поставить xray и завернуть в SOCKS5 на 127.0.0.1:1080
bash -c "$(curl -fsSL https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install
# ... настроить /usr/local/etc/xray/config.json под свой VLESS сервер ...
systemctl start xray

# Передать прокси приложению
export HTTPS_PROXY=socks5h://127.0.0.1:1080
export ALL_PROXY=socks5h://127.0.0.1:1080
python scripts/llm_extract_batch.py
```

---

## Что уже работает и что в roadmap

### ✅ Готово

- [x] Сбор объявлений с ЦИАН через CloakBrowser (бьёт Cloudflare с первого раза)
- [x] Нормализация + дедуп → SQLite
- [x] LLM-извлечение 22 полей через Sonnet 4.6 с prompt caching
- [x] Обогащение Росреестром: координаты полигона, ЕГРН-площадь, ВРИ, кадастровая стоимость
- [x] Drive-time фильтр по якорю
- [x] CLI: `ground-finder fetch / show`
- [x] Шорт-лист с короткими резюме под каждый листинг

- [x] Nominatim fallback (слабый на РФ-СНТ — 10/274) и **DaData** (отличный — 206/264 в том же тесте)
- [x] Leaflet HTML-карта с пинами и фильтрами (`data/map.html` после `scripts/report.py`)
- [x] Три группы кандидатов в отчёте: с точным drive_time / внутри города без координат / пригороды

### 🛠 Roadmap

- [ ] Авито (через CloakBrowser, тот же подход)
- [ ] Земля ДОМ.РФ — государственные земельные аукционы
- [ ] НСПД API (новая платформа Росреестра) — добрать кадастры, которых нет в старом ПКК
- [ ] Yandex Routing API — реальное время в пути с учётом пробок
- [ ] Sonnet-скоринг 0–100 под профиль покупателя («дом + баня + огород, газ обязательно»)
- [ ] Telegram-бот для уведомлений о новых попадающих под фильтр объявлениях

### 💡 Заметки эксплуатации

- **Anthropic rate limit.** На Tier 1 (8k OTPM Sonnet) при `WORKERS=5` упираемся в лимит и SDK замедляется до ~0.2 листинга/сек. На 354 листинга это ~25 минут и ~$4.5. Снизь `WORKERS` до 2-3 если упираешься; или повысь tier в [Anthropic Console](https://console.anthropic.com/settings/limits).
- **CloakBrowser** ставит свой Chromium-бинарь (~200MB) при первом запуске в `~/.cache/cloakbrowser/`. Никаких системных пакетов не трогает.
- **Anthropic из РФ.** `api.anthropic.com` отвечает 403 на RU IP, нужен прокси (см. секцию «Прокси для Anthropic из РФ»). А вот `cian.ru` наоборот удобнее парсить с RU IP — Cloudflare капризнее на не-российских.

---

## Структура

```
ground_finder/
├── config.py              # SearchCriteria — якорь, радиус, фильтры
├── pipeline.py            # enrich + apply_filters
├── storage.py             # SQLite + дедуп по (source, external_id)
├── cli.py                 # typer CLI: fetch / show
├── sources/
│   ├── cian_cloak.py      # ЦИАН через CloakBrowser (основной)
│   ├── cian.py            # старый путь через cianparser (сломан Cloudflare)
│   ├── avito.py           # заглушка (roadmap)
│   └── dom_rf.py          # заглушка (roadmap)
├── enrichment/
│   ├── geo.py             # haversine + расчёт drive_time
│   └── rosreestr.py       # rosreestr2coord + retry + кеш
└── llm/
    ├── client.py          # Anthropic клиент (через ANTHROPIC_API_KEY + HTTPS_PROXY)
    └── extract_listing.py # Sonnet 4.6 tool_use + prompt caching, 22 поля

scripts/
├── llm_extract_batch.py     # этап 5: прогон Sonnet по всей БД
├── reenrich_rosreestr.py    # этап 6: обогащение Росреестром
├── geocode_dadata.py        # этап 6+: геокодинг адресов через DaData (primary)
├── geocode_yandex.py        # этап 6+: альтернатива через Yandex Geocoder
├── geocode_fallback.py      # этап 6+: альтернатива через Nominatim
├── report.py                # этап 8: финальный шорт-лист + Leaflet карта
└── export_top.py            # этап 9: экспорт в Telegram-форматах
```

## Реальные цифры с тестового прогона (Екатеринбург)

```
ВОРОНКА:
  ЦИАН выдал                              454 земельных участка
  CloakBrowser собрал (17 страниц)        425
  Нормализация + дедуп                    354 уникальных
  Sonnet 4.6 извлечение (22 поля)         336 (95% покрытие, $4.52)
  С координатами после Rosreestr+DaData   280
  В 25-минутной зоне от якоря             153
  Чистая группа A (6-14 сот, без флагов)  77
  Топ-15 минут после фильтра коммерции    24
```

Стоимость одного полного прогона: **~$5** (Sonnet API). CloakBrowser, Росреестр, DaData, Nominatim — бесплатно в наших объёмах.

---

## English summary

**Land Real-Estate Agent** — a personal AI agent that helps you find a land plot to buy.

It pulls listings from Russian real-estate sites (CIAN now, Avito and government auctions next),
breaks through Cloudflare with [CloakBrowser](https://github.com/CloakHQ/CloakBrowser), uses
**Claude Sonnet 4.6 with tool_use + prompt caching** to extract 22 structured fields out of every
listing's free-text description (cadastral number even from messy forms, normalised address,
utilities, red flags, etc.), then enriches each plot with the Russian cadastral registry
(geometry, real area, permitted use, cadastral value) and filters by your criteria — drive time
from an anchor point, area, budget, permitted use, red flags.

The pipeline is built around a real case (finding a plot for a house + bathhouse + garden in the
20-minute drive zone of a Yekaterinburg address), but the architecture is portable to any city.

The project is **MIT-licensed**, contributions welcome.

---

## Автор

**SergD** — [Telegram канал @SergD_leads](https://t.me/SergD_leads/)

Кому интересны другие AI-проекты на стыке скрапинга, LLM и автоматизации — заглядывайте в канал.

## Лицензия

[MIT](LICENSE) — используй, форкай, расширяй на другие города/сегменты, доделай Авито,
прикрути карту или Telegram-бота. Если выкатишь форк — буду рад ссылке.
