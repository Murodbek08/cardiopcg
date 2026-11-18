import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

// Every JSON file under locales/<lng>/<namespace>.json is a namespace. uz is the base language.
const modules = import.meta.glob<{ default: Record<string, unknown> }>('./locales/*/*.json', { eager: true });

const resources: Record<string, Record<string, Record<string, unknown>>> = {};
for (const [path, mod] of Object.entries(modules)) {
  const m = /\.\/locales\/([^/]+)\/([^/]+)\.json$/.exec(path);
  if (!m) continue;
  const [, lng, ns] = m as unknown as [string, string, string];
  (resources[lng] ??= {})[ns] = mod.default;
}

export const NAMESPACES = [
  'common', 'auth', 'nav', 'dashboard', 'patients', 'exams', 'clinical', 'drugs', 'admin', 'notifications', 'errors', 'validation', 'doctor', 'nurse',
] as const;

void i18n.use(initReactI18next).init({
  resources,
  lng: 'uz',
  fallbackLng: 'uz',
  ns: [...NAMESPACES],
  defaultNS: 'common',
  interpolation: { escapeValue: false },
  returnNull: false,
});

export function setLanguage(lng: 'uz' | 'ru' | 'en'): void {
  void i18n.changeLanguage(lng);
  document.documentElement.lang = lng;
}

export default i18n;
