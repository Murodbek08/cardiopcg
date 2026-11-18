"""De-identification: strict allow-list, free-text sanitiser, PII scanner and final PII guard
(doc 02 sections 13.6 and 14).

Rule: a field that is not in the allow-list is DROPPED (default = not sent). Nothing in this
module ever sends data anywhere; it only builds the payload and reports what was dropped.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

REDACTED = "[REDACTED]"
SUSPICIOUS = "[REDACTED_SUSPICIOUS]"
MAX_TEXT = 500
MAX_ITEMS = 30


class PIIGuardError(Exception):
    """Raised when a payload that is about to leave the system still contains PII."""


# --------------------------------------------------------------------------- patterns

_PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("email", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")),
    ("url", re.compile(r"(?i)\b(?:https?://|www\.)\S+")),
    ("uuid", re.compile(r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")),
    ("pinfl", re.compile(r"\b\d{14}\b")),
    ("phone", re.compile(r"(?<!\d)\+?\d{3}[\s\-]?\(?\d{2}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}(?!\d)")),
    ("phone9", re.compile(r"(?<![\d/.])\(?\d{2}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}(?![\d/.])")),
    ("passport", re.compile(r"\b[A-Z]{2}\s?\d{7}\b")),
    (
        "date",
        re.compile(
            r"\b(?:\d{1,2}[./\-]\d{1,2}[./\-](?:19|20)\d{2}|(?:19|20)\d{2}[./\-]\d{1,2}[./\-]\d{1,2})\b"
        ),
    ),
    (
        "mrn",
        re.compile(
            r"(?i)\b(?:mrn|karta|kasallik\s+tarixi|история\s+болезни)\s*(?:№|raqami|nomeri|#|:)?\s*[A-Za-z0-9\-]{3,}"
        ),
    ),
    (
        "labelled_name",
        re.compile(
            r"(?i)\b(?:ism|ismi|familiya|familiyasi|f\.?\s?i\.?\s?o\.?|fio|otasining\s+ismi|имя|фамилия|name|patient|bemor|shifokor|doctor|hamshira|nurse|dr\.?)\s*[:=\-]\s*[^\s,;]+(?:\s+[^\s,;]+){0,2}"
        ),
    ),
    (
        "address",
        re.compile(
            r"(?i)(?:\b[\w'’`-]+\s+){0,2}\b(?:ko['’`]?chasi|ko['’`]?cha|mahalla(?:si)?|mfy|manzil|manzili|tuman|ул\.?|улица|street|address)\b[^,.;\n]{0,50}"
        ),
    ),
    (
        "surname_suffix",
        re.compile(
            r"\b[A-ZА-Я][a-zа-яё'’`]{2,}(?:ov|ova|ev|eva|ovich|ovna|evich|evna|yev|yeva|ugli|qizi|o['’`]g['’`]li|ов|ова|ев|ева|ович|овна)\b"
        ),
    ),
]

# small list of common first names (not exhaustive: the allow-list is the main defence)
_FIRST_NAMES = [
    "alisher",
    "bobur",
    "dilnoza",
    "madina",
    "jasur",
    "sardor",
    "zilola",
    "aziz",
    "botir",
    "nodira",
    "feruza",
    "shaxzod",
    "otabek",
    "rustam",
    "sherzod",
    "gulnora",
    "nargiza",
    "malika",
    "dilshod",
    "javlon",
    "ulugbek",
    "umid",
    "kamola",
    "laylo",
    "sevara",
    "muhammad",
    "ahmad",
    "mahmud",
    "abdulla",
    "sanjar",
    "bekzod",
    "azamat",
    "davron",
    "farhod",
    "hamid",
    "olim",
    "nilufar",
    "aleksandr",
    "sergey",
    "ivan",
    "dmitriy",
    "olga",
    "elena",
    "natalya",
]
_NAME_RE = re.compile(r"(?i)\b(?:" + "|".join(_FIRST_NAMES) + r")\b")

_INJECTION = re.compile(
    r"(?is)(ignore|disregard|forget|override)\s+(all\s+|any\s+|the\s+|your\s+)?(previous|prior|above|earlier|system)"
    r"|oldingi\s+.{0,25}(ko['’`]?rsatma|buyruq|qoida).{0,25}(unut|e['’`]?tiborsiz|bekor)"
    r"|(barcha|hamma)\s+dori\w*\s+ruxsat"
    r"|doza(?:ni)?\s+\d+\s*(x|marta|baravar)"
    r"|system\s*prompt|developer\s+message|new\s+instructions?|you\s+are\s+now|act\s+as\s+(a|an|the)\b|jailbreak"
    r"|</?\s*(system|assistant|user|instructions?)\s*>"
    r"|игнорируй\s+(все\s+)?(предыдущ|прежн)"
    r"|\bDAN\b mode"
)

_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩]")


@dataclass
class DeidFlags:
    pii_redactions: dict[str, int] = field(default_factory=dict)
    suspicious_fields: list[str] = field(default_factory=list)
    truncated_fields: list[str] = field(default_factory=list)

    def add_pii(self, kind: str) -> None:
        self.pii_redactions[kind] = self.pii_redactions.get(kind, 0) + 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "pii_redactions": self.pii_redactions,
            "suspicious_fields": self.suspicious_fields,
            "truncated_fields": self.truncated_fields,
        }


def scan_pii(text: str) -> list[str]:
    """Return the list of PII kinds found in `text` (empty = clean)."""
    kinds: list[str] = []
    t = text.replace(REDACTED, " ")
    for kind, rx in _PII_PATTERNS:
        if rx.search(t):
            kinds.append(kind)
    if _NAME_RE.search(t):
        kinds.append("first_name")
    return kinds


def _mask_pii(text: str, flags: DeidFlags) -> str:
    out = text
    for kind, rx in _PII_PATTERNS:
        out, n = rx.subn(REDACTED, out)
        for _ in range(n):
            flags.add_pii(kind)
    out, n = _NAME_RE.subn(REDACTED, out)
    for _ in range(n):
        flags.add_pii("first_name")
    return out


def sanitize_text(text: Any, field_name: str, flags: DeidFlags, max_len: int = MAX_TEXT) -> str | None:
    """doc 13.6 + 14.3: length cap, control chars, tag neutralisation, injection denylist, PII mask."""
    if text is None:
        return None
    s = str(text)
    s = _CTRL.sub(" ", s)
    s = s.replace("<", "‹").replace(">", "›")
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return None
    if _INJECTION.search(s):
        flags.suspicious_fields.append(field_name)
        return SUSPICIOUS
    if len(s) > max_len:
        s = s[:max_len]
        flags.truncated_fields.append(field_name)
    s = _mask_pii(s, flags)
    # a field that is nothing but redactions carries no information
    if not s.replace(REDACTED, "").strip(" .,;:-"):
        return REDACTED
    return s


# --------------------------------------------------------------------------- allow-list

_SEX = {
    "male": "male",
    "m": "male",
    "man": "male",
    "erkak": "male",
    "муж": "male",
    "female": "female",
    "f": "female",
    "woman": "female",
    "ayol": "female",
    "жен": "female",
    "other": "other",
    "boshqa": "other",
}

_RANGES: dict[str, tuple[float, float]] = {
    "weight_kg": (0.3, 400),
    "height_cm": (30, 250),
    "bmi": (8, 90),
    "symptom_duration_days": (0, 36500),
    "bp_sys": (40, 300),
    "bp_dia": (20, 200),
    "spo2": (30, 100),
    "temp_c": (30, 45),
    "resp_rate": (3, 80),
    "hr_bpm": (20, 250),
    "egfr_ml_min": (0, 200),
    "creatinine_umol_l": (10, 2000),
    "alt": (0, 5000),
    "potassium_mmol_l": (1, 10),
    "inr": (0.5, 10),
}
_VITALS = ("bp_sys", "bp_dia", "spo2", "temp_c", "resp_rate", "hr_bpm")
_LABS = ("egfr_ml_min", "creatinine_umol_l", "alt", "child_pugh", "potassium_mmol_l", "inr")
_ICD = re.compile(r"^[A-TV-Z]\d{2}(\.\d{1,2})?$")
_SLUG = re.compile(r"[^a-z0-9_]+")

ALLOWED_TOP_LEVEL = {
    "age_years",
    "age",
    "sex",
    "gender",
    "weight_kg",
    "height_cm",
    "bmi",
    "symptoms",
    "symptom_duration_days",
    "history",
    "known_conditions_icd10",
    "family_history",
    "vitals",
    "labs",
    "pregnancy",
    "lactation",
    "allergies",
    "current_medications",
    "conditions",
    "condition_flags",
    *_VITALS,
    *_LABS,
}
# explicitly known-dangerous keys: dropped AND recorded so the backend can see the leak attempt
KNOWN_PII_KEYS = {
    "name",
    "full_name",
    "first_name",
    "last_name",
    "patient_name",
    "ism",
    "familiya",
    "phone",
    "telefon",
    "address",
    "manzil",
    "passport",
    "pinfl",
    "jshshir",
    "email",
    "dob",
    "birth_date",
    "date_of_birth",
    "mrn",
    "card_number",
    "patient_id",
    "recording_id",
    "exam_id",
    "examination_id",
    "doctor",
    "doctor_name",
    "nurse",
    "nurse_name",
    "clinic",
    "clinic_name",
    "file",
    "filename",
    "file_name",
    "url",
    "audio_url",
    "id",
    "uuid",
}


def _num(v: Any, key: str) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None
    lo, hi = _RANGES.get(key, (float("-inf"), float("inf")))
    if not (lo <= f <= hi):
        return None
    return f


def _slug(s: str) -> str:
    return _SLUG.sub("_", s.strip().lower()).strip("_")[:60]


def _age_group(age: float) -> str:
    if age < 1:
        return "infant"
    if age < 12:
        return "child"
    if age < 18:
        return "adolescent"
    if age < 65:
        return "adult"
    return "elderly"


@dataclass
class DeidResult:
    llm_context: dict[str, Any]  # goes into <PATIENT_CONTEXT> (Call A)
    safety: dict[str, Any]  # goes into <PATIENT_SAFETY> (Call B) and the local KB filter
    input_fields: list[str]
    dropped_fields: list[str]
    flags: DeidFlags
    input_hash: str

    @property
    def age_years_exact(self) -> float | None:
        return self.safety.get("age_years")


def _paths(obj: Any, prefix: str = "") -> list[str]:
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out += _paths(v, f"{prefix}{k}.")
    elif isinstance(obj, list):
        out.append(prefix.rstrip(".") + "[]")
    else:
        out.append(prefix.rstrip("."))
    return out


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf8")).hexdigest()


def build_context(raw: dict[str, Any] | None) -> DeidResult:
    """Allow-list based build of the two payloads. Unknown keys are dropped (never sent)."""
    raw = dict(raw or {})
    flags = DeidFlags()
    dropped = sorted(k for k in raw if k not in ALLOWED_TOP_LEVEL)
    # nested containers may also carry stray keys
    for container, allowed in (("vitals", _VITALS), ("labs", _LABS)):
        c = raw.get(container)
        if isinstance(c, dict):
            dropped += [f"{container}.{k}" for k in c if k not in allowed]

    ctx: dict[str, Any] = {}
    safety: dict[str, Any] = {}

    a = raw.get("age_years", raw.get("age"))
    try:
        age = float(a) if a is not None and not isinstance(a, bool) else None
    except (TypeError, ValueError):
        age = None
    if age is not None and not (0 <= age <= 125):
        age = None
    if age is not None:
        age = float(int(age)) if age >= 1 else round(age, 2)
        safety["age_years"] = age
        ctx["age_years"] = "90+" if age >= 90 else int(age) if age >= 1 else age  # doc 14.1: 90+ masked
        ctx["age_group"] = _age_group(age)

    sx = raw.get("sex", raw.get("gender"))
    if sx is not None:
        v = _SEX.get(str(sx).strip().lower())
        ctx["sex"] = v or "unknown"
        safety["sex"] = ctx["sex"]

    for k in ("weight_kg", "height_cm", "symptom_duration_days"):
        v = _num(raw.get(k), k)
        if v is not None:
            ctx[k] = v
            safety[k] = v
    bmi = _num(raw.get("bmi"), "bmi")
    if bmi is None and "weight_kg" in ctx and "height_cm" in ctx:
        bmi = round(ctx["weight_kg"] / ((ctx["height_cm"] / 100.0) ** 2), 1)
    if bmi is not None:
        ctx["bmi"] = round(bmi, 1)

    for k in ("symptoms", "history", "family_history"):
        items = raw.get(k)
        if isinstance(items, (str,)):
            items = [items]
        if isinstance(items, list):
            clean = [sanitize_text(i, f"{k}[{n}]", flags) for n, i in enumerate(items[:MAX_ITEMS])]
            clean = [c for c in clean if c]
            if clean:
                ctx[k] = clean

    icd = raw.get("known_conditions_icd10")
    if isinstance(icd, list):
        codes = [str(c).strip().upper() for c in icd if _ICD.match(str(c).strip().upper())]
        if codes:
            ctx["known_conditions_icd10"] = codes[:MAX_ITEMS]

    vit_src = dict(raw.get("vitals") or {}) if isinstance(raw.get("vitals"), dict) else {}
    for k in _VITALS:
        if k in raw and k not in vit_src:
            vit_src[k] = raw[k]
    vitals = {k: v for k in _VITALS if (v := _num(vit_src.get(k), k)) is not None}
    if vitals:
        ctx["vitals"] = vitals
        safety.update({k: vitals[k] for k in ("bp_sys", "hr_bpm") if k in vitals})

    lab_src = dict(raw.get("labs") or {}) if isinstance(raw.get("labs"), dict) else {}
    for k in _LABS:
        if k in raw and k not in lab_src:
            lab_src[k] = raw[k]
    labs: dict[str, Any] = {
        k: v for k in _LABS if k != "child_pugh" and (v := _num(lab_src.get(k), k)) is not None
    }
    cp = str(lab_src.get("child_pugh") or "").strip().upper()
    if cp in ("A", "B", "C"):
        labs["child_pugh"] = cp
    safety.update(labs)

    for k in ("pregnancy", "lactation"):
        v = raw.get(k)
        if isinstance(v, bool):
            ctx[k] = v
            safety[k] = v
        else:
            ctx.setdefault(k, None)
            safety[k] = None

    allergies = raw.get("allergies")
    if isinstance(allergies, str):
        allergies = [allergies]
    if isinstance(allergies, list):
        al = [sanitize_text(i, f"allergies[{n}]", flags, 80) for n, i in enumerate(allergies[:MAX_ITEMS])]
        al = [i for i in al if i and i not in (REDACTED, SUSPICIOUS)]
        if al:
            safety["allergies"] = al

    meds = raw.get("current_medications")
    if isinstance(meds, list):
        out_m: list[dict[str, Any]] = []
        for n, m in enumerate(meds[:MAX_ITEMS]):
            if isinstance(m, str):
                m = {"inn": m}
            if not isinstance(m, dict):
                continue
            inn = sanitize_text(m.get("inn", m.get("name")), f"current_medications[{n}].inn", flags, 80)
            if not inn or inn in (REDACTED, SUSPICIOUS):
                continue
            item: dict[str, Any] = {"inn": inn}
            dm = _num(m.get("dose_mg"), "dose_mg")
            if dm is not None:
                item["dose_mg"] = dm
            fr = sanitize_text(m.get("freq"), f"current_medications[{n}].freq", flags, 20)
            if fr and fr not in (REDACTED, SUSPICIOUS):
                item["freq"] = fr
            out_m.append(item)
        if out_m:
            safety["current_medications"] = out_m

    conds = raw.get("conditions")
    cflags = raw.get("condition_flags")
    cl: list[str] = []
    for src_list in (conds, cflags):
        if isinstance(src_list, list):
            for n, c in enumerate(src_list[:MAX_ITEMS]):
                s = sanitize_text(c, f"conditions[{n}]", flags, 80)
                if s and s not in (REDACTED, SUSPICIOUS):
                    cl.append(s)
    if cl:
        safety["conditions"] = cl

    llm_ctx = ctx
    # Call-B safety payload = subset (doc 13.5); `conditions` appear in safety only
    input_fields = sorted(_paths(llm_ctx))
    h = sha256_hex(canonical_json({"ctx": llm_ctx, "safety": safety}))
    # PII guard (defence in depth): nothing that leaves may still match a PII pattern
    assert_no_pii(llm_ctx)
    assert_no_pii(safety)
    return DeidResult(
        llm_context=llm_ctx,
        safety=safety,
        input_fields=input_fields,
        dropped_fields=sorted(set(dropped)),
        flags=flags,
        input_hash=h,
    )


def iter_strings(obj: Any):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from iter_strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from iter_strings(v)


def assert_no_pii(payload: Any) -> None:
    """Final guard: raise if ANY string in the payload still looks like PII."""
    for s in iter_strings(payload):
        kinds = scan_pii(s)
        if kinds:
            raise PIIGuardError(f"PII patterns detected in outbound payload: {sorted(set(kinds))}")


def output_has_pii(text: str) -> list[str]:
    """Scan LLM output for echoed PII (phone/email/PINFL/names)."""
    return scan_pii(text)
