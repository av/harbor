import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter as Router } from "react-router-dom";
import { Toaster } from "react-hot-toast";

import { App } from "./App";
import { init } from "./theme";
import { OverlayProvider } from "./OverlayContext";

import "./font.css";
import "./main.css";

init();

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <Router>
      <OverlayProvider>
        <App />
      </OverlayProvider>
      <Toaster
        position="bottom-right"
        toastOptions={{
          className: "p-2 pl-4 bg-base-300/50 text-base-content backdrop-blur rounded-box shadow-none",
        }}
      />
    </Router>
  </React.StrictMode>,
);

setTimeout(() => {
  document.querySelector(".splash")?.classList.add("away");
});
