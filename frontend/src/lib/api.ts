import type { Heatmap, Place, Plan, TripInput } from "./types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch {
    throw new Error("Can't reach the server. Check your connection and try again.");
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    throw new Error(body?.error ?? `Request failed (${res.status})`);
  }
  return body as T;
}

export function geocode(q: string, signal?: AbortSignal): Promise<{ results: Place[] }> {
  return request(`/api/geocode?q=${encodeURIComponent(q)}`, { signal });
}

export function planTrip(input: TripInput, signal?: AbortSignal): Promise<Plan> {
  return request("/api/plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
    signal,
  });
}

export function fetchHeatmap(planId: string, signal?: AbortSignal): Promise<Heatmap> {
  return request(`/api/plans/${planId}/heatmap`, { signal });
}

export function reverseGeocode(lat: number, lon: number, signal?: AbortSignal): Promise<Place> {
  return request(`/api/reverse-geocode?lat=${lat}&lon=${lon}`, { signal });
}

const GEO_ERRORS: Record<number, string> = {
  1: "Location access was denied. Allow it in your browser's site settings, or type a place.",
  2: "Your location isn't available right now. Type a place instead.",
  3: "Finding your location took too long. Try again or type a place.",
};

/** The browser's current position, labelled via reverse geocoding. */
export function currentPlace(): Promise<Place> {
  return new Promise((resolve, reject) => {
    if (!("geolocation" in navigator)) {
      reject(new Error("This browser can't share your location. Type a place instead."));
      return;
    }
    if (!window.isSecureContext) {
      reject(new Error("Location needs a secure (https) connection. Type a place instead."));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const lat = Number(pos.coords.latitude.toFixed(5));
        const lon = Number(pos.coords.longitude.toFixed(5));
        try {
          resolve(await reverseGeocode(lat, lon));
        } catch {
          // The coordinates are what matter; a label is a nicety.
          resolve({ name: `Current location (${lat.toFixed(4)}, ${lon.toFixed(4)})`, lat, lon });
        }
      },
      (err) => reject(new Error(GEO_ERRORS[err.code] ?? "Couldn't get your location.")),
      { enableHighAccuracy: false, timeout: 15_000, maximumAge: 5 * 60_000 },
    );
  });
}
