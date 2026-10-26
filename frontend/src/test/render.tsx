import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { Providers } from "../Providers";

/** Renders inside the same providers the app mounts with. */
export function renderWithProviders(ui: ReactElement) {
  return render(ui, { wrapper: Providers });
}
