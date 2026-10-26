"use client";

import { useState } from "react";
import type { Place, TripInput } from "@/lib/types";
import { PlaceInput } from "./PlaceInput";

const INTERVALS = [10, 25, 50] as const;

/** `datetime-local` value for a Date, in the browser's time zone. */
function toLocalInput(d: Date): string {
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function nextHour(): Date {
  const d = new Date();
  d.setMinutes(0, 0, 0);
  d.setHours(d.getHours() + 1);
  return d;
}

const EXAMPLES: { label: string; origin: Place; destination: Place }[] = [
  {
    label: "Chicago → Denver",
    origin: { name: "Chicago, Illinois, United States", lat: 41.8756, lon: -87.6244 },
    destination: { name: "Denver, Colorado, United States", lat: 39.7392, lon: -104.9849 },
  },
  {
    label: "Dallas → Atlanta",
    origin: { name: "Dallas, Texas, United States", lat: 32.7763, lon: -96.7969 },
    destination: { name: "Atlanta, Georgia, United States", lat: 33.749, lon: -84.388 },
  },
  {
    label: "Seattle → Salt Lake City",
    origin: { name: "Seattle, Washington, United States", lat: 47.6038, lon: -122.3301 },
    destination: { name: "Salt Lake City, Utah, United States", lat: 40.7596, lon: -111.8868 },
  },
];

interface Props {
  loading: boolean;
  onSubmit: (input: TripInput) => void;
}

export function TripForm({ loading, onSubmit }: Props) {
  const [origin, setOrigin] = useState<Place | null>(null);
  const [destination, setDestination] = useState<Place | null>(null);
  // What's typed in each field, used when no suggestion was picked (the API geocodes it).
  const [originText, setOriginText] = useState("");
  const [destinationText, setDestinationText] = useState("");
  const [departure, setDeparture] = useState(() => toLocalInput(nextHour()));
  const [load, setLoad] = useState("42000");
  const [interval, setIntervalMi] = useState<(typeof INTERVALS)[number]>(25);
  const [error, setError] = useState<string | null>(null);

  const min = toLocalInput(new Date());
  const max = toLocalInput(new Date(Date.now() + 7 * 24 * 3600 * 1000));

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const from = origin ?? originText.trim();
    const to = destination ?? destinationText.trim();
    if (!from || !to) {
      setError("Enter an origin and a destination.");
      return;
    }
    const loadLb = Number(load.replace(/,/g, ""));
    if (!Number.isFinite(loadLb) || loadLb < 0 || loadLb > 120_000) {
      setError("Load weight must be between 0 and 120,000 lb.");
      return;
    }
    const dep = new Date(departure);
    if (Number.isNaN(dep.getTime())) {
      setError("Enter a valid departure date and time.");
      return;
    }
    setError(null);
    onSubmit({ origin: from, destination: to, departure: dep.toISOString(), load_lb: loadLb, interval_mi: interval });
  }

  return (
    <form className="trip-form" onSubmit={submit} noValidate>
      <PlaceInput
        label="Origin"
        value={origin}
        onChange={setOrigin}
        onTextChange={setOriginText}
        placeholder="City, address, or use your location"
        allowCurrentLocation
      />
      <PlaceInput
        label="Destination"
        value={destination}
        onChange={setDestination}
        onTextChange={setDestinationText}
        placeholder="City or address"
        labelAction={
          <button
            type="button"
            className="swap"
            title="Swap origin and destination"
            onClick={() => {
              setOrigin(destination);
              setDestination(origin);
            }}
          >
            ⇅ Swap
          </button>
        }
      />

      <div className="row">
        <div className="field">
          <label htmlFor="departure">Departure</label>
          <input
            id="departure"
            type="datetime-local"
            value={departure}
            min={min}
            max={max}
            onChange={(e) => setDeparture(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="load">Load weight (lb)</label>
          <input
            id="load"
            inputMode="numeric"
            value={load}
            onChange={(e) => setLoad(e.target.value)}
          />
        </div>
      </div>

      <div className="field">
        <span className="label">Weather checkpoint every</span>
        <div className="segmented" role="radiogroup" aria-label="Checkpoint interval">
          {INTERVALS.map((n) => (
            <button
              key={n}
              type="button"
              role="radio"
              aria-checked={interval === n}
              className={interval === n ? "on" : undefined}
              onClick={() => setIntervalMi(n)}
            >
              {n} mi
            </button>
          ))}
        </div>
      </div>

      {error && <div className="form-error">{error}</div>}

      <button type="submit" className="primary" disabled={loading}>
        {loading ? "Planning routes…" : "Find safest route"}
      </button>

      <div className="examples">
        <span className="muted">Try:</span>
        {EXAMPLES.map((ex) => (
          <button
            key={ex.label}
            type="button"
            className="link"
            onClick={() => {
              setOrigin(ex.origin);
              setDestination(ex.destination);
            }}
          >
            {ex.label}
          </button>
        ))}
      </div>
    </form>
  );
}
