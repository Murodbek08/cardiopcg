"""PostgreSQL native enums (doc 01 section 1.1). Python StrEnums mirror DB values."""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy.dialects import postgresql


class UserRole(StrEnum):
    admin = "admin"
    doctor = "doctor"
    nurse = "nurse"


class UserStatus(StrEnum):
    active = "active"
    suspended = "suspended"
    pending = "pending"


class Gender(StrEnum):
    male = "male"
    female = "female"


class BloodGroup(StrEnum):
    O_POS = "O+"
    O_NEG = "O-"
    A_POS = "A+"
    A_NEG = "A-"
    B_POS = "B+"
    B_NEG = "B-"
    AB_POS = "AB+"
    AB_NEG = "AB-"
    unknown = "unknown"


class ExamStatus(StrEnum):
    draft = "draft"
    uploaded = "uploaded"
    queued = "queued"
    processing = "processing"
    ai_ready = "ai_ready"
    in_review = "in_review"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class ExamPriority(StrEnum):
    routine = "routine"
    urgent = "urgent"
    emergency = "emergency"


class AuscultationSite(StrEnum):
    aortic = "aortic"
    pulmonic = "pulmonic"
    erb = "erb"
    tricuspid = "tricuspid"
    mitral = "mitral"
    apex = "apex"
    carotid = "carotid"
    other = "other"


class PatientPosition(StrEnum):
    supine = "supine"
    sitting = "sitting"
    left_lateral = "left_lateral"
    standing = "standing"
    other = "other"


class RecordingKind(StrEnum):
    audio = "audio"
    spectrogram = "spectrogram"
    waveform_image = "waveform_image"
    envelope_json = "envelope_json"
    other_image = "other_image"


class RecordingStatus(StrEnum):
    uploading = "uploading"
    uploaded = "uploaded"
    validated = "validated"
    rejected = "rejected"
    processed = "processed"


class JobStatus(StrEnum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class PcgClass(StrEnum):
    normal = "normal"
    murmur = "murmur"
    extra_heart_sound = "extra_heart_sound"
    artifact = "artifact"
    undetermined = "undetermined"


class Severity(StrEnum):
    none = "none"
    mild = "mild"
    moderate = "moderate"
    severe = "severe"
    critical = "critical"


class SegmentType(StrEnum):
    S1 = "S1"
    S2 = "S2"
    S3 = "S3"
    S4 = "S4"
    systole = "systole"
    diastole = "diastole"
    murmur = "murmur"
    click = "click"
    noise = "noise"


class MurmurTiming(StrEnum):
    systolic = "systolic"
    diastolic = "diastolic"
    continuous = "continuous"
    none = "none"


class ReportStatus(StrEnum):
    generating = "generating"
    ready = "ready"
    failed = "failed"
    superseded = "superseded"


class PrescriptionStatus(StrEnum):
    draft = "draft"
    suggested = "suggested"
    approved = "approved"
    rejected = "rejected"
    cancelled = "cancelled"


class ConclusionStatus(StrEnum):
    draft = "draft"
    signed = "signed"
    amended = "amended"


class AgreementLevel(StrEnum):
    agree = "agree"
    partial = "partial"
    disagree = "disagree"


class NotificationType(StrEnum):
    exam_uploaded = "exam_uploaded"
    analysis_done = "analysis_done"
    analysis_failed = "analysis_failed"
    review_requested = "review_requested"
    conclusion_signed = "conclusion_signed"
    critical_finding = "critical_finding"
    assignment = "assignment"
    system = "system"


class AuditAction(StrEnum):
    login = "login"
    login_failed = "login_failed"
    logout = "logout"
    token_refresh = "token_refresh"
    token_reuse_detected = "token_reuse_detected"
    password_change = "password_change"
    password_reset = "password_reset"
    create = "create"
    read = "read"
    update = "update"
    delete = "delete"
    restore = "restore"
    export = "export"
    download = "download"
    upload = "upload"
    assign = "assign"
    ai_call = "ai_call"
    status_change = "status_change"
    sign = "sign"
    approve = "approve"
    reject = "reject"
    permission_denied = "permission_denied"
    settings_change = "settings_change"


class AllergySeverity(StrEnum):
    mild = "mild"
    moderate = "moderate"
    severe = "severe"
    anaphylaxis = "anaphylaxis"


class HistoryKind(StrEnum):
    cardiac = "cardiac"
    chronic = "chronic"
    surgical = "surgical"
    family = "family"
    habit = "habit"
    other = "other"


class ExportFormat(StrEnum):
    pdf = "pdf"
    csv = "csv"
    json = "json"


# name of the PG type -> python enum (used by migration to create types explicitly)
PG_ENUMS: dict[str, type[StrEnum]] = {
    "user_role": UserRole,
    "user_status": UserStatus,
    "gender": Gender,
    "blood_group": BloodGroup,
    "exam_status": ExamStatus,
    "exam_priority": ExamPriority,
    "auscultation_site": AuscultationSite,
    "patient_position": PatientPosition,
    "recording_kind": RecordingKind,
    "recording_status": RecordingStatus,
    "job_status": JobStatus,
    "pcg_class": PcgClass,
    "severity": Severity,
    "segment_type": SegmentType,
    "murmur_timing": MurmurTiming,
    "report_status": ReportStatus,
    "prescription_status": PrescriptionStatus,
    "conclusion_status": ConclusionStatus,
    "agreement_level": AgreementLevel,
    "notification_type": NotificationType,
    "audit_action": AuditAction,
    "allergy_severity": AllergySeverity,
    "history_kind": HistoryKind,
    "export_format": ExportFormat,
}


def pg_enum(enum_cls: type[StrEnum], name: str) -> postgresql.ENUM:
    """Native PG enum, type creation is done explicitly by the migration."""
    return postgresql.ENUM(
        enum_cls,
        name=name,
        create_type=False,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )
