import React from "react";
import ReactDOM from "react-dom/client";
import "@fontsource-variable/figtree";
import "@fontsource-variable/bricolage-grotesque";
import "@mantine/core/styles.css";
import "./styles/ladrilho.css";
import App from "./App";
import { Providers } from "./Providers";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Providers>
      <App />
    </Providers>
  </React.StrictMode>,
);
