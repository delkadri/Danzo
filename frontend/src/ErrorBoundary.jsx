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
        <div className="min-h-screen p-6 flex items-center justify-center">
          <Card className="p-6 max-w-2xl w-full">
            <div className="text-2xl font-black text-red-400">
              ⚠️ Frontend crashed
            </div>

            <div className="mt-3 text-sm text-zinc-300">
              <b>Error:</b> {String(this.state.error)}
            </div>

            <pre className="mt-4 p-4 rounded-2xl bg-zinc-950 border border-zinc-800 overflow-auto text-xs text-zinc-300">
{this.state.info?.componentStack || "No stack trace"}
            </pre>

            <div className="mt-4 flex gap-2">
              <Button onClick={() => window.location.reload()}>
                Reload
              </Button>
              <Button variant="danger" onClick={() => (window.location.href = "/")}>
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
