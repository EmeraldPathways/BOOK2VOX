const clamp = (value, minimum, maximum) => Math.min(maximum, Math.max(minimum, value));

export function audioDuration(audio) {
  const duration = Number(audio?.duration);
  return Number.isFinite(duration) && duration > 0 ? duration : 0;
}

export function normalizeSelection(duration, startSeconds, endSeconds) {
  const ready = duration >= 3;
  if (!ready) {
    return { ready: false, start: 0, end: 0, startMax: 0, endMin: 0, endMax: 0 };
  }

  const startMax = Math.max(0, duration - 3);
  const start = clamp(startSeconds, 0, startMax);
  const endMin = Math.min(duration, start + 3);
  const endMax = Math.min(duration, start + 30);
  const end = clamp(endSeconds, endMin, endMax);
  return { ready: true, start, end, startMax, endMin, endMax };
}
