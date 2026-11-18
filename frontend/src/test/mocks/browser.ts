import { setupWorker } from 'msw/browser';
import { handlers } from './handlers';

/** __MOCK_LAYER__: DEV ONLY (vite --mode mock). Must never reach the production bundle. */
export async function startMocks(): Promise<void> {
  await setupWorker(...handlers).start({ onUnhandledFrame: 'bypass', quiet: true });
}
