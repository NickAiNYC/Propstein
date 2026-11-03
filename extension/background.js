chrome.runtime.onInstalled.addListener(() => {
  // Allow users to open the side panel by clicking the extension action icon
  if (chrome.sidePanel && chrome.sidePanel.setPanelBehavior) {
    chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch((err) => {
      console.warn("sidePanel.setPanelBehavior error:", err);
    });
  }

  // Create right-click context menu item for selected player text
  chrome.contextMenus.create({
    id: "propwire-check-edge",
    title: "Check PropWire Edge for '%s'",
    contexts: ["selection"]
  });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === "propwire-check-edge" && tab) {
    // 1. Open the side panel for the current window
    if (chrome.sidePanel && chrome.sidePanel.open) {
      chrome.sidePanel.open({ windowId: tab.windowId }).catch((err) => {
        console.warn("sidePanel.open error:", err);
      });
    }

    // 2. Broadcast the selected text to the side panel's DOM
    setTimeout(() => {
      chrome.runtime.sendMessage({
        action: "search_intent",
        query: info.selectionText
      }).catch(() => {
        // Suppress message failure if side panel is still launching
      });
    }, 400);
  }
});
