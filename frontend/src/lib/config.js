/**
 * API Configuration
 * 
 * This module provides a centralized configuration for API endpoints.
 * The API URL is determined by environment variables or defaults to localhost.
 */

// Get API base URL from environment or use default
export function getAPIBaseURL() {
  // First try environment variable (set via Vite)
  if (typeof import.meta !== 'undefined' && import.meta.env.VITE_API_URL) {
    return import.meta.env.VITE_API_URL;
  }
  
  // Fall back to window location if in browser
  if (typeof window !== 'undefined') {
    const protocol = window.location.protocol;
    const hostname = window.location.hostname;
    
    // If running on same domain, use same host but port 8001 for backend
    if (hostname === 'localhost' || hostname === '127.0.0.1') {
      return `${protocol}//localhost:8001`;
    }
    
    // If running on a domain, assume backend is at same domain
    return `${protocol}//${window.location.host}`;
  }
  
  // Default fallback
  return 'http://localhost:8001';
}

// Get WebSocket URL from API URL
export function getWSURL(path = 'ws-transcribe') {
  const apiURL = getAPIBaseURL();
  const wsProtocol = apiURL.startsWith('https') ? 'wss' : 'ws';
  const baseURL = apiURL.replace(/^https?:\/\//, '');
  return `${wsProtocol}://${baseURL}/${path}`;
}

export const API_BASE = getAPIBaseURL();
export const WS_BASE = getWSURL();
