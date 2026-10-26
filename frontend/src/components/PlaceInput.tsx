"use client";

import { useEffect, useId, useRef, useState } from "react";
import { currentPlace, geocode } from "@/lib/api";
import type { Place } from "@/lib/types";

interface Props {
  label: string;
  value: Place | null;
  onChange: (place: Place | null) => void;
  placeholder?: string;
  /** Show a button that fills the field with the browser's current location. */
  allowCurrentLocation?: boolean;
  /** Raw text as typed, so a form can submit it when no suggestion was picked. */
  onTextChange?: (text: string) => void;
  /** Extra control shown at the right end of the label row. */
  labelAction?: React.ReactNode;
}

/** Text input with debounced geocoding suggestions (keyboard accessible). */
export function PlaceInput({ label, value, onChange, placeholder, allowCurrentLocation, labelAction, onTextChange }: Props) {
  const id = useId();
  const [text, setText] = useState(value?.name ?? "");
  const [results, setResults] = useState<Place[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const [locating, setLocating] = useState(false);
  const [locateError, setLocateError] = useState<string | null>(null);

  // Show the chosen place's name when the parent sets a value (pick, swap,
  // example trips). Clearing the value while typing leaves the text alone.
  useEffect(() => {
    if (value) setText(value.name);
  }, [value]);

  useEffect(() => {
    onTextChange?.(text);
  }, [text, onTextChange]);

  useEffect(() => {
    // No lookup for the name of the place that's already chosen.
    if (value && text === value.name) return;
    const q = text.trim();
    if (q.length < 2) {
      setResults([]);
      return;
    }
    const ctrl = new AbortController();
    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        const { results } = await geocode(q, ctrl.signal);
        setResults(results);
        setActive(0);
        // A slow lookup can land after the user moved on; only pop open while focused.
        setOpen(document.activeElement === inputRef.current);
      } catch {
        if (!ctrl.signal.aborted) setResults([]);
      } finally {
        if (!ctrl.signal.aborted) setLoading(false);
      }
    }, 250);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only re-query when the text changes
  }, [text]);

  async function useCurrentLocation() {
    setLocating(true);
    setLocateError(null);
    setOpen(false);
    try {
      onChange(await currentPlace());
    } catch (e) {
      setLocateError((e as Error).message);
    } finally {
      setLocating(false);
    }
  }

  function choose(place: Place) {
    onChange(place);
    setOpen(false);
  }

  return (
    <div className={`field place-input${allowCurrentLocation ? " has-locate" : ""}`}>
      <div className="label-row">
        <label htmlFor={id}>{label}</label>
        {labelAction}
      </div>
      <input
        ref={inputRef}
        id={id}
        value={text}
        placeholder={placeholder}
        autoComplete="off"
        role="combobox"
        aria-expanded={open && results.length > 0}
        aria-controls={`${id}-list`}
        onChange={(e) => {
          setText(e.target.value);
          setLocateError(null);
          if (value) onChange(null);
        }}
        onFocus={() => results.length && setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => {
          if (!open || !results.length) return;
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setActive((a) => (a + 1) % results.length);
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setActive((a) => (a - 1 + results.length) % results.length);
          } else if (e.key === "Enter") {
            e.preventDefault();
            choose(results[active]);
          } else if (e.key === "Escape") {
            setOpen(false);
          }
        }}
      />
      {loading && <span className="input-spinner" aria-hidden />}
      {allowCurrentLocation && (
        <button
          type="button"
          className="locate"
          onClick={useCurrentLocation}
          disabled={locating}
          title="Use my current location"
          aria-label="Use my current location"
        >
          {locating ? (
            <span className="locate-spinner" aria-hidden />
          ) : (
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden>
              <circle cx="12" cy="12" r="4" fill="currentColor" />
              <circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" strokeWidth="2" />
              <path d="M12 1v3M12 20v3M1 12h3M20 12h3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          )}
        </button>
      )}
      {locating && <div className="muted small">Finding your location…</div>}
      {locateError && (
        <div className="form-error small" role="alert">
          {locateError}
        </div>
      )}
      {open && results.length > 0 && (
        <ul id={`${id}-list`} role="listbox" className="suggestions">
          {results.map((p, i) => (
            <li
              key={`${p.lat},${p.lon},${i}`}
              role="option"
              aria-selected={i === active}
              className={i === active ? "active" : undefined}
              onMouseDown={(e) => {
                e.preventDefault();
                choose(p);
              }}
              onMouseEnter={() => setActive(i)}
            >
              {p.name}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
