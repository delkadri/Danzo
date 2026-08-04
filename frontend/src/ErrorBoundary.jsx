import React from "react";
import { Card } from "./components/Card";
import { Button } from "./components/Button";

export class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, info: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, info) {
    this.setState({ info });
    console.error("React crashed:", error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="safe-top safe-bottom flex min-h-[100dvh] items-center justify-center p-4 sm:p-6">
          <Card className="w-full max-w-2xl p-4 sm:p-6">
            <div className="text-2xl font-black text-red-400">
              ⚠️ Frontend crashed
            </div>

            <div className="mt-3 text-sm text-zinc-700 dark:text-zinc-300">
              <b>Error:</b> {String(this.state.error)}
            </div>

            <pre className="mt-4 max-h-64 overflow-auto rounded-2xl border border-zinc-200 bg-zinc-50 p-4 text-xs text-zinc-700 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-300">
{this.state.info?.componentStack || "No stack trace"}
            </pre>

            <div className="mt-4 grid gap-2 sm:grid-cols-2">
              <Button className="w-full" onClick={() => window.location.reload()}>
                Reload
              </Button>
              <Button className="w-full" variant="danger" onClick={() => (window.location.href = "/")}>
                Go Home
              </Button>
            </div>
          </Card>
        </div>
      );
    }

    return this.props.children;
  }
}
