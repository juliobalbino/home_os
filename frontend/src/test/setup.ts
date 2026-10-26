import "@testing-library/jest-dom/vitest";

// Mantine reads media queries and observes element sizes; jsdom has neither.
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  }),
});

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
window.ResizeObserver = ResizeObserverStub;
window.scrollTo = () => undefined;
Element.prototype.scrollIntoView = () => undefined;
if (!("fonts" in document))
  Object.defineProperty(document, "fonts", {
    value: {
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    },
  });
