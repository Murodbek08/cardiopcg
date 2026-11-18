import type { Role } from '@/shared/api/types';

/**
 * UI permission matrix (doc 03, section 1.1 + doc 01, section 2). Mirrors backend permission names where they exist.
 * The backend is the source of truth; this only decides what is rendered.
 */
export type Permission =
  | 'user:manage'
  | 'patient:read'
  | 'patient:write'
  | 'patient:read_unmasked'
  | 'patient:export'
  | 'exam:create'
  | 'exam:read'
  | 'exam:edit_conclusion'
  | 'prescription:approve'
  | 'ai:read'
  | 'audit:read'
  | 'settings:write'
  | 'drugs:manage'
  | 'reports:admin'
  | 'reports:own'
  | 'analytics:admin'
  | 'analytics:doctor'
  | 'analytics:nurse';

const MATRIX: Record<Role, ReadonlySet<Permission>> = {
  admin: new Set<Permission>([
    'user:manage', 'patient:read', 'exam:read', 'ai:read', 'audit:read', 'settings:write', 'drugs:manage', 'reports:admin', 'analytics:admin', 'analytics:doctor', 'analytics:nurse',
  ]),
  doctor: new Set<Permission>([
    'patient:read', 'patient:write', 'patient:read_unmasked', 'patient:export', 'exam:create', 'exam:read', 'exam:edit_conclusion', 'prescription:approve', 'ai:read', 'reports:own', 'analytics:doctor',
  ]),
  nurse: new Set<Permission>(['patient:read', 'patient:write', 'patient:read_unmasked', 'exam:create', 'exam:read', 'ai:read', 'analytics:nurse']),
};

export function can(role: Role | null | undefined, permission: Permission): boolean {
  return !!role && MATRIX[role].has(permission);
}
