"""Offline metadata expansion and AND queries for the replay library."""
from functools import lru_cache
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys
import unicodedata


def normalize(value):
    text = unicodedata.normalize("NFKD", str(value)).casefold()
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w]+|_", " ", text).split())


def query_terms(query):
    """Double quotes group phrases; an unfinished quote remains usable while typing.

    Apostrophes and backslashes are literal, including in hero names and paths.
    """
    terms, current, quoted = [], [], False
    for character in query:
        if character == '"':
            quoted = not quoted
        elif not quoted and (character.isspace() or character == ','):
            if current:
                terms.append("".join(current))
                current = []
        else:
            current.append(character)
    if current:
        terms.append("".join(current))
    return tuple(dict.fromkeys(term.casefold() for term in terms if term.strip()))


def text_match(term, text):
    if len(term) <= 2 and term.isalnum():
        return re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text) is not None
    return term in text


@lru_cache(maxsize=1)
def hero_metadata():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets"
    try:
        icons = json.loads((root / "heroes.json").read_text(encoding="utf-8"))["heroes"]
    except (OSError, ValueError, KeyError):
        icons = {}
    try:
        snapshot = json.loads((root / "hero_search.json").read_text(encoding="utf-8"))
        rows = snapshot["heroes"]
    except (OSError, ValueError, KeyError):
        rows = []
    by_id = {str(row["id"]): row for row in rows}
    icons_by_id = {str(icon["id"]): (internal, icon) for internal, icon in icons.items()}
    lookup = {}
    for identifier in by_id.keys() | icons_by_id.keys():
        internal, icon = icons_by_id.get(identifier, ("", {}))
        row = by_id.get(identifier, {})
        names = [internal, icon.get("name", ""), row.get("localized_name", ""), *row.get("aliases", [])]
        terms = tuple(normalize(name) for name in names if name)
        abbreviations = frozenset(normalize(name).replace(" ", "") for name in row.get("abbreviations", []))
        descriptor = (terms, abbreviations)
        for identity in (internal, "npc_dota_hero_" + internal if internal else "", identifier, "Hero #" + identifier, icon.get("name", ""), row.get("localized_name", "")):
            if identity:
                lookup[normalize(identity)] = descriptor
    return lookup


def hero_match(term, hero):
    names, abbreviations = hero_metadata().get(normalize(hero), ((normalize(hero),), frozenset()))
    normalized = normalize(term)
    compact = normalized.replace(" ", "")
    if not compact:
        return False
    if compact in abbreviations:
        return True
    return any(text_match(normalized, name) or (len(compact) > 2 and compact in name.replace(" ", "")) for name in names)


def scalar_values(value, include_chat=True):
    """Values, never JSON property names; repeated parser fields are deduplicated."""
    if isinstance(value, dict):
        for key, child in value.items():
            # Index the selected transcript once, not again for every cached copy.
            if key != "chat" or include_chat:
                yield from scalar_values(child, include_chat and key != "local_results")
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from scalar_values(child, include_chat)
    elif value is not None:
        yield str(value).casefold()


@dataclass(frozen=True)
class PreparedText:
    raw: str
    normalized: str
    raw_words: frozenset
    normalized_words: frozenset


def prepare_text(values):
    fields = set(values)
    # NUL separators preserve per-field phrase matching and regex boundaries.
    raw = "\0".join(fields)
    normalized = "\0".join(normalize(field) for field in fields)
    return PreparedText(raw, normalized, frozenset(re.findall(r"\w+", raw)), frozenset(re.findall(r"\w+", normalized)))


@dataclass(frozen=True)
class CompiledTerm:
    raw: str
    normalized: str
    raw_pattern: object
    normalized_pattern: object
    heroes: frozenset
    compact: str

    def matches_text(self, text):
        return (self.raw in text.raw_words if self.raw_pattern else self.raw in text.raw) or (
            bool(self.normalized) and (self.normalized in text.normalized_words
                                      if self.normalized_pattern else self.normalized in text.normalized))


def short_pattern(term):
    return re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)") if len(term) <= 2 and term.isalnum() else None


@lru_cache(maxsize=128)
def compile_terms(terms):
    compiled = []
    descriptors = set(hero_metadata().values())
    for term in terms:
        normalized = normalize(term)
        compact = normalized.replace(" ", "")
        heroes = frozenset(descriptor for descriptor in descriptors if compact and (
            compact in descriptor[1] or any(text_match(normalized, name) or (
                len(compact) > 2 and compact in name.replace(" ", "")) for name in descriptor[0])))
        compiled.append(CompiledTerm(term, normalized, short_pattern(term), short_pattern(normalized), heroes, compact))
    return tuple(compiled)


DYNAMIC_FIELDS = ("notes", "rating", "client_override")


@dataclass
class SearchDocument:
    base: PreparedText
    heroes: frozenset
    unknown_heroes: tuple
    accounts: frozenset
    dynamic_values: tuple
    dynamic: PreparedText

    def refresh_dynamic(self, match):
        values = tuple(match.get(key) for key in DYNAMIC_FIELDS)
        if values != self.dynamic_values:
            self.dynamic_values = values
            self.dynamic = prepare_text(scalar_values(values))

    def matches(self, terms, nicknames):
        return all(bool(term.heroes & self.heroes)
                   or term.matches_text(self.base) or term.matches_text(self.dynamic)
                   or any(term.matches_text(nicknames[account]) for account in self.accounts if account in nicknames)
                   or (len(term.compact) > 2 and any(term.compact in hero for hero in self.unknown_heroes))
                   for term in terms)


def prepare_document(match):
    lookup = hero_metadata()
    players = match.get("players", [])
    identities = {normalize(player.get("hero", "")) for player in players}
    dynamic_values = tuple(match.get(key) for key in DYNAMIC_FIELDS)
    return SearchDocument(
        prepare_text(scalar_values({key: value for key, value in match.items() if key not in DYNAMIC_FIELDS})),
        frozenset(lookup[hero] for hero in identities if hero in lookup),
        tuple(hero.replace(" ", "") for hero in identities if hero not in lookup),
        frozenset(str(player.get("account_id")) for player in players),
        dynamic_values, prepare_text(scalar_values(dynamic_values)))


class SearchIndex:
    """One catalog generation; reload/update rebuild metadata, edits refresh cheaply.

    The UI owns a single index and replaces it when loading catalog metadata;
    incremental refreshes can retain unchanged match objects and their documents.
    Call update(match) after other metadata mutations, or update_accounts after
    nickname edits. Notes/ratings/client overrides are detected automatically.
    No cache data is stored in match dictionaries or the user database.
    """
    def __init__(self, catalog, accounts=()):
        self.documents = {id(match): prepare_document(match) for match in catalog}
        self.update_accounts(accounts)

    def update_accounts(self, accounts):
        self.nicknames = {str(account["id"]): prepare_text([account.get("nickname", "").casefold()]) for account in accounts}

    def update(self, match):
        self.documents[id(match)] = prepare_document(match)

    def refresh(self, catalog):
        """Keep prepared documents for unchanged objects; discard removed rows."""
        previous = self.documents
        self.documents = {id(match): previous[id(match)] if id(match) in previous
                          else prepare_document(match) for match in catalog}

    def matches(self, match, terms):
        document = self.documents.get(id(match))
        if document is None:
            self.update(match)
            document = self.documents[id(match)]
        document.refresh_dynamic(match)
        return document.matches(terms, self.nicknames)


def matches_query(match, terms, nicknames):
    """Compatibility helper for one-off callers without a persistent catalog index."""
    if not terms:
        return True
    names = {str(account): prepare_text([nickname.casefold()]) for account, nickname in nicknames.items()}
    return prepare_document(match).matches(compile_terms(tuple(terms)), names)
