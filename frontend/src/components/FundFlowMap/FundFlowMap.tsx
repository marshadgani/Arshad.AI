import FundFlowLegend from './FundFlowLegend';
import styles from './FundFlowMap.module.css';
import { FUND_FLOW_DIAGRAM_SVG } from './fundFlowDiagram';

/** Links the scrollable diagram to the honesty caption, so assistive tech
 *  reads "this is not live data" when focus lands on the diagram. */
const CAPTION_ID = 'fundflow-caption';

/* No loading/empty/error states: this renders a fixed, hand-authored diagram
   with no async fetch, so there is only ever "content". The honesty problem
   (looking like live data when it isn't) is solved by the Manual badge and
   the caption below instead. If this is ever wired to a real fund-flow
   source, add the standard 4-state handling then and drop this note. */
export default function FundFlowMap() {
  return (
    <section className={styles.section}>
      <div className={styles.sectionHead}>
        <div className={styles.titleGroup}>
          <div className={styles.sectionTitle}>Fund Flow</div>
          <span className={styles.manualBadge}>Manual</span>
        </div>
        <div className={styles.sectionMeta}>Full money map · v13 · updated Sep 2026</div>
      </div>

      <FundFlowLegend />

      <p id={CAPTION_ID} className={styles.diagramCaption}>
        This map is maintained by hand. It is not connected to any live bank or account
        data — balances, transfers and vendors shown here are Arshad&rsquo;s own notes,
        not synced records.
      </p>

      <div
        className={styles.canvasWrap}
        tabIndex={0}
        role="group"
        aria-label="Fund flow diagram, scroll horizontally to view"
        aria-describedby={CAPTION_ID}
        dangerouslySetInnerHTML={{ __html: FUND_FLOW_DIAGRAM_SVG }}
      />
    </section>
  );
}
