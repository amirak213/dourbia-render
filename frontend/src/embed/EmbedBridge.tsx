import { useEffect } from "react";

interface EmbedBridgeProps {
  mapOpen: boolean;
}

export default function EmbedBridge({ mapOpen }: EmbedBridgeProps) {
  useEffect(() => {
    window.parent.postMessage(
      { source: "dourbia-chat", type: "layout", mapOpen },
      "*",
    );
  }, [mapOpen]);

  return null;
}