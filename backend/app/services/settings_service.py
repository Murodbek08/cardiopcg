"""System settings registry (types, ranges, defaults) and DB access."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.system import SystemSetting


@dataclass(frozen=True)
class SettingDef:
    type: str  # int|float|bool|string|json
    default: Any
    public: bool = False
    min: float | None = None
    max: float | None = None
    description: str = ""


SETTING_DEFS: dict[str, SettingDef] = {
    "upload.max_audio_mb": SettingDef("int", 25, True, 1, 200, "Maksimal audio hajmi (MB)"),
    "upload.max_image_mb": SettingDef("int", 10, True, 1, 100, "Maksimal tasvir hajmi (MB)"),
    "upload.max_files_per_exam": SettingDef("int", 12, True, 1, 100, "Tekshiruvga maksimal fayllar soni"),
    "audio.min_duration_sec": SettingDef("int", 5, True, 1, 60, "Minimal audio davomiyligi (s)"),
    "audio.max_duration_sec": SettingDef("int", 120, True, 10, 600, "Maksimal audio davomiyligi (s)"),
    "analysis.auto_start": SettingDef(
        "bool", True, False, description="Yuklagach avtomatik navbatga qo'yish"
    ),
    "analysis.model_version": SettingDef("string", "pcg-cnn-1.0.0", False, description="Model versiyasi"),
    "ai.llm_model": SettingDef("string", "deepseek-chat", False, description="LLM modeli"),
    "ai.llm_enabled": SettingDef("bool", True, False, description="LLM izohini yoqish"),
    "ai.drug_suggestions_enabled": SettingDef("bool", True, False, description="AI dori takliflari"),
    "ai.critical_probability_threshold": SettingDef(
        "float", 0.85, False, 0.0, 1.0, "critical_finding chegarasi"
    ),
    "security.lockout_attempts": SettingDef("int", 5, False, 3, 20, "Bloklashgacha urinishlar"),
    "security.lockout_minutes": SettingDef("int", 15, False, 1, 1440, "Blok davomiyligi (daqiqa)"),
    "security.password_min_length": SettingDef("int", 10, True, 8, 64, "Parol minimal uzunligi"),
    "retention.audit_days": SettingDef("int", 1825, False, 30, 36500, "Audit saqlash muddati (kun)"),
    "retention.raw_llm_days": SettingDef("int", 90, False, 1, 3650, "Xom LLM javobi muddati (kun)"),
    "clinic.name": SettingDef("string", "CardioPCG AI", True, description="Klinika nomi"),
    "clinic.logo_key": SettingDef("string", "", True, description="Logo storage kaliti"),
    "clinic.report_footer": SettingDef("string", "", True, description="PDF pastki matni"),
}


def coerce(key: str, value: Any) -> Any:
    d = SETTING_DEFS.get(key)
    if d is None:
        raise AppError(
            422,
            "VALIDATION_ERROR",
            f"Noma'lum sozlama: {key}",
            [{"field": key, "msg": "unknown key", "type": "value_error"}],
        )

    def bad(msg: str) -> AppError:
        return AppError(
            422, "VALIDATION_ERROR", f"{key}: {msg}", [{"field": key, "msg": msg, "type": "value_error"}]
        )

    if d.type == "bool":
        if not isinstance(value, bool):
            raise bad("bool kutilgan")
        return value
    if d.type in ("int", "float"):
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise bad("son kutilgan")
        if d.type == "int":
            if int(value) != value:
                raise bad("butun son kutilgan")
            value = int(value)
        else:
            value = float(value)
        if d.min is not None and value < d.min:
            raise bad(f"kamida {d.min}")
        if d.max is not None and value > d.max:
            raise bad(f"koʻpi bilan {d.max}")
        return value
    if d.type == "string":
        if not isinstance(value, str) or len(value) > 500:
            raise bad("matn kutilgan (<=500)")
        return value
    return value


async def get_all(db: AsyncSession) -> dict[str, Any]:
    rows = (await db.execute(select(SystemSetting))).scalars().all()
    out = {k: d.default for k, d in SETTING_DEFS.items()}
    for r in rows:
        if r.key in SETTING_DEFS:
            out[r.key] = r.value
    return out


async def get_value(db: AsyncSession, key: str) -> Any:
    row = await db.get(SystemSetting, key)
    return row.value if row is not None else SETTING_DEFS[key].default


async def get_many(db: AsyncSession, *keys: str) -> dict[str, Any]:
    rows = (await db.execute(select(SystemSetting).where(SystemSetting.key.in_(keys)))).scalars().all()
    out = {k: SETTING_DEFS[k].default for k in keys}
    for r in rows:
        out[r.key] = r.value
    return out
