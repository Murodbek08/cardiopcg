"""Import all models so that Base.metadata is complete (Alembic autogenerate)."""

from app.db.base import Base
from app.models.analysis import AnalysisJob, AnalysisResult, PcgSegment
from app.models.clinical import AiReport, DoctorConclusion, DrugRecommendation, Prescription
from app.models.examination import ExamCounter, Examination, ExamStatusHistory
from app.models.kb import KbDrug, KbDrugVersion, KbInteraction, KbMeta
from app.models.patient import Allergy, CurrentMedication, MedicalHistory, Patient, patient_mrn_seq
from app.models.recording import Recording
from app.models.system import (
    AuditLog,
    ExportJob,
    IdempotencyKey,
    Notification,
    SystemSetting,
)
from app.models.user import PasswordResetToken, RefreshToken, User

__all__ = [
    "AiReport",
    "Allergy",
    "AnalysisJob",
    "AnalysisResult",
    "AuditLog",
    "Base",
    "CurrentMedication",
    "DoctorConclusion",
    "DrugRecommendation",
    "ExamCounter",
    "ExamStatusHistory",
    "Examination",
    "ExportJob",
    "IdempotencyKey",
    "KbDrug",
    "KbDrugVersion",
    "KbInteraction",
    "KbMeta",
    "MedicalHistory",
    "Notification",
    "PasswordResetToken",
    "Patient",
    "PcgSegment",
    "Prescription",
    "Recording",
    "RefreshToken",
    "SystemSetting",
    "User",
    "patient_mrn_seq",
]
