
"""initial

Revision ID: 0001
Revises:
Create Date: 2026-11-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import json

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None

ENUMS = {
    "user_role": ["admin", "doctor", "nurse"],
    "user_status": ["active", "suspended", "pending"],
    "gender": ["male", "female"],
    "blood_group": ["O+", "O-", "A+", "A-", "B+", "B-", "AB+", "AB-", "unknown"],
    "exam_status": ["draft", "uploaded", "queued", "processing", "ai_ready", "in_review", "completed", "failed", "cancelled"],
    "exam_priority": ["routine", "urgent", "emergency"],
    "auscultation_site": ["aortic", "pulmonic", "erb", "tricuspid", "mitral", "apex", "carotid", "other"],
    "patient_position": ["supine", "sitting", "left_lateral", "standing", "other"],
    "recording_kind": ["audio", "spectrogram", "waveform_image", "envelope_json", "other_image"],
    "recording_status": ["uploading", "uploaded", "validated", "rejected", "processed"],
    "job_status": ["pending", "running", "succeeded", "failed", "cancelled"],
    "pcg_class": ["normal", "murmur", "extra_heart_sound", "artifact", "undetermined"],
    "severity": ["none", "mild", "moderate", "severe", "critical"],
    "segment_type": ["S1", "S2", "S3", "S4", "systole", "diastole", "murmur", "click", "noise"],
    "murmur_timing": ["systolic", "diastolic", "continuous", "none"],
    "report_status": ["generating", "ready", "failed", "superseded"],
    "prescription_status": ["draft", "suggested", "approved", "rejected", "cancelled"],
    "conclusion_status": ["draft", "signed", "amended"],
    "agreement_level": ["agree", "partial", "disagree"],
    "notification_type": ["exam_uploaded", "analysis_done", "analysis_failed", "review_requested", "conclusion_signed", "critical_finding", "assignment", "system"],
    "audit_action": ["login", "login_failed", "logout", "token_refresh", "token_reuse_detected", "password_change", "password_reset", "create", "read", "update", "delete", "restore", "export", "download", "upload", "assign", "ai_call", "status_change", "sign", "approve", "reject", "permission_denied", "settings_change"],
    "allergy_severity": ["mild", "moderate", "severe", "anaphylaxis"],
    "history_kind": ["cardiac", "chronic", "surgical", "family", "habit", "other"],
    "export_format": ["pdf", "csv", "json"],
}

# (key, value, type, description, is_public)
SETTINGS_SEED = [
    ("upload.max_audio_mb", 25, "int", "Maksimal audio hajmi (MB)", True),
    ("upload.max_image_mb", 10, "int", "Maksimal tasvir hajmi (MB)", True),
    ("upload.max_files_per_exam", 12, "int", "Tekshiruvga maksimal fayllar soni", True),
    ("audio.min_duration_sec", 5, "int", "Minimal audio davomiyligi (s)", True),
    ("audio.max_duration_sec", 120, "int", "Maksimal audio davomiyligi (s)", True),
    ("analysis.auto_start", True, "bool", "Yuklagach tahlilni avtomatik navbatga qo'yish", False),
    ("analysis.model_version", "pcg-cnn-1.0.0", "string", "Tahlil model versiyasi", False),
    ("ai.llm_model", "deepseek-chat", "string", "LLM modeli", False),
    ("ai.llm_enabled", True, "bool", "LLM izohini yoqish", False),
    ("ai.drug_suggestions_enabled", True, "bool", "AI dori takliflarini yoqish", False),
    ("ai.critical_probability_threshold", 0.85, "float", "critical_finding bildirishnomasi chegarasi", False),
    ("security.lockout_attempts", 5, "int", "Bloklashgacha noto'g'ri urinishlar", False),
    ("security.lockout_minutes", 15, "int", "Blok davomiyligi (daqiqa)", False),
    ("security.password_min_length", 10, "int", "Parol minimal uzunligi", True),
    ("retention.audit_days", 1825, "int", "Audit saqlash muddati (kun)", False),
    ("retention.raw_llm_days", 90, "int", "Xom LLM javobi saqlash muddati (kun)", False),
    ("clinic.name", "CardioPCG AI", "string", "Klinika nomi", True),
    ("clinic.logo_key", "", "string", "Logo storage kaliti", True),
    ("clinic.report_footer", "", "string", "PDF hisobot pastki matni", True),
]


def upgrade() -> None:
    bind = op.get_bind()
    for ext in ("pgcrypto", "pg_trgm", "citext", "btree_gin"):
        op.execute(f'CREATE EXTENSION IF NOT EXISTS "{ext}"')
    for name, values in ENUMS.items():
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)
    op.execute("CREATE SEQUENCE IF NOT EXISTS patient_mrn_seq START 1")

    op.create_table('audit_logs',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('username_snapshot', sa.String(length=32), nullable=True),
    sa.Column('role_snapshot', postgresql.ENUM('admin', 'doctor', 'nurse', name='user_role', create_type=False), nullable=True),
    sa.Column('action', postgresql.ENUM('login', 'login_failed', 'logout', 'token_refresh', 'token_reuse_detected', 'password_change', 'password_reset', 'create', 'read', 'update', 'delete', 'restore', 'export', 'download', 'upload', 'assign', 'ai_call', 'status_change', 'sign', 'approve', 'reject', 'permission_denied', 'settings_change', name='audit_action', create_type=False), nullable=False),
    sa.Column('resource_type', sa.String(length=40), nullable=True),
    sa.Column('resource_id', sa.UUID(), nullable=True),
    sa.Column('patient_id', sa.UUID(), nullable=True),
    sa.Column('ip', postgresql.INET(), nullable=True),
    sa.Column('user_agent', sa.String(length=300), nullable=True),
    sa.Column('request_id', sa.String(length=40), nullable=True),
    sa.Column('method', sa.String(length=8), nullable=True),
    sa.Column('path', sa.String(length=300), nullable=True),
    sa.Column('status_code', sa.SmallInteger(), nullable=True),
    sa.Column('success', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('changes', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_logs'))
    )
    op.create_index('idx_audit_action_ts', 'audit_logs', ['action', sa.literal_column('ts DESC')], unique=False)
    op.create_index('idx_audit_patient_ts', 'audit_logs', ['patient_id', sa.literal_column('ts DESC')], unique=False, postgresql_where=sa.text('patient_id IS NOT NULL'))
    op.create_index('idx_audit_request', 'audit_logs', ['request_id'], unique=False)
    op.create_index('idx_audit_resource', 'audit_logs', ['resource_type', 'resource_id'], unique=False)
    op.create_index('idx_audit_ts', 'audit_logs', [sa.literal_column('ts DESC')], unique=False)
    op.create_index('idx_audit_user_ts', 'audit_logs', ['user_id', sa.literal_column('ts DESC')], unique=False)
    op.create_table('exam_counters',
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('last', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('day', name=op.f('pk_exam_counters'))
    )
    op.create_table('idempotency_keys',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('endpoint', sa.String(length=100), nullable=False),
    sa.Column('response_hash', sa.String(length=64), nullable=True),
    sa.Column('status_code', sa.SmallInteger(), nullable=True),
    sa.Column('response_body', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('key', 'user_id', name='pk_idempotency_keys')
    )
    op.create_table('users',
    sa.Column('username', postgresql.CITEXT(), nullable=False),
    sa.Column('email', postgresql.CITEXT(), nullable=True),
    sa.Column('password_hash', sa.Text(), nullable=False),
    sa.Column('full_name', sa.String(length=160), nullable=False),
    sa.Column('role', postgresql.ENUM('admin', 'doctor', 'nurse', name='user_role', create_type=False), nullable=False),
    sa.Column('status', postgresql.ENUM('active', 'suspended', 'pending', name='user_status', create_type=False), server_default='active', nullable=False),
    sa.Column('phone', sa.String(length=32), nullable=True),
    sa.Column('specialty', sa.String(length=120), nullable=True),
    sa.Column('license_no', sa.String(length=64), nullable=True),
    sa.Column('department', sa.String(length=120), nullable=True),
    sa.Column('avatar_key', sa.Text(), nullable=True),
    sa.Column('locale', sa.String(length=5), server_default='uz', nullable=False),
    sa.Column('must_change_password', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('failed_login_count', sa.SmallInteger(), server_default='0', nullable=False),
    sa.Column('lock_count', sa.SmallInteger(), server_default='0', nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('password_changed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('security_version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('password_history', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('char_length(username) >= 3', name=op.f('ck_users_username_len')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_users_created_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('email', name=op.f('uq_users_email')),
    sa.UniqueConstraint('username', name=op.f('uq_users_username'))
    )
    op.create_index('idx_users_fullname_trgm', 'users', ['full_name'], unique=False, postgresql_using='gin', postgresql_ops={'full_name': 'gin_trgm_ops'})
    op.create_index('idx_users_role_status', 'users', ['role', 'status'], unique=False, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_table('export_jobs',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.String(length=30), nullable=False),
    sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('format', postgresql.ENUM('pdf', 'csv', 'json', name='export_format', create_type=False), nullable=False),
    sa.Column('status', postgresql.ENUM('pending', 'running', 'succeeded', 'failed', 'cancelled', name='job_status', create_type=False), server_default='pending', nullable=False),
    sa.Column('file_key', sa.Text(), nullable=True),
    sa.Column('size_bytes', sa.BigInteger(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_export_jobs_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_export_jobs'))
    )
    op.create_table('notifications',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('type', postgresql.ENUM('exam_uploaded', 'analysis_done', 'analysis_failed', 'review_requested', 'conclusion_signed', 'critical_finding', 'assignment', 'system', name='notification_type', create_type=False), nullable=False),
    sa.Column('title', sa.String(length=160), nullable=False),
    sa.Column('body', sa.Text(), nullable=True),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('is_read', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_notifications_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_notifications'))
    )
    op.create_index('idx_notif_user_created', 'notifications', ['user_id', sa.literal_column('created_at DESC')], unique=False)
    op.create_index('idx_notif_user_read_created', 'notifications', ['user_id', 'is_read', sa.literal_column('created_at DESC')], unique=False)
    op.create_table('password_reset_tokens',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_password_reset_tokens_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_password_reset_tokens')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_password_reset_tokens_token_hash'))
    )
    op.create_table('patients',
    sa.Column('mrn', sa.String(length=16), nullable=False),
    sa.Column('last_name', sa.String(length=80), nullable=False),
    sa.Column('first_name', sa.String(length=80), nullable=False),
    sa.Column('middle_name', sa.String(length=80), nullable=True),
    sa.Column('birth_date', sa.Date(), nullable=False),
    sa.Column('gender', postgresql.ENUM('male', 'female', name='gender', create_type=False), nullable=False),
    sa.Column('phone', sa.String(length=32), nullable=True),
    sa.Column('email', postgresql.CITEXT(), nullable=True),
    sa.Column('address', sa.Text(), nullable=True),
    sa.Column('national_id_enc', postgresql.BYTEA(), nullable=True),
    sa.Column('national_id_hash', sa.String(length=64), nullable=True),
    sa.Column('blood_group', postgresql.ENUM('O+', 'O-', 'A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'unknown', name='blood_group', create_type=False), server_default='unknown', nullable=False),
    sa.Column('height_cm', sa.Numeric(precision=5, scale=1), nullable=True),
    sa.Column('weight_kg', sa.Numeric(precision=5, scale=1), nullable=True),
    sa.Column('emergency_contact_name', sa.String(length=160), nullable=True),
    sa.Column('emergency_contact_phone', sa.String(length=32), nullable=True),
    sa.Column('primary_doctor_id', sa.UUID(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('height_cm IS NULL OR (height_cm >= 30 AND height_cm <= 260)', name=op.f('ck_patients_height_range')),
    sa.CheckConstraint('weight_kg IS NULL OR (weight_kg >= 1 AND weight_kg <= 400)', name=op.f('ck_patients_weight_range')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_patients_created_by_users')),
    sa.ForeignKeyConstraint(['primary_doctor_id'], ['users.id'], name=op.f('fk_patients_primary_doctor_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_patients')),
    sa.UniqueConstraint('mrn', name=op.f('uq_patients_mrn')),
    sa.UniqueConstraint('national_id_hash', name=op.f('uq_patients_national_id_hash'))
    )
    op.create_index('idx_patients_birth', 'patients', ['birth_date'], unique=False)
    op.create_index('idx_patients_created', 'patients', [sa.literal_column('created_at DESC')], unique=False)
    op.create_index('idx_patients_doctor', 'patients', ['primary_doctor_id'], unique=False, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('idx_patients_name_trgm', 'patients', [sa.literal_column("(last_name || ' ' || first_name || ' ' || coalesce(middle_name, '')) gin_trgm_ops")], unique=False, postgresql_using='gin')
    op.create_index('idx_patients_phone', 'patients', ['phone'], unique=False)
    op.create_table('refresh_tokens',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('family_id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('parent_id', sa.UUID(), nullable=True),
    sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('family_started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_reason', sa.String(length=32), nullable=True),
    sa.Column('ip', postgresql.INET(), nullable=True),
    sa.Column('user_agent', sa.String(length=300), nullable=True),
    sa.Column('device_label', sa.String(length=120), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['parent_id'], ['refresh_tokens.id'], name=op.f('fk_refresh_tokens_parent_id_refresh_tokens')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_refresh_tokens_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_refresh_tokens')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_refresh_tokens_token_hash'))
    )
    op.create_index('idx_rt_expires', 'refresh_tokens', ['expires_at'], unique=False)
    op.create_index('idx_rt_family', 'refresh_tokens', ['family_id'], unique=False)
    op.create_index('idx_rt_user_active', 'refresh_tokens', ['user_id'], unique=False, postgresql_where=sa.text('revoked_at IS NULL'))
    op.create_table('system_settings',
    sa.Column('key', sa.String(length=80), nullable=False),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('value_type', sa.String(length=12), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('is_public', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], name=op.f('fk_system_settings_updated_by_users')),
    sa.PrimaryKeyConstraint('key', name=op.f('pk_system_settings'))
    )
    op.create_table('allergies',
    sa.Column('patient_id', sa.UUID(), nullable=False),
    sa.Column('substance', sa.String(length=160), nullable=False),
    sa.Column('substance_code', sa.String(length=64), nullable=True),
    sa.Column('reaction', sa.String(length=200), nullable=True),
    sa.Column('severity', postgresql.ENUM('mild', 'moderate', 'severe', 'anaphylaxis', name='allergy_severity', create_type=False), server_default='moderate', nullable=False),
    sa.Column('noted_date', sa.Date(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('recorded_by', sa.UUID(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], name=op.f('fk_allergies_patient_id_patients'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['recorded_by'], ['users.id'], name=op.f('fk_allergies_recorded_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_allergies'))
    )
    op.create_index('idx_allergy_code', 'allergies', [sa.literal_column('lower(substance_code)')], unique=False)
    op.create_index('idx_allergy_patient_active', 'allergies', ['patient_id'], unique=False, postgresql_where=sa.text('is_active'))
    op.create_index('uq_allergy_patient_substance', 'allergies', ['patient_id', sa.literal_column('lower(substance)')], unique=True, postgresql_where=sa.text('is_active'))
    op.create_table('current_medications',
    sa.Column('patient_id', sa.UUID(), nullable=False),
    sa.Column('drug_name', sa.String(length=160), nullable=False),
    sa.Column('inn_code', sa.String(length=64), nullable=True),
    sa.Column('dose', sa.String(length=60), nullable=True),
    sa.Column('frequency', sa.String(length=60), nullable=True),
    sa.Column('route', sa.String(length=30), nullable=True),
    sa.Column('start_date', sa.Date(), nullable=True),
    sa.Column('end_date', sa.Date(), nullable=True),
    sa.Column('prescribed_by', sa.String(length=160), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('recorded_by', sa.UUID(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], name=op.f('fk_current_medications_patient_id_patients'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['recorded_by'], ['users.id'], name=op.f('fk_current_medications_recorded_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_current_medications'))
    )
    op.create_index('idx_med_inn', 'current_medications', [sa.literal_column('lower(inn_code)')], unique=False)
    op.create_index('idx_med_patient_active', 'current_medications', ['patient_id'], unique=False, postgresql_where=sa.text('is_active'))
    op.create_table('examinations',
    sa.Column('exam_no', sa.String(length=20), nullable=False),
    sa.Column('patient_id', sa.UUID(), nullable=False),
    sa.Column('status', postgresql.ENUM('draft', 'uploaded', 'queued', 'processing', 'ai_ready', 'in_review', 'completed', 'failed', 'cancelled', name='exam_status', create_type=False), server_default='draft', nullable=False),
    sa.Column('priority', postgresql.ENUM('routine', 'urgent', 'emergency', name='exam_priority', create_type=False), server_default='routine', nullable=False),
    sa.Column('performed_by', sa.UUID(), nullable=False),
    sa.Column('assigned_doctor_id', sa.UUID(), nullable=True),
    sa.Column('examined_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('complaints', sa.Text(), nullable=True),
    sa.Column('symptoms', postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('patient_position', postgresql.ENUM('supine', 'sitting', 'left_lateral', 'standing', 'other', name='patient_position', create_type=False), nullable=True),
    sa.Column('heart_rate_bpm', sa.SmallInteger(), nullable=True),
    sa.Column('bp_systolic', sa.SmallInteger(), nullable=True),
    sa.Column('bp_diastolic', sa.SmallInteger(), nullable=True),
    sa.Column('spo2_pct', sa.SmallInteger(), nullable=True),
    sa.Column('temperature_c', sa.Numeric(precision=3, scale=1), nullable=True),
    sa.Column('weight_kg_at_exam', sa.Numeric(precision=5, scale=1), nullable=True),
    sa.Column('ai_requested_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ai_completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancel_reason', sa.Text(), nullable=True),
    sa.Column('failure_reason', sa.Text(), nullable=True),
    sa.Column('current_job_id', sa.UUID(), nullable=True),
    sa.Column('reviewed_by', sa.UUID(), nullable=True),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status <> 'completed' OR completed_at IS NOT NULL", name=op.f('ck_examinations_completed_has_ts')),
    sa.CheckConstraint('bp_systolic IS NULL OR bp_diastolic IS NULL OR bp_systolic > bp_diastolic', name=op.f('ck_examinations_bp_order')),
    sa.ForeignKeyConstraint(['assigned_doctor_id'], ['users.id'], name=op.f('fk_examinations_assigned_doctor_id_users')),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], name=op.f('fk_examinations_patient_id_patients')),
    sa.ForeignKeyConstraint(['performed_by'], ['users.id'], name=op.f('fk_examinations_performed_by_users')),
    sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], name=op.f('fk_examinations_reviewed_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_examinations')),
    sa.UniqueConstraint('exam_no', name=op.f('uq_examinations_exam_no'))
    )
    op.create_index('idx_exam_created_brin', 'examinations', ['created_at'], unique=False, postgresql_using='brin')
    op.create_index('idx_exam_doctor_status', 'examinations', ['assigned_doctor_id', 'status'], unique=False, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('idx_exam_examined_at', 'examinations', ['examined_at'], unique=False)
    op.create_index('idx_exam_patient_examined', 'examinations', ['patient_id', sa.literal_column('examined_at DESC')], unique=False)
    op.create_index('idx_exam_performed_created', 'examinations', ['performed_by', sa.literal_column('created_at DESC')], unique=False)
    op.create_index('idx_exam_priority_status', 'examinations', ['priority', 'status'], unique=False, postgresql_where=sa.text("status IN ('ai_ready','in_review')"))
    op.create_index('idx_exam_status_created', 'examinations', ['status', sa.literal_column('created_at DESC')], unique=False, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_table('medical_history',
    sa.Column('patient_id', sa.UUID(), nullable=False),
    sa.Column('kind', postgresql.ENUM('cardiac', 'chronic', 'surgical', 'family', 'habit', 'other', name='history_kind', create_type=False), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('icd10_code', sa.String(length=10), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('onset_date', sa.Date(), nullable=True),
    sa.Column('resolved_date', sa.Date(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('recorded_by', sa.UUID(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], name=op.f('fk_medical_history_patient_id_patients'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['recorded_by'], ['users.id'], name=op.f('fk_medical_history_recorded_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_medical_history'))
    )
    op.create_index('idx_mh_patient_active', 'medical_history', ['patient_id'], unique=False, postgresql_where=sa.text('is_active'))
    op.create_index('idx_mh_patient_kind', 'medical_history', ['patient_id', 'kind'], unique=False)
    op.create_table('analysis_jobs',
    sa.Column('examination_id', sa.UUID(), nullable=False),
    sa.Column('status', postgresql.ENUM('pending', 'running', 'succeeded', 'failed', 'cancelled', name='job_status', create_type=False), server_default='pending', nullable=False),
    sa.Column('stage', sa.String(length=32), server_default='queued', nullable=False),
    sa.Column('progress_pct', sa.SmallInteger(), server_default='0', nullable=False),
    sa.Column('celery_task_id', sa.String(length=64), nullable=True),
    sa.Column('attempt', sa.SmallInteger(), server_default='1', nullable=False),
    sa.Column('max_attempts', sa.SmallInteger(), server_default='3', nullable=False),
    sa.Column('error_code', sa.String(length=40), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('model_version', sa.String(length=40), nullable=True),
    sa.Column('options', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('requested_by', sa.UUID(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['examination_id'], ['examinations.id'], name=op.f('fk_analysis_jobs_examination_id_examinations')),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], name=op.f('fk_analysis_jobs_requested_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_analysis_jobs'))
    )
    op.create_index('idx_job_active', 'analysis_jobs', ['status'], unique=False, postgresql_where=sa.text("status IN ('pending','running')"))
    op.create_index('idx_job_exam_created', 'analysis_jobs', ['examination_id', sa.literal_column('created_at DESC')], unique=False)
    op.create_table('doctor_conclusions',
    sa.Column('examination_id', sa.UUID(), nullable=False),
    sa.Column('doctor_id', sa.UUID(), nullable=False),
    sa.Column('status', postgresql.ENUM('draft', 'signed', 'amended', name='conclusion_status', create_type=False), server_default='draft', nullable=False),
    sa.Column('diagnosis_text', sa.Text(), nullable=False),
    sa.Column('icd10_codes', postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('final_pcg_class', postgresql.ENUM('normal', 'murmur', 'extra_heart_sound', 'artifact', 'undetermined', name='pcg_class', create_type=False), nullable=False),
    sa.Column('final_severity', postgresql.ENUM('none', 'mild', 'moderate', 'severe', 'critical', name='severity', create_type=False), nullable=False),
    sa.Column('agreement_with_ai', postgresql.ENUM('agree', 'partial', 'disagree', name='agreement_level', create_type=False), nullable=False),
    sa.Column('disagreement_reason', sa.Text(), nullable=True),
    sa.Column('recommendations', sa.Text(), nullable=False),
    sa.Column('follow_up_date', sa.Date(), nullable=True),
    sa.Column('follow_up_notes', sa.Text(), nullable=True),
    sa.Column('referred_to', sa.String(length=160), nullable=True),
    sa.Column('amend_reason', sa.Text(), nullable=True),
    sa.Column('signed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('signature_hash', sa.String(length=64), nullable=True),
    sa.Column('amends_id', sa.UUID(), nullable=True),
    sa.Column('is_current', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['amends_id'], ['doctor_conclusions.id'], name=op.f('fk_doctor_conclusions_amends_id_doctor_conclusions')),
    sa.ForeignKeyConstraint(['doctor_id'], ['users.id'], name=op.f('fk_doctor_conclusions_doctor_id_users')),
    sa.ForeignKeyConstraint(['examination_id'], ['examinations.id'], name=op.f('fk_doctor_conclusions_examination_id_examinations')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_doctor_conclusions'))
    )
    op.create_index('idx_concl_agreement', 'doctor_conclusions', ['agreement_with_ai', 'signed_at'], unique=False)
    op.create_index('idx_concl_doctor_signed', 'doctor_conclusions', ['doctor_id', sa.literal_column('signed_at DESC')], unique=False)
    op.create_index('idx_concl_final_class', 'doctor_conclusions', ['final_pcg_class'], unique=False)
    op.create_index('uq_conclusion_current_exam', 'doctor_conclusions', ['examination_id'], unique=True, postgresql_where=sa.text('is_current'))
    op.create_table('exam_status_history',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('examination_id', sa.UUID(), nullable=False),
    sa.Column('from_status', postgresql.ENUM('draft', 'uploaded', 'queued', 'processing', 'ai_ready', 'in_review', 'completed', 'failed', 'cancelled', name='exam_status', create_type=False), nullable=True),
    sa.Column('to_status', postgresql.ENUM('draft', 'uploaded', 'queued', 'processing', 'ai_ready', 'in_review', 'completed', 'failed', 'cancelled', name='exam_status', create_type=False), nullable=False),
    sa.Column('changed_by', sa.UUID(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['changed_by'], ['users.id'], name=op.f('fk_exam_status_history_changed_by_users')),
    sa.ForeignKeyConstraint(['examination_id'], ['examinations.id'], name=op.f('fk_exam_status_history_examination_id_examinations')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_exam_status_history'))
    )
    op.create_index('idx_esh_exam_created', 'exam_status_history', ['examination_id', 'created_at'], unique=False)
    op.create_table('recordings',
    sa.Column('examination_id', sa.UUID(), nullable=False),
    sa.Column('kind', postgresql.ENUM('audio', 'spectrogram', 'waveform_image', 'envelope_json', 'other_image', name='recording_kind', create_type=False), nullable=False),
    sa.Column('status', postgresql.ENUM('uploading', 'uploaded', 'validated', 'rejected', 'processed', name='recording_status', create_type=False), server_default='uploading', nullable=False),
    sa.Column('site', postgresql.ENUM('aortic', 'pulmonic', 'erb', 'tricuspid', 'mitral', 'apex', 'carotid', 'other', name='auscultation_site', create_type=False), nullable=True),
    sa.Column('storage_key', sa.Text(), nullable=False),
    sa.Column('derived_from_id', sa.UUID(), nullable=True),
    sa.Column('original_filename', sa.String(length=255), nullable=False),
    sa.Column('mime_type', sa.String(length=100), nullable=False),
    sa.Column('ext', sa.String(length=8), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('duration_sec', sa.Numeric(precision=7, scale=3), nullable=True),
    sa.Column('sample_rate_hz', sa.Integer(), nullable=True),
    sa.Column('channels', sa.SmallInteger(), nullable=True),
    sa.Column('bit_depth', sa.SmallInteger(), nullable=True),
    sa.Column('codec', sa.String(length=30), nullable=True),
    sa.Column('width_px', sa.Integer(), nullable=True),
    sa.Column('height_px', sa.Integer(), nullable=True),
    sa.Column('quality_score', sa.Numeric(precision=4, scale=3), nullable=True),
    sa.Column('snr_db', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('validation_report', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('scan_status', sa.String(length=16), server_default='pending', nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('uploaded_by', sa.UUID(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("kind <> 'audio' OR site IS NOT NULL", name=op.f('ck_recordings_audio_has_site')),
    sa.CheckConstraint('size_bytes > 0', name=op.f('ck_recordings_size_positive')),
    sa.ForeignKeyConstraint(['derived_from_id'], ['recordings.id'], name=op.f('fk_recordings_derived_from_id_recordings')),
    sa.ForeignKeyConstraint(['examination_id'], ['examinations.id'], name=op.f('fk_recordings_examination_id_examinations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], name=op.f('fk_recordings_uploaded_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_recordings')),
    sa.UniqueConstraint('storage_key', name=op.f('uq_recordings_storage_key'))
    )
    op.create_index('idx_rec_exam_kind', 'recordings', ['examination_id', 'kind'], unique=False)
    op.create_index('idx_rec_exam_site', 'recordings', ['examination_id', 'site'], unique=False, postgresql_where=sa.text("kind = 'audio' AND deleted_at IS NULL"))
    op.create_index('idx_rec_sha256', 'recordings', ['sha256'], unique=False)
    op.create_table('analysis_results',
    sa.Column('examination_id', sa.UUID(), nullable=False),
    sa.Column('job_id', sa.UUID(), nullable=False),
    sa.Column('is_current', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('model_version', sa.String(length=40), nullable=False),
    sa.Column('pcg_class', postgresql.ENUM('normal', 'murmur', 'extra_heart_sound', 'artifact', 'undetermined', name='pcg_class', create_type=False), nullable=False),
    sa.Column('class_probs', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('confidence', sa.Numeric(precision=4, scale=3), nullable=False),
    sa.Column('severity', postgresql.ENUM('none', 'mild', 'moderate', 'severe', 'critical', name='severity', create_type=False), server_default='none', nullable=False),
    sa.Column('murmur_timing', postgresql.ENUM('systolic', 'diastolic', 'continuous', 'none', name='murmur_timing', create_type=False), server_default='none', nullable=False),
    sa.Column('murmur_grade', sa.SmallInteger(), nullable=True),
    sa.Column('murmur_shape', sa.String(length=30), nullable=True),
    sa.Column('heart_rate_bpm', sa.Numeric(precision=5, scale=1), nullable=True),
    sa.Column('hr_variability_ms', sa.Numeric(precision=7, scale=2), nullable=True),
    sa.Column('s1_count', sa.Integer(), nullable=True),
    sa.Column('s2_count', sa.Integer(), nullable=True),
    sa.Column('mean_s1_s2_ms', sa.Numeric(precision=7, scale=2), nullable=True),
    sa.Column('mean_s2_s1_ms', sa.Numeric(precision=7, scale=2), nullable=True),
    sa.Column('systole_ms', sa.Numeric(precision=7, scale=2), nullable=True),
    sa.Column('diastole_ms', sa.Numeric(precision=7, scale=2), nullable=True),
    sa.Column('dominant_freq_hz', sa.Numeric(precision=7, scale=2), nullable=True),
    sa.Column('features', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('quality_ok', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('quality_notes', sa.Text(), nullable=True),
    sa.Column('waveform_key', sa.Text(), nullable=True),
    sa.Column('spectrogram_recording_id', sa.UUID(), nullable=True),
    sa.Column('processing_ms', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.CheckConstraint('confidence >= 0 AND confidence <= 1', name=op.f('ck_analysis_results_confidence_range')),
    sa.ForeignKeyConstraint(['examination_id'], ['examinations.id'], name=op.f('fk_analysis_results_examination_id_examinations')),
    sa.ForeignKeyConstraint(['job_id'], ['analysis_jobs.id'], name=op.f('fk_analysis_results_job_id_analysis_jobs')),
    sa.ForeignKeyConstraint(['spectrogram_recording_id'], ['recordings.id'], name=op.f('fk_analysis_results_spectrogram_recording_id_recordings')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_analysis_results'))
    )
    op.create_index('idx_ar_class_created', 'analysis_results', ['pcg_class', 'created_at'], unique=False)
    op.create_index('idx_ar_model', 'analysis_results', ['model_version'], unique=False)
    op.create_index('idx_ar_severity', 'analysis_results', ['severity'], unique=False)
    op.create_index('uq_analysis_current_exam', 'analysis_results', ['examination_id'], unique=True, postgresql_where=sa.text('is_current'))
    op.create_table('ai_reports',
    sa.Column('examination_id', sa.UUID(), nullable=False),
    sa.Column('analysis_result_id', sa.UUID(), nullable=False),
    sa.Column('status', postgresql.ENUM('generating', 'ready', 'failed', 'superseded', name='report_status', create_type=False), server_default='generating', nullable=False),
    sa.Column('is_current', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('llm_provider', sa.String(length=30), server_default='deepseek', nullable=False),
    sa.Column('llm_model', sa.String(length=40), nullable=False),
    sa.Column('prompt_version', sa.String(length=20), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('findings', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('differential_diagnoses', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('recommended_tests', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('red_flags', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('patient_friendly_text', sa.Text(), nullable=True),
    sa.Column('disclaimer', sa.Text(), nullable=False),
    sa.Column('input_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('raw_response', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('prompt_tokens', sa.Integer(), nullable=True),
    sa.Column('completion_tokens', sa.Integer(), nullable=True),
    sa.Column('latency_ms', sa.Integer(), nullable=True),
    sa.Column('cost_usd', sa.Numeric(precision=8, scale=5), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['analysis_result_id'], ['analysis_results.id'], name=op.f('fk_ai_reports_analysis_result_id_analysis_results')),
    sa.ForeignKeyConstraint(['examination_id'], ['examinations.id'], name=op.f('fk_ai_reports_examination_id_examinations')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_reports'))
    )
    op.create_index('idx_ai_report_created', 'ai_reports', ['created_at'], unique=False)
    op.create_index('idx_ai_report_result', 'ai_reports', ['analysis_result_id'], unique=False)
    op.create_index('uq_ai_report_current_exam', 'ai_reports', ['examination_id'], unique=True, postgresql_where=sa.text('is_current'))
    op.create_table('pcg_segments',
    sa.Column('analysis_result_id', sa.UUID(), nullable=False),
    sa.Column('recording_id', sa.UUID(), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('type', postgresql.ENUM('S1', 'S2', 'S3', 'S4', 'systole', 'diastole', 'murmur', 'click', 'noise', name='segment_type', create_type=False), nullable=False),
    sa.Column('start_ms', sa.Integer(), nullable=False),
    sa.Column('end_ms', sa.Integer(), nullable=False),
    sa.Column('cycle_no', sa.Integer(), nullable=True),
    sa.Column('peak_amplitude', sa.REAL(), nullable=True),
    sa.Column('energy', sa.REAL(), nullable=True),
    sa.Column('dominant_freq_hz', sa.REAL(), nullable=True),
    sa.Column('confidence', sa.REAL(), nullable=True),
    sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.CheckConstraint('end_ms > start_ms', name=op.f('ck_pcg_segments_segment_order')),
    sa.ForeignKeyConstraint(['analysis_result_id'], ['analysis_results.id'], name=op.f('fk_pcg_segments_analysis_result_id_analysis_results'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['recording_id'], ['recordings.id'], name=op.f('fk_pcg_segments_recording_id_recordings')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pcg_segments'))
    )
    op.create_index('idx_seg_rec_type', 'pcg_segments', ['recording_id', 'type'], unique=False)
    op.create_index('idx_seg_result_rec_start', 'pcg_segments', ['analysis_result_id', 'recording_id', 'start_ms'], unique=False)
    op.create_table('prescriptions',
    sa.Column('examination_id', sa.UUID(), nullable=False),
    sa.Column('patient_id', sa.UUID(), nullable=False),
    sa.Column('ai_report_id', sa.UUID(), nullable=True),
    sa.Column('status', postgresql.ENUM('draft', 'suggested', 'approved', 'rejected', 'cancelled', name='prescription_status', create_type=False), server_default='suggested', nullable=False),
    sa.Column('prescribed_by', sa.UUID(), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('safety_check', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('doctor_notes', sa.Text(), nullable=True),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['ai_report_id'], ['ai_reports.id'], name=op.f('fk_prescriptions_ai_report_id_ai_reports')),
    sa.ForeignKeyConstraint(['examination_id'], ['examinations.id'], name=op.f('fk_prescriptions_examination_id_examinations')),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], name=op.f('fk_prescriptions_patient_id_patients')),
    sa.ForeignKeyConstraint(['prescribed_by'], ['users.id'], name=op.f('fk_prescriptions_prescribed_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_prescriptions'))
    )
    op.create_index('idx_rx_exam', 'prescriptions', ['examination_id'], unique=False)
    op.create_index('idx_rx_patient_status', 'prescriptions', ['patient_id', 'status'], unique=False)
    op.create_table('drug_recommendations',
    sa.Column('prescription_id', sa.UUID(), nullable=False),
    sa.Column('source', sa.String(length=10), nullable=False),
    sa.Column('drug_name', sa.String(length=160), nullable=False),
    sa.Column('inn_code', sa.String(length=64), nullable=True),
    sa.Column('atc_code', sa.String(length=10), nullable=True),
    sa.Column('dose', sa.String(length=60), nullable=False),
    sa.Column('route', sa.String(length=30), nullable=False),
    sa.Column('frequency', sa.String(length=80), nullable=False),
    sa.Column('duration_days', sa.SmallInteger(), nullable=True),
    sa.Column('instructions', sa.Text(), nullable=True),
    sa.Column('rationale', sa.Text(), nullable=True),
    sa.Column('contraindications', postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('side_effects', postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('interaction_warnings', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('allergy_warning', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('safety_pending', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('override_reason', sa.Text(), nullable=True),
    sa.Column('reject_reason', sa.Text(), nullable=True),
    sa.Column('status', postgresql.ENUM('draft', 'suggested', 'approved', 'rejected', 'cancelled', name='prescription_status', create_type=False), server_default='suggested', nullable=False),
    sa.Column('sort_order', sa.SmallInteger(), server_default='0', nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['prescription_id'], ['prescriptions.id'], name=op.f('fk_drug_recommendations_prescription_id_prescriptions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_drug_recommendations'))
    )
    op.create_index('idx_drugrec_rx_sort', 'drug_recommendations', ['prescription_id', 'sort_order'], unique=False)

    # --- audit_logs is append-only: block UPDATE/DELETE/TRUNCATE at DB level ---
    op.execute("""
    CREATE OR REPLACE FUNCTION audit_logs_immutable() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'audit_logs is append-only';
    END;
    $$ LANGUAGE plpgsql
    """)
    op.execute("""
    CREATE TRIGGER trg_audit_logs_no_update_delete
    BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION audit_logs_immutable()
    """)
    op.execute("""
    CREATE TRIGGER trg_audit_logs_no_truncate
    BEFORE TRUNCATE ON audit_logs
    FOR EACH STATEMENT EXECUTE FUNCTION audit_logs_immutable()
    """)

    # --- seed system settings (non-secret defaults) ---
    st = sa.table(
        "system_settings",
        sa.column("key", sa.String), sa.column("value", postgresql.JSONB), sa.column("value_type", sa.String),
        sa.column("description", sa.Text), sa.column("is_public", sa.Boolean),
    )
    op.bulk_insert(st, [
        {"key": k, "value": v, "value_type": t, "description": d, "is_public": pub}
        for (k, v, t, d, pub) in SETTINGS_SEED
    ])


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_no_update_delete ON audit_logs")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_no_truncate ON audit_logs")

    op.drop_index('idx_drugrec_rx_sort', table_name='drug_recommendations')
    op.drop_table('drug_recommendations')
    op.drop_index('idx_rx_patient_status', table_name='prescriptions')
    op.drop_index('idx_rx_exam', table_name='prescriptions')
    op.drop_table('prescriptions')
    op.drop_index('idx_seg_result_rec_start', table_name='pcg_segments')
    op.drop_index('idx_seg_rec_type', table_name='pcg_segments')
    op.drop_table('pcg_segments')
    op.drop_index('uq_ai_report_current_exam', table_name='ai_reports', postgresql_where=sa.text('is_current'))
    op.drop_index('idx_ai_report_result', table_name='ai_reports')
    op.drop_index('idx_ai_report_created', table_name='ai_reports')
    op.drop_table('ai_reports')
    op.drop_index('uq_analysis_current_exam', table_name='analysis_results', postgresql_where=sa.text('is_current'))
    op.drop_index('idx_ar_severity', table_name='analysis_results')
    op.drop_index('idx_ar_model', table_name='analysis_results')
    op.drop_index('idx_ar_class_created', table_name='analysis_results')
    op.drop_table('analysis_results')
    op.drop_index('idx_rec_sha256', table_name='recordings')
    op.drop_index('idx_rec_exam_site', table_name='recordings', postgresql_where=sa.text("kind = 'audio' AND deleted_at IS NULL"))
    op.drop_index('idx_rec_exam_kind', table_name='recordings')
    op.drop_table('recordings')
    op.drop_index('idx_esh_exam_created', table_name='exam_status_history')
    op.drop_table('exam_status_history')
    op.drop_index('uq_conclusion_current_exam', table_name='doctor_conclusions', postgresql_where=sa.text('is_current'))
    op.drop_index('idx_concl_final_class', table_name='doctor_conclusions')
    op.drop_index('idx_concl_doctor_signed', table_name='doctor_conclusions')
    op.drop_index('idx_concl_agreement', table_name='doctor_conclusions')
    op.drop_table('doctor_conclusions')
    op.drop_index('idx_job_exam_created', table_name='analysis_jobs')
    op.drop_index('idx_job_active', table_name='analysis_jobs', postgresql_where=sa.text("status IN ('pending','running')"))
    op.drop_table('analysis_jobs')
    op.drop_index('idx_mh_patient_kind', table_name='medical_history')
    op.drop_index('idx_mh_patient_active', table_name='medical_history', postgresql_where=sa.text('is_active'))
    op.drop_table('medical_history')
    op.drop_index('idx_exam_status_created', table_name='examinations', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_index('idx_exam_priority_status', table_name='examinations', postgresql_where=sa.text("status IN ('ai_ready','in_review')"))
    op.drop_index('idx_exam_performed_created', table_name='examinations')
    op.drop_index('idx_exam_patient_examined', table_name='examinations')
    op.drop_index('idx_exam_examined_at', table_name='examinations')
    op.drop_index('idx_exam_doctor_status', table_name='examinations', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_index('idx_exam_created_brin', table_name='examinations', postgresql_using='brin')
    op.drop_table('examinations')
    op.drop_index('idx_med_patient_active', table_name='current_medications', postgresql_where=sa.text('is_active'))
    op.drop_index('idx_med_inn', table_name='current_medications')
    op.drop_table('current_medications')
    op.drop_index('uq_allergy_patient_substance', table_name='allergies', postgresql_where=sa.text('is_active'))
    op.drop_index('idx_allergy_patient_active', table_name='allergies', postgresql_where=sa.text('is_active'))
    op.drop_index('idx_allergy_code', table_name='allergies')
    op.drop_table('allergies')
    op.drop_table('system_settings')
    op.drop_index('idx_rt_user_active', table_name='refresh_tokens', postgresql_where=sa.text('revoked_at IS NULL'))
    op.drop_index('idx_rt_family', table_name='refresh_tokens')
    op.drop_index('idx_rt_expires', table_name='refresh_tokens')
    op.drop_table('refresh_tokens')
    op.drop_index('idx_patients_phone', table_name='patients')
    op.drop_index('idx_patients_name_trgm', table_name='patients', postgresql_using='gin')
    op.drop_index('idx_patients_doctor', table_name='patients', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_index('idx_patients_created', table_name='patients')
    op.drop_index('idx_patients_birth', table_name='patients')
    op.drop_table('patients')
    op.drop_table('password_reset_tokens')
    op.drop_index('idx_notif_user_read_created', table_name='notifications')
    op.drop_index('idx_notif_user_created', table_name='notifications')
    op.drop_table('notifications')
    op.drop_table('export_jobs')
    op.drop_index('idx_users_role_status', table_name='users', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_index('idx_users_fullname_trgm', table_name='users', postgresql_using='gin', postgresql_ops={'full_name': 'gin_trgm_ops'})
    op.drop_table('users')
    op.drop_table('idempotency_keys')
    op.drop_table('exam_counters')
    op.drop_index('idx_audit_user_ts', table_name='audit_logs')
    op.drop_index('idx_audit_ts', table_name='audit_logs')
    op.drop_index('idx_audit_resource', table_name='audit_logs')
    op.drop_index('idx_audit_request', table_name='audit_logs')
    op.drop_index('idx_audit_patient_ts', table_name='audit_logs', postgresql_where=sa.text('patient_id IS NOT NULL'))
    op.drop_index('idx_audit_action_ts', table_name='audit_logs')
    op.drop_table('audit_logs')

    op.execute("DROP FUNCTION IF EXISTS audit_logs_immutable()")
    op.execute("DROP SEQUENCE IF EXISTS patient_mrn_seq")
    bind = op.get_bind()
    for name in ENUMS:
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
