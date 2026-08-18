/**
 * Top-level error boundary.
 *
 * Defence in depth, not a fix. On 2026-08-13 a single dangling identifier in
 * one card's render threw a ReferenceError; React unmounted the whole tree and
 * the operator was left looking at the bare page background with no indication
 * that anything had failed, no way to retry, and nothing on screen to report.
 * A rendering fault in one view must degrade to a controlled screen, never to a
 * blank one.
 *
 * Colours come from the CSS custom properties in index.css rather than the
 * duplicated JS constants, so this cannot drift from the palette.
 *
 * The message shown is deliberately generic. The real exception goes to the
 * console for diagnosis — stack traces and backend details are not put on
 * screen, where they would be read by ordinary users and pasted into tickets.
 */
import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  /** Shown instead of the default copy — used by the boundary's own tests. */
  label?: string;
}

interface State {
  error: Error | null;
}

const panel: React.CSSProperties = {
  background: "var(--surface, #171a1d)",
  border: "1px solid var(--border, #252a31)",
  borderRadius: 10,
  padding: "28px 30px",
  maxWidth: 520,
  textAlign: "center",
};

const buttonBase: React.CSSProperties = {
  borderRadius: 6,
  padding: "9px 16px",
  fontWeight: 500,
  fontSize: 13,
  cursor: "pointer",
};

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // The whole point of the boundary is that the failure stays diagnosable.
    // Without this the exception is swallowed with the unmounted tree.
    console.error("Energy IQ: render failure contained by the error boundary", error, info);
  }

  private retry = () => this.setState({ error: null });

  private reload = () => window.location.reload();

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <div
        role="alert"
        style={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: 24,
          background: "var(--bg, #0b0d10)",
          fontFamily: "inherit",
        }}
      >
        <div style={panel}>
          <div
            style={{
              fontSize: 14,
              fontWeight: 600,
              color: "var(--text, #f5f7fa)",
              letterSpacing: -0.1,
            }}
          >
            {this.props.label ?? "Se produjo un error al mostrar esta vista."}
          </div>
          <p
            style={{
              fontSize: 12.5,
              color: "var(--text-secondary, #9aa4af)",
              lineHeight: 1.6,
              margin: "10px 0 22px",
            }}
          >
            El resto de la plataforma sigue funcionando y no se ha perdido ningún dato. Puedes
            reintentar esta vista o recargar la plataforma. Los detalles técnicos se registraron en
            la consola del navegador.
          </p>
          <div style={{ display: "flex", gap: 10, justifyContent: "center", flexWrap: "wrap" }}>
            <button
              type="button"
              onClick={this.retry}
              style={{
                ...buttonBase,
                background: "var(--accent, #2563eb)",
                color: "#fff",
                border: "1px solid var(--accent, #2563eb)",
              }}
            >
              Reintentar
            </button>
            <button
              type="button"
              onClick={this.reload}
              style={{
                ...buttonBase,
                background: "var(--surface-inner, #121417)",
                color: "var(--text-secondary, #9aa4af)",
                border: "1px solid var(--border, #252a31)",
              }}
            >
              Recargar plataforma
            </button>
          </div>
        </div>
      </div>
    );
  }
}

export default ErrorBoundary;
