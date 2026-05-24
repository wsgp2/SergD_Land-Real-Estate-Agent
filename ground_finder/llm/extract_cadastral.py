from __future__ import annotations

import json
from dataclasses import dataclass

from ground_finder.llm.client import MODEL, get_client

SYSTEM_PROMPT = """Ты эксперт по российским кадастровым номерам в объявлениях о продаже земельных участков.

Кадастровый номер в РФ имеет каноничный формат: XX:XX:XXXXXXX:XXXX
— это «двойка-двойка-шесть-или-семь-несколько»: код субъекта, код района, код квартала, номер участка.
Пример: 66:41:0612003:13 (Свердловская область, Чкаловский р-н Екатеринбурга).

В тексте объявлений ЦИАН/Авито кадастровый номер может быть записан в любом из этих видов:
- «Кадастровый номер: 66:41:0612003:13»
- «Кад.№ 66 41 0612003 13»  (через пробелы вместо двоеточий)
- «66:41:061-2003:13»        (с дефисами/мусором)
- «664106120031» / «6641 0612003 13»  (слитно или с разрывами)
- «66-41-0612003-13»         (через дефисы)
- внутри подписи к фото или ссылки на ПКК
- может быть несколько кадастров — выбирай тот, который относится к продаваемому участку (обычно первый или явно помеченный)

ВАЖНО:
1. Если нашёл — приведи к каноничному виду XX:XX:XXXXXXX:XXXX (двоеточия, без пробелов и дефисов).
2. Не выдумывай. Если не уверен — confidence ≤ 0.5. Если кадастра в тексте нет — cadastral_number: null, confidence: 0.0.
3. Не путай кадастровый номер с телефоном, ID объявления, индексом, номером дома.
   Узнать кадастр: ровно 4 группы цифр, первая 2 цифры (код субъекта), вторая 2, третья 6 или 7, четвёртая 1-6 цифр.
4. Свердловская область — код 66. Если первая группа другая — это либо ошибка, либо участок не в Свердловской.
   Не отбрасывай — просто отметь нормально и пониженной confidence (~0.7).

Используй tool `record_cadastral` для ответа. Никогда не отвечай свободным текстом."""


TOOL_SCHEMA = {
    "name": "record_cadastral",
    "description": "Записать извлечённый кадастровый номер.",
    "input_schema": {
        "type": "object",
        "properties": {
            "cadastral_number": {
                "type": ["string", "null"],
                "description": "Кадастровый номер в каноничном виде XX:XX:XXXXXXX:XXXX, или null если не найден.",
            },
            "confidence": {
                "type": "number",
                "description": "От 0.0 до 1.0 — насколько уверен в правильности извлечения.",
            },
            "raw_form": {
                "type": ["string", "null"],
                "description": "Как именно кадастр был записан в исходном тексте (для аудита).",
            },
            "reasoning": {
                "type": "string",
                "description": "1-2 предложения почему именно так / почему не найден.",
            },
        },
        "required": ["cadastral_number", "confidence", "raw_form", "reasoning"],
        "additionalProperties": False,
    },
}


@dataclass
class CadastralExtraction:
    cadastral_number: str | None
    confidence: float
    raw_form: str | None
    reasoning: str
    cache_read_tokens: int
    cache_write_tokens: int
    input_tokens: int
    output_tokens: int


def extract(text: str, *, max_text_chars: int = 4000) -> CadastralExtraction:
    if len(text) > max_text_chars:
        text = text[:max_text_chars]

    client = get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=400,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[{**TOOL_SCHEMA, "cache_control": {"type": "ephemeral"}}],
        tool_choice={"type": "tool", "name": "record_cadastral"},
        messages=[
            {
                "role": "user",
                "content": f"Извлеки кадастровый номер из текста объявления:\n\n---\n{text}\n---",
            }
        ],
    )

    tool_block = next(
        (b for b in response.content if b.type == "tool_use" and b.name == "record_cadastral"),
        None,
    )
    if tool_block is None:
        return CadastralExtraction(
            cadastral_number=None,
            confidence=0.0,
            raw_form=None,
            reasoning="LLM did not return tool_use block",
            cache_read_tokens=response.usage.cache_read_input_tokens or 0,
            cache_write_tokens=response.usage.cache_creation_input_tokens or 0,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

    data = tool_block.input
    return CadastralExtraction(
        cadastral_number=data.get("cadastral_number"),
        confidence=float(data.get("confidence", 0.0)),
        raw_form=data.get("raw_form"),
        reasoning=data.get("reasoning", ""),
        cache_read_tokens=response.usage.cache_read_input_tokens or 0,
        cache_write_tokens=response.usage.cache_creation_input_tokens or 0,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )


if __name__ == "__main__":
    sample = """Участок, 10 сот., ИЖС
    Кад. № 66 41 0612003 13
    Свердловская область, Екатеринбург, ул. Опытная, д.5
    Газ по границе, электричество. Возможна ипотека.
    """
    print(json.dumps(extract(sample).__dict__, ensure_ascii=False, indent=2))
