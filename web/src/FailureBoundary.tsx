import { Component, type ReactNode } from "react";

export class FailureBoundary extends Component<{
  children: ReactNode;
  onReload?: () => void;
}, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <main className="fatal-state" role="alert" data-failure-code="MM-UI-RENDER-FAIL">
        <span>Money Map</span>
        <h1>This view could not be displayed.</h1>
        <p>Reload Money Map, then check the last action’s status before trying it again. Unsaved edits may be lost.</p>
        <button className="primary-button" type="button" onClick={() => {
          if (this.props.onReload) this.props.onReload();
          else window.location.reload();
        }}>Reload Money Map</button>
      </main>
    );
  }
}

export function reportRenderFailure() {
  // React errors can include financial values. Keep only the fixed incident code.
  console.error("MM-UI-RENDER-FAIL");
}
