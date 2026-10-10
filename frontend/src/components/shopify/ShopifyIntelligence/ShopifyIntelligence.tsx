import { useShopifyInventoryCover } from '../../../hooks/useShopifyInventoryCover';
import { useShopifyServiceDebt } from '../../../hooks/useShopifyServiceDebt';
import { ShopifyDiscountSimulator } from '../ShopifyDiscountSimulator';
import { ShopifyInventoryCover } from '../ShopifyInventoryCover';
import { ShopifyServiceDebt } from '../ShopifyServiceDebt';
import styles from './ShopifyIntelligence.module.css';

/** Wires the three intelligence cards to their hooks for the /shopify page. */
export function ShopifyIntelligence() {
  const inventory = useShopifyInventoryCover();
  const debt = useShopifyServiceDebt();

  return (
    <div className={styles.stack}>
      <ShopifyInventoryCover
        data={inventory.inventory}
        isLoading={inventory.isLoading}
        error={inventory.error}
        onRetry={inventory.refresh}
      />
      <ShopifyDiscountSimulator />
      <ShopifyServiceDebt
        data={debt.serviceDebt}
        isLoading={debt.isLoading}
        error={debt.error}
        onRetry={debt.refresh}
      />
    </div>
  );
}
