import { Component } from "react";

/** Last line of defence: a rendering bug shows a recoverable screen instead of a blank page. */
export class ErrorBoundary extends Component {
  state = { error: null };

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error("UI error", error, info?.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="grid h-dvh place-items-center bg-canvas px-6 text-center">
        <div className="max-w-sm">
          <h1 className="text-lg font-semibold text-fg">Something went wrong</h1>
          <p className="mt-2 text-sm text-fg-muted">The interface hit an unexpected error. Reloading starts a fresh session.</p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="mt-5 h-9 rounded-lg bg-accent px-4 text-sm font-medium text-accent-fg hover:bg-accent-hover"
          >
            Reload
          </button>
        </div>
      </div>
    );
  }
}
