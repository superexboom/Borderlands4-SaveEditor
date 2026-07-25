"""Shared editor-tab helpers.

Pure functions taking a tab (or specific widget/list) as an argument. No
imports from any qt_..._editor_tab module — keeping the dependency arrow
one-way is what lets a fix here land in every editor at once, so behaviour
that should be uniform across tabs can't drift.

Weapon keeps its own tokenizer variant (``parse_component_string_with_skin``)
because its grammar differs from the shared one — it preserves interleaved
raw text plus skin ``"c"`` tokens. Everything else routes through the
plain ``parse_component_string``.
"""

import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Iterator, Literal

from PyQt6.QtWidgets import QRadioButton, QCheckBox, QMessageBox, QComboBox, QListWidget
from PyQt6.QtCore import Qt

from core import resource_loader


TokenKind = Literal["simple", "single", "list", "quoted", "raw"]


@dataclass
class Token:
    """One token parsed from a serial's component string.

    ``raw`` is always the exact source text for the token (including
    surrounding whitespace for ``raw`` kind), so concatenating every
    ``token.raw`` in order reproduces the input byte-for-byte. That's what
    lets rebuild preserve unknown tokens and reorder without churn — the
    parser hands back the source, not a canonicalized re-emit.

    Fields per kind:
      - simple  ``{N}``            → value=N
      - single  ``{parent:value}`` → parent=parent, value=value
      - list    ``{parent:[a b]}`` → parent=parent, children=[a, b]
      - quoted  ``"c", N`` / ``"c", "path"`` → value=N (int form)
                                                or raw string carries the text
      - raw     : interstitial text between recognized tokens
                  (whitespace, ``||`` delimiter, unrecognized fragments)

    Any input the tokenizer can't classify becomes a ``raw`` token so
    concatenating ``token.raw`` still round-trips byte-for-byte — the state
    model never loses source text.
    """
    raw: str
    kind: TokenKind
    parent: int | None = None
    children: list[int] = field(default_factory=list)
    value: int | None = None


class TokenOrderedState:
    """Ordered list of parsed tokens with widget bindings for rebuild.

    Default ``render()`` walks tokens in current order and concatenates each
    token's ``raw`` — preserving unknown tokens and interstitial whitespace.
    Bindings patch specific tokens with their current widget value; a binding
    that returns ``None`` falls back to the token's raw form so unbound-but-
    known-shape tokens still round-trip.

    ``move()`` reorders tokens AND re-keys bindings so a getter attached to
    a token follows the token to its new index (see ``move``'s docstring).
    Callers may bind once at load and reorder freely.

    **Header-token-0 pattern.** Serials carry a pre-component header of the
    form ``"<mfg_id>, 0, 1, <level>| 2, <seed>||"`` (possibly with trailing
    whitespace before the first ``{P}`` token). The tokenizer treats this
    entire header as a single ``kind='raw'`` token at index 0, because none
    of its fields match a ``{…}`` or ``"c",…`` pattern. Editor tabs that
    expose ``level`` / ``seed`` widgets should therefore ``bind(0, getter)``
    with a getter that:

      1. Parses the source header once (regex against the raw at load time)
         to lift out ``mfg_id`` (immutable), the source ``level``, and the
         source ``seed`` — plus any trailing raw text after ``||`` — so the
         values the user did NOT touch keep their exact source form.
      2. Reads the CURRENT widget values on every call; if a widget is
         empty, falls back to the captured source value.
      3. Returns ``f"{mfg_id}, 0, 1, {level}| 2, {seed}||{trailing}"``.

    Emitted string equals the source raw byte-for-byte when nothing changed,
    so the load-then-regenerate round-trip stays byte-identical. That is the
    single most important pattern for the four sibling tabs (shield / repkit
    / enhancement / class-mod) — the seed-bug class of failure comes from
    rebuilding the header from widgets without preserving the source seed
    when the user never touched the seed field.
    """

    def __init__(self, tokens: list[Token]):
        self.tokens: list[Token] = list(tokens)
        self._bindings: dict[int, Callable[[], str | None]] = {}

    def bind(self, index: int, getter: Callable[[], str | None]) -> None:
        """Attach a widget-value getter to the token at ``index``.

        ``getter`` is called during ``render()`` and returns the widget's
        current representation (e.g. ``"{246:12}"``) or ``None`` to fall
        back to the token's raw form.
        """
        if not 0 <= index < len(self.tokens):
            raise IndexError(f"bind index {index} out of range (have {len(self.tokens)})")
        self._bindings[index] = getter

    def binding_for(self, index: int) -> Callable[[], str | None] | None:
        """Return the binding at ``index``, or ``None`` if unbound.

        Public accessor so callers (editor tabs that need to carry a binding
        forward across a token-shape reshuffle) don't reach into the private
        ``._bindings`` dict.
        """
        return self._bindings.get(index)

    def clear_bindings(self) -> None:
        """Drop every binding without touching tokens.

        Used at load time to reset bindings from a prior item before attaching
        fresh closures. Public form of the previous private ``._bindings.clear()``
        reach-in.
        """
        self._bindings.clear()

    def has_binding(self, index: int) -> bool:
        """True iff a binding exists at ``index``. Convenience for callers
        that want to know without materializing the getter."""
        return index in self._bindings

    def move(self, from_index: int, to_index: int) -> None:
        """Reorder tokens: pop from ``from_index``, insert at ``to_index``.

        Bindings are re-keyed against the *new* index of every token affected
        by the shift — the getter attached to the moved token follows it to
        ``to_index``, and every getter on a token that slid to make room is
        re-keyed to its new position — so a caller that bound before calling
        ``move`` never sees a getter fire for the wrong token. That means
        editor tabs may bind once at load and reorder freely; no re-bind pass
        is required after a move. ``from_index == to_index`` is a no-op;
        out-of-range raises ``IndexError`` so callers see the bug rather than
        silently losing a token.
        """
        n = len(self.tokens)
        if not 0 <= from_index < n:
            raise IndexError(f"from_index {from_index} out of range (have {n})")
        if not 0 <= to_index < n:
            raise IndexError(f"to_index {to_index} out of range (have {n})")
        if from_index == to_index:
            return
        token = self.tokens.pop(from_index)
        self.tokens.insert(to_index, token)
        # Rebuild binding dict against the new order. Cheapest correct thing:
        # compute the shift for every affected index in a single pass.
        lo, hi = (from_index, to_index) if from_index < to_index else (to_index, from_index)
        new_bindings: dict[int, Callable[[], str | None]] = {}
        for idx, getter in self._bindings.items():
            if idx == from_index:
                new_bindings[to_index] = getter
            elif lo <= idx <= hi:
                new_bindings[idx + (-1 if from_index < to_index else 1)] = getter
            else:
                new_bindings[idx] = getter
        self._bindings = new_bindings

    def swap(self, i: int, j: int) -> None:
        """Swap tokens at positions ``i`` and ``j`` in place, and swap their
        bindings so a getter continues to fire for the same token identity.

        Distinct from ``move``: swap leaves every OTHER token at its original
        index — critical when interstitial whitespace (kind='raw') tokens sit
        between typed tokens and callers want to reorder the typed pair
        without disturbing spacing. ``move(i, i+1)`` would slide the swap
        partner into the raw slot; ``swap(i, next_typed_after_i)`` keeps the
        raw tokens exactly where they were, so the rendered serial gains no
        stray spaces and loses no separators.
        """
        n = len(self.tokens)
        if not 0 <= i < n:
            raise IndexError(f"swap i={i} out of range (have {n})")
        if not 0 <= j < n:
            raise IndexError(f"swap j={j} out of range (have {n})")
        if i == j:
            return
        self.tokens[i], self.tokens[j] = self.tokens[j], self.tokens[i]
        bi = self._bindings.pop(i, None)
        bj = self._bindings.pop(j, None)
        if bi is not None:
            self._bindings[j] = bi
        if bj is not None:
            self._bindings[i] = bj

    def insert(self, index: int, token: Token) -> None:
        """Insert ``token`` at ``index``; every binding at ``index`` or higher
        shifts up by one so a getter attached to a token follows the token to
        its new position. Same guarantee as ``move``: editor tabs may bind
        once and structurally mutate freely without a re-bind pass.

        ``0 <= index <= len(self.tokens)`` — matches ``list.insert`` semantics
        (appending is ``index == len(self.tokens)``); out-of-range raises
        ``IndexError`` so callers see the bug rather than silently mis-placing
        a token.
        """
        n = len(self.tokens)
        if not 0 <= index <= n:
            raise IndexError(f"insert index {index} out of range (0..{n})")
        self.tokens.insert(index, token)
        self._bindings = {
            (idx + 1 if idx >= index else idx): getter
            for idx, getter in self._bindings.items()
        }

    def remove(self, index: int) -> None:
        """Pop the token at ``index``; its binding (if any) is dropped, and
        every binding at a higher index shifts down by one — analog to
        ``move``'s re-key pass, so a token's getter always follows the token.
        Out-of-range raises ``IndexError`` so callers see the bug rather than
        silently losing a token to the wrong slot.
        """
        n = len(self.tokens)
        if not 0 <= index < n:
            raise IndexError(f"remove index {index} out of range (have {n})")
        self.tokens.pop(index)
        new_bindings: dict[int, Callable[[], str | None]] = {}
        for idx, getter in self._bindings.items():
            if idx == index:
                continue
            new_bindings[idx - 1 if idx > index else idx] = getter
        self._bindings = new_bindings

    def reorder_subset(self, subset: list[int], permutation: list[int]) -> None:
        """Permute the tokens at ``subset`` (indices into ``self.tokens``).

        ``permutation`` must be a permutation of ``range(len(subset))``. After
        the call, the token previously at ``subset[permutation[k]]`` (and its
        binding, if any) occupies ``subset[k]``. Tokens at positions NOT in
        ``subset`` — and their bindings — are unchanged.

        The right primitive for a subset reorder (e.g. weapon DnD, where the
        user permutes just the part-typed tokens and interleaved ``raw``
        whitespace tokens must stay put). Cheaper and clearer than emulating
        the same effect with a chain of ``move()`` calls, which would need
        the caller to track shifting indices as each move fires.
        """
        if len(set(subset)) != len(subset):
            raise ValueError(
                f"reorder_subset requires unique subset indices; got {subset}",
            )
        if len(permutation) != len(subset):
            raise ValueError(
                f"permutation length {len(permutation)} != subset length {len(subset)}",
            )
        if sorted(permutation) != list(range(len(subset))):
            raise ValueError(
                f"permutation must be of range({len(subset)}), got {permutation}",
            )
        n = len(self.tokens)
        for idx in subset:
            if not 0 <= idx < n:
                raise IndexError(f"subset index {idx} out of range (have {n})")
        old_tokens = [self.tokens[subset[p]] for p in permutation]
        old_bindings = [self._bindings.get(subset[p]) for p in permutation]
        for k, idx in enumerate(subset):
            self.tokens[idx] = old_tokens[k]
            if old_bindings[k] is None:
                self._bindings.pop(idx, None)
            else:
                self._bindings[idx] = old_bindings[k]

    def iter_by_parent(self, parent_id: int) -> Iterator[tuple[int, "Token"]]:
        """Yield ``(index, token)`` for every token whose ``.parent`` matches
        ``parent_id``. Convenience for editor tabs that bind widgets by
        parent-ID convention (e.g. all shield-body tokens share the same
        parent id) — walks the token list once, filters, no allocation of
        an intermediate list.
        """
        for i, tok in enumerate(self.tokens):
            if tok.parent == parent_id:
                yield i, tok

    def render(self) -> str:
        """Walk tokens in current order and concatenate. Bindings that return
        ``None`` fall back to the token's raw form so unbound-but-known-shape
        tokens still round-trip byte-identical.

        Getters that raise are treated as returning ``None`` (fall through to
        ``token.raw``). ``TokenOrderedState`` has no ``main_app`` reference so
        it can't log the drift; callers that care about visibility should use
        ``ItemBrowser.render_from_state(state, expected_raw=...)`` which
        compares the rendered output against a source string and logs any
        divergence. The silent-fallback default here keeps a getter bug from
        crashing a live save load; the parity check surfaces it.
        """
        parts: list[str] = []
        for idx, token in enumerate(self.tokens):
            getter = self._bindings.get(idx)
            if getter is not None:
                try:
                    value = getter()
                except Exception:
                    value = None
                if value is not None:
                    parts.append(value)
                    continue
            parts.append(token.raw)
        return "".join(parts)

    def remove_with_whitespace(self, index: int) -> None:
        """Remove token at ``index`` and, if an adjacent raw token is
        whitespace-only, remove one of them too so the rendered stream stays
        single-spaced instead of accumulating gaps on repeated deletes.

        Prefers the trailing raw (``index+1``) so head padding after ``||``
        survives; falls back to the leading raw (``index-1``) when we deleted
        the last typed token. Only touches whitespace-only raws — a raw that
        carries ``|``/``||`` delimiter text is left alone so structural
        separators are preserved — the ``not raw.strip()`` filter ensures
        only pure-whitespace raws are candidates, so a raw that carries a
        ``|`` or ``||`` delimiter is never collapsed.
        """
        n = len(self.tokens)
        if not 0 <= index < n:
            raise IndexError(f"remove index {index} out of range (have {n})")
        trailing_ok = (
            index + 1 < len(self.tokens)
            and self.tokens[index + 1].kind == 'raw'
            and not self.tokens[index + 1].raw.strip()
        )
        leading_ok = (
            index > 0
            and self.tokens[index - 1].kind == 'raw'
            and not self.tokens[index - 1].raw.strip()
        )
        if trailing_ok:
            # Higher index first so lower doesn't shift under us.
            self.remove(index + 1)
            self.remove(index)
        elif leading_ok:
            self.remove(index)
            self.remove(index - 1)
        else:
            self.remove(index)


# C4sh's skill_name_EN carries a trailing tree letter (" B" / " G" / " R") that
# is stripped for display. Shared here so class-mod and loadout use one source.
C4SH_TREE_SUFFIX_RE = re.compile(r" [BGR]$")


# Serial header shape: "<mfg_id>, 0, 1, <level>| 2, <seed>||<trailing>". The
# groups let ``make_header_getter`` lift out mfg_id (immutable) + source level
# + source seed so an unedited round-trip re-emits the header byte-for-byte.
HEADER_RE = re.compile(
    r'^(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\|\s*(\d+),\s*(\d+)\|\|(.*)$',
    re.DOTALL,
)


def make_header_getter(header_raw: str, *,
                       level_getter: Callable[[], str] | None = None,
                       seed_getter: Callable[[], str] | None = None,
                       ) -> Callable[[], str | None]:
    """Build a header getter closure that preserves the source header verbatim
    except for level / seed values overridden by widget getters.

    ``level_getter`` / ``seed_getter`` return the widget's current text; empty
    strings fall back to the captured source value so an unedited round-trip
    stays byte-identical. Passing ``seed_getter=None`` (the default) preserves
    the source seed unconditionally — that is the fix for the shield / repkit
    seed-hardcoding bug class: load-then-save with no seed edits stays
    byte-identical because the widget-splice ``main_part = f"..."`` rebuild
    that hardcoded 305/306/307 is gone.

    Returns a getter that yields ``None`` (fall through to token.raw) if
    ``header_raw`` doesn't parse — this preserves any pre-existing raw text
    a caller passes rather than silently corrupting an unrecognized header.
    """
    m = HEADER_RE.match(header_raw)
    if not m:
        return lambda: None
    mfg_id, unk1, unk2, level_src, unk3, seed_src, trailing = m.groups()

    def getter() -> str | None:
        try:
            if level_getter is not None:
                text = (level_getter() or '').strip()
                level = text or level_src
            else:
                level = level_src
            if seed_getter is not None:
                text = (seed_getter() or '').strip()
                seed = text or seed_src
            else:
                seed = seed_src
        except Exception:
            return None
        return f"{mfg_id}, {unk1}, {unk2}, {level}| {unk3}, {seed}||{trailing}"

    return getter


def log_editor(main_app, tag: str, message: str) -> None:
    """Route diagnostic output through ``main_app.log`` when present, else
    ``print`` with a ``[tag]`` prefix so headless / test runs still see it.

    Replaces the per-editor ``_log_XX`` methods that all had this same shape.
    """
    if main_app is not None and hasattr(main_app, "log"):
        main_app.log(message)
    else:
        print(f"[{tag}] {message}")


def find_mfg_combo_index(combo: QComboBox, mfg_id: int) -> int:
    """Return the index of the combo entry whose text ends with ``" - <mfg_id>"``.

    Verbatim shape from grenade/shield/repkit/heavy/enhancement callers.
    Returns -1 if no entry matches.
    """
    needle = f" - {mfg_id}"
    for i in range(combo.count()):
        if combo.itemText(i).endswith(needle):
            return i
    return -1


def selected_mfg_id_from_combo(combo: QComboBox) -> int | None:
    """Parse the manufacturer ID from a "<name> - <id>" combo entry.

    Returns ``None`` if the combo has no selection or the id can't be parsed.
    Shared by grenade/shield/repkit/heavy which all format mfg entries as
    ``"<localized_name> - <id>"``.
    """
    text = combo.currentText()
    if not text or ' - ' not in text:
        return None
    try:
        return int(text.rsplit(' - ', 1)[-1])
    except (ValueError, IndexError):
        return None


def combo_data_ids(combo: QComboBox) -> set[int]:
    """Return the set of integer ``userData`` values across all combo entries.

    Cast on ingestion: pandas hands out numpy.int64 but tokens are Python int
    and dict/set hash equality depends on identical concrete types. See
    ``list_widget_by_userrole`` for full rationale.
    """
    ids: set[int] = set()
    for i in range(combo.count()):
        data = combo.itemData(i)
        if data is not None:
            ids.add(int(data))
    return ids


def load_tab_ui_loc(tab_key: str, lang: str) -> dict[str, object]:
    """Read ``<tab_key>`` from the language-appropriate UI localization JSON.

    Returns an empty dict when the file or key is missing so callers can
    ``.get(...)`` chains without a None guard. Shared body of the pre-extract
    ``_load_ui_localization`` methods on grenade/shield/heavy/repkit.
    """
    loc_file = resource_loader.get_ui_localization_file(lang)
    full_loc = resource_loader.load_json_resource(loc_file) or {}
    return full_loc.get(tab_key, {})


def populate_flag_combo(flag_combo: QComboBox, lang: str, *, default_key: str = "3") -> None:
    """Populate a flag combo with the seven ``get_flag_labels`` values and
    snap the current index to the ``default_key`` entry.

    Verbatim shape from grenade/heavy/repkit; shield/class_mod had the same
    outcome via a slightly different for-loop.
    """
    flag_combo.clear()
    flags_map = resource_loader.get_flag_labels(lang)
    flag_values = [flags_map[k] for k in ("1", "3", "5", "17", "33", "65", "129")]
    flag_combo.addItems(flag_values)
    default_label = flags_map.get(default_key)
    if default_label is None:
        return
    idx = flag_combo.findText(default_label)
    if idx >= 0:
        flag_combo.setCurrentIndex(idx)


def parse_component_string(text: str) -> Iterator[dict]:
    """Regex-tokenize the ``||``-delimited component section into dicts of
    ``{type: 'simple'|'elemental'|'group', id, sub_id?, sub_ids?}``.

    Shared grammar for grenade / shield / repkit / heavy / enhancement /
    class-mod. Weapon uses ``parse_component_string_with_skin`` because
    ``"c"`` skin tokens are unique to weapons. Yielded as a generator to
    match existing call sites.
    """
    for match in re.finditer(r'\{(\d+)(?::(\d+|\[[\d\s]+\]))?\}', text):
        outer_id = int(match.group(1))
        inner = match.group(2)
        if inner is None:
            yield {'type': 'simple', 'id': outer_id}
        elif '[' in inner:
            sub_ids = [int(s) for s in inner.strip('[]').split()]
            yield {'type': 'group', 'id': outer_id, 'sub_ids': sub_ids}
        else:
            yield {'type': 'elemental', 'id': outer_id, 'sub_id': int(inner)}


def parse_component_string_with_skin(text: str) -> list[dict | str]:
    """Weapon-only variant of ``parse_component_string``.

    Emits an interleaved list of raw-text fragments and token dicts (each
    token dict carries ``'raw'`` — the exact matched substring — so the
    caller can splice results back into the serial). Adds ``"c", <id>`` and
    ``"c", "<path>"`` skin tokens which no other editor understands.

    Returned as a list (not generator) because callers walk it multiple times
    and use raw-text fragments as padding between tokens.
    """
    components: list[dict | str] = []
    last_index = 0
    pattern = r'\{(\d+)(?::(\d+|\[[\d\s]+\]))?\}|\"c\",\s*(?:(\d+)|\"([^\"]+)\")'
    for match in re.finditer(pattern, text):
        components.append(text[last_index:match.start()])
        part_data = {'raw': match.group(0)}
        if match.group(3):
            part_data.update({'type': 'skin', 'id': int(match.group(3))})
        elif match.group(4):
            part_data.update({'type': 'skin', 'id': match.group(4)})
        else:
            outer_id = int(match.group(1))
            inner = match.group(2)
            if inner is None:
                part_data.update({'type': 'simple', 'id': outer_id})
            elif '[' in inner:
                part_data.update({
                    'type': 'group', 'id': outer_id,
                    'sub_ids': [int(sid) for sid in inner.strip('[]').split()],
                })
            else:
                part_data.update({'type': 'elemental', 'id': outer_id, 'sub_id': int(inner)})
        components.append(part_data)
        last_index = match.end()
    components.append(text[last_index:])
    return [c for c in components if c]


def parse_component_tokens(text: str) -> list[Token]:
    """Structured, token-preserving variant of ``parse_component_string``.

    Yields ``Token`` objects for every match plus a ``raw`` token for every
    interstitial fragment (whitespace, ``||`` delimiters, unrecognized text).
    Concatenating ``token.raw`` in order reproduces ``text`` byte-for-byte,
    which is what lets ``TokenOrderedState.render`` preserve unknown tokens
    and interstitial whitespace by default.

    Base grammar (no skin support). Weapon uses
    ``parse_component_tokens_with_skin`` because ``"c"`` skin tokens are
    weapon-only. The two parsers stay side-by-side rather than one via a
    flag so the base grammar can't accidentally start matching skin tokens.
    """
    tokens: list[Token] = []
    last_end = 0
    for match in re.finditer(r'\{(\d+)(?::(\d+|\[[\d\s]+\]))?\}', text):
        if match.start() > last_end:
            tokens.append(Token(raw=text[last_end:match.start()], kind="raw"))
        outer_id = int(match.group(1))
        inner = match.group(2)
        raw = match.group(0)
        if inner is None:
            tokens.append(Token(raw=raw, kind="simple", value=outer_id))
        elif '[' in inner:
            children = [int(s) for s in inner.strip('[]').split()]
            tokens.append(Token(raw=raw, kind="list", parent=outer_id, children=children))
        else:
            tokens.append(Token(raw=raw, kind="single", parent=outer_id, value=int(inner)))
        last_end = match.end()
    if last_end < len(text):
        tokens.append(Token(raw=text[last_end:], kind="raw"))
    return tokens


def parse_component_tokens_with_skin(text: str) -> list[Token]:
    """Weapon-only structured tokenizer — same shape as
    ``parse_component_tokens`` but also matches ``"c", N`` and ``"c", "path"``
    skin tokens (emitted as ``kind='quoted'``).

    Interstitial text becomes ``kind='raw'`` tokens so byte-identical
    reassembly holds through arbitrary edits. The skin variant matters at
    all only because weapons interleave skin markers between component
    tokens — every other editor's grammar is a pure ``{N}`` / ``{P:V}`` /
    ``{P:[…]}`` stream.
    """
    tokens: list[Token] = []
    last_end = 0
    pattern = r'\{(\d+)(?::(\d+|\[[\d\s]+\]))?\}|\"c\",\s*(?:(\d+)|\"([^\"]+)\")'
    for match in re.finditer(pattern, text):
        if match.start() > last_end:
            tokens.append(Token(raw=text[last_end:match.start()], kind="raw"))
        raw = match.group(0)
        if match.group(3):
            # numeric skin id, e.g. `"c", 12`
            tokens.append(Token(raw=raw, kind="quoted", value=int(match.group(3))))
        elif match.group(4):
            # path-form skin, e.g. `"c", "Path/To/Asset"` — kept as raw only;
            # the string value lives inside token.raw.
            tokens.append(Token(raw=raw, kind="quoted"))
        else:
            outer_id = int(match.group(1))
            inner = match.group(2)
            if inner is None:
                tokens.append(Token(raw=raw, kind="simple", value=outer_id))
            elif '[' in inner:
                children = [int(sid) for sid in inner.strip('[]').split()]
                tokens.append(Token(raw=raw, kind="list", parent=outer_id, children=children))
            else:
                tokens.append(Token(raw=raw, kind="single", parent=outer_id, value=int(inner)))
        last_end = match.end()
    if last_end < len(text):
        tokens.append(Token(raw=text[last_end:], kind="raw"))
    return tokens


def set_flag_from_item(flag_combo: QComboBox, item: dict,
                       *, main_app=None, tag: str = "editor") -> None:
    """Snap ``flag_combo`` to the entry whose display text starts with the
    numeric prefix of ``item['state_flags']``. No-op if the field is absent.

    On miss (item carries a flag prefix that no combo entry matches), logs via
    ``log_editor`` so silent state pollution surfaces — matches the visibility
    policy of ``set_rarity_by_id`` below.
    """
    raw = item.get("state_flags")
    if raw is None:
        return
    prefix = str(raw).strip().split(" ")[0]
    for i in range(flag_combo.count()):
        if flag_combo.itemText(i).startswith(f"{prefix} "):
            flag_combo.setCurrentIndex(i)
            return
    log_editor(main_app, tag, f"set_flag_from_item: no combo match for prefix={prefix!r}")


def set_rarity_by_id(rarity_combo: QComboBox, part_id: int,
                     *, main_app=None, tag: str = "editor") -> None:
    """Snap ``rarity_combo`` to the entry whose UserRole data equals
    ``part_id``. Casts on ingestion: pandas hands out numpy.int64 but tokens
    are Python int, and future numpy versions may change hash semantics.

    Signal blocked so cascading ``currentTextChanged`` handlers stay quiet
    during the load path. On miss, logs via ``log_editor`` so silent state
    pollution surfaces instead of leaving the combo at whatever default
    index it held.
    """
    for i in range(rarity_combo.count()):
        data = rarity_combo.itemData(i)
        if data is not None and int(data) == part_id:
            rarity_combo.blockSignals(True)
            rarity_combo.setCurrentIndex(i)
            rarity_combo.blockSignals(False)
            return
    log_editor(main_app, tag, f"set_rarity_by_id: no combo match for part_id={part_id}")


def legendary_lookup(legendary_avail_list: QListWidget) -> dict:
    """Build ``{(part_id:int, mfg_id:int): QListWidgetItem}`` from a
    legendary-avail QListWidget. Tuple parts cast to int on ingestion —
    UserRole values are numpy.int64 from pandas; tokens are Python int and
    dict hash equality depends on identical concrete types.
    """
    table = {}
    for i in range(legendary_avail_list.count()):
        av_item = legendary_avail_list.item(i)
        data = av_item.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, tuple) and len(data) == 2:
            table[(int(data[0]), int(data[1]))] = av_item
    return table


def summarize_item(item, *, template: str, none_text: str, fallback_name: str = "Item") -> str:
    """Render an item summary from a template like
    ``"Selected · {name} · Lv.{level}"``.

    Returns ``none_text`` when ``item`` is falsy so callers can pass this to
    ``ItemBrowser(..., summary_formatter=...)`` without their own guard.
    Falls back to a hardcoded shape if the localized template omits a
    placeholder — same defensive shape as the pre-extract methods had.
    """
    if not item:
        return none_text
    name = item.get("name") or item.get("manufacturer") or fallback_name
    level = item.get('level', 'N/A')
    try:
        return template.format(name=name, level=level)
    except (KeyError, IndexError):
        return f"Selected · {name} · Lv.{level}"


def populate_radio_buttons(container, entries, *, on_toggle,
                            include_none: bool = True, none_label: str = "None"):
    """Populate a ``QVBoxLayout`` ``container`` with a leading ``None`` radio
    (optional) and one radio per ``(text, part_id)`` in ``entries``. Signals
    are wired intrinsically here — do not re-connect ``toggled`` at the call
    site.

    Returns ``(data_radios: list[QRadioButton], none_rb: QRadioButton | None)``.
    The data list holds only data-driven radios (not the None one). Callers
    unpack the tuple explicitly and assign both attributes rather than the
    helper mutating the caller via an ``owner`` kwarg.
    """
    while container.count():
        child = container.takeAt(0)
        if child.widget():
            child.widget().deleteLater()

    data_radios: list[QRadioButton] = []
    none_rb: QRadioButton | None = None
    if include_none:
        none_rb = QRadioButton(none_label)
        none_rb.setChecked(True)
        none_rb.toggled.connect(on_toggle)
        container.addWidget(none_rb)

    for text, part_id in entries:
        rb = QRadioButton(text)
        rb.setProperty("part_id", part_id)
        rb.toggled.connect(on_toggle)
        container.addWidget(rb)
        data_radios.append(rb)
    container.addStretch()

    return data_radios, none_rb


def populate_checkboxes(container, entries, *, on_toggle) -> list[QCheckBox]:
    """Populate a ``QVBoxLayout`` ``container`` with one checkbox per
    ``(text, part_id)`` in ``entries``. Signals wired here; no None option
    (checkboxes are non-exclusive).

    Returns the list of QCheckBox widgets.
    """
    while container.count():
        child = container.takeAt(0)
        if child.widget():
            child.widget().deleteLater()

    checkboxes: list[QCheckBox] = []
    for text, part_id in entries:
        cb = QCheckBox(text)
        cb.setProperty("part_id", part_id)
        cb.toggled.connect(on_toggle)
        container.addWidget(cb)
        checkboxes.append(cb)
    container.addStretch()
    return checkboxes


def iter_children(token: dict) -> Iterator:
    """Yield child ids for ``elemental`` (one) and ``group`` (many) tokens
    uniformly. ``simple`` tokens yield nothing — callers can iterate
    ``for child in iter_children(token)`` without a shape branch.

    Grammar examples (produced by ``parse_component_string``):
      - simple    ``{247}``          → yields nothing
      - elemental ``{247:5}``        → yields ``5``
      - group     ``{247:[1 2 3]}``  → yields ``1``, ``2``, ``3``
    """
    ttype = token.get('type')
    if ttype == 'elemental':
        yield token['sub_id']
    elif ttype == 'group':
        yield from token['sub_ids']


def emit_update_or_warn(tab, *, new_serial: str, no_selection_title: str,
                        no_selection_msg: str, no_valid_code_title: str,
                        no_valid_code_msg: str, success_msg: str) -> bool:
    """Shared body of the 5-tab ``_update_XX`` methods: guard on selection,
    guard on encode error, then emit ``update_item_requested`` with the
    standard payload shape.

    Reads ``tab.selected_item_path`` and ``tab._encode_error``; emits on
    ``tab.update_item_requested`` (the pyqtSignal every editor tab defines).
    Returns True when the signal was emitted, False on any guard trip.
    """
    if not getattr(tab, 'selected_item_path', None):
        QMessageBox.warning(tab, no_selection_title, no_selection_msg)
        return False
    if getattr(tab, '_encode_error', False):
        QMessageBox.warning(tab, no_valid_code_title, no_valid_code_msg)
        return False
    if not new_serial:
        return False
    tab.update_item_requested.emit({
        'item_path': tab.selected_item_path,
        'original_item_data': {},
        'new_item_data': {'serial': new_serial},
        'success_msg': success_msg,
    })
    return True


@contextmanager
def block_signals(*widgets):
    """Context manager that calls ``blockSignals(True)`` on entry and
    ``blockSignals(False)`` on exit for every widget passed. Kept lightweight
    for the load path (nested inside ``_is_loading`` guards, not a substitute
    for them). ``try/finally`` guarantees unblocking even if the body raises.
    """
    for w in widgets:
        w.blockSignals(True)
    try:
        yield
    finally:
        for w in widgets:
            w.blockSignals(False)
