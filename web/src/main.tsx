import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { FailureBoundary, reportRenderFailure } from "./FailureBoundary";
import "./styles.css";

createRoot(document.getElementById("root")!, { onCaughtError: reportRenderFailure }).render(
  <StrictMode>
    <FailureBoundary><App /></FailureBoundary>
  </StrictMode>,
);
