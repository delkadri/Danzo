import { io } from "socket.io-client";

// Railway prod => set VITE_BACKEND_URL in frontend env
const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || "http://localhost:5000";

export const socket = io(BACKEND_URL, {
  transports: ["websocket"],
  reconnection: true
});
