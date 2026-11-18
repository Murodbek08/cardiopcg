export const PASSWORD_MIN_LENGTH = 12;

export interface PasswordChecks {
  length: boolean;
  case: boolean;
  digit: boolean;
  special: boolean;
}

export function checkPassword(pw: string, minLength = PASSWORD_MIN_LENGTH): PasswordChecks {
  return {
    length: pw.length >= minLength,
    case: /[a-z]/.test(pw) && /[A-Z]/.test(pw),
    digit: /\d/.test(pw),
    special: /[^A-Za-z0-9]/.test(pw),
  };
}

const COMMON = ['password', 'qwerty', '123456', 'admin', 'letmein', 'welcome', 'parol', 'cardio', 'iloveyou'];

/**
 * Client-side strength heuristic 0-4 (UI hint only; the server enforces zxcvbn >= 3 and is authoritative).
 */
export function passwordScore(pw: string): 0 | 1 | 2 | 3 | 4 {
  if (!pw) return 0;
  const lower = pw.toLowerCase();
  if (COMMON.some((c) => lower.includes(c)) && pw.length < 16) return 1;
  const c = checkPassword(pw);
  const classes = [c.case, c.digit, c.special].filter(Boolean).length;
  let score = 0;
  if (pw.length >= 8) score++;
  if (pw.length >= 12) score++;
  if (classes >= 2) score++;
  if (classes === 3 && pw.length >= 14) score++;
  // repeated chars penalty
  if (/(.)\1{3,}/.test(pw)) score = Math.max(0, score - 1);
  return Math.min(4, score) as 0 | 1 | 2 | 3 | 4;
}

/** Cryptographically random temporary password that satisfies all rules (for admin user creation). */
export function generatePassword(length = 16): string {
  const lowers = 'abcdefghijkmnopqrstuvwxyz';
  const uppers = 'ABCDEFGHJKLMNPQRSTUVWXYZ';
  const digits = '23456789';
  const specials = '!@#$%^&*-_=+';
  const all = lowers + uppers + digits + specials;
  const rnd = (n: number) => {
    const a = new Uint32Array(1);
    // rejection sampling to avoid modulo bias
    const limit = Math.floor(0x100000000 / n) * n;
    do crypto.getRandomValues(a);
    while ((a[0] as number) >= limit);
    return (a[0] as number) % n;
  };
  const pick = (s: string) => s[rnd(s.length)] as string;
  const chars = [pick(lowers), pick(uppers), pick(digits), pick(specials)];
  while (chars.length < length) chars.push(pick(all));
  for (let i = chars.length - 1; i > 0; i--) {
    const j = rnd(i + 1);
    [chars[i], chars[j]] = [chars[j] as string, chars[i] as string];
  }
  return chars.join('');
}
