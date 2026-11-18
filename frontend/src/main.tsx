import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource-variable/inter';
import '@fontsource-variable/jetbrains-mono';
import './styles/globals.css';
import '@/i18n';
import { setupZodUz } from '@/shared/lib/zod-uz';
import { bootstrapSession, initSession } from '@/shared/api/session';
import { applyTheme, useThemeStore } from '@/shared/store/theme';
import { AppProviders } from '@/app/providers/app-providers';
import { AppRouter } from '@/app/router';

async function main() {
  // Mock layer: only when explicitly started with `vite --mode mock`. The condition is a compile-time
  // constant, so production builds drop this branch (and MSW) entirely. Verified by scripts/check-bundle.mjs.
  if (import.meta.env.MODE === 'mock') {
    const { startMocks } = await import('./test/mocks/browser');
    await startMocks();
  }
  setupZodUz();
  applyTheme(useThemeStore.getState().mode);
  initSession();
  await bootstrapSession(); // restores the session from the httpOnly refresh cookie before routing

  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <AppProviders>
        <AppRouter />
      </AppProviders>
    </StrictMode>,
  );
}

void main();
