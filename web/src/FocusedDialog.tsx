import {
  type ReactNode,
  type RefObject,
  useEffect,
  useId,
  useRef,
} from "react";
import { createPortal } from "react-dom";

import "./focused-dialog.css";

const focusableSelector = [
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "a[href]",
  '[tabindex]:not([tabindex="-1"])',
].join(", ");

export function FocusedDialog({
  title,
  description,
  returnFocusRef,
  onClose,
  children,
  tone = "default",
  className = "",
}: {
  title: string;
  description: string;
  returnFocusRef?: RefObject<HTMLElement | null>;
  onClose: () => void;
  children: ReactNode;
  tone?: "default" | "boundary";
  className?: string;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const identifier = useId();
  const titleId = `focused-dialog-title-${identifier}`;
  const descriptionId = `focused-dialog-description-${identifier}`;
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    const previous = returnFocusRef?.current ?? document.activeElement as HTMLElement | null;
    const shell = document.querySelector<HTMLElement>(".app-shell");
    shell?.setAttribute("inert", "");
    document.body.classList.add("modal-open");
    const dialog = dialogRef.current;
    const initial =
      dialog?.querySelector<HTMLElement>("[data-autofocus]") ??
      dialog?.querySelector<HTMLElement>("input, select, textarea, button");
    initial?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeRef.current();
        return;
      }
      if (event.key !== "Tab" || !dialog) return;
      const focusable = Array.from(dialog.querySelectorAll<HTMLElement>(focusableSelector));
      if (focusable.length === 0) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable.at(-1) ?? first;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      shell?.removeAttribute("inert");
      document.body.classList.remove("modal-open");
      previous?.focus();
    };
  }, [returnFocusRef]);

  return createPortal(
    <div
      className="focused-dialog-backdrop"
      onMouseDown={(event) => event.target === event.currentTarget && onClose()}
      role="presentation"
    >
      <div
        className={`focused-dialog focused-dialog-${tone} ${className}`.trim()}
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        tabIndex={-1}
      >
        <header className="focused-dialog-heading">
          <div>
            <h2 id={titleId}>{title}</h2>
            <p id={descriptionId}>{description}</p>
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label={`Close ${title}`}>
            ×
          </button>
        </header>
        {children}
      </div>
    </div>,
    document.body,
  );
}
