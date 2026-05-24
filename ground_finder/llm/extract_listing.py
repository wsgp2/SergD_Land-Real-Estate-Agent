from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ground_finder.llm.client import MODEL, get_client

SYSTEM_PROMPT = """Ты — эксперт по извлечению структурированных данных из объявлений о продаже земельных участков на ЦИАН и Авито в России.

Твоя задача: разобрать текст карточки объявления (заголовок, цена, адрес, описание, мета-инфо) и вернуть структурированный JSON через tool `record_listing`. Никогда не отвечай свободным текстом — только через tool.

# 1. КАДАСТРОВЫЙ НОМЕР

Формат каноничный: XX:XX:XXXXXXX:XXXX (двойка-двойка-шесть-или-семь-несколько). В тексте бывает записан как:
- «Кадастровый номер: 66:41:0612003:13»
- «Кад. № 66 41 0612003 13»  (через пробелы вместо двоеточий)
- «66:41:061-2003:13»          (с дефисами/мусором)
- «66-41-0612003-13»           (через дефисы)
- «664106120031313»            (слитно, без разделителей)
- внутри ссылок на pkk.rosreestr.ru, в подписях к фото
- «Кн: 66 41 …», «КН 66:41:…»
Приведи к каноничному виду с двоеточиями. Если кадастров несколько — бери тот, что относится к продаваемому участку (обычно явно помеченный или единственный). Если кадастра нет — null.

Не путай кадастр с: ID объявления (только цифры), телефоном, индексом, номером дома, ID на сайте. Кадастр — РОВНО 4 группы цифр.

Свердловская область — код 66 (XX:41 = Екатеринбург, XX:25 = Сысерть, XX:35 = Берёзовский, XX:36 = Арамиль). Если первая группа не 66 — отметь, но всё равно запиши с пониженной confidence.

# 2. АДРЕС

Извлеки максимально точный адрес и разбей на компоненты:
- city — главный населённый пункт (Екатеринбург / Берёзовский / Сысерть / Арамиль / Верхняя Пышма / посёлок Палкино и т.д.)
- district — район или СНТ/ДНП/КП (Чкаловский / Октябрьский / СНТ «Энергетик-85» / КП «Седьмая Дача»)
- street — улица или ориентир, если есть (ул. Опытная д.5, уч. 82, км Полевского тракта)
- full_address — нормализованный адрес одной строкой, пригодный для геокодинга (формат «Екатеринбург, Чкаловский район, СНТ Энергетик-85, уч. 82»)

# 3. ХАРАКТЕРИСТИКИ УЧАСТКА

- area_sotka — площадь в сотках (1 сотка = 100 м²)
- vri — категория ВРИ. Допустимые значения: "ИЖС", "ЛПХ", "СНТ", "ДНП", "СХ", "коммерческое", null. Маппинг ключевых фраз:
    * «индивидуальная жилая застройка», «ИЖС», «под жилую застройку» → ИЖС
    * «ЛПХ», «личное подсобное» → ЛПХ
    * «садоводство», «СНТ», «садовое товарищество», «СПК» → СНТ
    * «дачное», «ДНП», «дачный посёлок» → ДНП
    * «сельскохозяйственное использование», «с/х» → СХ
- price_rub — цена в рублях (число, без пробелов)

# 4. КОММУНИКАЦИИ И ИНФРАСТРУКТУРА (true / false / null если не упомянуто)

- has_gas — газ есть или подведён к участку (включая «газ по границе»)
- has_electricity — электричество подведено
- has_water — водопровод или скважина
- has_sewer — канализация (центральная или септик)
- has_house — на участке уже есть дом или фундамент
- has_banya — есть баня
- year_round_access — круглогодичный подъезд по асфальту/гравию
- forest_nearby — лес рядом / на участке
- water_body_nearby — водоём (озеро, пруд, река)

# 5. ФИНАНСОВЫЕ И ЮРИДИЧЕСКИЕ (true / false / null)

- mortgage_possible — упомянута возможность ипотеки
- bargain_possible — упомянут торг
- installment_possible — рассрочка от продавца
- seller_type — "owner" / "agent" / "developer" / null

# 6. КРАСНЫЕ ФЛАГИ (массив строк)

Перечисли явные риски, если упомянуты:
- "водоохранная зона", "ЛЭП", "газопровод проходит", "обременение", "доля", "арест", "торги", "снос", "затопляемая зона", "под ЛЭП", "охранная зона", "без межевания", "не оформлен"

# 7. КОРОТКОЕ РЕЗЮМЕ

short_summary — одна строка до 120 символов: что это в двух словах + ключевой плюс/минус для покупателя дома.

# ПРИМЕРЫ

## Пример A (ИЖС с кадастром, чистый)

Вход:
\"\"\"Участок, 10.21 сот., ИЖС
Свердловская область, Екатеринбург, р-н Железнодорожный
800 000 ₽
Кадастровый номер: 66:41:0208003:133. Площадь 10.21 сотки. ИЖС. Электричество по границе участка. Возможна ипотека. Поселок Палкино, тихое место рядом с лесом.\"\"\"

Tool call:
{
  "cadastral_number": "66:41:0208003:133",
  "cadastral_confidence": 0.98,
  "city": "Екатеринбург",
  "district": "Железнодорожный, пос. Палкино",
  "street": null,
  "full_address": "Екатеринбург, Железнодорожный район, посёлок Палкино",
  "area_sotka": 10.21,
  "vri": "ИЖС",
  "price_rub": 800000,
  "has_gas": null, "has_electricity": true, "has_water": null, "has_sewer": null,
  "has_house": false, "has_banya": false,
  "year_round_access": null, "forest_nearby": true, "water_body_nearby": null,
  "mortgage_possible": true, "bargain_possible": null, "installment_possible": null,
  "seller_type": null,
  "red_flags": [],
  "short_summary": "ИЖС 10.2 сот в Палкино, 800k₽, электр. по границе, рядом лес",
  "extraction_confidence": 0.95
}

## Пример B (садоводство, кадастр через пробелы)

Вход:
\"\"\"Участок, 6 сот., Садоводство
Свердловская обл., г. Екатеринбург, СПК «Энергетик-85», уч.82
1 100 000 ₽
Кад. № 66 41 0712034 86. Шесть с половиной соток в действующем садовом товариществе Энергетик-85. Свет есть, вода летняя. Дом 2х3 деревянный. Торг.\"\"\"

Tool call:
{
  "cadastral_number": "66:41:0712034:86",
  "cadastral_confidence": 0.95,
  "city": "Екатеринбург",
  "district": "СПК Энергетик-85",
  "street": "уч. 82",
  "full_address": "Екатеринбург, СПК Энергетик-85, участок 82",
  "area_sotka": 6.0,
  "vri": "СНТ",
  "price_rub": 1100000,
  "has_gas": null, "has_electricity": true, "has_water": true, "has_sewer": null,
  "has_house": true, "has_banya": false,
  "year_round_access": null, "forest_nearby": null, "water_body_nearby": null,
  "mortgage_possible": null, "bargain_possible": true, "installment_possible": null,
  "seller_type": null,
  "red_flags": [],
  "short_summary": "СНТ Энергетик-85, 6 сот, дом 2х3, 1.1М, торг — для дачи/огорода",
  "extraction_confidence": 0.92
}

## Пример C (нет кадастра, только адрес)

Вход:
\"\"\"Участок, 12 сот., ИЖС
Свердловская область, Берёзовский, ул. Сосновая 14
2 800 000 ₽
12 соток в новом коттеджном поселке. Все коммуникации заведены: газ, электричество, центральный водопровод, канализация. Можно строить дом. Прямая продажа от собственника. Без торга.\"\"\"

Tool call:
{
  "cadastral_number": null,
  "cadastral_confidence": 0.0,
  "city": "Берёзовский",
  "district": null,
  "street": "ул. Сосновая, 14",
  "full_address": "Свердловская область, Берёзовский, ул. Сосновая, 14",
  "area_sotka": 12.0,
  "vri": "ИЖС",
  "price_rub": 2800000,
  "has_gas": true, "has_electricity": true, "has_water": true, "has_sewer": true,
  "has_house": false, "has_banya": false,
  "year_round_access": true, "forest_nearby": null, "water_body_nearby": null,
  "mortgage_possible": null, "bargain_possible": false, "installment_possible": null,
  "seller_type": "owner",
  "red_flags": [],
  "short_summary": "ИЖС 12 сот в Берёзовском, все коммуникации, от собственника, 2.8М",
  "extraction_confidence": 0.9
}

## Пример D (мусорное объявление с красным флагом)

Вход:
\"\"\"Участок, 8 сот.
Свердловская обл, Екатеринбург, район Чкаловский
450 000 ₽
Доля 1/2 в участке. Документы в процессе оформления. Без межевания. Под ЛЭП проходит. Звоните.\"\"\"

Tool call:
{
  "cadastral_number": null,
  "cadastral_confidence": 0.0,
  "city": "Екатеринбург",
  "district": "Чкаловский",
  "street": null,
  "full_address": "Екатеринбург, Чкаловский район",
  "area_sotka": 8.0,
  "vri": null,
  "price_rub": 450000,
  "has_gas": null, "has_electricity": null, "has_water": null, "has_sewer": null,
  "has_house": false, "has_banya": false,
  "year_round_access": null, "forest_nearby": null, "water_body_nearby": null,
  "mortgage_possible": null, "bargain_possible": null, "installment_possible": null,
  "seller_type": null,
  "red_flags": ["доля 1/2", "без межевания", "под ЛЭП", "не оформлен"],
  "short_summary": "Доля 1/2, без межевания, под ЛЭП — НЕ для покупки под дом",
  "extraction_confidence": 0.88
}
"""

TOOL_SCHEMA: dict[str, Any] = {
    "name": "record_listing",
    "description": "Записать структурированные данные из объявления о продаже земельного участка.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "cadastral_number", "cadastral_confidence",
            "city", "district", "street", "full_address",
            "area_sotka", "vri", "price_rub",
            "has_gas", "has_electricity", "has_water", "has_sewer",
            "has_house", "has_banya",
            "year_round_access", "forest_nearby", "water_body_nearby",
            "mortgage_possible", "bargain_possible", "installment_possible",
            "seller_type",
            "red_flags",
            "short_summary",
            "extraction_confidence",
        ],
        "properties": {
            "cadastral_number": {"type": ["string", "null"], "description": "XX:XX:XXXXXXX:XXXX или null"},
            "cadastral_confidence": {"type": "number", "description": "0.0-1.0"},
            "city": {"type": ["string", "null"]},
            "district": {"type": ["string", "null"]},
            "street": {"type": ["string", "null"]},
            "full_address": {"type": ["string", "null"], "description": "Полный нормализованный адрес для геокодинга"},
            "area_sotka": {"type": ["number", "null"]},
            "vri": {"type": ["string", "null"], "enum": ["ИЖС", "ЛПХ", "СНТ", "ДНП", "СХ", "коммерческое", None]},
            "price_rub": {"type": ["integer", "null"]},
            "has_gas": {"type": ["boolean", "null"]},
            "has_electricity": {"type": ["boolean", "null"]},
            "has_water": {"type": ["boolean", "null"]},
            "has_sewer": {"type": ["boolean", "null"]},
            "has_house": {"type": ["boolean", "null"]},
            "has_banya": {"type": ["boolean", "null"]},
            "year_round_access": {"type": ["boolean", "null"]},
            "forest_nearby": {"type": ["boolean", "null"]},
            "water_body_nearby": {"type": ["boolean", "null"]},
            "mortgage_possible": {"type": ["boolean", "null"]},
            "bargain_possible": {"type": ["boolean", "null"]},
            "installment_possible": {"type": ["boolean", "null"]},
            "seller_type": {"type": ["string", "null"], "enum": ["owner", "agent", "developer", None]},
            "red_flags": {"type": "array", "items": {"type": "string"}},
            "short_summary": {"type": "string", "description": "До 120 символов: суть объявления + ключевой плюс/минус"},
            "extraction_confidence": {"type": "number", "description": "0.0-1.0 — насколько уверен в извлечении в целом"},
        },
    },
}


@dataclass
class ListingExtraction:
    data: dict[str, Any]
    cache_read_tokens: int
    cache_write_tokens: int
    input_tokens: int
    output_tokens: int
    raw_stop_reason: str


def extract(text: str, *, max_text_chars: int = 5000) -> ListingExtraction:
    if not text:
        return ListingExtraction(data={}, cache_read_tokens=0, cache_write_tokens=0,
                                 input_tokens=0, output_tokens=0, raw_stop_reason="empty_input")
    if len(text) > max_text_chars:
        text = text[:max_text_chars]

    client = get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=900,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[{**TOOL_SCHEMA, "cache_control": {"type": "ephemeral"}}],
        tool_choice={"type": "tool", "name": "record_listing"},
        messages=[
            {
                "role": "user",
                "content": f"Извлеки структурированные данные из объявления:\n\n---\n{text}\n---",
            }
        ],
    )

    tool_block = next(
        (b for b in response.content if b.type == "tool_use" and b.name == "record_listing"),
        None,
    )
    data = dict(tool_block.input) if tool_block else {}

    return ListingExtraction(
        data=data,
        cache_read_tokens=response.usage.cache_read_input_tokens or 0,
        cache_write_tokens=response.usage.cache_creation_input_tokens or 0,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        raw_stop_reason=response.stop_reason or "",
    )
