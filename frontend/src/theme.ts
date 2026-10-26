import { createTheme } from "@mantine/core";
import type { CSSVariablesResolver, MantineColorsTuple } from "@mantine/core";

/** Bottle-green glaze of Brazilian hydraulic tiles; shade 7 is the brand green. */
const azulejo: MantineColorsTuple = [
  "#e9f4ef",
  "#d3e9df",
  "#a6d1be",
  "#76b79b",
  "#4fa07e",
  "#35906c",
  "#24805e",
  "#17634f",
  "#0f4f3f",
  "#09392d",
];

/** Ochre pigment used on tile borders: pending, overdue, attention. */
const ocre: MantineColorsTuple = [
  "#fbf4e2",
  "#f4e5bf",
  "#ead095",
  "#dfba68",
  "#d6a843",
  "#c8952b",
  "#a77a1d",
  "#7f5c13",
  "#5f440c",
  "#402d06",
];

/** Fired clay red for destructive and error states. */
const barro: MantineColorsTuple = [
  "#fbecea",
  "#f3d1cd",
  "#e6a39b",
  "#d87268",
  "#cb4d42",
  "#b83e33",
  "#a3372f",
  "#862c25",
  "#68221c",
  "#4a1713",
];

const inputDefaults = { size: "md", withAsterisk: false } as const;

export const theme = createTheme({
  primaryColor: "azulejo",
  primaryShade: { light: 7, dark: 4 },
  colors: { azulejo, ocre, barro },
  autoContrast: true,
  fontFamily: '"Figtree Variable", "Segoe UI", system-ui, sans-serif',
  fontFamilyMonospace: 'ui-monospace, "Cascadia Mono", Menlo, monospace',
  headings: {
    fontFamily:
      '"Bricolage Grotesque Variable", "Figtree Variable", system-ui, sans-serif',
    fontWeight: "700",
    sizes: {
      h1: { fontSize: "2rem", lineHeight: "1.1" },
      h2: { fontSize: "1.375rem", lineHeight: "1.2" },
      h3: { fontSize: "1.0625rem", lineHeight: "1.3" },
    },
  },
  defaultRadius: "sm",
  radius: { xs: "3px", sm: "6px", md: "8px", lg: "12px", xl: "16px" },
  cursorType: "pointer",
  focusRing: "auto",
  components: {
    TextInput: { defaultProps: inputDefaults },
    PasswordInput: { defaultProps: inputDefaults },
    NativeSelect: { defaultProps: inputDefaults },
    Textarea: { defaultProps: inputDefaults },
    FileInput: { defaultProps: inputDefaults },
    Button: { defaultProps: { size: "md" } },
  },
});

/** Cement grounds and grout lines replace Mantine's neutral grays. */
export const resolver: CSSVariablesResolver = () => ({
  variables: {},
  light: {
    "--mantine-color-body": "#eceeea",
    "--mantine-color-text": "#14231e",
    "--mantine-color-dimmed": "#4a5d56",
    "--mantine-color-default-border": "#cfd6cf",
    "--mantine-color-placeholder": "#62746d",
  },
  dark: {
    "--mantine-color-body": "#0e1613",
    "--mantine-color-text": "#e3ebe6",
    "--mantine-color-dimmed": "#a5b5ad",
    "--mantine-color-default": "#16211d",
    "--mantine-color-default-hover": "#1c2a25",
    "--mantine-color-default-border": "#2a3a33",
    "--mantine-color-placeholder": "#8a9b93",
  },
});
