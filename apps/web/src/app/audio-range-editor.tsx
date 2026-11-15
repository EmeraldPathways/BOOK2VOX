"use client";

import { useEffect, useRef, useState } from "react";

type AudioRangeEditorProps = {
  file: File | null;
  startSeconds: number;
  endSeconds: number;
  onChange: (startSeconds: number, endSeconds: number) => void;
};

const clamp = (value: number, minimum: number, maximum: number) => Math.min(maximum, Math.max(minimum, value));

export default function AudioRangeEditor({ file, startSeconds, endSeconds, onChange }: AudioRangeEditorProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [sourceUrl, setSourceUrl] = useState("");
  const [duration, setDuration] = useState(0);
  const [peaks, setPeaks] = useState<number[]>([]);
  const [previewing, setPreviewing] = useState(false);
  const rangeReady = duration >= 3;
  const safeStart = rangeReady ? clamp(startSeconds, 0, Math.max(0, duration - 3)) : 0;
  const safeEnd = rangeReady ? clamp(endSeconds, Math.min(duration, safeStart + 3), Math.min(duration, safeStart + 30)) : 0;

  useEffect(() => {
    if (!file) {
      setSourceUrl("");
      setDuration(0);
      setPeaks([]);
      return;
    }
    const url = URL.createObjectURL(file);
    let cancelled = false;
    setSourceUrl(url);
    setDuration(0);
    setPeaks([]);
    void fetch(url)
      .then(response => response.arrayBuffer())
      .then(async buffer => {
        const context = new AudioContext();
        try {
          const decoded = await context.decodeAudioData(buffer);
          if (cancelled) return;
          const channel = decoded.getChannelData(0);
          const bucketSize = Math.max(1, Math.floor(channel.length / 1200));
          const nextPeaks: number[] = [];
          for (let offset = 0; offset < channel.length; offset += bucketSize) {
            let peak = 0;
            for (let index = offset; index < Math.min(channel.length, offset + bucketSize); index += 1) {
              peak = Math.max(peak, Math.abs(channel[index]));
            }
            nextPeaks.push(peak);
          }
          setPeaks(nextPeaks);
        } finally {
          await context.close();
        }
      })
      .catch(() => {
        if (!cancelled) setPeaks([]);
      });
    return () => {
      cancelled = true;
      URL.revokeObjectURL(url);
    };
  }, [file]);

  const drawWaveform = () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const width = Math.max(1, canvas.clientWidth);
    const height = 112;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = width * ratio;
    canvas.height = height * ratio;
    const context = canvas.getContext("2d");
    if (!context) return;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, width, height);
    context.fillStyle = "#101816";
    context.fillRect(0, 0, width, height);
    const selectionStart = duration ? (safeStart / duration) * width : 0;
    const selectionEnd = duration ? (safeEnd / duration) * width : 0;
    context.fillStyle = "rgba(166, 201, 174, .18)";
    context.fillRect(selectionStart, 0, Math.max(0, selectionEnd - selectionStart), height);
    context.strokeStyle = "#a6c9ae";
    context.lineWidth = 1;
    context.beginPath();
    if (peaks.length) {
      const step = width / peaks.length;
      peaks.forEach((peak, index) => {
        const x = index * step;
        const amplitude = Math.max(2, peak * height * 0.45);
        context.moveTo(x, height / 2 - amplitude);
        context.lineTo(x, height / 2 + amplitude);
      });
    }
    context.stroke();
    if (duration) {
      context.strokeStyle = "#d7f0dc";
      context.lineWidth = 2;
      context.beginPath();
      context.moveTo(selectionStart, 0);
      context.lineTo(selectionStart, height);
      context.moveTo(selectionEnd, 0);
      context.lineTo(selectionEnd, height);
      context.stroke();
    }
  };

  useEffect(() => {
    drawWaveform();
    const canvas = canvasRef.current;
    if (!canvas || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(drawWaveform);
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [duration, peaks, safeStart, safeEnd]);

  useEffect(() => {
    if (!duration || !rangeReady) return;
    const nextStart = clamp(startSeconds, 0, Math.max(0, duration - 3));
    const nextEnd = clamp(endSeconds, Math.min(duration, nextStart + 3), Math.min(duration, nextStart + 30));
    if (nextStart !== startSeconds || nextEnd !== endSeconds) onChange(nextStart, nextEnd);
  }, [duration]);

  const changeStart = (value: number) => {
    const nextStart = clamp(value, 0, Math.max(0, duration - 3));
    const nextEnd = clamp(Math.max(safeEnd, nextStart + 3), nextStart + 3, Math.min(duration, nextStart + 30));
    onChange(nextStart, nextEnd);
  };

  const changeEnd = (value: number) => {
    const nextEnd = clamp(value, Math.min(duration, safeStart + 3), Math.min(duration, safeStart + 30));
    onChange(safeStart, nextEnd);
  };

  const previewSelection = () => {
    const audio = audioRef.current;
    if (!audio || !rangeReady) return;
    audio.currentTime = safeStart;
    setPreviewing(true);
    void audio.play().catch(() => setPreviewing(false));
  };

  return (
    <div style={{ margin: "12px 0", padding: 12, border: "1px solid #52665a", borderRadius: 9 }}>
      <audio
        ref={audioRef}
        controls
        src={sourceUrl || undefined}
        onPause={() => setPreviewing(false)}
        onTimeUpdate={event => {
          if (previewing && event.currentTarget.currentTime >= safeEnd) {
            event.currentTarget.pause();
            event.currentTarget.currentTime = safeStart;
            setPreviewing(false);
          }
        }}
        style={{ width: "100%", height: 38 }}
      />
      <canvas ref={canvasRef} aria-label="Voice recording waveform" style={{ display: "block", width: "100%", height: 112, marginTop: 10, borderRadius: 6 }} />
      <div style={{ display: "grid", gap: 6, marginTop: 10 }}>
        <label style={{ fontSize: 13 }}>Start: {safeStart.toFixed(1)}s</label>
        <input aria-label="Voice selection start" type="range" min="0" max={Math.max(0, duration - 3)} step="0.1" value={safeStart} disabled={!rangeReady} onChange={event => changeStart(Number(event.target.value))} />
        <label style={{ fontSize: 13 }}>End: {safeEnd.toFixed(1)}s · selected {(safeEnd - safeStart).toFixed(1)}s</label>
        <input aria-label="Voice selection end" type="range" min={Math.min(duration, safeStart + 3)} max={Math.min(duration, safeStart + 30)} step="0.1" value={safeEnd} disabled={!rangeReady} onChange={event => changeEnd(Number(event.target.value))} />
      </div>
      {!file && <p style={{ fontSize: 13, color: "#9caea4", marginBottom: 0 }}>Choose an audio file to select a voice range.</p>}
      {file && !rangeReady && <p style={{ fontSize: 13, color: "#ffb2a5", marginBottom: 0 }}>The recording must be at least 3 seconds long.</p>}
      {rangeReady && (safeEnd - safeStart < 3 || safeEnd - safeStart > 30) && <p style={{ fontSize: 13, color: "#ffb2a5", marginBottom: 0 }}>Select between 3 and 30 seconds.</p>}
      <button type="button" onClick={previewSelection} disabled={!rangeReady || previewing} style={{ marginTop: 10, background: "#35493d", border: 0, borderRadius: 7, padding: "8px 12px", color: "white", cursor: rangeReady ? "pointer" : "not-allowed" }}>
        {previewing ? "Previewing selection…" : "Preview selection"}
      </button>
    </div>
  );
}
