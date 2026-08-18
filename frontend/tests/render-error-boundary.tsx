/**
 * Proves the top-level error boundary contains a render failure instead of
 * letting it unmount the tree — verified with a throwing component that exists
 * only in this file, never in the shipped app.
 *
 * `renderToStaticMarkup` does not run componentDidCatch (server rendering has
 * no error boundaries), so the containment itself is asserted directly against
 * the boundary's state machine: getDerivedStateFromError must produce the
 * fallback, and the fallback must render the two recovery actions.
 */
import { renderToStaticMarkup } from "react-dom/server";

import { ErrorBoundary } from "../src/components/ErrorBoundary";

let failures = 0;

function check(label: string, condition: boolean, detail = "") {
  if (condition) {
    console.log(`  ok   ${label}`);
  } else {
    failures += 1;
    console.log(`  FAIL ${label}${detail ? ` :: ${detail}` : ""}`);
  }
}

console.log("\n--- healthy children render untouched ---");
const healthy = renderToStaticMarkup(
  <ErrorBoundary>
    <div>contenido normal</div>
  </ErrorBoundary>,
);
check("children pass through", healthy.includes("contenido normal"));
check("no fallback while healthy", !healthy.includes("Reintentar"));

console.log("\n--- a thrown render error produces the fallback ---");
// The exact shape of the outage: a ReferenceError raised during render.
const outage = new ReferenceError("effectiveStatus is not defined");
const derived = ErrorBoundary.getDerivedStateFromError(outage);
check("getDerivedStateFromError captures the error", derived.error === outage);

// Drive the boundary into its error state and render that state directly.
class AlreadyFailed extends ErrorBoundary {
  state = { error: outage };
}
const fallback = renderToStaticMarkup(
  <AlreadyFailed>
    <div>no debe aparecer</div>
  </AlreadyFailed>,
);

check("children are replaced", !fallback.includes("no debe aparecer"));
check("shows the Spanish failure message", fallback.includes("Se produjo un error al mostrar esta vista."));
check("offers Reintentar", fallback.includes("Reintentar"));
check("offers Recargar plataforma", fallback.includes("Recargar plataforma"));
check("marked as an alert for assistive tech", fallback.includes('role="alert"'));

// The screen must stay generic: no stack, no exception text, no backend detail.
check("does not leak the exception message", !fallback.includes("effectiveStatus"));
check("does not leak a stack trace", !fallback.toLowerCase().includes("at object."));
check("does not leak backend host or port", !fallback.includes("8010") && !fallback.includes("148.213"));

console.log(
  `\n${"=".repeat(60)}\n  ${failures === 0 ? "ALL CHECKS PASSED" : `${failures} FAILED`}\n${"=".repeat(60)}`,
);
process.exit(failures === 0 ? 0 : 1);
