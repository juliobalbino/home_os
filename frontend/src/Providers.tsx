import { MantineProvider } from "@mantine/core";
import type { ReactNode } from "react";
import { MotionConfig } from "motion/react";
import { resolver, theme } from "./theme";
import { ToastProvider } from "./ui/Toaster";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <MantineProvider
      theme={theme}
      cssVariablesResolver={resolver}
      defaultColorScheme="auto"
    >
      <MotionConfig reducedMotion="user">
        <ToastProvider>{children}</ToastProvider>
      </MotionConfig>
    </MantineProvider>
  );
}
