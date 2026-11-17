"""Text helpers shared by the station loader, place lookup, and geocode cache."""
import hashlib
import re

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
STATE_BY_NAME = {name.lower(): code for code, name in US_STATES.items()}

_PREFIXES = {"st": "saint", "ste": "sainte", "ft": "fort", "mt": "mount"}


def city_key(name: str) -> str:
    """Normalise a city name for matching ("St. Louis" -> "saintlouis")."""
    words = re.sub(r"[^\w\s]", " ", name.lower()).split()
    if words and words[0] in _PREFIXES:
        words[0] = _PREFIXES[words[0]]
    return "".join(words)


def state_code(value: str):
    """'TX' or 'Texas' -> 'TX'; anything else -> None."""
    value = value.strip()
    if value.upper() in US_STATES:
        return value.upper()
    return STATE_BY_NAME.get(value.lower())


def query_key(text: str) -> str:
    """Normalise a place query so 'Dallas,TX', ' dallas , tx ', 'Dallas, Texas' all share a cache row."""
    cleaned = re.sub(r"\s+", " ", text.strip().lower())
    # Expand full state names to the 2-letter code so variants collapse.
    if "," in cleaned:
        city, _, tail = cleaned.rpartition(",")
        code = state_code(tail.strip())
        if code:
            cleaned = f"{city.strip()}, {code.lower()}"
    return cleaned


def address_hash(address: str, city: str, state: str) -> str:
    """Stable hash used to detect when a station's address changed and it needs re-geocoding."""
    raw = f"{address.strip().lower()}|{city.strip().lower()}|{state.strip().upper()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()
