import { Component, type ErrorInfo, type ReactNode } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('[UNCAUGHT REACT ERROR BOUNDARY]:', error, errorInfo);
  }

  private handleReload = () => {
    this.setState({ hasError: false, error: null });
    window.location.reload();
  };

  public render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div className="min-h-screen flex items-center justify-center bg-[#F6F7F5] text-[#1F2522] p-6 antialiased">
          <div className="max-w-md w-full bg-white border border-[#E1E4DF] rounded-3xl p-8 shadow-xl text-center space-y-4">
            <div className="w-14 h-14 rounded-2xl bg-rose-50 text-rose-600 flex items-center justify-center mx-auto">
              <AlertTriangle className="w-7 h-7" />
            </div>

            <h2 className="text-xl font-extrabold text-[#1F2522]">Something went wrong</h2>

            <p className="text-sm text-[#5F6863] leading-relaxed">
              {this.state.error?.message || 'An unexpected rendering error occurred. Your trip data and active state are safely saved.'}
            </p>

            <button
              onClick={this.handleReload}
              className="w-full inline-flex items-center justify-center gap-2 py-3 px-5 bg-[#355F58] hover:bg-[#2A4B46] text-white font-bold text-sm rounded-2xl transition-all shadow-md active:scale-95"
            >
              <RefreshCw className="w-4 h-4" />
              Reload Application
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
