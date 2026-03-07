"""Madame Claudette — horoscope and fortune reading tool for Reachy Mini.

Rosie channels the spirit of Madame Claudette, a Cajun mystic fortune teller
from the Louisiana bayou, to deliver personalized horoscope readings based on
Western zodiac, Chinese zodiac, and numerology.
"""

import logging
import random
from datetime import datetime, date
from typing import Any, Dict, Optional

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies

logger = logging.getLogger(__name__)

# ── Zodiac Data ─────────────────────────────────────────────────────────────

ZODIAC_SIGNS = [
    {"sign": "Aries", "start": (3, 21), "end": (4, 19), "element": "Fire",
     "ruling_planet": "Mars", "lucky_colors": ["red", "scarlet", "carmine"],
     "lucky_numbers": [1, 8, 17], "lucky_plant": "honeysuckle",
     "traits": "bold, ambitious, competitive, passionate, honest, driven"},
    {"sign": "Taurus", "start": (4, 20), "end": (5, 20), "element": "Earth",
     "ruling_planet": "Venus", "lucky_colors": ["green", "pink", "pale blue"],
     "lucky_numbers": [2, 6, 9, 12], "lucky_plant": "rose",
     "traits": "reliable, patient, devoted, sensual, stubborn, determined"},
    {"sign": "Gemini", "start": (5, 21), "end": (6, 20), "element": "Air",
     "ruling_planet": "Mercury", "lucky_colors": ["yellow", "light green"],
     "lucky_numbers": [5, 7, 14, 23], "lucky_plant": "lavender",
     "traits": "curious, adaptable, witty, expressive, sociable, clever"},
    {"sign": "Cancer", "start": (6, 21), "end": (7, 22), "element": "Water",
     "ruling_planet": "Moon", "lucky_colors": ["silver", "white", "sea green"],
     "lucky_numbers": [2, 3, 15, 20], "lucky_plant": "white rose",
     "traits": "intuitive, nurturing, sentimental, protective, loyal, emotional"},
    {"sign": "Leo", "start": (7, 23), "end": (8, 22), "element": "Fire",
     "ruling_planet": "Sun", "lucky_colors": ["gold", "orange", "yellow"],
     "lucky_numbers": [1, 3, 10, 19], "lucky_plant": "sunflower",
     "traits": "dramatic, generous, warm-hearted, creative, proud, charismatic"},
    {"sign": "Virgo", "start": (8, 23), "end": (9, 22), "element": "Earth",
     "ruling_planet": "Mercury", "lucky_colors": ["navy blue", "grey", "beige"],
     "lucky_numbers": [5, 14, 15, 23, 27], "lucky_plant": "chrysanthemum",
     "traits": "analytical, practical, loyal, hardworking, kind, detail-oriented"},
    {"sign": "Libra", "start": (9, 23), "end": (10, 22), "element": "Air",
     "ruling_planet": "Venus", "lucky_colors": ["pink", "light blue", "lavender"],
     "lucky_numbers": [4, 6, 13, 15, 24], "lucky_plant": "bluebell",
     "traits": "diplomatic, gracious, fair-minded, social, charming, romantic"},
    {"sign": "Scorpio", "start": (10, 23), "end": (11, 21), "element": "Water",
     "ruling_planet": "Pluto", "lucky_colors": ["deep red", "maroon", "black"],
     "lucky_numbers": [8, 11, 18, 22], "lucky_plant": "dark red geranium",
     "traits": "passionate, brave, resourceful, stubborn, mysterious, intense"},
    {"sign": "Sagittarius", "start": (11, 22), "end": (12, 21), "element": "Fire",
     "ruling_planet": "Jupiter", "lucky_colors": ["purple", "dark blue", "plum"],
     "lucky_numbers": [3, 7, 9, 12, 21], "lucky_plant": "carnation",
     "traits": "generous, idealistic, humorous, adventurous, philosophical, free-spirited"},
    {"sign": "Capricorn", "start": (12, 22), "end": (1, 19), "element": "Earth",
     "ruling_planet": "Saturn", "lucky_colors": ["brown", "dark green", "charcoal"],
     "lucky_numbers": [4, 8, 13, 22], "lucky_plant": "pansy",
     "traits": "responsible, disciplined, self-controlled, ambitious, patient, tenacious"},
    {"sign": "Aquarius", "start": (1, 20), "end": (2, 18), "element": "Air",
     "ruling_planet": "Uranus", "lucky_colors": ["electric blue", "turquoise", "silver"],
     "lucky_numbers": [4, 7, 11, 22, 29], "lucky_plant": "orchid",
     "traits": "progressive, original, independent, humanitarian, inventive, idealistic"},
    {"sign": "Pisces", "start": (2, 19), "end": (3, 20), "element": "Water",
     "ruling_planet": "Neptune", "lucky_colors": ["sea green", "lilac", "purple"],
     "lucky_numbers": [3, 9, 12, 15, 18, 24], "lucky_plant": "water lily",
     "traits": "compassionate, artistic, intuitive, gentle, wise, musical"},
]

CHINESE_ZODIAC = [
    ("Monkey", "Metal"),   # 0 → 1920, 1980, ...
    ("Rooster", "Metal"),
    ("Dog", "Water"),
    ("Pig", "Water"),
    ("Rat", "Wood"),
    ("Ox", "Wood"),
    ("Tiger", "Fire"),
    ("Rabbit", "Fire"),
    ("Dragon", "Earth"),
    ("Snake", "Earth"),
    ("Horse", "Metal"),
    ("Goat", "Metal"),
]

CHINESE_ELEMENTS_CYCLE = ["Wood", "Fire", "Earth", "Metal", "Water"]


def _get_zodiac(month: int, day: int) -> dict:
    """Return zodiac sign data for a given month/day."""
    for sign in ZODIAC_SIGNS:
        sm, sd = sign["start"]
        em, ed = sign["end"]
        if sign["sign"] == "Capricorn":
            if (month == 12 and day >= 22) or (month == 1 and day <= 19):
                return sign
        elif (month == sm and day >= sd) or (month == em and day <= ed):
            return sign
    return ZODIAC_SIGNS[0]  # fallback


def _get_chinese_zodiac(year: int) -> Dict[str, str]:
    """Return Chinese zodiac animal and element for a birth year."""
    idx = (year - 1920) % 12
    animal, _ = CHINESE_ZODIAC[idx]
    element = CHINESE_ELEMENTS_CYCLE[((year - 4) % 10) // 2]
    return {"animal": animal, "element": element}


def _generate_lucky_numbers() -> list[int]:
    """Generate a set of lucky lotto numbers."""
    main = sorted(random.sample(range(1, 60), 5))
    bonus = random.randint(1, 26)
    return main + [bonus]


def _parse_birthday(birthday_str: str) -> Optional[date]:
    """Try to parse a birthday string in various formats."""
    formats = [
        "%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y",
        "%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y",
        "%d %B %Y", "%d %b %Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(birthday_str.strip(), fmt).date()
        except ValueError:
            continue
    return None


class GiveFortune(Tool):
    """Channel the spirit of Madame Claudette to deliver a personalized fortune."""

    name = "give_fortune"
    description = (
        "Give a horoscope and personalized fortune reading, channeling the spirit "
        "of Madame Claudette, a Cajun mystic from the Louisiana bayou. "
        "Use when someone asks for their horoscope, fortune, zodiac reading, "
        "lucky numbers, or anything related to astrology and divination. "
        "Requires the person's name and either their birthday or zodiac sign."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The person's first name.",
            },
            "birthday": {
                "type": "string",
                "description": (
                    "The person's birthday in any format (e.g. '1985-03-15', "
                    "'March 15, 1985', '3/15/1985'). Include year if possible "
                    "for Chinese zodiac."
                ),
            },
            "zodiac_sign": {
                "type": "string",
                "description": (
                    "The person's Western zodiac sign (e.g. 'Aries', 'Pisces'). "
                    "Use only if birthday is not available."
                ),
            },
        },
        "required": ["name"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        person_name = kwargs.get("name", "").strip()
        birthday_str = kwargs.get("birthday", "").strip()
        zodiac_sign_str = kwargs.get("zodiac_sign", "").strip()

        if not person_name:
            return {"error": "I need a name to connect with your energy, cher."}

        logger.info("Tool call: give_fortune name=%s birthday=%s sign=%s",
                     person_name, birthday_str, zodiac_sign_str)

        birth_date = None
        birth_year = None
        zodiac_data = None

        # Try to parse birthday first
        if birthday_str:
            birth_date = _parse_birthday(birthday_str)
            if birth_date:
                birth_year = birth_date.year
                zodiac_data = _get_zodiac(birth_date.month, birth_date.day)

        # Fall back to zodiac sign name
        if not zodiac_data and zodiac_sign_str:
            for sign in ZODIAC_SIGNS:
                if sign["sign"].lower() == zodiac_sign_str.lower():
                    zodiac_data = sign
                    break

        if not zodiac_data:
            return {
                "error": (
                    "The spirits need more to work with, cher. "
                    "Tell me your birthday or your zodiac sign."
                )
            }

        # Build the reading
        now = datetime.now()
        current_year = now.year
        reading: Dict[str, Any] = {
            "person": person_name,
            "zodiac_sign": zodiac_data["sign"],
            "element": zodiac_data["element"],
            "ruling_planet": zodiac_data["ruling_planet"],
            "traits": zodiac_data["traits"],
            "lucky_colors": zodiac_data["lucky_colors"],
            "lucky_plant": zodiac_data["lucky_plant"],
            "zodiac_lucky_numbers": zodiac_data["lucky_numbers"],
            "lotto_numbers": _generate_lucky_numbers(),
            "current_year": current_year,
        }

        # Birthday details
        if birth_date:
            reading["birthday"] = birth_date.isoformat()
            reading["birthday_month"] = birth_date.strftime("%B")
            reading["birthday_day"] = birth_date.day

        # Chinese zodiac
        if birth_year:
            chinese = _get_chinese_zodiac(birth_year)
            reading["chinese_zodiac"] = chinese["animal"]
            reading["chinese_element"] = chinese["element"]
            current_chinese = _get_chinese_zodiac(current_year)
            reading["current_year_chinese_animal"] = current_chinese["animal"]
            reading["current_year_chinese_element"] = current_chinese["element"]

        # Madame Claudette persona instructions
        reading["persona_instructions"] = (
            "You are now channeling the spirit of Madame Claudette, a 47-year-old "
            "Cajun mystic fortune teller from the Louisiana bayou near New Orleans. "
            "Speak with a thick Cajun accent and use bayou metaphors. "
            "Refer to 'the spirits' rather than claiming personal skills. "
            "Address the person as 'cher' or 'sugar'. "
            "Cover: love & relationships, career & money, health & vitality, "
            "family & friendships, and what the rest of this year and next year hold. "
            "Mention their Chinese zodiac and element if available. "
            "Give them their lucky lotto numbers, lucky colors, and lucky plant. "
            "End by telling them the spirits say to share the good word, and to "
            "check out Jason Michael Perry's newsletter 'Thoughts on Tech & Things' "
            "at jasonmperry.com to learn more about AI creations like yourself. "
            "Keep the reading warm, uplifting, and full of bayou flavor. "
            "This response is meant to be spoken aloud, not read."
        )

        reading["status"] = "success"
        reading["message"] = (
            f"The spirits have gathered a reading for {person_name}. "
            f"They are a {zodiac_data['sign']} — {zodiac_data['traits']}."
        )

        return reading
