export type RiskLevel = 0 | 1 | 2 | 3 | 4;
export type RiskLabel = "Low" | "Moderate" | "High" | "Severe" | "No Travel";

export interface Place {
  name: string;
  lat: number;
  lon: number;
}

export interface Weather {
  wind_mph: number;
  gust_mph: number | null;
  rain_in_hr: number;
  snow_in_hr: number;
  temp_f: number | null;
  weather_code: number | null;
  wind_risk: RiskLabel;
  rain_risk: RiskLabel;
  snow_risk: RiskLabel;
}

export interface Checkpoint {
  index: number;
  mile: number;
  lat: number;
  lon: number;
  eta: string;
  elapsed_s: number;
  risk: RiskLevel;
  risk_label: RiskLabel;
  reasons: string[];
  weather: Weather | null;
}

export interface RouteSummary {
  miles_by_risk: Record<RiskLabel, number>;
  severe_miles: number;
  high_miles: number;
  no_travel_miles: number;
  average_risk: number;
  max_risk: RiskLevel;
  max_risk_label: RiskLabel;
}

export interface Route {
  id: string;
  name: string;
  distance_mi: number;
  duration_s: number;
  arrival: string;
  geometry: [number, number][];
  checkpoints: Checkpoint[];
  summary: RouteSummary;
  rank: number;
  recommended: boolean;
}

export interface Plan {
  plan_id: string;
  origin: Place;
  destination: Place;
  departure: string;
  load_lb: number;
  interval_mi: number;
  routes: Route[];
  recommended_route_id: string;
  recommendation_reason: string;
  no_travel_warning: boolean;
}

export interface HeatPoint {
  lat: number;
  lon: number;
  risk: (number | null)[];
  wind: (number | null)[];
  rain: (number | null)[];
  snow: (number | null)[];
}

export interface Heatmap {
  plan_id: string;
  hours: string[];
  spacing_mi: number;
  points: HeatPoint[];
}

export type HeatMetric = "risk" | "wind" | "rain" | "snow";

export interface TripInput {
  origin: Place | string;
  destination: Place | string;
  departure: string; // ISO 8601 with offset
  load_lb: number;
  interval_mi: 10 | 25 | 50;
}
