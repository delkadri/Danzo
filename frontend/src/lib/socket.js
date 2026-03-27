import { io } from "socket.io-client";

// Default to same-origin so the frontend can work behind a single public domain.
const backendUrl = import.meta.env.VITE_BACKEND_URL?.trim() || window.location.origin;

export const socket = io(backendUrl, {
  path: "/socket.io",
  transports: ["websocket", "polling"],
});
