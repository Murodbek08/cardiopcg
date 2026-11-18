"""RBAC: permission matrix (doc 01 section 2) and object-level policy."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from app.models.enums import ExamStatus, UserRole


class Permission(StrEnum):
    patient_read = "patient:read"
    patient_write = "patient:write"
    patient_delete = "patient:delete"
    patient_restore = "patient:restore"
    history_delete = "history:delete"
    exam_create = "exam:create"
    exam_assign = "exam:assign"
    exam_cancel = "exam:cancel"
    exam_delete = "exam:delete"
    national_id_read = "patient:national_id"
    recording_upload = "recording:upload"
    recording_delete = "recording:delete"
    analysis_start = "analysis:start"
    analysis_rerun = "analysis:rerun"
    report_read = "report:read"
    report_read_full = "report:read_full"
    report_regenerate = "report:regenerate"
    prescription_read = "prescription:read"
    prescription_read_approved = "prescription:read_approved"
    prescription_write = "prescription:write"
    prescription_approve = "prescription:approve"
    conclusion_read = "conclusion:read"
    conclusion_write = "conclusion:write"
    conclusion_sign = "conclusion:sign"
    conclusion_read_signed = "conclusion:read_signed"
    analytics_admin = "analytics:admin"
    analytics_doctor = "analytics:doctor"
    analytics_nurse = "analytics:nurse"
    audit_read = "audit:read"
    audit_read_own = "audit:read_own"
    user_manage = "user:manage"
    settings_write = "settings:write"
    export_pdf = "export:pdf"
    export_csv = "export:csv"
    export_audit = "export:audit"
    drug_kb_read = "drug_kb:read"
    drug_kb_write = "drug_kb:write"


P = Permission

_COMMON = {
    P.patient_read,
    P.patient_write,
    P.exam_create,
    P.exam_assign,
    P.exam_cancel,
    P.recording_upload,
    P.analysis_start,
    P.report_read,
    P.conclusion_read_signed,
    P.export_pdf,
}

PERMISSIONS: dict[UserRole, frozenset[Permission]] = {
    UserRole.admin: frozenset(
        _COMMON
        | {
            P.patient_delete,
            P.patient_restore,
            P.history_delete,
            P.exam_delete,
            P.national_id_read,
            P.recording_delete,
            P.analysis_rerun,
            P.report_read_full,
            P.report_regenerate,
            P.prescription_read,
            P.conclusion_read,
            P.analytics_admin,
            P.analytics_doctor,
            P.analytics_nurse,
            P.audit_read,
            P.user_manage,
            P.settings_write,
            P.export_csv,
            P.export_audit,
            P.drug_kb_read,
            P.drug_kb_write,
        }
    ),
    UserRole.doctor: frozenset(
        _COMMON
        | {
            P.patient_delete,
            P.history_delete,
            P.national_id_read,
            P.recording_delete,
            P.analysis_rerun,
            P.report_read_full,
            P.report_regenerate,
            P.prescription_read,
            P.prescription_write,
            P.prescription_approve,
            P.conclusion_read,
            P.conclusion_write,
            P.conclusion_sign,
            P.analytics_doctor,
            P.audit_read_own,
            P.export_csv,
            P.drug_kb_read,
        }
    ),
    UserRole.nurse: frozenset(
        _COMMON | {P.prescription_read_approved, P.analytics_nurse, P.recording_delete}
    ),
}


def has_permission(role: UserRole | str, perm: Permission) -> bool:
    return perm in PERMISSIONS.get(UserRole(role), frozenset())


def permissions_for(role: UserRole | str) -> list[str]:
    return sorted(p.value for p in PERMISSIONS.get(UserRole(role), frozenset()))


class Policy:
    """Object-level rules on top of the role matrix."""

    def can(self, user: Any, action: Permission, obj: Any = None) -> bool:
        if not has_permission(user.role, action):
            return False
        if obj is None:
            return True
        checker = getattr(self, "_obj_" + action.name, None)
        return True if checker is None else bool(checker(user, obj))

    # -- examinations: nurse sees own exams and exams of own patients (patient.created_by) --
    @staticmethod
    def nurse_owns_exam(user: Any, exam: Any, patient_created_by: Any = None) -> bool:
        return exam.performed_by == user.id or (
            patient_created_by is not None and patient_created_by == user.id
        )

    @staticmethod
    def _obj_exam_cancel(user: Any, exam: Any) -> bool:
        if user.role == UserRole.nurse:
            return exam.performed_by == user.id and exam.status in (ExamStatus.draft, ExamStatus.uploaded)
        return True

    @staticmethod
    def _obj_recording_delete(user: Any, exam: Any) -> bool:
        if user.role == UserRole.nurse:
            return exam.performed_by == user.id and exam.status in (ExamStatus.draft, ExamStatus.uploaded)
        if user.role == UserRole.doctor:
            return exam.status != ExamStatus.completed
        return True


policy = Policy()
