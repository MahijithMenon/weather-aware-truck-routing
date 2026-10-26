import type { Checkpoint, RiskLevel, Route } from "./types";

type LL = [number, number];

function haversineMi(a: LL, b: LL): number {
  const toRad = Math.PI / 180;
  const dLat = (b[0] - a[0]) * toRad;
  const dLon = (b[1] - a[1]) * toRad;
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(a[0] * toRad) * Math.cos(b[0] * toRad) * Math.sin(dLon / 2) ** 2;
  return 2 * 3958.8 * Math.asin(Math.sqrt(h));
}

export interface RiskSegment {
  risk: RiskLevel;
  points: LL[];
}

/**
 * Split a route's line into runs colored by checkpoint risk. Mirrors the
 * backend's mileage rule: each checkpoint covers the road halfway to its
 * neighbours.
 */
export function riskSegments(route: Route): RiskSegment[] {
  const geom = route.geometry as LL[];
  const cps = route.checkpoints;
  if (geom.length < 2 || !cps.length) return [{ risk: 0, points: geom }];

  // Cumulative miles along the (display-simplified) line, scaled to the true length.
  const cum = [0];
  for (let i = 1; i < geom.length; i++) cum.push(cum[i - 1] + haversineMi(geom[i - 1], geom[i]));
  const scale = route.distance_mi / (cum[cum.length - 1] || 1);
  for (let i = 0; i < cum.length; i++) cum[i] *= scale;

  // Boundaries where the governing checkpoint changes.
  const bounds = cps.slice(0, -1).map((c, i) => (c.mile + cps[i + 1].mile) / 2);
  const riskAt = (k: number) => cps[k].risk;

  const segments: RiskSegment[] = [];
  let k = 0;
  let current: RiskSegment = { risk: riskAt(0), points: [geom[0]] };
  for (let i = 1; i < geom.length; i++) {
    while (k < bounds.length && cum[i] > bounds[k]) {
      // Interpolate the exact boundary point so colors switch at the right mile.
      const t = (bounds[k] - cum[i - 1]) / (cum[i] - cum[i - 1] || 1);
      const p: LL = [
        geom[i - 1][0] + (geom[i][0] - geom[i - 1][0]) * t,
        geom[i - 1][1] + (geom[i][1] - geom[i - 1][1]) * t,
      ];
      k++;
      if (riskAt(k) !== current.risk) {
        current.points.push(p);
        segments.push(current);
        current = { risk: riskAt(k), points: [p] };
      }
    }
    current.points.push(geom[i]);
  }
  segments.push(current);
  return segments;
}

/** Where the truck is `elapsedS` seconds after departure (from checkpoint ETAs). */
export function positionAt(checkpoints: Checkpoint[], elapsedS: number): LL | null {
  if (!checkpoints.length || elapsedS < 0) return null;
  const last = checkpoints[checkpoints.length - 1];
  if (elapsedS >= last.elapsed_s) return null; // already arrived
  for (let i = 1; i < checkpoints.length; i++) {
    const a = checkpoints[i - 1];
    const b = checkpoints[i];
    if (elapsedS <= b.elapsed_s) {
      const t = (elapsedS - a.elapsed_s) / (b.elapsed_s - a.elapsed_s || 1);
      return [a.lat + (b.lat - a.lat) * t, a.lon + (b.lon - a.lon) * t];
    }
  }
  return null;
}
