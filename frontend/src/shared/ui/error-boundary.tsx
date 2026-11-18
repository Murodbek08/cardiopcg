import { Component, type ErrorInfo, type ReactNode } from 'react';
import { IconAlertOctagon } from '@tabler/icons-react';
import i18n from '@/i18n';
import { Button } from './button';

interface Props {
  children: ReactNode;
  fallback?: (error: Error, reset: () => void) => ReactNode;
  onError?: (error: Error, info: ErrorInfo) => void;
}
interface State {
  error: Error | null;
}

/** React error boundary. Never logs props/state (PHI); only the error message and component stack. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    this.props.onError?.(error, info);
    console.error('[ErrorBoundary]', error.message);
  }

  reset = () => this.setState({ error: null });

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    if (this.props.fallback) return this.props.fallback(error, this.reset);
    return (
      <div role="alert" className="mx-auto flex max-w-md flex-col items-center gap-3 px-6 py-16 text-center">
        <span className="flex h-12 w-12 items-center justify-center rounded-full bg-danger-50 text-danger-500">
          <IconAlertOctagon size={26} aria-hidden />
        </span>
        <h2 className="text-h2 font-semibold">{i18n.t('errors:server')}</h2>
        <p className="text-sm text-muted">{i18n.t('errors:server_body')}</p>
        <div className="flex gap-2">
          <Button onClick={this.reset}>{i18n.t('actions.retry', { ns: 'common' })}</Button>
          <Button variant="outline" onClick={() => window.location.assign('/')}>
            {i18n.t('errors:go_home')}
          </Button>
        </div>
      </div>
    );
  }
}
