/**
 * Panel entry — mounts the Live Sniper panel. Used by BOTH the Chrome side
 * panel and the web companion page (the bridge degrades gracefully when
 * extension APIs are absent).
 */
import { createRoot } from "react-dom/client";
import { LiveSniperPanel } from "@propstein/ui";
import { createChromePanelBridge } from "./panel-bridge.ts";
import "@propstein/ui/theme.css";

const rootEl = document.getElementById("panel-root-mount");
if (rootEl) {
  createRoot(rootEl).render(<LiveSniperPanel bridge={createChromePanelBridge()} />);
}
