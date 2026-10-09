import styles from "./HeroImagingPreview.module.css";

/**
 * A deliberately synthetic, decorative visualization for the home screen.
 * It does not display a patient study, backend metrics, or model availability.
 */
export default function HeroImagingPreview() {
  return (
    <section
      className={styles.preview}
      aria-label="Animated illustrative medical imaging preview, not diagnostic image data"
    >
      <div className={styles.grid} aria-hidden="true" />
      <div className={styles.glow} aria-hidden="true" />

      <header className={styles.header}>
        <div className={styles.identity}>
          <span className={styles.led} aria-hidden="true" />
          <span>MEDAXIS IMAGING ENGINE</span>
        </div>
        <span className={styles.previewPill}>ILLUSTRATIVE</span>
      </header>

      <div className={styles.scene} aria-hidden="true">
        <div className={styles.orbitA} />
        <div className={styles.orbitB} />
        <div className={styles.orbitC} />
        <div className={styles.halo} />

        <div className={styles.floatingTop}>
          <span className={styles.micro}>MULTIPLANAR REVIEW</span>
          <strong>AXIAL / CORONAL / SAGITTAL</strong>
          <span className={styles.softLine} />
        </div>

        <div className={styles.floatingBottom}>
          <span className={styles.micro}>VOLUME WORKSPACE</span>
          <strong>3D GEOMETRY</strong>
          <div className={styles.barSequence}>
            {[14, 26, 19, 34, 25, 39, 21, 29, 17].map((height, index) => (
              <span key={index} style={{ height: `${height}px`, animationDelay: `${index * -0.14}s` }} />
            ))}
          </div>
        </div>

        <div className={styles.sliceFrame}>
          <div className={styles.sliceImage}>
            <svg
              className={styles.phantom}
              viewBox="0 0 320 320"
              role="presentation"
              focusable="false"
              xmlns="http://www.w3.org/2000/svg"
            >
              <defs>
                <radialGradient id="medaxis-hero-body" cx="48%" cy="44%" r="64%">
                  <stop offset="0%" stopColor="#c1cbd2" />
                  <stop offset="57%" stopColor="#828f9a" />
                  <stop offset="100%" stopColor="#424d5a" />
                </radialGradient>
                <linearGradient id="medaxis-hero-soft" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0%" stopColor="#8695a1" stopOpacity=".75" />
                  <stop offset="100%" stopColor="#cad6dc" stopOpacity=".38" />
                </linearGradient>
                <clipPath id="medaxis-hero-clip">
                  <ellipse cx="160" cy="163" rx="117" ry="126" />
                </clipPath>
              </defs>

              <g className={styles.sliceAnatomy}>
                <ellipse cx="160" cy="163" rx="125" ry="134" fill="#d4dce2" opacity=".25" />
                <ellipse cx="160" cy="163" rx="119" ry="128" fill="#111b27" stroke="#d4e3e8" strokeWidth="6" />
                <ellipse cx="160" cy="163" rx="113" ry="122" fill="url(#medaxis-hero-body)" />
                <g clipPath="url(#medaxis-hero-clip)">
                  <ellipse cx="112" cy="157" rx="47" ry="73" fill="#091119" />
                  <ellipse cx="211" cy="157" rx="46" ry="75" fill="#091119" />
                  <ellipse cx="110" cy="156" rx="40" ry="66" fill="#172530" opacity=".55" />
                  <ellipse cx="212" cy="157" rx="39" ry="68" fill="#172530" opacity=".55" />
                  <path d="M155 99 C168 110 171 128 170 145 C167 157 154 174 157 190 C162 205 173 212 175 232 C161 243 144 237 141 225 C140 207 149 199 146 183 C143 164 145 143 149 126 Z" fill="url(#medaxis-hero-soft)" />
                  <ellipse cx="160" cy="196" rx="20" ry="27" fill="#dbe8ed" opacity=".9" />
                  <ellipse cx="160" cy="196" rx="11" ry="19" fill="#f0f7fa" />
                  <ellipse cx="130" cy="85" rx="14" ry="11" fill="#edf3f5" opacity=".75" />
                  <ellipse cx="191" cy="85" rx="14" ry="11" fill="#edf3f5" opacity=".75" />
                  <path d="M67 118 C81 98 98 91 116 85 M253 118 C239 98 222 91 204 85" fill="none" stroke="#e1eaf0" strokeWidth="4" strokeOpacity=".25" strokeLinecap="round" />
                  <path d="M61 196 Q77 237 115 247 M259 196 Q243 237 205 247" fill="none" stroke="#eef6f9" strokeWidth="4" strokeOpacity=".2" strokeLinecap="round" />
                </g>
                <ellipse cx="160" cy="163" rx="119" ry="128" fill="none" stroke="#e2ecf3" strokeOpacity=".75" strokeWidth="3" />
              </g>
            </svg>
            <div className={styles.scanBeam} />
            <div className={styles.crosshairX} />
            <div className={styles.crosshairY} />
            <div className={styles.crosshairCenter} />
            <div className={styles.cornerTL} />
            <div className={styles.cornerTR} />
            <div className={styles.cornerBL} />
            <div className={styles.cornerBR} />
          </div>
          <div className={styles.sliceCaption}>
            <span>SIMULATED AXIAL IMAGE</span>
            <span>VISUAL PREVIEW</span>
          </div>
        </div>
      </div>

      <footer className={styles.footer}>
        <div className={styles.footerLabel}>
          <span className={styles.activityDot} aria-hidden="true" />
          <span>RESEARCH VISUALIZATION</span>
        </div>
        <span className={styles.disclaimer}>Synthetic artwork · No patient data</span>
      </footer>
    </section>
  );
}
