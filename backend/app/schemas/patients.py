from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import EmailStr, Field, field_validator

from app.models.enums import AllergySeverity, BloodGroup, Gender, HistoryKind
from app.schemas.auth import _check_phone
from app.schemas.common import Out, Strict


def _no_future(v: date | None) -> date | None:
    if v is not None and v > date.today():
        raise ValueError("Kelajak sanasi bo'lishi mumkin emas")
    return v


class PatientCreate(Strict):
    last_name: str = Field(min_length=1, max_length=80)
    first_name: str = Field(min_length=1, max_length=80)
    middle_name: str | None = Field(default=None, max_length=80)
    birth_date: date
    gender: Gender
    phone: str | None = None
    email: EmailStr | None = None
    address: str | None = Field(default=None, max_length=1000)
    national_id: str | None = Field(default=None, min_length=5, max_length=32)
    blood_group: BloodGroup = BloodGroup.unknown
    height_cm: float | None = Field(default=None, ge=30, le=260)
    weight_kg: float | None = Field(default=None, ge=1, le=400)
    emergency_contact_name: str | None = Field(default=None, max_length=160)
    emergency_contact_phone: str | None = None
    primary_doctor_id: UUID | None = None
    ai_consent: bool = False
    notes: str | None = Field(default=None, max_length=5000)

    _bd = field_validator("birth_date")(_no_future)
    _ph = field_validator("phone", "emergency_contact_phone")(_check_phone)

    @field_validator("birth_date")
    @classmethod
    def _plausible_age(cls, v: date) -> date:
        if v.year < 1900:
            raise ValueError("Tug'ilgan sana noto'g'ri")
        return v


class PatientUpdate(Strict):
    last_name: str | None = Field(default=None, min_length=1, max_length=80)
    first_name: str | None = Field(default=None, min_length=1, max_length=80)
    middle_name: str | None = Field(default=None, max_length=80)
    birth_date: date | None = None
    gender: Gender | None = None
    phone: str | None = None
    email: EmailStr | None = None
    address: str | None = Field(default=None, max_length=1000)
    national_id: str | None = Field(default=None, min_length=5, max_length=32)
    blood_group: BloodGroup | None = None
    height_cm: float | None = Field(default=None, ge=30, le=260)
    weight_kg: float | None = Field(default=None, ge=1, le=400)
    emergency_contact_name: str | None = Field(default=None, max_length=160)
    emergency_contact_phone: str | None = None
    primary_doctor_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=5000)
    ai_consent: bool | None = None
    is_active: bool | None = None

    _bd = field_validator("birth_date")(_no_future)
    _ph = field_validator("phone", "emergency_contact_phone")(_check_phone)


class DoctorBrief(Out):
    id: UUID
    full_name: str


class AllergyIn(Strict):
    substance: str = Field(min_length=1, max_length=160)
    substance_code: str | None = Field(default=None, max_length=64)
    reaction: str | None = Field(default=None, max_length=200)
    severity: AllergySeverity = AllergySeverity.moderate
    noted_date: date | None = None


class AllergyPatch(Strict):
    substance: str | None = Field(default=None, min_length=1, max_length=160)
    substance_code: str | None = Field(default=None, max_length=64)
    reaction: str | None = Field(default=None, max_length=200)
    severity: AllergySeverity | None = None
    noted_date: date | None = None
    is_active: bool | None = None


class AllergyOut(Out):
    id: UUID
    patient_id: UUID
    substance: str
    substance_code: str | None = None
    reaction: str | None = None
    severity: AllergySeverity
    noted_date: date | None = None
    is_active: bool


class HistoryIn(Strict):
    kind: HistoryKind
    title: str = Field(min_length=1, max_length=200)
    icd10_code: str | None = Field(default=None, max_length=10)
    description: str | None = Field(default=None, max_length=5000)
    onset_date: date | None = None
    resolved_date: date | None = None


class HistoryPatch(Strict):
    kind: HistoryKind | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    icd10_code: str | None = Field(default=None, max_length=10)
    description: str | None = Field(default=None, max_length=5000)
    onset_date: date | None = None
    resolved_date: date | None = None
    is_active: bool | None = None


class HistoryOut(Out):
    id: UUID
    patient_id: UUID
    kind: HistoryKind
    title: str
    icd10_code: str | None = None
    description: str | None = None
    onset_date: date | None = None
    resolved_date: date | None = None
    is_active: bool


class MedicationIn(Strict):
    drug_name: str = Field(min_length=1, max_length=160)
    inn_code: str | None = Field(default=None, max_length=64)
    dose: str | None = Field(default=None, max_length=60)
    frequency: str | None = Field(default=None, max_length=60)
    route: str | None = Field(default=None, max_length=30)
    start_date: date | None = None
    end_date: date | None = None
    prescribed_by: str | None = Field(default=None, max_length=160)


class MedicationPatch(Strict):
    drug_name: str | None = Field(default=None, min_length=1, max_length=160)
    inn_code: str | None = Field(default=None, max_length=64)
    dose: str | None = Field(default=None, max_length=60)
    frequency: str | None = Field(default=None, max_length=60)
    route: str | None = Field(default=None, max_length=30)
    start_date: date | None = None
    end_date: date | None = None
    prescribed_by: str | None = Field(default=None, max_length=160)
    is_active: bool | None = None


class MedicationOut(Out):
    id: UUID
    patient_id: UUID
    drug_name: str
    inn_code: str | None = None
    dose: str | None = None
    frequency: str | None = None
    route: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    prescribed_by: str | None = None
    is_active: bool


class PatientListItem(Out):
    id: UUID
    mrn: str
    full_name: str
    birth_date: date
    age: int
    gender: Gender
    phone: str | None = None
    primary_doctor: DoctorBrief | None = None
    last_exam_at: datetime | None = None
    exam_count: int
    has_allergies: bool


class PatientStats(Out):
    exam_count: int
    last_exam_at: datetime | None = None
    last_pcg_class: str | None = None


class PatientOut(Out):
    id: UUID
    mrn: str
    last_name: str
    first_name: str
    middle_name: str | None = None
    full_name: str
    birth_date: date
    age: int
    gender: Gender
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    national_id: str | None = None
    blood_group: BloodGroup
    height_cm: float | None = None
    weight_kg: float | None = None
    bmi: float | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    primary_doctor: DoctorBrief | None = None
    notes: str | None = None
    ai_consent: bool = False
    is_active: bool
    version: int
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class PatientDetail(PatientOut):
    allergies: list[AllergyOut] = []
    medical_history: list[HistoryOut] = []
    current_medications: list[MedicationOut] = []
    stats: PatientStats


class TimelineItem(Out):
    ts: datetime
    type: str
    exam_id: UUID | None = None
    exam_no: str | None = None
    pcg_class: str | None = None
    severity: str | None = None
    status: str | None = None
    extra: dict[str, Any] = {}
