import { FundFlowLegend } from './FundFlowLegend';
import { MAP_META, formatReviewed } from './mapMeta';
import { MAP_SVG } from './mapSvg';
import styles from './FundFlowMap.module.css';

/**
 * The fund-flow section on the Personal Finance page.
 *
 * Composition only — the diagram lives in ./mapSvg and its provenance in
 * ./mapMeta. What remains here is the section frame and the honesty
 * labelling (the "Static" badge and the caption), which is the part a reader
 * must not be able to miss: the diagram depicts real financial topology but
 * is hand-maintained and never synced to any account, integration or API.
 */
export default function FundFlowMap() {
  return (
    <section className={styles.section}>
      <div className={styles.sectionHead}>
        <div className={styles.sectionTitle}>Fund Flow</div>
        <div className={styles.sectionMetaGroup}>
          <div className={styles.sectionMeta}>Full money map · {MAP_META.revision}</div>
          {/* Sibling idiom to LiveBadge (frontend/src/components/shopify/LiveBadge) —
              that component is commerce-token-bound and hardcodes "Live"; this is its
              static opposite. If a third static/live badge appears elsewhere, extract
              a shared component instead of copying this pattern again. */}
          <span className={styles.staticBadge}>
            <span className={styles.staticBadgeDot} aria-hidden="true" />
            Static
          </span>
        </div>
      </div>

      <FundFlowLegend />

      <p className={styles.staticCaption}>
        Hand-maintained diagram — not synced to live account data · last reviewed{' '}
        {formatReviewed(MAP_META.lastReviewed)}
      </p>

      <div
        className={styles.canvasWrap}
        role="img"
        aria-label="Personal fund flow diagram"
        dangerouslySetInnerHTML={{ __html: MAP_SVG }}
      />
    </section>
  );
}
