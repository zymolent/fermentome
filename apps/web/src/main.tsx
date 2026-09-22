import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { App } from "@/App";
import "@/styles/globals.css";

/**
 * The atlas is a local SQLite file that changes only when a curator runs a command, so data is
 * treated as fresh for a minute and refetching on window focus is off: a background refetch
 * every time the window is clicked would be pure noise against a file that has not moved.
 */
const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 60_000, refetchOnWindowFocus: false, retry: 1 },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
