export function audioDownloadName(format, kind = "preview") {
  if (kind === "chapter") return `book2vox-chapter.${format}`;
  return format === "mp3" ? "book2vox-chapter.mp3" : "book2vox-preview.wav";
}

export function audioDownloadLabel(format) {
  return `Download ${format.toUpperCase()}`;
}
