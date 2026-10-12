const crestSource = `${import.meta.env.BASE_URL}branding/pbhs-125-crest.png`;

export function BrandCrest({ context = "header", decorative = false }) {
  return (
    <img
      className={`brand-crest brand-crest--${context}`}
      src={crestSource}
      alt={decorative ? "" : "Pretoria Boys High School 125th anniversary crest"}
      aria-hidden={decorative || undefined}
      draggable="false"
    />
  );
}

export function BrandLockup({ compact = false }) {
  return (
    <span className={`brand-lockup${compact ? " brand-lockup--compact" : ""}`}>
      <strong>PBHS Mathematics</strong>
      <small>Memo Converter</small>
    </span>
  );
}
