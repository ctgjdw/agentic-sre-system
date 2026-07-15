import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { TopBar } from "./components/TopBar";
import "./theme.css";

const qc = new QueryClient({ defaultOptions: { queries: { refetchInterval: 3000 } } });

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <TopBar />
        <main style={{ maxWidth: 1280, margin: "0 auto", padding: "0 16px" }}>
          <Routes>
            <Route path="/" element={<Navigate to="/cases" replace />} />
            <Route path="/cases" element={<div>queue (Task 28)</div>} />
            <Route path="/cases/:id" element={<div>detail (Tasks 29-30)</div>} />
            <Route path="/cases/:id/artifact/:kind" element={<div>artifact (Task 31)</div>} />
            <Route path="/governance" element={<div>governance (Task 32)</div>} />
            <Route path="/chat" element={<div>chat (Task 45)</div>} />
          </Routes>
        </main>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
